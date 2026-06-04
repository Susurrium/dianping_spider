#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
补时间脚本：从 mitm_logs 原始抓包重建 文字→时间 映射，回填到 store_reviews

两种 API 格式：
  A) siftedreviewlist: content + time("4月6日")
  B) shopreview:       reviewBody + lastTimeStr("4月19日") / addTime(ISO)
"""

import json
import gzip
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / 'mitm_logs'
OUT = ROOT / 'output' / 'store_reviews'


def find_review_list(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            r = find_review_list(v)
            if r:
                return r
    elif isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and ('content' in obj[0] or 'reviewBody' in obj[0]):
            return obj
        for v in obj:
            r = find_review_list(v)
            if r:
                return r
    return None


def extract_richtext(node):
    out = []
    if isinstance(node, dict):
        if 'text' in node and isinstance(node['text'], str):
            out.append(node['text'])
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                out.append(extract_richtext(v))
    elif isinstance(node, list):
        for x in node:
            out.append(extract_richtext(x))
    return ''.join(out)


def extract_text(r):
    text = r.get('content') or ''
    if text:
        return text
    rb = r.get('reviewBody')
    if isinstance(rb, dict):
        return extract_richtext(rb)
    if isinstance(rb, str):
        return rb
    return ''


def extract_time(r):
    t = r.get('time')
    if t and isinstance(t, str):
        return t.strip()
    t = r.get('lastTimeStr')
    if t and isinstance(t, str):
        return t.strip()
    iso = r.get('addTime') or r.get('lastTime')
    if iso and isinstance(iso, str):
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', iso)
        if m:
            return f"{int(m.group(2))}月{int(m.group(3))}日"
    return ''


def build_map():
    text2time = {}
    files = list(LOG.glob('review_*.json'))
    parsed, failed = 0, 0
    for f in files:
        try:
            raw = f.read_bytes()
        except OSError:
            failed += 1
            continue
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        try:
            d = json.loads(raw.decode('utf-8', errors='replace'))
        except Exception:
            failed += 1
            continue

        data = d.get('data', d) if isinstance(d, dict) else d
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                pass
        lst = find_review_list(data) or find_review_list(d)
        if not lst:
            continue
        parsed += 1
        for r in lst:
            if not isinstance(r, dict):
                continue
            text = extract_text(r)
            t = extract_time(r)
            if text and t:
                text2time[text[:40]] = t

    print(f"原始文件: {len(files)} | 解析成功: {parsed} | 失败: {failed}")
    print(f"映射条目: {len(text2time)}")
    return text2time


def backfill(text2time, dry_run=True):
    total_filled = 0
    total_miss = 0
    for f in sorted(OUT.glob('*.json')):
        if 'manifest' in f.name:
            continue
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(d, list) or not d:
            continue

        filled = 0
        miss = 0
        for r in d:
            if r.get('发布时间', '').strip():
                continue
            key = r.get('文字', '')[:40]
            if key in text2time:
                r['发布时间'] = text2time[key]
                filled += 1
            else:
                miss += 1

        total_filled += filled
        total_miss += miss
        if filled > 0 or miss > 0:
            status = '[预览]' if dry_run else '[已写]'
            print(f"  {status} {f.name}: 补 {filled}, 仍缺 {miss}")
            if not dry_run and filled > 0:
                f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n总计: 补回 {total_filled} 条, 仍缺 {total_miss} 条")


if __name__ == '__main__':
    print("=== 1. 建立 文字→时间 映射 ===")
    m = build_map()
    print("\n=== 2. 回填 ===")
    dry = '--write' not in sys.argv
    backfill(m, dry_run=dry)
    if dry:
        print("\n预览模式。确认后运行: python3 backfill_time.py --write")
