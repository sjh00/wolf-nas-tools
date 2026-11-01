"""端口占用诊断与回收。

为什么需要这个模块
------------------
Granian 的 worker 由 `multiprocessing.Process(name='granian-worker')` 创建，
并通过 `SocketHolder(fd)` **继承父进程的监听 socket**。一旦父进程异常退出
（SIGKILL、OOM、容器被强停），worker 会被 PID 1 收养成为孤儿，却依然持有
该 socket —— 端口从此被永久占用，任何新实例 bind 都报 `Address already in use`。

更麻烦的是孤儿 worker 的 cmdline 形如
`python -c "from multiprocessing.spawn import spawn_main; ..."`，**不含入口
脚本名**，所以按 cmdline 匹配 `run.py` 的扫描（stop-server.sh / 早期版本）
定位不到它。

另外容器内以非 root（UID 911）运行，`psutil.net_connections()` 会因权限
不足抛 AccessDenied，导致「预检认为端口空闲 → bind 失败」的假阴性。

因此这里改用 **/proc/net/tcp{,6}** 定位监听 socket（该文件对所有用户可读），
再遍历 `/proc/<pid>/fd` 反查持有者（进程属同一用户时可读）。

CLI
---
    python -m app.core.port_guard find --port 3000
    python -m app.core.port_guard reclaim --port 3000 [--workdir /wolfnas]
"""

from __future__ import annotations

import argparse
import errno
import os
import signal
import sys
import time
from dataclasses import dataclass

try:  # 非 Linux 平台回退用；缺失时降级为「无法枚举」
    import psutil
except ImportError:  # pragma: no cover - 依赖环境
    psutil = None  # type: ignore[assignment]

# 结束进程时的宽限：先 TERM 等其自行退出，超时再 KILL
TERM_GRACE = 10.0
KILL_GRACE = 5.0
# 回收后等待端口释放的上限
RELEASE_GRACE = 10.0

# 判定「本应用进程」的 cmdline 特征
_OWN_CMDLINE_MARKERS = ("run.py", "granian", "uvicorn", "hypercorn")


@dataclass(frozen=True)
class Holder:
    """端口持有者。"""

    pid: int
    cmdline: str
    ours: bool

    def describe(self) -> str:
        tail = "" if self.ours else "（非本应用）"
        return f"pid={self.pid}{tail} cmd={self.cmdline or '（无权限查看）'}"


# ---------------------------------------------------------------------------
# 监听 socket 定位
# ---------------------------------------------------------------------------


def _listen_inodes(port: int) -> set[int]:
    """返回监听指定端口的 socket inode 集合。

    解析 /proc/net/tcp 与 /proc/net/tcp6：字段为
    `sl local_address rem_address st ... inode`，其中 local_address 形如
    `0100007F:0BB8`（IP:端口，均为十六进制），st == 0A 表示 LISTEN。
    """
    inodes: set[int] = set()
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path, encoding="ascii", errors="ignore") as fh:
                next(fh, None)  # 跳过表头
                for line in fh:
                    parts = line.split()
                    # 至少 10 列才可能包含 inode
                    if len(parts) < 10 or parts[3] != "0A":
                        continue
                    try:
                        local_port = int(parts[1].rsplit(":", 1)[1], 16)
                    except (IndexError, ValueError):
                        continue
                    if local_port != port:
                        continue
                    inode = parts[9]
                    if inode.isdigit() and inode != "0":
                        inodes.add(int(inode))
        except OSError:
            continue
    return inodes


def _pids_holding(inodes: set[int]) -> set[int]:
    """遍历 /proc/<pid>/fd 反查持有这些 socket 的进程。

    非 root 只能读到自己进程的 fd 表；持有端通常是同用户的孤儿 worker，
    因此可读到。读不到的条目直接跳过，不视为错误。
    """
    if not inodes:
        return set()
    targets = {f"socket:[{inode}]" for inode in inodes}
    pids: set[int] = set()
    try:
        entries = os.listdir("/proc")
    except OSError:
        return pids
    for entry in entries:
        if not entry.isdigit():
            continue
        fd_dir = f"/proc/{entry}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(f"{fd_dir}/{fd}") in targets:
                    pids.add(int(entry))
                    break
            except OSError:
                continue
    return pids


