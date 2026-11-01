#!/bin/sh
# 优雅重启 Granian（SIGUSR1 信号）
#
# 优先按 PID 文件定位；PID 文件缺失（异常退出、被清理）时回退到 /proc 扫描，
# 避免「找不到 PID 文件 → 旧进程仍在跑 → 新实例端口冲突」的死循环。
# 运行镜像未安装 procps，故用 /proc/<pid>/cmdline 判断，不依赖 ps/pgrep。

PIDFILE="${1:-/data/granian.pid}"

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

# 兜底：PID 文件缺失时按进程特征定位
if [ "$signalled" -eq 0 ]; then
    echo "尝试按进程特征定位残留 Granian ..."
    for piddir in /proc/[0-9]*; do
        pid="${piddir#/proc/}"
        [ -r "$piddir/cmdline" ] || continue
        cmd=$(tr '\0' ' ' < "$piddir/cmdline" 2>/dev/null)
        case "$cmd" in
            *run.py*)
                echo "发送 USR1 信号到残留 Granian 进程 $pid ..."
                kill -USR1 "$pid" 2>/dev/null && signalled=1
                ;;
        esac
    done
fi

if [ "$signalled" -eq 0 ]; then
    echo "未发现运行中的 Granian，无需重启（直接启动即可）"
    exit 1
fi
