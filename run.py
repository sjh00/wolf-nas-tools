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

from granian import Granian
from granian.constants import Interfaces, Loops
from granian.log import LogLevels

import log
from app.core.banner import print_startup_banner
from app.core.port_guard import reclaim as reclaim_port
from app.core.settings import settings
from version import APP_VERSION

# 本应用根目录：用于识别 cmdline 无特征的孤儿 worker（按工作目录判定）
_APP_ROOT = Path(__file__).resolve().parent


def _port_log(level: str, message: str) -> None:
    """把 port_guard 的日志接到项目日志。"""
    if level == "error":
        log.error(message)
        # 同时输出到控制台，确保容器日志里能直接看到（不只是文件）
        log.console(message)
    elif level == "warn":
        log.warn(message)
        log.console(message)
    else:
        log.console(message)


def _ensure_port_available(port: int) -> bool:
    """bind 之前确保端口可用。

    Granian 的 worker 继承父进程的监听 socket，父进程异常退出后 worker 会成为
    孤儿并继续占用端口；其 cmdline 不含入口脚本名，按名字杀不掉。这里交由
    port_guard 通过 /proc/net/tcp 反查持有者（非 root 亦可），按进程组回收。

    :return: True 表示端口可用
    """
    ok, blockers = reclaim_port(port, str(_APP_ROOT), log=_port_log)
    if not ok:
        for holder in blockers:
            log.console(f"  占用者：{holder.describe()}")
        log.console("启动中止：端口被其他程序占用。请停止该进程，或改用 WOLFNAS_PORT 指定其他端口。")
        return False
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

    # 端口预检：回收本应用残留（含孤儿 worker），或对其他占用者给出明确提示
    if not _ensure_port_available(port):
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
        if e.errno == errno.EADDRINUSE:
            # 预检与实际 bind 之间被抢占（极少见）：再尝试回收一次后给出提示
            log.console(f"绑定端口 {port} 失败，重新检测占用情况 ...")
            ok, blockers = reclaim_port(port, str(_APP_ROOT), log=_port_log)
            if not ok:
                for holder in blockers:
                    log.console(f"  占用者：{holder.describe()}")
            log.console(f"启动失败：端口 {port} 已被占用，请停止占用进程后重试")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
