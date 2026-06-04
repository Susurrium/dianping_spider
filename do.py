#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
一条命令搞定一家店：按编号自动查店名 + 进评价页 + 滚动抓取。

用法:
    python3 do.py 5              # 跑第 5 家店（自动查名字）
    python3 do.py 5 6 7 8        # 连续跑多家
    python3 do.py 5-10           # 跑 5 到 10
    python3 do.py list           # 列出所有待跑的店
    python3 do.py list 1-20      # 列出 1-20

流程:
    首页 → 搜索店名 → 进店 → OCR找评价入口 → 进评价页 → 滚动抓取 → 返回首页
"""

import gzip
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from human_click import get_window, human_click, human_scroll, parse_coord, load_points
from ocr_locate import find_review_module
from review_exporter import load_stores_from_xlsx

XLSX = ROOT / '达美乐_门店.xlsx'
OUT_DIR = ROOT / 'output' / 'store_reviews'
PCAP = Path('/tmp/wx_capture/raw.pcap')
KEYS = Path('/tmp/wx_keys.log')


def get_stores():
    return load_stores_from_xlsx(XLSX)


def is_done(idx, name):
    safe = name.replace('/', '_')
    f = OUT_DIR / f'{idx:03d}_{safe}.json'
    if not f.exists(): return False
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return isinstance(d, list) and len(d) >= 10
    except: return False


def get_count(idx, name):
    safe = name.replace('/', '_')
    f = OUT_DIR / f'{idx:03d}_{safe}.json'
    if not f.exists(): return 0
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return len(d) if isinstance(d, list) else 0
    except: return 0


# --- tshark ---
def start_tshark():
    PCAP.parent.mkdir(parents=True, exist_ok=True)
    if PCAP.exists(): PCAP.unlink()
    proc = subprocess.Popen(
        ['sg', 'wireshark', '-c', f"tshark -i wlp2s0 -f 'tcp port 443' -w {PCAP}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, preexec_fn=os.setsid)
    time.sleep(2)
    return proc

def stop_tshark(proc):
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except: pass


# --- 解析 ---
def parse_pcap(store_name, idx):
    dump = Path('/tmp/wx_dump/do')
    if dump.exists(): shutil.rmtree(dump)
    dump.mkdir(parents=True)
    subprocess.run(['sg', 'wireshark', '-c',
        f"tshark -r {PCAP} -o tls.keylog_file:{KEYS} --export-objects http,{dump} -q"],
        check=False, capture_output=True)
    rows, seen = [], set()
    for f in dump.iterdir():
        if 'siftedreviewlist' not in f.name: continue
        raw = f.read_bytes()
        try: raw = gzip.decompress(raw)
        except: pass
        try: d = json.loads(raw)
        except: continue
        lst = d.get('list') or (d.get('data', {}).get('list') if isinstance(d.get('data'), dict) else []) or []
        for r in lst:
            if not isinstance(r, dict): continue
            text = r.get('content') or r.get('reviewBody') or ''
            if not text: continue
            ui = r.get('userInfo')
            user = (ui.get('userName') if isinstance(ui, dict) else '') or r.get('userName', '')
            key = (user, text[:40])
            if key in seen: continue
            seen.add(key)
            rows.append({'门店': store_name, '发布时间': '', '发布人': user, '文字': text})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = store_name.replace('/', '_')
    out = OUT_DIR / f'{idx:03d}_{safe}.json'
    existing = []
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding='utf-8'))
            if not isinstance(existing, list): existing = []
        except: existing = []
    ms = set()
    merged = []
    for r in existing + rows:
        k = (r.get('发布人',''), r.get('文字','')[:40])
        if k in ms: continue
        ms.add(k)
        merged.append(r)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
    return len(rows), len(merged)


# --- 操作 ---
def paste(text):
    subprocess.run(['xclip', '-selection', 'clipboard', '-i'],
                   input=text.encode('utf-8'), check=True)
    time.sleep(0.12)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+v'], check=False)
    time.sleep(0.25)


def do_one(win, points, idx, store_name):
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])

    def click(key):
        rx, ry = parse_coord(points[key])
        human_click(win, rx, ry, base_w=base_w, base_h=base_h)

    print(f"\n{'─'*50}")
    print(f" {idx:03d} {store_name}")
    print(f"{'─'*50}")

    # 1. 搜索
    subprocess.run(['xdotool', 'windowactivate', '--sync', str(win['wid'])], check=False)
    time.sleep(0.4)
    click('home_search_input')
    time.sleep(0.8)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+a'], check=False)
    time.sleep(0.1)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Delete'], check=False)
    time.sleep(0.2)
    paste(store_name)
    time.sleep(0.6)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Return'], check=False)
    print(" 🔍 搜索...", end='', flush=True)
    time.sleep(4.5)

    # 2. 进店
    click('first_shop_result')
    print(" 🏪", end='', flush=True)
    time.sleep(4.5)

    # 3. 找评价入口
    found = False
    for _ in range(6):
        pos = find_review_module(win['wid'])
        if pos:
            human_click(win, pos[0], pos[1], base_w=base_w, base_h=base_h)
            found = True
            break
        rx, ry = parse_coord(points['detail_scroll_anchor'])
        human_scroll(win, rx, ry, dy=-400, base_w=base_w, base_h=base_h)
        time.sleep(1.8)
    if not found:
        print(" ❌ 找不到评价入口")
        for _ in range(3):
            click('back_button'); time.sleep(1)
        return 0
    print(" ⭐", end='', flush=True)
    time.sleep(3.5)

    # 4. 滚动抓取
    tshark = start_tshark()
    last_size = 0
    no_growth = 0
    scrolls = 0
    print(" 📜", end='', flush=True)

    while scrolls < 200:
        # 50 tick 分 5 批
        for _ in range(5):
            subprocess.run(['xdotool', 'click', '--window', str(win['wid']),
                            '--repeat', '10', '--delay', '30', '5'], check=False)
            time.sleep(0.08)
        scrolls += 1
        time.sleep(random.uniform(1.2, 1.5))

        if scrolls % 5 == 0:
            cur = PCAP.stat().st_size if PCAP.exists() else 0
            if cur > last_size + 50000:
                last_size = cur
                no_growth = 0
                print('.', end='', flush=True)
            else:
                no_growth += 1
            if no_growth >= 3 and scrolls > 10:
                break

    time.sleep(2)
    stop_tshark(tshark)

    # 5. 解析
    new, total = parse_pcap(store_name, idx)
    print(f" ✅ +{new} = {total} 条")

    # 6. 返回首页
    for _ in range(4):
        click('back_button')
        time.sleep(1.0)
    time.sleep(1)
    return total


def parse_range(arg):
    """解析 '5-10' 或 '5' 为列表"""
    m = re.match(r'(\d+)-(\d+)$', arg)
    if m:
        return list(range(int(m.group(1)), int(m.group(2)) + 1))
    return [int(arg)]


def main():
    if len(sys.argv) < 2:
        print("用法: python3 do.py <编号>     # 如: python3 do.py 5")
        print("      python3 do.py 5-10      # 跑 5 到 10")
        print("      python3 do.py list      # 列出待跑的店")
        return 1

    stores = get_stores()

    # list 命令
    if sys.argv[1] == 'list':
        rng = range(1, len(stores)+1)
        if len(sys.argv) > 2:
            ids = parse_range(sys.argv[2])
            rng = ids
        for i in rng:
            if i < 1 or i > len(stores): continue
            s = stores[i-1]
            cnt = get_count(i, s.name)
            done = '✅' if cnt >= 10 else '  '
            print(f"  {done} {i:03d} {s.name} ({cnt} 条)")
        return 0

    # 解析编号
    ids = []
    for arg in sys.argv[1:]:
        ids.extend(parse_range(arg))

    # 检查环境
    win = get_window()
    if not win:
        print("❌ 找不到大众点评窗口"); return 1
    if not KEYS.exists() or KEYS.stat().st_size < 50:
        print("❌ keys 无效"); return 1
    points = load_points()

    # 跑
    for idx in ids:
        if idx < 1 or idx > len(stores):
            print(f"  ⚠️ 编号 {idx} 超范围"); continue
        name = stores[idx-1].name
        if is_done(idx, name):
            print(f"  ⏭️  {idx:03d} {name} 已完成"); continue
        do_one(win, points, idx, name)

    return 0


if __name__ == '__main__':
    sys.exit(main())
