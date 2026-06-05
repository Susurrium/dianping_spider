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
CLASH_PORT="${CLASH_PORT:-7890}"
UPSTREAM_PROXY="${UPSTREAM_PROXY:-http://127.0.0.1:${CLASH_PORT}}"
WECHAT_PLATFORM="${WECHAT_PLATFORM:-auto}"
WECHAT_WIN_EXE="${WECHAT_WIN_EXE:-}"
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

WSL_INTEROP_AVAILABLE=0
if grep -qi microsoft /proc/version 2>/dev/null && command -v cmd.exe >/dev/null 2>&1; then
  WSL_INTEROP_AVAILABLE=1
fi

find_windows_wechat() {
  if [ -n "$WECHAT_WIN_EXE" ]; then
    printf '%s\n' "$WECHAT_WIN_EXE"
    return 0
  fi
  for candidate in \
    "/mnt/c/Program Files/Tencent/WeChat/WeChat.exe" \
    "/mnt/c/Program Files (x86)/Tencent/WeChat/WeChat.exe" \
    "/mnt/c/Users/${USER}/AppData/Roaming/Tencent/WeChat/WeChat.exe"
  do
    if [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  for candidate in /mnt/c/Users/*/AppData/Roaming/Tencent/WeChat/WeChat.exe; do
    if [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

to_windows_path() {
  local path="$1"
  if [[ "$path" =~ ^[A-Za-z]:\\ ]]; then
    printf '%s\n' "$path"
  else
    wslpath -w "$path"
  fi
}

choose_wechat_platform() {
  case "$WECHAT_PLATFORM" in
    linux|windows)
      printf '%s\n' "$WECHAT_PLATFORM"
      ;;
    auto)
      if [ "$WSL_INTEROP_AVAILABLE" -eq 1 ] && find_windows_wechat >/dev/null; then
        printf 'windows\n'
      else
        printf 'linux\n'
      fi
      ;;
    *)
      echo "Unsupported WECHAT_PLATFORM=$WECHAT_PLATFORM (use auto, windows, or linux)" >&2
      exit 1
      ;;
  esac
}

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
if [ "$WSL_INTEROP_AVAILABLE" -eq 1 ]; then
  taskkill.exe /IM WeChat.exe /F >/dev/null 2>&1 || true
  taskkill.exe /IM WeChatAppEx.exe /F >/dev/null 2>&1 || true
fi
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

wechat_platform="$(choose_wechat_platform)"
if [ "$wechat_platform" = "windows" ]; then
  WINDOWS_WECHAT="$(find_windows_wechat || true)"
  if [ -z "$WINDOWS_WECHAT" ]; then
    echo "❌ Windows WeChat executable not found"
    echo "   Use WECHAT_WIN_EXE='/mnt/c/Program Files/Tencent/WeChat/WeChat.exe' bash start_mitm.sh"
    exit 1
  fi
  WINDOWS_WECHAT_PATH="$(to_windows_path "$WINDOWS_WECHAT")"
  cmd.exe /C start "" "$WINDOWS_WECHAT_PATH"
  echo "✅ Windows 微信已启动: $WINDOWS_WECHAT"
  echo "   Windows 微信使用 Windows 代理设置；请确认 Clash 监听 ${CLASH_PORT}"
else
  # 启动 Linux 微信（不再用环境变量，让它读系统代理）
  if [ ! -x "$WECHAT_BIN" ]; then
    echo "❌ Linux 微信可执行文件不存在或不可执行: $WECHAT_BIN"
    echo "   可通过 WECHAT_BIN=/path/to/WeChatLinux_x86_64.AppImage bash start_mitm.sh 指定"
    echo "   WSL + Windows 微信可用 WECHAT_PLATFORM=windows WECHAT_WIN_EXE=/mnt/c/.../WeChat.exe"
    exit 1
  fi
  nohup "$WECHAT_BIN" \
      > /tmp/wx.log 2>&1 &
  disown
  echo "✅ Linux 微信已启动"
fi
sleep 3

echo
echo "下一步:"
echo "  1. 扫码登录 → 进大众点评 → 进店评价页"
echo "  2. python3 run.py"
echo
echo "退出时记得运行: bash stop_mitm.sh （恢复系统代理）"
echo
echo "实时看抓取日志: tail -f /tmp/mitm_capture.log"
