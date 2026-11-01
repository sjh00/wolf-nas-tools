#!/usr/bin/env python3
"""WolfNas 启动入口 — Granian 异步服务器

用法:
    python run.py                    # 生产模式
    python run.py --dev              # 开发模式（热重载）
    python run.py -w 4               # 指定 worker 数
"""  # noqa: EXE001

import errno
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import psutil
from granian import Granian
from granian.constants import Interfaces, Loops
from granian.log import LogLevels

import log
from app.core.banner import print_startup_banner
from app.core.settings import settings
from version import APP_VERSION

# 本应用的进程特征：启动命令里包含入口文件名
_SELF_CMDLINE_MARKER = "run.py"
# 结束遗留进程时的等待上限（秒）：先 TERM 宽限，超时再 KILL
_TERM_GRACE = 10.0
_KILL_GRACE = 5.0


def _listening_holders(port: int) -> list[tuple[int, str]]:
    """返回正在 LISTEN 指定端口的进程 [(pid, cmdline)]。

    非 root 运行时可能拿不到全局连接表（AccessDenied），此时返回空列表，
    由调用方按「端口空闲」处理——真正的占用仍会在 bind 阶段以 OSError 暴露。
    """
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError) as e:  # pragma: no cover - 依赖运行权限
        log.debug(f"[Startup]无法枚举端口占用（权限不足），跳过预检: {e}")
        return []
    holders: list[tuple[int, str]] = []
    seen: set[int] = set()
    for conn in conns:
        if not conn.laddr or conn.laddr.port != port:
            continue
        if conn.status != psutil.CONN_LISTEN or conn.pid is None:
            continue
        if conn.pid in seen:
            continue
        seen.add(conn.pid)
        try:
            cmd = " ".join(psutil.Process(conn.pid).cmdline())
        except (psutil.Error, OSError):
            cmd = ""
        holders.append((conn.pid, cmd))
    return holders


def _split_holders(holders: list[tuple[int, str]]) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """把端口占用者分成（本应用遗留进程, 其他进程）。"""
    own = [h for h in holders if _SELF_CMDLINE_MARKER in h[1]]
    others = [h for h in holders if _SELF_CMDLINE_MARKER not in h[1]]
    return own, others


def _terminate(pid: int) -> None:
    """先 TERM 再 KILL 结束进程；进程不存在时静默忽略。"""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    try:
        proc.terminate()
        proc.wait(timeout=_TERM_GRACE)
        return
    except psutil.TimeoutExpired:
        log.warn(f"[Startup]进程 {pid} 未响应 TERM，强制结束")
    except psutil.NoSuchProcess:
        return
    try:
        proc.kill()
        proc.wait(timeout=_KILL_GRACE)
    except (psutil.NoSuchProcess, psutil.TimeoutExpired) as e:
        log.warn(f"[Startup]结束进程 {pid} 失败: {e}")


def _reclaim_port(port: int) -> bool:
    """启动前确保端口可用。

    典型场景：上一轮容器停止时 PID 文件缺失或未被清理，`stop-server.sh`
    无法定位进程，旧 Granian 继续占用端口；s6 重启服务后新实例 bind 失败，
    表现为 `RuntimeError: Address already in use`，且每轮重启都会重演。

    这里在 bind 之前兜底：属于本应用的遗留进程直接回收，其余占用者给出
    可操作的提示并中止启动（不抛裸 traceback）。

    :return: True 表示端口可用（或已回收），False 表示被其他程序占用
    """
    holders = _listening_holders(port)
    if not holders:
        return True

    own, others = _split_holders(holders)
    if others:
        log.console(f"启动中止：端口 {port} 被其他进程占用")
        for pid, cmd in others:
            log.console(f"  pid={pid}  命令={cmd or '（无权限查看）'}")
        log.console("请停止该进程后重试；若不属于本应用，请检查端口映射是否与其他服务冲突。")
        return False

    for pid, cmd in own:
        log.warn(f"[Startup]检测到本应用遗留进程仍占用端口 {port}：pid={pid} {cmd}".rstrip())
        _terminate(pid)

    remaining = _listening_holders(port)
    if remaining:
        for pid, cmd in remaining:
            log.console(f"启动中止：端口 {port} 仍被占用 pid={pid} {cmd}".rstrip())
        return False
    log.console(f"已回收端口 {port}，继续启动")
    return True


def main():
    args = set(sys.argv[1:])
    dev = "--dev" in args
    workers = 1
    for a in args:
        if a.startswith("-w"):
            workers = int(a.split("=", 1)[-1] if "=" in a else sys.argv[sys.argv.index(a) + 1])

    print_startup_banner()
    log.console("WolfNas FastAPI 启动中...")
    log.console(f"模式: {'dev' if dev else 'prod'}, workers={workers}")
    log.console(f"当前版本号：{APP_VERSION}")

    app_conf = settings.get("app") or {}
    host = app_conf.get("web_host", "::").replace("[", "").replace("]", "")
    # WOLFNAS_PORT 为主；NEXUS_PORT 是旧品牌名，仍读取以兼容既有部署
    port = int(os.environ.get("WOLFNAS_PORT") or os.environ.get("NEXUS_PORT") or app_conf.get("web_port") or 3000)
    log.console(f"监听地址：{host}:{port}")

    # 端口预检：回收本应用遗留进程，或对其余占用者给出明确提示
    if not _reclaim_port(port):
        sys.exit(1)

    ssl_kwargs = {}
    if (ssl_cert := app_conf.get("ssl_cert")) and (ssl_key := app_conf.get("ssl_key")):
        ssl_kwargs["ssl_cert"] = ssl_cert
        ssl_kwargs["ssl_key"] = ssl_key
        log.console("SSL 已启用")

    # 确保 PID 文件目录存在
    os.makedirs(Path(settings.data_path), exist_ok=True)

    server = Granian(
        "api.main:app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        loop=Loops.auto,
        workers=workers,
        reload=dev,
        reload_ignore_dirs=[
            "logs",
            "__pycache__",
            ".venv",
            ".git",
            "alembic",
            "data",
            "static",
            "uploads",
            "temp",
            "docs",
            "tests",
            "config",
        ],
        log_enabled=True,
        log_level=LogLevels.info if dev else LogLevels.warning,
        log_access=dev,
        pid_file=Path(settings.data_path or ".") / "granian.pid",
        workers_kill_timeout=5,
        **ssl_kwargs,
    )

    def _on_shutdown():
        log.console("服务器已关闭")

    server.on_shutdown(_on_shutdown)
    try:
        server.serve()
    except OSError as e:
        # 预检与 bind 之间仍可能被抢占（例如同时启动两个实例），
        # 给出与预检一致的提示，避免用户只看到裸 traceback。
        if e.errno == errno.EADDRINUSE:
            log.console(f"启动失败：端口 {port} 已被占用，请停止占用进程后重试")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
