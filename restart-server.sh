#!/bin/sh
# 优雅重启 Granian（SIGUSR1 信号）
#
# 优先按 PID 文件定位；PID 文件缺失或进程已死时回退到 port_guard 按端口反查
# （解析 /proc/net/tcp，非 root 亦可用，且能识别 cmdline 无特征的孤儿 worker）。
# 运行镜像未安装 procps，故不依赖 ps/pgrep。

PIDFILE="${1:-/data/granian.pid}"
PORT="${2:-${WOLFNAS_PORT:-${NEXUS_PORT:-3000}}}"
WORKDIR="${WORKDIR:-/wolfnas}"

if [ ! -f "$PIDFILE" ] && [ -f "./data/granian.pid" ]; then
    PIDFILE="./data/granian.pid"
fi

signalled=0

if [ -f "$PIDFILE" ]; then
    for pid in $(cat "$PIDFILE"); do
        if kill -0 "$pid" 2>/dev/null; then
            echo "发送 USR1 信号到 Granian 进程 $pid ..."
            kill -USR1 "$pid" 2>/dev/null && signalled=1
        else
            echo "进程 $pid 不存在"
        fi
    done
else
    echo "未找到 PID 文件: $PIDFILE"
fi

if [ "$signalled" -eq 0 ]; then
    PYBIN="${WORKDIR}/.venv/bin/python"
    if [ -x "$PYBIN" ]; then
        echo "按端口 ${PORT} 查找残留进程 ..."
        # find 仅诊断；真正重启交给上层（s6 / docker restart），避免此处误杀
        ( cd "${WORKDIR}" && PYTHONPATH="src" "$PYBIN" -m app.core.port_guard find --port "${PORT}" --workdir "${WORKDIR}" )
    fi
    echo "未发现运行中的 Granian，无需重启（直接启动即可）"
    exit 1
fi
