#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/dashboard.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "正在停止 Headscale 控制台 (PID: $PID)..."
        kill "$PID" || kill -9 "$PID"
        rm -f "$PID_FILE"
        echo "✅ 服务已停止"
    else
        echo "进程未运行，清除 PID 文件"
        rm -f "$PID_FILE"
    fi
else
    echo "未发现运行中的服务 PID 文件"
fi
