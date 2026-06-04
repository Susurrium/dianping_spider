#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
全自动批量抓取：从 xlsx 读店铺列表，逐家搜索→进店→进评价→滚动抓取→返回。

用法:
    python3 batch_grab.py --limit 5          # 跑 5 家
    python3 batch_grab.py --start 4          # 从第 4 家开始
    python3 batch_grab.py                    # 全跑

前置条件:
    - PC 微信用 SSLKEYLOGFILE 启动
    - 大众点评小程序在首页
    - miniapp_points_single_col.json 已录好坐标
"""

import json
import os
import random
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from human_click import get_window, human_click, human_scroll, parse_coord, load_points
from review_exporter import load_stores_from_xlsx

XLSX = ROOT / '达美乐_门店.xlsx'
OUT_DIR = ROOT / 'output' / 'store_reviews'
PCAP = Path('/tmp/wx_capture/raw.pcap')
KEYS = Path('/tmp/wx_keys.log')


def paste(text):
    subprocess.run(['xclip', '-selection', 'clipboard', '-i'],
                   input=text.encode('utf-8'), check=True)
    time.sleep(0.15)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+v'], check=False)
    time.sleep(0.3)


def start_tshark(duration):
    PCAP.parent.mkdir(parents=True, exist_ok=True)
    if PCAP.exists():
        PCAP.unlink()
    cmd = f"tshark -i wlp2s0 -f 'tcp port 443' -w {PCAP} -a duration:{duration}"
    proc = subprocess.Popen(['sg', 'wireshark', '-c', cmd],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            preexec_fn=os.setsid)
    time.sleep(3)
    return proc


def stop_tshark(proc):
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=8)
        except Exception:
            pass


def parse_reviews(store_name, idx):
    """用 tshark export-objects 解析评论"""
    import gzip
    dump_dir = Path('/tmp/wx_dump/batch')
    if dump_dir.exists():
        shutil.rmtree(dump_dir)
    dump_dir.mkdir(parents=True)
    subprocess.run(['sg', 'wireshark', '-c',
                    f"tshark -r {PCAP} -o tls.keylog_file:{KEYS} --export-objects http,{dump_dir} -q"],
                   check=False, capture_output=True)
    rows = []
    seen = set()
    for f in dump_dir.iterdir():
        if 'outsidesiftedreviewlist' not in f.name:
            continue
        raw = f.read_bytes()
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        try:
            d = json.loads(raw)
        except Exception:
            continue
        review_list = d.get('list', [])
        if not review_list and isinstance(d.get('data'), dict):
            review_list = d['data'].get('list', [])
        for r in review_list:
            if not isinstance(r, dict):
                continue
            text = r.get('content') or r.get('reviewBody') or ''
            if not text:
                continue
            ui = r.get('userInfo')
            user = (ui.get('userName') if isinstance(ui, dict) else '') or r.get('userName', '')
            pub = ''
            ri = r.get('reviewIndexes')
            if isinstance(ri, dict):
                pub = ri.get('addTime') or ''
            pub = pub or r.get('createDateString') or r.get('addTimeStr') or ''
            key = (user, text[:40])
            if key in seen:
                continue
            seen.add(key)
            rows.append({'门店': store_name, '发布时间': pub, '发布人': user, '文字': text})

    # merge
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = store_name.replace('/', '_')
    out_path = OUT_DIR / f'{idx:03d}_{safe}.json'
    existing = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding='utf-8'))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    merged_seen = set()
    merged = []
    for r in existing + rows:
        key = (r.get('发布人', ''), r.get('文字', '')[:40])
        if key in merged_seen:
            continue
        merged_seen.add(key)
        merged.append(r)
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
    return len(rows), len(merged)


def is_done(idx, name):
    safe = name.replace('/', '_')
    f = OUT_DIR / f'{idx:03d}_{safe}.json'
    if not f.exists():
        return False
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return isinstance(d, list) and len(d) >= 10
    except Exception:
        return False


def run_one_store(win, points, idx, store_name, scrolls=35):
    """全自动单店：搜索→进店→进评价→滚动→抓取→返回"""
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])

    def click(key):
        rx, ry = parse_coord(points[key])
        human_click(win, rx, ry, base_w=base_w, base_h=base_h)

    def scroll_page():
        rx, ry = parse_coord(points['review_list_anchor'])
        # 分 5 批 × 10 tick
        for _ in range(5):
            subprocess.run(['xdotool', 'click', '--window', str(win['wid']),
                            '--repeat', '10', '--delay', '30', '5'], check=False)
            time.sleep(0.1)
        time.sleep(random.uniform(1.2, 1.5))

    print(f"\n{'='*50}")
    print(f"[{datetime.now():%H:%M:%S}] {idx:03d} {store_name}")
    print(f"{'='*50}")

    # 1. 搜索
    print("  ▶ 搜索")
    subprocess.run(['xdotool', 'windowactivate', '--sync', str(win['wid'])], check=False)
    time.sleep(0.5)
    click('home_search_input')
    time.sleep(1.0)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+a'], check=False)
    time.sleep(0.2)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Delete'], check=False)
    time.sleep(0.3)
    paste(store_name)
    time.sleep(0.8)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Return'], check=False)
    time.sleep(4.0)

    # 2. 点第一家店
    print("  ▶ 进店")
    click('first_shop_result')
    time.sleep(4.0)

    # 3. 滚详情页找评价 + 点进去（用 OCR）
    print("  ▶ 找评价入口")
    from ocr_locate import find_review_module
    found = False
    for attempt in range(6):
        pos = find_review_module(win['wid'])
        if pos:
            print(f"    找到@{pos}")
            human_click(win, pos[0], pos[1], base_w=base_w, base_h=base_h)
            found = True
            break
        # 滚详情页
        rx, ry = parse_coord(points['detail_scroll_anchor'])
        human_scroll(win, rx, ry, dy=-400, base_w=base_w, base_h=base_h)
        time.sleep(2.0)
    if not found:
        print("  ❌ 找不到评价入口")
        # 返回首页
        for _ in range(3):
            click('back_button')
            time.sleep(1.5)
        return 0

    time.sleep(4.0)

    # 4. 启动 tshark + 滚动评价页
    duration = scrolls * 2 + 30
    print(f"  ▶ 抓取 ({scrolls} 次滚动)")
    tshark = start_tshark(duration)
    for i in range(1, scrolls + 1):
        scroll_page()
        if i % 10 == 0:
            print(f"    滚动 {i}/{scrolls}")
    time.sleep(3)
    stop_tshark(tshark)

    # 5. 解析
    new, total = parse_reviews(store_name, idx)
    print(f"  ✅ 新增 {new} 条, 总计 {total} 条")

    # 6. 返回首页
    print("  ▶ 返回首页")
    for _ in range(4):
        click('back_button')
        time.sleep(1.2)

    return total


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--start', type=int, default=1)
    ap.add_argument('--scrolls', type=int, default=35)
    args = ap.parse_args()

    win = get_window()
    if not win:
        print("❌ 找不到大众点评窗口")
        return 1
    if not KEYS.exists() or KEYS.stat().st_size < 100:
        print("❌ keys 文件无效")
        return 1

    points = load_points()
    stores = load_stores_from_xlsx(XLSX)
    print(f"共 {len(stores)} 家店")

    todo = []
    for i, s in enumerate(stores, 1):
        if i < args.start:
            continue
        if is_done(i, s.name):
            continue
        todo.append((i, s.name))
    if args.limit > 0:
        todo = todo[:args.limit]
    print(f"待跑: {len(todo)} 家")

    stats = {'ok': 0, 'fail': 0}
    try:
        for idx, name in todo:
            n = run_one_store(win, points, idx, name, args.scrolls)
            if n > 0:
                stats['ok'] += 1
            else:
                stats['fail'] += 1
            # 每 5 家休息 20s
            if (stats['ok'] + stats['fail']) % 5 == 0:
                print("  💤 休息 20s")
                time.sleep(20)
    except KeyboardInterrupt:
        print("\n⏹️ 中断")

    print(f"\n📊 完成: 成功 {stats['ok']}, 失败 {stats['fail']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
