#!/bin/bash
# 解析当前 pcap，落库评论数据
set -e
cd /home/hetaisheng/dianping_spider
PCAP=${1:-/tmp/wx_capture/raw.pcap}
echo "📦 解析 $PCAP"
ls -la $PCAP
python3 sslkey_collector.py --pcap $PCAP --keys /tmp/wx_keys.log 2>&1 | tail -30
echo
echo "=== 抓到的店统计 ==="
ls mitm_logs/review_*.json 2>/dev/null | sed 's/.*review_\([^_]*\)_.*/\1/' | sort -u | wc -l
echo "  unique shopuuid 数"