# ---------------------------------------------------------------------------
# 进程信息
# ---------------------------------------------------------------------------


def _read_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            raw = fh.read()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()


def _read_cwd(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def _is_our_process(pid: int, workdir: str | None) -> bool:
    """判断是否是本应用的进程。

    优先看 cmdline 特征（run.py / granian / 常见 ASGI 服务器）；
    孤儿 worker 的 cmdline 只有 multiprocessing 引导代码，此时退化为
    判断工作目录是否为本应用根目录。
    """
    cmd = _read_cmdline(pid)
    low = cmd.lower()
    if any(marker in low for marker in _OWN_CMDLINE_MARKERS):
        return True
    if workdir:
        cwd = _read_cwd(pid)
        if cwd and os.path.normpath(cwd) == os.path.normpath(workdir):
            # 同一工作目录且持有本应用的监听端口 → 认定为本应用残留
            return True
    return False


# ---------------------------------------------------------------------------
# 平台回退（非 Linux 无 /proc）
# ---------------------------------------------------------------------------


def _fallback_holders(port: int, workdir: str | None) -> list[Holder]:
    """非 Linux 平台：退回 psutil 枚举（需要足够权限）。"""
    if psutil is None:
        return []
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError):
        return []
    seen: set[int] = set()
    holders: list[Holder] = []
    for conn in conns:
        if not conn.laddr or conn.laddr.port != port:
            continue
        if conn.status != psutil.CONN_LISTEN or conn.pid is None or conn.pid in seen:
            continue
        seen.add(conn.pid)
        try:
            cmd = " ".join(psutil.Process(conn.pid).cmdline())
        except (psutil.Error, OSError):
            cmd = ""
        low = cmd.lower()
        ours = any(marker in low for marker in _OWN_CMDLINE_MARKERS)
        if not ours and workdir:
            try:
                ours = os.path.normpath(psutil.Process(conn.pid).cwd()) == os.path.normpath(workdir)
            except (psutil.Error, OSError):
                ours = False
        holders.append(Holder(pid=conn.pid, cmdline=cmd, ours=ours))
    return holders


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def has_proc_fs() -> bool:
    return os.path.isdir("/proc/net")


def find_holders(port: int, workdir: str | None = None) -> list[Holder]:
    """列出正在 LISTEN 指定端口的进程。"""
    if not has_proc_fs():
        return _fallback_holders(port, workdir)
    pids = _pids_holding(_listen_inodes(port))
    return [Holder(pid=pid, cmdline=_read_cmdline(pid), ours=_is_our_process(pid, workdir)) for pid in sorted(pids)]


def _pgid(pid: int) -> int | None:
    """取进程组 ID；平台不支持（Windows）时返回 None。"""
    getter = getattr(os, "getpgid", None)
    if getter is None:
        return None
    try:
        return getter(pid)
    except OSError:
        return None


def _signal_process(pid: int, sig: int) -> None:
    """向进程（若它是组长则连同整组）发送信号。

    Granian 父进程与 worker 在同一进程组内，按组发信号才能确保
    孤儿 worker 一并退出，避免 socket 被继续持有。
    组 ID 等于自身组时不按组发信号，防止误伤调用方。
    """
    pgid = _pgid(pid)
    own_pgid = _pgid(0)
    killpg = getattr(os, "killpg", None)
    if pgid is not None and pgid == pid and pgid != own_pgid and killpg is not None:
        try:
            killpg(pgid, sig)
            return
        except OSError:
            pass
    try:
        os.kill(pid, sig)
    except OSError as e:
        if e.errno != errno.ESRCH:
            raise


