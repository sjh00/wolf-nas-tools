"""port_guard 回归测试。

真实故障链：
1. Granian worker 由 multiprocessing 创建，通过 SocketHolder(fd) 继承父进程的
   监听 socket；
2. 父进程异常退出（SIGKILL/OOM/容器强停）后 worker 被 PID 1 收养，仍持有该
   socket，端口被永久占用；
3. 孤儿 worker 的 cmdline 是 `python -c "from multiprocessing.spawn import
   spawn_main; ..."`，**不含入口脚本名**，按 `run.py` 匹配的扫描找不到它；
4. 容器内以非 root 运行，psutil.net_connections() 抛 AccessDenied，导致预检
   误判「端口空闲」，随后 bind 失败：RuntimeError: Address already in use。

因此 port_guard 改用 /proc/net/tcp{,6} 定位监听 inode（所有用户可读），
再遍历 /proc/<pid>/fd 反查持有者，并按进程组结束，兼顾孤儿 worker。
"""

import os
import signal
from pathlib import Path

import pytest

from app.core import port_guard


class TestListenInodesParsing:
    """解析 /proc/net/tcp 找到监听指定端口的 socket inode。"""

    @staticmethod
    def _write_proc(tmp_path: Path, name: str, body: str) -> Path:
        p = tmp_path / name
        p.write_text(body, encoding="ascii")
        return p

    def _patch_proc(self, monkeypatch, tmp_path, tcp: str, tcp6: str = "") -> None:
        tcp_file = self._write_proc(tmp_path, "tcp", tcp)
        tcp6_file = self._write_proc(tmp_path, "tcp6", tcp6)

        real_open = open

        def fake_open(path, *args, **kwargs):
            if str(path) == "/proc/net/tcp":
                return real_open(tcp_file, *args, **kwargs)
            if str(path) == "/proc/net/tcp6":
                return real_open(tcp6_file, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", fake_open)

    def test_finds_listen_inode_for_port(self, monkeypatch, tmp_path):
        # 0BB8 = 3000, 0A = LISTEN
        body = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 00000000:0BB8 00000000:0000 0A 00000000:00000000 00:00000000 00000000   911        0 98765 1\n"
        )
        self._patch_proc(monkeypatch, tmp_path, body)
        assert port_guard._listen_inodes(3000) == {98765}

    def test_ignores_non_listen_states(self, monkeypatch, tmp_path):
        # 01 = ESTABLISHED，非监听
        body = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 00000000:0BB8 0100007F:1F90 01 00000000:00000000 00:00000000 00000000   911        0 11111 1\n"
        )
        self._patch_proc(monkeypatch, tmp_path, body)
        assert port_guard._listen_inodes(3000) == set()

    def test_ignores_other_ports(self, monkeypatch, tmp_path):
        # 1F90 = 8080
        body = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000   911        0 22222 1\n"
        )
        self._patch_proc(monkeypatch, tmp_path, body)
        assert port_guard._listen_inodes(3000) == set()

    def test_parses_ipv6_listener(self, monkeypatch, tmp_path):
        """web_host 默认是 ::，监听在 tcp6 里。"""
        body6 = (
            "  sl  local_address                         remote_address                        st tx_queue rx_queue "
            "tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 00000000000000000000000000000000:0BB8 00000000000000000000000000000000:0000 0A "
            "00000000:00000000 00:00000000 00000000   911        0 33333 1\n"
        )
        self._patch_proc(monkeypatch, tmp_path, "", body6)
        assert port_guard._listen_inodes(3000) == {33333}

    def test_merges_tcp_and_tcp6(self, monkeypatch, tmp_path):
        body = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 00000000:0BB8 00000000:0000 0A 00000000:00000000 00:00000000 00000000   911        0 44444 1\n"
        )
        body6 = (
            "  sl  local_address                         remote_address                        st tx_queue rx_queue "
            "tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 00000000000000000000000000000000:0BB8 00000000000000000000000000000000:0000 0A "
            "00000000:00000000 00:00000000 00000000   911        0 55555 1\n"
        )
        self._patch_proc(monkeypatch, tmp_path, body, body6)
        assert port_guard._listen_inodes(3000) == {44444, 55555}

    def test_missing_proc_file_is_tolerated(self, monkeypatch):
        def boom(path, *args, **kwargs):
            raise OSError("no proc")

        monkeypatch.setattr("builtins.open", boom)
        assert port_guard._listen_inodes(3000) == set()


