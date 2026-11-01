#!/bin/sh
# 停止 Granian 服务器
#
# Granian 的 worker 由 multiprocessing 创建并继承父进程的监听 socket；父进程若
# 异常退出，worker 会变成孤儿继续占用端口。因此停止策略必须按 **进程组** 处理：
#   1. 有 PID 文件 → 向该进程所在进程组发 TERM（worker 一并退出）
#   2. PID 文件缺失/进程已死 → 调用 port_guard 按端口反查持有者并回收
#      （port_guard 解析 /proc/net/tcp，非 root 亦可；不依赖 procps）

PIDFILE="${1:-/data/granian.pid}"
PORT="${2:-${WOLFNAS_PORT:-${NEXUS_PORT:-3000}}}"
WORKDIR="${WORKDIR:-/wolfnas}"

if [ ! -f "$PIDFILE" ] && [ -f "./data/granian.pid" ]; then
    PIDFILE="./data/granian.pid"
fi

sent=0

if [ -f "$PIDFILE" ]; then
    for pid in $(cat "$PIDFILE"); do
        if kill -0 "$pid" 2>/dev/null; then
            # 取进程组 ID：与自身组不同时按组结束，确保 worker 一并退出
            pgid=$(awk '{print $5}' "/proc/$pid/stat" 2>/dev/null)
            self_pgid=$(awk '{print $5}' "/proc/self/stat" 2>/dev/null)
            if [ -n "$pgid" ] && [ "$pgid" != "$self_pgid" ] && [ "$pgid" = "$pid" ]; then
                echo "发送 TERM 信号到 Granian 进程组 $pid ..."
                kill -TERM "-$pgid" 2>/dev/null && sent=1
            else
                echo "发送 TERM 信号到 Granian 进程 $pid ..."
                kill -TERM "$pid" 2>/dev/null && sent=1
            fi
        else
            echo "进程 $pid 不存在"
        fi
    done
    rm -f "$PIDFILE"
else
    echo "未找到 PID 文件: $PIDFILE"
fi

# 兜底：按端口反查并回收（含 cmdline 无特征的孤儿 worker）
PYBIN="${WORKDIR}/.venv/bin/python"
if [ -x "$PYBIN" ]; then
    echo "按端口 ${PORT} 检查残留进程 ..."
    ( cd "${WORKDIR}" && PYTHONPATH="src" "$PYBIN" -m app.core.port_guard reclaim --port "${PORT}" --workdir "${WORKDIR}" )
    rc=$?
    [ "$rc" -eq 0 ] && sent=1
else
    echo "未找到 ${PYBIN}，跳过端口检查"
fi

if [ "$sent" -eq 0 ]; then
    echo "未发现运行中的 Granian 进程"
fi

exit 0
