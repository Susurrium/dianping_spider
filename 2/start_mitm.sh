#!/bin/bash
# 启动 mitmdump + 微信
#
# 方案：
#   - 临时把系统代理从 7890 切到 8080（mitmdump）
#   - mitmdump 上游 = 7890 (Clash)
#   - 微信小程序(WeChatAppEx)自动读系统代理 → 走 mitmdump
#   - 跑完用 stop_mitm.sh 恢复系统代理

cd /home/hetaisheng/dianping_spider || exit 1

# 1. 备份当前系统代理设置
ORIG_HTTP_PORT=$(gsettings get org.gnome.system.proxy.http port)
ORIG_HTTPS_PORT=$(gsettings get org.gnome.system.proxy.https port)
ORIG_MODE=$(gsettings get org.gnome.system.proxy mode)
echo "$ORIG_HTTP_PORT" > /tmp/.proxy_orig_http_port
echo "$ORIG_HTTPS_PORT" > /tmp/.proxy_orig_https_port
echo "$ORIG_MODE" > /tmp/.proxy_orig_mode
echo "📦 备份原代理: http=$ORIG_HTTP_PORT https=$ORIG_HTTPS_PORT mode=$ORIG_MODE"

# 2. 杀旧 mitmdump + 微信
echo '1234' | sudo -S -p '' fuser -k 8080/tcp 2>/dev/null || true
killall -9 wechat WeChatAppEx wxocr wxplayer crashpad_handler 2>/dev/null || true
pkill -9 -f WeChatLinux 2>/dev/null || true
sleep 3
echo '1234' | sudo -S -p '' umount -l /tmp/.mount_WeChat* 2>/dev/null || true
rm -rf ~/.xwechat/lock && mkdir -p ~/.xwechat/lock

if pgrep -f "WeChatLinux\|WeChatAppEx" > /dev/null; then
  echo "⚠️ 还有残留微信进程，强杀"
  pgrep -f "WeChatLinux\|WeChatAppEx" | xargs -r kill -9 2>/dev/null
  sleep 2
fi

# 3. 启动 mitmdump（监听 8080，上游 Clash 7890）
> /tmp/mitm_capture.log
> /tmp/mitmdump_out.log
nohup mitmdump \
  -s /home/hetaisheng/dianping_spider/mitm_dianping.py \
  -p 8080 \
  --mode upstream:http://127.0.0.1:7890 \
  -q < /dev/null > /tmp/mitmdump_out.log 2>&1 &
disown
sleep 4

if ! pgrep -f 'mitmdump.*8080' > /dev/null; then
  echo "❌ mitmdump 启动失败"
  cat /tmp/mitmdump_out.log
  exit 1
fi
echo "✅ mitmdump 已启动 (8080 → Clash 7890)"

# 4. 切换系统代理到 8080（mitmdump）
gsettings set org.gnome.system.proxy mode 'manual'
gsettings set org.gnome.system.proxy.http host '127.0.0.1'
gsettings set org.gnome.system.proxy.http port 8080
gsettings set org.gnome.system.proxy.https host '127.0.0.1'
gsettings set org.gnome.system.proxy.https port 8080
echo "🔀 系统代理切换到 8080 (mitmdump)"

# 5. 启动微信（不再用环境变量，让它读系统代理）
nohup /home/hetaisheng/.local/opt/wechat/current/WeChatLinux_x86_64.AppImage \
    > /tmp/wx.log 2>&1 &
disown
sleep 3

echo "✅ 微信已启动"
echo
echo "下一步:"
echo "  1. 扫码登录 → 进大众点评 → 进店评价页"
echo "  2. python3 go.py"
echo
echo "退出时记得运行: bash stop_mitm.sh （恢复系统代理为 7890）"
echo
echo "实时看抓取日志: tail -f /tmp/mitm_capture.log"
