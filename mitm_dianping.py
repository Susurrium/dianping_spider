# -*- coding:utf-8 -*-
"""mitmdump addon: 抓 dianping 评论 API + 直接写入 store_reviews"""
import json
import gzip
from pathlib import Path
from datetime import datetime
from mitmproxy import http
import tempfile

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / 'output' / 'store_reviews'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 当前抓的店（grab.py 通过文件传递）
TARGET_FILE = Path('/tmp/mitm_target.json')


def load_target():
    if not TARGET_FILE.exists():
        return None
    try:
        return json.loads(TARGET_FILE.read_text())
    except Exception:
        return None


def extract_richtext(node):
    """递归提取富文本(reviewBody)里的纯文字"""
    out = []
    if isinstance(node, dict):
        if isinstance(node.get('text'), str):
            out.append(node['text'])
        for v in node.values():
            if isinstance(v, (dict, list)):
                out.append(extract_richtext(v))
    elif isinstance(node, list):
        for x in node:
            out.append(extract_richtext(x))
    return ''.join(out)


def extract_text(r):
    """提取评论文字（兼容 content / reviewBody 两种格式）"""
    c = r.get('content')
    if isinstance(c, str) and c:
        return c
    rb = r.get('reviewBody')
    if isinstance(rb, str) and rb:
        return rb
    if isinstance(rb, dict):
        return extract_richtext(rb)
    return ''


def extract_time(r):
    """提取发布时间（兼容多种字段）"""
    import re
    t = r.get('time')
    if isinstance(t, str) and t.strip():
        return t.strip()
    t = r.get('lastTimeStr')
    if isinstance(t, str) and t.strip():
        return t.strip()
    iso = r.get('addTime') or r.get('lastTime')
    if isinstance(iso, str):
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', iso)
        if m:
            return f"{int(m.group(2))}月{int(m.group(3))}日"
    return ''


def extract_score(r):
    """提取顾客评分，统一成 5 / 4 / 3.5 这种格式。"""
    for key in ('star', 'score', 'starScore', 'rating', 'accurateStar'):
        v = r.get(key)
        if v is None:
            continue
        try:
            num = float(v)
        except (TypeError, ValueError):
            text = str(v).strip()
            if text:
                return text
            continue
        if num > 10:
            num = num / 10
        if float(num).is_integer():
            return str(int(num))
        return str(num)
    return ''


def merge_rows(target, rows):
    safe = target['name'].replace('/', '_')
    out = OUT_DIR / f"{target['idx']:03d}_{safe}.json"
    existing = []
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding='utf-8'))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    seen = {}
    for item in existing:
        key = (item.get('发布人', ''), item.get('文字', '')[:40])
        seen[key] = item

    new_count = 0
    for row in rows:
        key = (row.get('发布人', ''), row.get('文字', '')[:40])
        old = seen.get(key)
        if old is None:
            existing.append(row)
            seen[key] = row
            new_count += 1
            continue
        if (not old.get('顾客评分')) and row.get('顾客评分'):
            old['顾客评分'] = row.get('顾客评分', '')
        if (not old.get('评分')) and row.get('评分'):
            old['评分'] = row.get('评分', '')
        if (not old.get('发布时间')) and row.get('发布时间'):
            old['发布时间'] = row.get('发布时间', '')
        if (not old.get('发布人')) and row.get('发布人'):
            old['发布人'] = row.get('发布人', '')

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', delete=False, dir=out.parent, encoding='utf-8') as tmp:
        json.dump(existing, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    tmp_path.replace(out)
    return len(existing), new_count


def response(flow: http.HTTPFlow):
    url = flow.request.url
    if 'siftedreviewlist' not in url and 'shopreview' not in url:
        return

    target = load_target()
    if not target:
        print(f"[!] 抓到评论 API 但未指定目标店: {url[:100]}")
        return

    raw = flow.response.content
    try:
        d = json.loads(raw)
    except Exception:
        try:
            d = json.loads(gzip.decompress(raw))
        except Exception:
            print(f"[!] 解析失败: {url[:100]}")
            return

    review_list = d.get('list') or (d.get('data', {}).get('list') if isinstance(d.get('data'), dict) else []) or []
    if not isinstance(review_list, list):
        return

    rows = []
    for r in review_list:
        if not isinstance(r, dict):
            continue
        text = extract_text(r)
        if not text:
            continue
        ui = r.get('userInfo')
        user = (ui.get('userName') if isinstance(ui, dict) else '') or r.get('userName', '')
        score = extract_score(r)
        rows.append({
            '门店': target['name'],
            '发布时间': extract_time(r),
            '发布人': user,
            '顾客评分': score,
            '评分': score,
            '文字': text,
        })

    if not rows:
        return

    total, new_count = merge_rows(target, rows)
    print(f"[{datetime.now():%H:%M:%S}] {target['idx']:03d} {target['name']}: +{new_count} → {total} 条")
