#!/usr/bin/env bash
# Stop mitmdump/WeChat and restore the proxy saved by start_mitm.sh.

MITM_PORT="${MITM_PORT:-8080}"
CLASH_PORT="${CLASH_PORT:-7890}"

if command -v fuser >/dev/null 2>&1; then
  fuser -k "${MITM_PORT}/tcp" 2>/dev/null || sudo fuser -k "${MITM_PORT}/tcp" 2>/dev/null || true
fi

killall -9 wechat WeChatAppEx wxocr wxplayer crashpad_handler 2>/dev/null || true
pkill -9 -f WeChatLinux 2>/dev/null || true
if grep -qi microsoft /proc/version 2>/dev/null && command -v taskkill.exe >/dev/null 2>&1; then
  taskkill.exe /IM WeChat.exe /F >/dev/null 2>&1 || true
  taskkill.exe /IM WeChatAppEx.exe /F >/dev/null 2>&1 || true
fi
sleep 1

ORIG_HTTP_PORT=$(cat /tmp/.proxy_orig_http_port 2>/dev/null)
ORIG_HTTPS_PORT=$(cat /tmp/.proxy_orig_https_port 2>/dev/null)
ORIG_MODE=$(cat /tmp/.proxy_orig_mode 2>/dev/null)

if [ -n "$ORIG_HTTP_PORT" ]; then
  gsettings set org.gnome.system.proxy.http port "$ORIG_HTTP_PORT"
  gsettings set org.gnome.system.proxy.https port "$ORIG_HTTPS_PORT"
  gsettings set org.gnome.system.proxy mode "${ORIG_MODE//\'/}"
  echo "Restored WSL proxy: http=$ORIG_HTTP_PORT https=$ORIG_HTTPS_PORT"
else
  gsettings set org.gnome.system.proxy mode 'manual'
  gsettings set org.gnome.system.proxy.http host '127.0.0.1'
  gsettings set org.gnome.system.proxy.http port "$CLASH_PORT"
  gsettings set org.gnome.system.proxy.https host '127.0.0.1'
  gsettings set org.gnome.system.proxy.https port "$CLASH_PORT"
  echo "Restored WSL proxy to Clash port ${CLASH_PORT}"
fi

rm -f /tmp/.proxy_orig_http_port /tmp/.proxy_orig_https_port /tmp/.proxy_orig_mode
echo "Stopped"
