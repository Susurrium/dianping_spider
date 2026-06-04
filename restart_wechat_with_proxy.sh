#!/usr/bin/env bash
# 重启 PC 微信，让流量强制走 Clash 7890 → mitm 9092
# 用法: bash restart_wechat_with_proxy.sh

set -e

echo "=== 1. 关闭旧的微信进程 ==="
for proc in 'WeChatAppEx' 'wechat\b' 'WeChatLinux_x86_64.AppImage'; do
  pids=$(pgrep -f "$proc" 2>/dev/null)
  if [ -n "$pids" ]; then
    echo "  killing $proc: $pids"
    echo "$pids" | xargs -r kill 2>/dev/null
  fi
done
sleep 3
# 强杀残留
for proc in 'WeChatAppEx' 'wechat\b' 'WeChatLinux'; do
  pids=$(pgrep -f "$proc" 2>/dev/null)
  if [ -n "$pids" ]; then
    echo "$pids" | xargs -r kill -9 2>/dev/null
  fi
done
sleep 2
echo "  ✅ 微信全部退出"

echo
echo "=== 2. 确保系统代理 manual 7890 ==="
gsettings set org.gnome.system.proxy mode 'manual'
gsettings set org.gnome.system.proxy.http host '127.0.0.1'
gsettings set org.gnome.system.proxy.http port 7890
gsettings set org.gnome.system.proxy.https host '127.0.0.1'
gsettings set org.gnome.system.proxy.https port 7890
echo "  ✅ 系统代理: $(gsettings get org.gnome.system.proxy mode) :$(gsettings get org.gnome.system.proxy.http port)"

echo
echo "=== 3. 用代理环境变量启动微信 ==="
WECHAT="/home/hetaisheng/.local/opt/wechat/current/WeChatLinux_x86_64.AppImage"
if [ ! -x "$WECHAT" ]; then
  echo "  ❌ 没找到 $WECHAT"
  exit 1
fi

# 关键：注入代理环境变量，让 Chromium 内核自动用 7890
HTTP_PROXY="http://127.0.0.1:7890" \
HTTPS_PROXY="http://127.0.0.1:7890" \
http_proxy="http://127.0.0.1:7890" \
https_proxy="http://127.0.0.1:7890" \
ALL_PROXY="http://127.0.0.1:7890" \
all_proxy="http://127.0.0.1:7890" \
NO_PROXY="localhost,127.0.0.1,::1" \
no_proxy="localhost,127.0.0.1,::1" \
nohup "$WECHAT" > /tmp/wechat_with_proxy.log 2>&1 &
disown
sleep 5

echo
echo "=== 4. 验证微信启动了 ==="
WX_PID=$(pgrep -f WeChatLinux_x86_64.AppImage | head -1)
if [ -n "$WX_PID" ]; then
  echo "  ✅ 微信主进程 PID=$WX_PID"
  echo "  环境变量包含代理:"
  cat /proc/$WX_PID/environ 2>/dev/null | tr '\0' '\n' | grep -iE 'proxy' | head -5
else
  echo "  ❌ 微信启动失败，看 /tmp/wechat_with_proxy.log"
fi

echo
echo "=== 5. 接下来手动操作 ==="
echo "  a. 微信窗口出现后，用手机扫码登录（如果需要）"
echo "  b. 进入大众点评小程序"
echo "  c. 进店 → 进评价页"
echo "  d. 浏览器打开 http://127.0.0.1:8765/"
echo "  e. 点击'可靠极速采当前店'"
echo
echo "  这次新启动的微信进程会读 HTTP_PROXY，所有流量自动经 Clash → mitm 拦截评论"
