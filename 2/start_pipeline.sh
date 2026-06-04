#!/bin/bash
# 在你自己的 terminal 里跑这个脚本（不要在 codex/kiro 工具调用里跑）
# 它会启动一个长时间运行的 Python 进程，几小时内不能被 SIGTERM 杀
#
# 前置条件：
#   1. PC 微信用 wrapper 启动（带 SSLKEYLOGFILE）：
#      bash /tmp/wx_with_keylog.sh
#   2. 微信扫码登录
#   3. 进入大众点评小程序首页
#
# 用法:
#   bash start_pipeline.sh                  # 全跑 389 家
#   bash start_pipeline.sh --limit 5        # 试水 5 家
#   bash start_pipeline.sh --start 100      # 跳前 100 家
#   bash start_pipeline.sh --city 上海      # 只跑上海

set -e
cd /home/hetaisheng/dianping_spider

KEYS=/tmp/wx_keys.log

echo "=========================================="
echo "🚀 大众点评小程序全自动评论采集"
echo "=========================================="

# 1. 环境检查
echo
echo "▶ 环境检查"
if [ ! -f "$KEYS" ]; then
  echo "  ❌ /tmp/wx_keys.log 不存在"
  echo "     请先用 wrapper 启动微信:"
  echo "       bash /tmp/wx_with_keylog.sh"
  exit 1
fi
KEY_LINES=$(wc -l < "$KEYS")
echo "  keys 文件: $KEY_LINES 行"

# 2. 检查 PC 微信窗口
WID=$(xdotool search --name '大众点评' 2>/dev/null | head -1)
if [ -z "$WID" ]; then
  echo "  ❌ 找不到 PC 微信小程序'大众点评'窗口"
  echo "     请先打开 PC 微信 → 大众点评小程序 → 首页"
  exit 1
fi
echo "  窗口 wid=$WID"

# 3. 检查 tshark 工具链
if ! command -v tshark >/dev/null 2>&1; then
  echo "  ❌ tshark 未装: sudo apt install tshark"
  exit 1
fi
if ! groups | grep -q wireshark; then
  echo "  ⚠️ 当前用户不在 wireshark 组（可能影响 tshark 抓包）"
fi
echo "  tshark: $(which tshark)"

# 4. 检查录制好的坐标
if [ ! -f miniapp_points_single_col.json ]; then
  echo "  ❌ 没有录好的坐标，先跑: python3 coord_recorder.py"
  exit 1
fi
echo "  坐标: miniapp_points_single_col.json"

# 5. 启动总控
echo
echo "▶ 启动总控"
echo "  日志: 实时显示 + 进度存到 output/auto_run_progress.json"
echo "  评论: 写入 output/store_reviews/"
echo
exec python3 run_all_stores.py "$@"
