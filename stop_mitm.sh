#!/bin/bash
# 停止 mitmdump + 微信，并恢复 start_mitm.sh 备份的系统代理

MITM_PORT="${MITM_PORT:-8080}"

# 1. 停 mitmdump 和微信
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${MITM_PORT}/tcp" 2>/dev/null || sudo fuser -k "${MITM_PORT}/tcp" 2>/dev/null || true
fi
killall -9 wechat WeChatAppEx wxocr wxplayer crashpad_handler 2>/dev/null || true
pkill -9 -f WeChatLinux 2>/dev/null || true
sleep 1

# 2. 恢复系统代理
ORIG_HTTP_PORT=$(cat /tmp/.proxy_orig_http_port 2>/dev/null)
ORIG_HTTPS_PORT=$(cat /tmp/.proxy_orig_https_port 2>/dev/null)
ORIG_MODE=$(cat /tmp/.proxy_orig_mode 2>/dev/null)

if [ -n "$ORIG_HTTP_PORT" ]; then
  gsettings set org.gnome.system.proxy.http port $ORIG_HTTP_PORT
  gsettings set org.gnome.system.proxy.https port $ORIG_HTTPS_PORT
  gsettings set org.gnome.system.proxy mode "${ORIG_MODE//\'/}"
  echo "✅ 系统代理已恢复: http=$ORIG_HTTP_PORT https=$ORIG_HTTPS_PORT"
else
  # 没有备份就强制恢复到 7890
  gsettings set org.gnome.system.proxy mode 'manual'
  gsettings set org.gnome.system.proxy.http host '127.0.0.1'
  gsettings set org.gnome.system.proxy.http port 7890
  gsettings set org.gnome.system.proxy.https host '127.0.0.1'
  gsettings set org.gnome.system.proxy.https port 7890
  echo "✅ 系统代理强制恢复为 7890"
fi

rm -f /tmp/.proxy_orig_http_port /tmp/.proxy_orig_https_port /tmp/.proxy_orig_mode
echo "✅ 已停止"
