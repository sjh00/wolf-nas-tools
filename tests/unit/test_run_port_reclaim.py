"""启动端口预检的回归测试。

真实故障：容器停止时 PID 文件缺失（异常退出/被清理），stop-server.sh 无法
定位 Granian 进程，旧实例继续占用端口；s6 重启服务后新实例 bind 失败：

    RuntimeError: Address already in use (os error 98)

且每轮重启都会重演。修复后 run.py 在 bind 前做端口预检：
本应用遗留进程自动回收，其他程序占用则给出可操作提示并中止。
"""

import errno
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUN_PY = ROOT / "run.py"


def _load_run_module():
    """按文件路径加载根目录的 run.py（不在包内，无法直接 import）。"""
    spec = importlib.util.spec_from_file_location("wolfnas_run_under_test", RUN_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def run_mod():
    return _load_run_module()


class TestSplitHolders:
    """占用者分类：本应用遗留进程 vs 其他程序。"""

    def test_own_process_detected_by_entrypoint(self, run_mod):
        holders = [(100, "/wolfnas/.venv/bin/python run.py")]
        own, others = run_mod._split_holders(holders)
        assert [p for p, _ in own] == [100]
        assert others == []

    def test_own_process_detected_via_uv_runner(self, run_mod):
        holders = [(101, "uv run --no-sync python run.py")]
        own, others = run_mod._split_holders(holders)
        assert [p for p, _ in own] == [101]
        assert others == []

    def test_foreign_process_is_not_reclaimed(self, run_mod):
        holders = [(200, "nginx: master process nginx")]
        own, others = run_mod._split_holders(holders)
        assert own == []
        assert [p for p, _ in others] == [200]

    def test_mixed_holders(self, run_mod):
        holders = [(100, "python run.py"), (200, "node /srv/app.js")]
        own, others = run_mod._split_holders(holders)
        assert [p for p, _ in own] == [100]
        assert [p for p, _ in others] == [200]

    def test_unknown_cmdline_treated_as_foreign(self, run_mod):
        """读不到 cmdline 时按他人进程处理——宁可报错，不误杀无关进程。"""
        holders = [(300, "")]
        own, others = run_mod._split_holders(holders)
        assert own == []
        assert [p for p, _ in others] == [300]


class TestReclaimPort:
    def test_free_port_passes(self, run_mod, monkeypatch):
        monkeypatch.setattr(run_mod, "_listening_holders", lambda port: [])
        assert run_mod._reclaim_port(3000) is True

    def test_stale_own_process_terminated(self, run_mod, monkeypatch):
        """本应用遗留进程应被回收，回收成功后放行。"""
        calls: list[int] = []
        states = {"first": True}

        def fake_holders(port):
            # 第一次返回占用，回收后再查应为空
            if states["first"]:
                states["first"] = False
                return [(4321, "python run.py")]
            return []

        monkeypatch.setattr(run_mod, "_listening_holders", fake_holders)
        monkeypatch.setattr(run_mod, "_terminate", lambda pid: calls.append(pid))

        assert run_mod._reclaim_port(3000) is True
        assert calls == [4321]

    def test_stale_process_survives_blocks_start(self, run_mod, monkeypatch):
        """回收失败（端口仍被占）时不得继续启动，否则又会 bind 失败。"""
        monkeypatch.setattr(run_mod, "_listening_holders", lambda port: [(4321, "python run.py")])
        monkeypatch.setattr(run_mod, "_terminate", lambda pid: None)

        assert run_mod._reclaim_port(3000) is False

    def test_foreign_process_blocks_start_and_never_killed(self, run_mod, monkeypatch):
        """他人进程：拒绝启动，且绝不尝试结束它。"""
        calls: list[int] = []
        monkeypatch.setattr(run_mod, "_listening_holders", lambda port: [(999, "postgres -D /data")])
        monkeypatch.setattr(run_mod, "_terminate", lambda pid: calls.append(pid))

        assert run_mod._reclaim_port(5432) is False
        assert calls == [], "不得结束非本应用进程"


class TestNoPermissionFallback:
    def test_access_denied_returns_empty(self, run_mod, monkeypatch):
        """非 root 拿不到连接表时返回空列表，交给 bind 阶段兜底。"""

        def boom(kind="inet"):
            raise run_mod.psutil.AccessDenied(pid=1)

        monkeypatch.setattr(run_mod.psutil, "net_connections", boom)
        assert run_mod._listening_holders(3000) == []


class TestServeErrorHandling:
    def test_eaddrinuse_reported_cleanly(self, run_mod):
        """bind 阶段仍撞车时给出友好提示，而不是裸 traceback。"""
        assert run_mod.errno.EADDRINUSE == errno.EADDRINUSE
