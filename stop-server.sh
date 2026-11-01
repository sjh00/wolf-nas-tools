#!/bin/sh
# 停止 Granian 服务器
#
# 优先按 PID 文件精确停止；PID 文件缺失（异常退出、被清理）时回退到
# 按端口定位监听进程，避免旧实例继续占用端口、导致下次启动报
# "Address already in use"。回退逻辑依赖 run.py 自带的端口回收，
# 这里只负责发出请求并做最终校验。

PIDFILE="${1:-/data/granian.pid}"
PORT="${2:-${WOLFNAS_PORT:-${NEXUS_PORT:-3000}}}"

if [ ! -f "$PIDFILE" ] && [ -f "./data/granian.pid" ]; then
    PIDFILE="./data/granian.pid"
fi

stopped=0

if [ -f "$PIDFILE" ]; then
    for pid in $(cat "$PIDFILE"); do
        if kill -0 "$pid" 2>/dev/null; then
            echo "发送 TERM 信号到 Granian 进程 $pid ..."
            kill -TERM "$pid" 2>/dev/null && stopped=1
        else
            echo "进程 $pid 不存在"
        fi
    done
    rm -f "$PIDFILE"
else
    echo "未找到 PID 文件: $PIDFILE"
fi

# 兜底：PID 文件缺失时按端口停止监听进程（非 root 可能无权限，失败不阻塞）
if [ "$stopped" -eq 0 ]; then
    echo "尝试按端口 ${PORT} 定位残留进程 ..."
    # 通过 /proc 扫描，避免依赖 ps/lsof（运行镜像未安装 procps）
    for piddir in /proc/[0-9]*; do
        pid="${piddir#/proc/}"
        [ -r "$piddir/cmdline" ] || continue
        cmd=$(tr '\0' ' ' < "$piddir/cmdline" 2>/dev/null)
        case "$cmd" in
            *run.py*)
                echo "发送 TERM 信号到残留 Granian 进程 $pid ..."
                kill -TERM "$pid" 2>/dev/null && stopped=1
                ;;
        esac
    done
fi

if [ "$stopped" -eq 0 ]; then
    echo "未发现运行中的 Granian 进程"
fi

exit 0
