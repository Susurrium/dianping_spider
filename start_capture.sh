#!/bin/bash
# 用户自己启动这个脚本来开始抓包，不会被 codex 工具调用 SIGTERM 杀
# 用法: bash start_capture.sh
set -e
PCAP=/tmp/wx_capture/raw.pcap
mkdir -p /tmp/wx_capture
echo "🚀 启动 tshark 持续抓 wlp2s0 上的 443 流量"
echo "   pcap: $PCAP"
echo "   keys: /tmp/wx_keys.log"
echo "   按 Ctrl+C 停止"
exec sg wireshark -c "tshark -i wlp2s0 -f 'tcp port 443' -w $PCAP"
