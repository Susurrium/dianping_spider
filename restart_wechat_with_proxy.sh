#!/usr/bin/env bash
# Restart PC WeChat and point it at the selected Clash port.
#
# Usage examples:
#   bash restart_wechat_with_proxy.sh
#   CLASH_PORT=17890 bash restart_wechat_with_proxy.sh
#   WECHAT_PLATFORM=windows WECHAT_WIN_EXE='/mnt/c/Program Files/Tencent/WeChat/WeChat.exe' bash restart_wechat_with_proxy.sh
#   WECHAT_PLATFORM=linux WECHAT_BIN=/opt/wechat/WeChatLinux_x86_64.AppImage bash restart_wechat_with_proxy.sh

set -e

CLASH_PORT="${CLASH_PORT:-7890}"
PROXY_URL="http://127.0.0.1:${CLASH_PORT}"
WECHAT_PLATFORM="${WECHAT_PLATFORM:-auto}"
WECHAT_BIN="${WECHAT_BIN:-}"
WECHAT_WIN_EXE="${WECHAT_WIN_EXE:-}"
WSL_INTEROP_AVAILABLE=0
if grep -qi microsoft /proc/version 2>/dev/null && command -v cmd.exe >/dev/null 2>&1; then
  WSL_INTEROP_AVAILABLE=1
fi

find_linux_wechat() {
  for candidate in \
    "$HOME/.local/opt/wechat/current/WeChatLinux_x86_64.AppImage" \
    "$HOME/Applications/WeChatLinux_x86_64.AppImage" \
    "/opt/wechat/WeChatLinux_x86_64.AppImage"
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

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

stop_linux_wechat() {
  for proc in 'WeChatAppEx' 'wechat\b' 'WeChatLinux_x86_64.AppImage' 'WeChatLinux'; do
    pids=$(pgrep -f "$proc" 2>/dev/null || true)
    if [ -n "$pids" ]; then
      echo "  killing Linux process $proc: $pids"
      echo "$pids" | xargs -r kill 2>/dev/null || true
    fi
  done
  sleep 2
  for proc in 'WeChatAppEx' 'wechat\b' 'WeChatLinux'; do
    pids=$(pgrep -f "$proc" 2>/dev/null || true)
    if [ -n "$pids" ]; then
      echo "$pids" | xargs -r kill -9 2>/dev/null || true
    fi
  done
}

stop_windows_wechat() {
  if [ "$WSL_INTEROP_AVAILABLE" -eq 1 ]; then
    taskkill.exe /IM WeChat.exe /F >/dev/null 2>&1 || true
    taskkill.exe /IM WeChatAppEx.exe /F >/dev/null 2>&1 || true
  fi
}

start_linux_wechat() {
  local wechat="$1"
  if [ ! -x "$wechat" ]; then
    echo "  Linux WeChat is not executable: $wechat"
    exit 1
  fi
  HTTP_PROXY="$PROXY_URL" \
  HTTPS_PROXY="$PROXY_URL" \
  http_proxy="$PROXY_URL" \
  https_proxy="$PROXY_URL" \
  ALL_PROXY="$PROXY_URL" \
  all_proxy="$PROXY_URL" \
  NO_PROXY="localhost,127.0.0.1,::1" \
  no_proxy="localhost,127.0.0.1,::1" \
  nohup "$wechat" > /tmp/wechat_with_proxy.log 2>&1 &
  disown
}

start_windows_wechat() {
  local wechat="$1"
  if [ "$WSL_INTEROP_AVAILABLE" -ne 1 ]; then
    echo "  Windows WeChat launch requires WSL interop (cmd.exe)."
    exit 1
  fi
  if [[ ! "$wechat" =~ ^[A-Za-z]:\\ ]] && [ ! -f "$wechat" ]; then
    echo "  Windows WeChat executable not found: $wechat"
    echo "  Set WECHAT_WIN_EXE to a Windows path or /mnt/c path."
    exit 1
  fi
  local win_path
  win_path="$(to_windows_path "$wechat")"
  cmd.exe /C start "" "$win_path"
}

choose_platform() {
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

echo "=== 1. Stop old WeChat processes ==="
stop_linux_wechat
stop_windows_wechat
echo "  WeChat processes stopped where accessible"

echo
echo "=== 2. Ensure WSL GNOME proxy uses Clash port ${CLASH_PORT} ==="
if command -v gsettings >/dev/null 2>&1; then
  gsettings set org.gnome.system.proxy mode 'manual' || true
  gsettings set org.gnome.system.proxy.http host '127.0.0.1' || true
  gsettings set org.gnome.system.proxy.http port "$CLASH_PORT" || true
  gsettings set org.gnome.system.proxy.https host '127.0.0.1' || true
  gsettings set org.gnome.system.proxy.https port "$CLASH_PORT" || true
  echo "  WSL proxy: $(gsettings get org.gnome.system.proxy mode 2>/dev/null || echo unknown) :$(gsettings get org.gnome.system.proxy.http port 2>/dev/null || echo "$CLASH_PORT")"
else
  echo "  gsettings not found; skipped WSL GNOME proxy update"
fi

echo
echo "=== 3. Start WeChat (${WECHAT_PLATFORM}) ==="
platform="$(choose_platform)"
case "$platform" in
  windows)
    wechat="$(find_windows_wechat || true)"
    if [ -z "$wechat" ]; then
      echo "  Windows WeChat not found. Set WECHAT_WIN_EXE, for example:"
      echo "  WECHAT_WIN_EXE='/mnt/c/Program Files/Tencent/WeChat/WeChat.exe' bash restart_wechat_with_proxy.sh"
      exit 1
    fi
    start_windows_wechat "$wechat"
    echo "  Started Windows WeChat: $wechat"
    echo "  Note: Windows WeChat uses Windows proxy settings; keep Clash listening on ${CLASH_PORT}."
    ;;
  linux)
    wechat="${WECHAT_BIN:-$(find_linux_wechat || true)}"
    if [ -z "$wechat" ]; then
      echo "  Linux WeChat not found. Set WECHAT_BIN or use WECHAT_PLATFORM=windows WECHAT_WIN_EXE=..."
      exit 1
    fi
    start_linux_wechat "$wechat"
    echo "  Started Linux WeChat with proxy env ${PROXY_URL}: $wechat"
    ;;
esac

sleep 5

echo
echo "=== 4. Next steps ==="
echo "  a. Log in to WeChat if needed"
echo "  b. Open the Dianping mini program"
echo "  c. Enter a store review page"
echo "  d. Open http://127.0.0.1:8765/"
echo "  e. Click the reliable fast capture button"