def _alive(pid: int) -> bool:
    """进程是否仍存在。

    不能直接用 `os.kill(pid, 0)` 探测：Windows 上该调用会**终止**目标进程
    （TerminateProcess），而非空操作。优先用 psutil.pid_exists，POSIX 才回退
    到信号 0。
    """
    if psutil is not None:
        try:
            return bool(psutil.pid_exists(pid))
        except Exception:  # noqa: BLE001, S110 - 回退到 POSIX 信号 0 探测
            pass
    if os.name == "posix":
        try:
            os.kill(pid, 0)
            return True
        except OSError as e:
            return e.errno == errno.EPERM
    return False


def _kill_signal() -> int:
    """强制结束信号；Windows 无 SIGKILL 时复用 SIGTERM（等同 TerminateProcess）。"""
    return getattr(signal, "SIGKILL", signal.SIGTERM)


def _terminate(pid: int, grace: float = TERM_GRACE) -> None:
    """先 TERM（宽限 grace 秒）再强制结束。"""
    if pid == os.getpid():
        return
    try:
        _signal_process(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not _alive(pid):
            return
        time.sleep(0.2)
    try:
        _signal_process(pid, _kill_signal())
    except OSError:
        return
    deadline = time.monotonic() + KILL_GRACE
    while time.monotonic() < deadline:
        if not _alive(pid):
            return
        time.sleep(0.2)


def reclaim(port: int, workdir: str | None = None, *, log=None) -> tuple[bool, list[Holder]]:
    """确保端口可用：回收本应用残留进程。

    :param port: 待检查端口
    :param workdir: 本应用根目录，用于识别 cmdline 无特征的孤儿 worker
    :param log: 可选日志回调 `log(level, message)`
    :return: (端口是否可用, 无法回收的外部占用者列表)
    """

    def emit(level: str, msg: str) -> None:
        if log is not None:
            log(level, msg)

    holders = find_holders(port, workdir)
    if not holders:
        # 端口有监听却查不到进程：通常是权限不足（持有者属于其他用户）。
        # 这种情况必须报错，不能当作「端口空闲」放行，否则 bind 仍会失败。
        if has_proc_fs() and _listen_inodes(port):
            emit(
                "error",
                f"端口 {port} 处于监听状态，但无法定位持有进程（权限不足）。"
                f"请以 root 在容器内执行：ss -lntp | grep :{port}，或重启容器。",
            )
            return False, []
        return True, []

    foreign = [h for h in holders if not h.ours]
    if foreign:
        for h in foreign:
            emit("error", f"端口 {port} 被其他程序占用：{h.describe()}")
        return False, foreign

    for h in holders:
        emit("warn", f"端口 {port} 被本应用残留进程占用：{h.describe()}，正在结束")
        _terminate(h.pid)

    deadline = time.monotonic() + RELEASE_GRACE
    while time.monotonic() < deadline:
        if not find_holders(port, workdir):
            emit("info", f"已回收端口 {port}")
            return True, []
        time.sleep(0.3)

    remaining = find_holders(port, workdir)
    for h in remaining:
        emit("error", f"端口 {port} 回收失败，仍被占用：{h.describe()}")
    return False, remaining


# ---------------------------------------------------------------------------
# CLI（供 shell 脚本调用）
# ---------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="port_guard", description="端口占用诊断与回收")
    parser.add_argument("action", choices=("find", "reclaim"))
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--workdir", default=None)
    args = parser.parse_args(argv)

    def log(level: str, msg: str) -> None:
        print(f"[port_guard] {msg}", flush=True)

    if args.action == "find":
        holders = find_holders(args.port, args.workdir)
        if not holders:
            print(f"端口 {args.port} 空闲", flush=True)
            return 0
        for h in holders:
            print(f"  {h.describe()}", flush=True)
        return 0

    ok, _ = reclaim(args.port, args.workdir, log=log)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main())
