#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR/backend"

PID_FILE="$DIR/dashboard.pid"

# 优先选择拥有依赖的 python
if [ -f "/home/ubuntu/antigravity-feishu-bot/venv/bin/python3" ]; then
    PY_BIN="/home/ubuntu/antigravity-feishu-bot/venv/bin/python3"
elif [ -f "$DIR/venv/bin/python3" ]; then
    PY_BIN="$DIR/venv/bin/python3"
else
    PY_BIN="$(which python3)"
fi

if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "Headscale 控制台已在运行中 (PID: $(cat "$PID_FILE"))"
    exit 0
fi

echo "正在启动 Headscale 控制台服务..."
setsid $PY_BIN main.py </dev/null > "$DIR/dashboard.log" 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$PID_FILE"

sleep 2

if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "✅ 控制台启动成功！PID: $(cat "$PID_FILE")"
    echo "🌐 本地访问地址: http://127.0.0.1:8086"
    echo "📄 运行日志文件: $DIR/dashboard.log"
else
    echo "❌ 启动失败，请检查日志: $DIR/dashboard.log"
    cat "$DIR/dashboard.log"
    exit 1
fi
