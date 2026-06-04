#!/bin/bash
# 启动 mitmdump + 微信
#
# 方案：
#   - 临时把系统代理切到 MITM_PORT（默认 8080）
#   - mitmdump 上游 = UPSTREAM_PROXY（默认 http://127.0.0.1:7890）
#   - 微信小程序(WeChatAppEx)自动读系统代理 → 走 mitmdump
#   - 跑完用 stop_mitm.sh 恢复系统代理

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MITM_PORT="${MITM_PORT:-8080}"
UPSTREAM_PROXY="${UPSTREAM_PROXY:-http://127.0.0.1:7890}"
DEFAULT_WECHAT_BIN=""
for candidate in \
  "$HOME/.local/opt/wechat/current/WeChatLinux_x86_64.AppImage" \
  "$HOME/Applications/WeChatLinux_x86_64.AppImage" \
  "/opt/wechat/WeChatLinux_x86_64.AppImage"
do
  if [ -x "$candidate" ]; then
    DEFAULT_WECHAT_BIN="$candidate"
    break
  fi
done
WECHAT_BIN="${WECHAT_BIN:-$DEFAULT_WECHAT_BIN}"

cd "$ROOT_DIR" || exit 1

# 1. 备份当前系统代理设置
ORIG_HTTP_PORT=$(gsettings get org.gnome.system.proxy.http port)
ORIG_HTTPS_PORT=$(gsettings get org.gnome.system.proxy.https port)
ORIG_MODE=$(gsettings get org.gnome.system.proxy mode)
echo "$ORIG_HTTP_PORT" > /tmp/.proxy_orig_http_port
echo "$ORIG_HTTPS_PORT" > /tmp/.proxy_orig_https_port
echo "$ORIG_MODE" > /tmp/.proxy_orig_mode
echo "📦 备份原代理: http=$ORIG_HTTP_PORT https=$ORIG_HTTPS_PORT mode=$ORIG_MODE"

# 2. 杀旧 mitmdump + 微信
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${MITM_PORT}/tcp" 2>/dev/null || sudo fuser -k "${MITM_PORT}/tcp" 2>/dev/null || true
fi
killall -9 wechat WeChatAppEx wxocr wxplayer crashpad_handler 2>/dev/null || true
pkill -9 -f WeChatLinux 2>/dev/null || true
sleep 3
sudo umount -l /tmp/.mount_WeChat* 2>/dev/null || true
rm -rf ~/.xwechat/lock && mkdir -p ~/.xwechat/lock

if pgrep -f "WeChatLinux\|WeChatAppEx" > /dev/null; then
  echo "⚠️ 还有残留微信进程，强杀"
  pgrep -f "WeChatLinux\|WeChatAppEx" | xargs -r kill -9 2>/dev/null
  sleep 2
fi

# 3. 启动 mitmdump
> /tmp/mitm_capture.log
> /tmp/mitmdump_out.log
nohup mitmdump \
  -s "${ROOT_DIR}/mitm_dianping.py" \
  -p "$MITM_PORT" \
  --mode "upstream:${UPSTREAM_PROXY}" \
  -q < /dev/null > /tmp/mitmdump_out.log 2>&1 &
disown
sleep 4

if ! pgrep -f "mitmdump.*${MITM_PORT}" > /dev/null; then
  echo "❌ mitmdump 启动失败"
  cat /tmp/mitmdump_out.log
  exit 1
fi
echo "✅ mitmdump 已启动 (${MITM_PORT} → ${UPSTREAM_PROXY})"

# 4. 切换系统代理到 mitmdump
gsettings set org.gnome.system.proxy mode 'manual'
gsettings set org.gnome.system.proxy.http host '127.0.0.1'
gsettings set org.gnome.system.proxy.http port "$MITM_PORT"
gsettings set org.gnome.system.proxy.https host '127.0.0.1'
gsettings set org.gnome.system.proxy.https port "$MITM_PORT"
echo "🔀 系统代理切换到 ${MITM_PORT} (mitmdump)"

# 5. 启动微信（不再用环境变量，让它读系统代理）
if [ ! -x "$WECHAT_BIN" ]; then
  echo "❌ 微信可执行文件不存在或不可执行: $WECHAT_BIN"
  echo "   可通过 WECHAT_BIN=/path/to/WeChatLinux_x86_64.AppImage bash start_mitm.sh 指定"
  exit 1
fi

nohup "$WECHAT_BIN" \
    > /tmp/wx.log 2>&1 &
disown
sleep 3

echo "✅ 微信已启动"
echo
echo "下一步:"
echo "  1. 扫码登录 → 进大众点评 → 进店评价页"
echo "  2. python3 run.py"
echo
echo "退出时记得运行: bash stop_mitm.sh （恢复系统代理）"
echo
echo "实时看抓取日志: tail -f /tmp/mitm_capture.log"