class TestProcessClassification:
    """孤儿 worker 的 cmdline 不含 run.py，需要按工作目录识别。"""

    def test_entrypoint_script_is_own(self, monkeypatch):
        monkeypatch.setattr(port_guard, "_read_cmdline", lambda pid: "/wolfnas/.venv/bin/python run.py")
        assert port_guard._is_our_process(1, "/wolfnas") is True

    def test_granian_worker_cmdline_is_own(self, monkeypatch):
        """multiprocessing 引导代码里含 granian 包名，也应识别为本应用。"""
        cmd = (
            "/wolfnas/.venv/bin/python -c from multiprocessing.spawn import spawn_main; "
            "spawn_main(tracker_fd=14, pipe_handle=20) --multiprocessing-fork"
        )
        monkeypatch.setattr(port_guard, "_read_cmdline", lambda pid: cmd)
        monkeypatch.setattr(port_guard, "_read_cwd", lambda pid: "/wolfnas")
        assert port_guard._is_our_process(2, "/wolfnas") is True

    def test_bare_spawn_worker_matched_by_workdir(self, monkeypatch):
        """cmdline 完全无特征时，靠工作目录 + 持有端口认定为本应用。"""
        cmd = "python -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=14)"
        monkeypatch.setattr(port_guard, "_read_cmdline", lambda pid: cmd)
        monkeypatch.setattr(port_guard, "_read_cwd", lambda pid: "/wolfnas")
        assert port_guard._is_our_process(3, "/wolfnas") is True

    def test_foreign_process_not_matched(self, monkeypatch):
        monkeypatch.setattr(port_guard, "_read_cmdline", lambda pid: "nginx: master process nginx")
        monkeypatch.setattr(port_guard, "_read_cwd", lambda pid: "/etc/nginx")
        assert port_guard._is_our_process(4, "/wolfnas") is False

    def test_unreadable_process_not_matched_without_workdir(self, monkeypatch):
        monkeypatch.setattr(port_guard, "_read_cmdline", lambda pid: "")
        monkeypatch.setattr(port_guard, "_read_cwd", lambda pid: "")
        assert port_guard._is_our_process(5, None) is False


class TestSignalProcessGroup:
    """按组发信号，确保孤儿 worker 一并退出。"""

    def _patch_env(self, monkeypatch, pgid_map, calls):
        monkeypatch.setattr(port_guard, "_pgid", lambda pid: pgid_map.get(pid))
        monkeypatch.setattr(os, "kill", lambda pid, sig: calls.append(("kill", pid, sig)))
        if hasattr(os, "killpg"):
            monkeypatch.setattr(os, "killpg", lambda pgid, sig: calls.append(("killpg", pgid, sig)))
        else:  # Windows
            monkeypatch.setattr(port_guard, "_fake_killpg", None, raising=False)

    def test_kills_group_when_pid_is_leader(self, monkeypatch):
        calls: list[tuple] = []
        # 目标 pid 4321 是组长（pgid == pid），且与自身组不同
        self._patch_env(monkeypatch, {4321: 4321, 0: 1111}, calls)
        port_guard._signal_process(4321, signal.SIGTERM)
        if hasattr(os, "killpg"):
            assert calls == [("killpg", 4321, signal.SIGTERM)]
        else:  # Windows 无进程组，退化为单进程
            assert calls == [("kill", 4321, signal.SIGTERM)]

    def test_falls_back_to_single_pid_when_not_leader(self, monkeypatch):
        calls: list[tuple] = []
        # 目标 pid 5000 的组是 4000（非自身 pid），按单进程处理更安全
        self._patch_env(monkeypatch, {5000: 4000, 0: 1111}, calls)
        port_guard._signal_process(5000, signal.SIGTERM)
        assert calls == [("kill", 5000, signal.SIGTERM)]

    def test_never_kills_own_group(self, monkeypatch):
        """自身进程组的组长是自己时，绝不能 killpg —— 否则会杀掉调用方。"""
        calls: list[tuple] = []
        my_pid = os.getpid()
        self._patch_env(monkeypatch, {my_pid: my_pid, 0: my_pid}, calls)
        port_guard._signal_process(my_pid, signal.SIGTERM)
        assert not any(c[0] == "killpg" for c in calls)


