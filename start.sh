#!/usr/bin/env bash
# 自动启动 auto_pipeline 的便捷脚本
# 用法: ./start.sh
# 前置: 在 PC 微信里打开"大众点评"小程序，进入任意一家店的评论页

set -e
cd "$(dirname "$(readlink -f "$0")")"
CLASH_PORT="${CLASH_PORT:-7890}"

echo "🔧 启动器：自动批量采集 388+ 家店评论"
echo "—————————————————————————————"

# 1. 自检 mitmdump
if ! ss -ltn 2>/dev/null | grep -q ':9092 '; then
  echo "📡 启动 mitmdump 9092 (with DP_SEARCH_REWRITE=1)"
  mkdir -p mitm_logs
  nohup env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy DP_SEARCH_REWRITE=1 mitmdump \
    --listen-port 9092 \
    --set ssl_insecure=true \
    -s "$(pwd)/dianping_interceptor.py" \
    > mitm_logs/manual_mitmdump.log 2>&1 &
  disown
  sleep 4
  ss -ltn 2>/dev/null | grep -q ':9092 ' || { echo "❌ mitmdump 启动失败，见 mitm_logs/manual_mitmdump.log"; exit 1; }
fi
echo "✅ mitmdump 9092 监听中"

# 2. 强制 Clash 分流
python3 -c "
import sys; sys.path.insert(0, '.')
from manual_review_console import enable_clash_mitm_rule
enable_clash_mitm_rule(proxy_port=9092, include_search_domains=False)
"
echo "✅ Clash 点评 API → DP-MITM 已启用；系统代理仍保持 ${CLASH_PORT}"

# 3. 启动 auto_pipeline（前台，方便看输出）
echo
echo "🚀 启动 auto_pipeline.py"
echo "   日志会同时写入 output/auto_pipeline_log.jsonl"
echo "   单店超时 420s，每 5 家自动审计"
echo "   Ctrl+C 可随时中止"
echo
exec python3 auto_pipeline.py "$@"
