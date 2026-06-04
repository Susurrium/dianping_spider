#!/bin/bash
# 在 SSLKEYLOGFILE 模式 和 mitmdump 模式 之间切换
#
# 用法:
#   bash switch_mode.sh mitm        # 切到 mitmdump（推荐，更稳定）
#   bash switch_mode.sh keylog      # 切到 SSLKEYLOGFILE（旧）
#   bash switch_mode.sh status      # 看现在是哪个模式

set -e
ROOT=/home/hetaisheng/dianping_spider
cd $ROOT

case "${1:-status}" in

  status)
    echo "=== 微信进程 ==="
    WX_PID=$(for pid in $(ls /proc/ | grep -E '^[0-9]+$'); do
      exe=$(readlink /proc/$pid/exe 2>/dev/null)
      if [[ "$exe" == */wechat ]] && [[ "$exe" != *AppEx ]]; then echo $pid; break; fi
    done)
    if [ -z "$WX_PID" ]; then
      echo "  ❌ 微信没在跑"
      echo
      echo "=== 当前模式: 无 ==="
      exit 0
    fi

    echo "  ✅ 微信 PID: $WX_PID"

    PROXY=$(cat /proc/$WX_PID/environ 2>/dev/null | tr '\0' '\n' | grep -i 'https_proxy=' | head -1)
    KEYLOG=$(cat /proc/$WX_PID/environ 2>/dev/null | tr '\0' '\n' | grep -i 'SSLKEYLOGFILE=' | head -1)
    MITMPID=$(pgrep -f 'mitmdump.*8080' | head -1)

    echo
    if [ -n "$PROXY" ] && [ -n "$MITMPID" ]; then
      echo "=== 当前模式: mitmdump ✅ ==="
      echo "  $PROXY"
      echo "  mitmdump PID: $MITMPID"
      echo
      echo "  抓评论: python3 scroll.py <编号>"
    elif [ -n "$KEYLOG" ]; then
      echo "=== 当前模式: SSLKEYLOGFILE ✅ ==="
      echo "  $KEYLOG"
      KEYS_LINES=$(wc -l < /tmp/wx_keys.log 2>/dev/null || echo 0)
      echo "  keys 文件: $KEYS_LINES 行"
      echo
      echo "  抓评论: python3 grab.py <编号>"
    else
      echo "=== 当前模式: 未知（微信没带任何注入）==="
      echo "  $PROXY"
      echo "  $KEYLOG"
    fi
    ;;

  mitm)
    echo "=== 切到 mitmdump 模式 ==="

    # 杀微信
    killall -9 wechat WeChatAppEx crashpad_handler 2>/dev/null || true
    sleep 2
    echo '1234' | sudo -S -p '' umount -l /tmp/.mount_WeChat* 2>/dev/null || true
    rm -rf ~/.xwechat/lock && mkdir -p ~/.xwechat/lock

    # 启 mitmdump
    if ! pgrep -f 'mitmdump.*8080' > /dev/null; then
      echo '1234' | sudo -S -p '' fuser -k 8080/tcp 2>/dev/null || true
      sleep 1
      > /tmp/mitm_capture.log
      nohup mitmdump -s mitm_dianping.py -p 8080 \
        --mode upstream:http://127.0.0.1:7890 \
        -q < /dev/null > /tmp/mitmdump_out.log 2>&1 &
      disown
      sleep 3
    fi

    if ! pgrep -f 'mitmdump.*8080' > /dev/null; then
      echo "❌ mitmdump 启动失败"
      cat /tmp/mitmdump_out.log
      exit 1
    fi
    echo "✅ mitmdump 在跑（8080 → Clash 7890）"

    # 启微信带 https_proxy
    env https_proxy=http://127.0.0.1:8080 http_proxy=http://127.0.0.1:8080 \
        HTTPS_PROXY=http://127.0.0.1:8080 HTTP_PROXY=http://127.0.0.1:8080 \
        no_proxy='' NO_PROXY='' \
        nohup /home/hetaisheng/.local/opt/wechat/current/WeChatLinux_x86_64.AppImage \
        > /tmp/wx.log 2>&1 &
    disown
    sleep 4
    echo "✅ 微信启动（代理 → mitmdump）"
    echo
    echo "  扫码登录 → 进大众点评 → 进店评价页"
    echo "  抓评论:  python3 scroll.py <编号>"
    ;;

  keylog)
    echo "=== 切到 SSLKEYLOGFILE 模式 ==="

    # 杀微信 + mitmdump
    killall -9 wechat WeChatAppEx crashpad_handler 2>/dev/null || true
    pkill -f mitmdump 2>/dev/null || true
    sleep 2
    echo '1234' | sudo -S -p '' umount -l /tmp/.mount_WeChat* 2>/dev/null || true
    rm -rf ~/.xwechat/lock && mkdir -p ~/.xwechat/lock

    # 启动微信带 SSLKEYLOGFILE
    : > /tmp/wx_keys.log
    SSLKEYLOGFILE=/tmp/wx_keys.log \
      LD_PRELOAD=/tmp/keylog_inject.so \
      nohup /home/hetaisheng/.local/opt/wechat/current/WeChatLinux_x86_64.AppImage \
      > /tmp/wx.log 2>&1 &
    disown
    sleep 4
    echo "✅ 微信启动（SSLKEYLOGFILE=/tmp/wx_keys.log）"
    echo
    echo "  扫码登录后等几秒，验证 keys 写入:"
    echo "    wc -l /tmp/wx_keys.log"
    echo
    echo "  抓评论:  python3 grab.py <编号>"
    ;;

  *)
    echo "用法: bash switch_mode.sh [mitm|keylog|status]"
    exit 1
    ;;
esac