class TestTerminate:
    def test_never_targets_self(self, monkeypatch):
        monkeypatch.setattr(os, "kill", lambda *a: pytest.fail("不应向自身发信号"))
        port_guard._terminate(os.getpid())


class TestReclaim:
    def test_free_port_ok(self, monkeypatch):
        monkeypatch.setattr(port_guard, "find_holders", lambda port, workdir=None: [])
        monkeypatch.setattr(port_guard, "has_proc_fs", lambda: False)
        ok, blockers = port_guard.reclaim(3000, "/wolfnas")
        assert ok is True
        assert blockers == []

    def test_listening_but_unresolvable_blocks(self, monkeypatch):
        """端口在监听但定位不到进程（权限不足）时，必须报错而非放行。

        否则会重演「预检认为空闲 → bind 失败」的假阴性。
        """
        monkeypatch.setattr(port_guard, "find_holders", lambda port, workdir=None: [])
        monkeypatch.setattr(port_guard, "has_proc_fs", lambda: True)
        monkeypatch.setattr(port_guard, "_listen_inodes", lambda port: {12345})

        ok, blockers = port_guard.reclaim(3000, "/wolfnas")
        assert ok is False
        assert blockers == []

    def test_foreign_holder_blocks_and_is_never_killed(self, monkeypatch):
        foreign = port_guard.Holder(pid=999, cmdline="postgres -D /data", ours=False)
        monkeypatch.setattr(port_guard, "find_holders", lambda port, workdir=None: [foreign])
        killed: list[int] = []
        monkeypatch.setattr(port_guard, "_terminate", lambda pid, grace=None: killed.append(pid))

        ok, blockers = port_guard.reclaim(5432, "/wolfnas")
        assert ok is False
        assert [b.pid for b in blockers] == [999]
        assert killed == [], "不得结束非本应用进程"

    def test_own_holder_is_terminated_and_port_released(self, monkeypatch):
        own = port_guard.Holder(pid=777, cmdline="python run.py", ours=True)
        state = {"first": True}

        def fake_find(port, workdir=None):
            if state["first"]:
                state["first"] = False
                return [own]
            return []

        monkeypatch.setattr(port_guard, "find_holders", fake_find)
        killed: list[int] = []
        monkeypatch.setattr(port_guard, "_terminate", lambda pid, grace=None: killed.append(pid))

        ok, _ = port_guard.reclaim(3000, "/wolfnas")
        assert ok is True
        assert killed == [777]

    def test_own_holder_survives_returns_false(self, monkeypatch):
        own = port_guard.Holder(pid=777, cmdline="python run.py", ours=True)
        monkeypatch.setattr(port_guard, "find_holders", lambda port, workdir=None: [own])
        monkeypatch.setattr(port_guard, "_terminate", lambda pid, grace=None: None)
        monkeypatch.setattr(port_guard, "RELEASE_GRACE", 0.1)

        ok, blockers = port_guard.reclaim(3000, "/wolfnas")
        assert ok is False
        assert [b.pid for b in blockers] == [777]


class TestHolderDescribe:
    def test_describe_marks_foreign(self):
        assert "非本应用" in port_guard.Holder(1, "nginx", ours=False).describe()

    def test_describe_own(self):
        text = port_guard.Holder(2, "python run.py", ours=True).describe()
        assert "pid=2" in text
        assert "非本应用" not in text
