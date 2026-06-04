#!/bin/bash
# 单店端到端全自动：tshark 抓 + 自动化点击 + 解析 + 存 JSON
#
# 用法: bash single_shop_e2e.sh '达美乐比萨拱秀路店' [scrolls=8] [duration=90]
#
# 输出: output/store_reviews/<shopuuid>.json (包含店名 + 完整评论列表)

set -e
cd /home/hetaisheng/dianping_spider

KEYWORD="${1:-达美乐比萨拱秀路店}"
SCROLLS="${2:-8}"
DURATION="${3:-90}"
KEYS=/tmp/wx_keys.log
PCAP=/tmp/wx_capture/raw.pcap

mkdir -p /tmp/wx_capture output/store_reviews

echo "=========================================="
echo "🚀 单店端到端全自动"
echo "  关键词: $KEYWORD"
echo "  滚动:   $SCROLLS 次"
echo "  抓包:   $DURATION 秒"
echo "  时间:   $(date +%H:%M:%S)"
echo "=========================================="

# 1. 检查环境
if [ ! -f "$KEYS" ] || [ "$(wc -l < $KEYS)" -lt 5 ]; then
  echo "❌ keys 文件无效: $KEYS"
  exit 1
fi
WID=$(xdotool search --name '大众点评' 2>/dev/null | head -1)
if [ -z "$WID" ]; then
  echo "❌ 找不到大众点评窗口"
  exit 1
fi
echo "✅ keys: $(wc -l < $KEYS) 行, 窗口 wid=$WID"

# 2. 启动 tshark 在后台
rm -f $PCAP
echo
echo "▶ 启动 tshark $DURATION 秒..."
sg wireshark -c "tshark -i wlp2s0 -f 'tcp port 443' -w $PCAP -a duration:$DURATION 2>/tmp/tshark.err" \
  >/tmp/tshark.out 2>&1 &
TSHARK_PID=$!
sleep 3
ps -p $TSHARK_PID >/dev/null 2>&1 && echo "  tshark 已启动 PID=$TSHARK_PID" || (echo "  ❌ tshark 启动失败"; cat /tmp/tshark.err; exit 1)

# 3. 跑自动化点击
echo
echo "▶ 自动化点击流程"
python3 test_single_shop.py --keyword "$KEYWORD" --scrolls $SCROLLS 2>&1 | sed 's/^/    /'

# 4. 等 tshark 完成
echo
echo "▶ 等 tshark 完成..."
wait $TSHARK_PID 2>/dev/null
PCAP_SIZE=$(stat -c %s "$PCAP" 2>/dev/null)
echo "  pcap: $PCAP_SIZE bytes"

# 5. 解析 pcap → mitm_logs/review_*.json + events.jsonl
echo
echo "▶ collector 解析 pcap"
PRE_REV=$(ls mitm_logs/review_*.json 2>/dev/null | wc -l)
python3 sslkey_collector.py --pcap "$PCAP" --keys "$KEYS" 2>&1 | grep -E '✅|review|outsidesifted|📊|📦' | head -20
POST_REV=$(ls mitm_logs/review_*.json 2>/dev/null | wc -l)
NEW_REV=$((POST_REV - PRE_REV))
echo "  新增 review_*.json: $NEW_REV"

# 6. 整理评论 → output/store_reviews/<shopuuid>.json
echo
echo "▶ 整理评论 → output/store_reviews/"
python3 - <<'PYEOF'
import json
import re
from pathlib import Path
from datetime import datetime

LOG_DIR = Path('mitm_logs')
OUT_DIR = Path('output/store_reviews')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 从 review_*.json 文件名提取 shopuuid
# 找最近 5 分钟的文件
import time
cutoff = time.time() - 300

shop_data = {}  # shopuuid -> {name, all_reviews: [...]}
for f in LOG_DIR.glob('review_*.json'):
    if f.stat().st_mtime < cutoff:
        continue
    m = re.match(r'review_([A-Za-z0-9_-]+)_\d+_\d+\.json$', f.name)
    if not m:
        continue
    shopuuid = m.group(1)
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        continue
    name = d.get('storeName', '') or ''
    data = d.get('data', {})
    
    # 评论列表的位置：data.data.list 或 data.list
    review_list = []
    if isinstance(data, dict):
        inner = data.get('data') if isinstance(data.get('data'), dict) else data
        if isinstance(inner, dict):
            review_list = inner.get('list', [])
    
    if not review_list:
        continue
    
    # 提取评论文本（reviewBody 是详细文本）
    extracted = []
    for r in review_list:
        if not isinstance(r, dict):
            continue
        rid = r.get('reviewId', '') or r.get('reviewID', '')
        # 用户名
        user_info = r.get('userInfo', {}) if isinstance(r.get('userInfo'), dict) else {}
        user_name = user_info.get('userName') or r.get('userName', '')
        # 文本
        body = r.get('reviewBody', '') or r.get('reviewText', '') or r.get('content', '')
        # 时间
        add_time = r.get('reviewIndexes', {}).get('addTime') if isinstance(r.get('reviewIndexes'), dict) else r.get('addTime', '')
        if not add_time:
            add_time = r.get('createDateString') or r.get('createTime') or ''
        # 评分
        star = r.get('star', 0)
        # 图片
        photos = []
        if isinstance(r.get('reviewPics'), list):
            for p in r['reviewPics']:
                if isinstance(p, dict) and p.get('bigUrl'):
                    photos.append(p['bigUrl'])
        extracted.append({
            'reviewId': rid,
            'userName': user_name,
            'addTime': add_time,
            'star': star,
            'text': body,
            'photos': photos,
        })
    
    if shopuuid not in shop_data:
        shop_data[shopuuid] = {'storeName': name, 'reviews': []}
    if name and not shop_data[shopuuid]['storeName']:
        shop_data[shopuuid]['storeName'] = name
    shop_data[shopuuid]['reviews'].extend(extracted)

# 去重 reviewId + 写入
for shopuuid, info in shop_data.items():
    seen = set()
    deduped = []
    for r in info['reviews']:
        rid = r.get('reviewId') or (r.get('userName') + r.get('text', '')[:20])
        if rid in seen:
            continue
        seen.add(rid)
        deduped.append(r)
    
    out = {
        'shopuuid': shopuuid,
        'storeName': info['storeName'],
        'reviewCount': len(deduped),
        'capturedAt': datetime.now().isoformat(timespec='seconds'),
        'reviews': deduped,
    }
    out_file = OUT_DIR / f'{shopuuid}.json'
    out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  💾 {shopuuid}: {info['storeName']} -> {len(deduped)} 条评论 -> {out_file}")

if not shop_data:
    print("  ⚠️ 没有抓到任何评论数据（可能 tshark 没抓到 outsidesiftedreviewlist API）")
PYEOF

echo
echo "=========================================="
echo "✅ 完成 $(date +%H:%M:%S)"
echo "=========================================="
