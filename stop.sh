#!/usr/bin/env bash
# 停止后台 auto_pipeline
cd "$(dirname "$(readlink -f "$0")")"
PID_FILE="output/.auto_pipeline.pid"
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "停止 auto_pipeline PID=$PID"
    kill "$PID"
    sleep 2
    if kill -0 "$PID" 2>/dev/null; then
      kill -9 "$PID"
    fi
    rm -f "$PID_FILE"
    echo "✅ 已停止"
  else
    echo "PID $PID 已不存在"
    rm -f "$PID_FILE"
  fi
else
  pkill -f 'auto_pipeline.py' && echo "通过 pkill 停止" || echo "无运行中的 auto_pipeline"
fi
