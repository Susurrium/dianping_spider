#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
纯滚动脚本（配合 mitmdump 使用，不依赖 SSLKEYLOGFILE/tshark）

用法:
    python3 scroll.py 5            # 自动滚到底（看 reviews 文件停止增长）
    python3 scroll.py 5 499        # 指定评论数

跟 grab.py 区别:
- grab.py 用 tshark 抓 pcap + SSLKEYLOGFILE 解密 → 已废
- scroll.py 只负责滚动；mitmdump (mitm_dianping.py) 自动写文件
"""

import json
import random
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from human_click import get_window, load_points, parse_coord
from review_exporter import load_stores_from_xlsx

XLSX = ROOT / '达美乐_门店.xlsx'
OUT_DIR = ROOT / 'output' / 'store_reviews'
TARGET = Path('/tmp/mitm_target.json')

stop_flag = threading.Event()


def review_file(idx, name):
    return OUT_DIR / f"{idx:03d}_{name.replace('/','_')}.json"


def review_count(idx, name):
    f = review_file(idx, name)
    if not f.exists():
        return 0
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return len(d) if isinstance(d, list) else 0
    except Exception:
        return 0


def human_scroll_session(wid, idx, name, max_pages=200):
    """跟 grab.py 同样保守的滚动参数：5批×10tick×30ms + 等1.2-1.5s"""
    subprocess.run(['xdotool', 'windowactivate', '--sync', str(wid)], check=False)
    time.sleep(0.3)

    points = load_points()
    rx, ry = parse_coord(points['review_list_anchor'])
    win = get_window()
    if win:
        subprocess.run(['xdotool', 'mousemove', str(win['x'] + rx), str(win['y'] + ry)],
                       check=False)
    time.sleep(0.3)

    last_count = review_count(idx, name)
    no_growth = 0
    total = 0

    while total < max_pages and not stop_flag.is_set():
        # 5 批 × 10 tick × 30ms（和 grab.py 一样的安全参数）
        for _ in range(5):
            for _ in range(10):
                subprocess.run(['xdotool', 'click', '--window', str(wid), '5'], check=False)
                time.sleep(0.03)
            time.sleep(0.08)
        total += 1

        time.sleep(random.uniform(1.2, 1.5))

        # 每 3 次滚动检查 reviews 文件是否还在增长
        if total % 3 == 0:
            cur = review_count(idx, name)
            growth = cur - last_count
            last_count = cur
            if growth > 0:
                no_growth = 0
                print(f' [{cur}]', end='', flush=True)
            else:
                no_growth += 1
                print('.', end='', flush=True)
            if no_growth >= 2 and total > 6:
                print(' [无增长，停]', end='', flush=True)
                break

    return total, last_count


def main():
    if len(sys.argv) < 2:
        print("用法: python3 scroll.py <编号> [评论数]")
        return 1

    idx = int(sys.argv[1])
    stores = load_stores_from_xlsx(XLSX)
    if idx < 1 or idx > len(stores):
        print(f"❌ 编号超范围 1-{len(stores)}")
        return 1
    name = stores[idx - 1].name

    expected = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    max_pages = (expected // 14) + 5 if expected > 0 else 200

    # 检查 mitmdump 在跑
    r = subprocess.run(['pgrep', '-f', 'mitmdump.*8080'], capture_output=True, text=True)
    if not r.stdout.strip():
        print("❌ mitmdump 没在跑，先 bash start_mitm.sh")
        return 1

    # 设置当前目标（让 mitm_dianping.py 知道写哪个文件）
    TARGET.write_text(json.dumps({'idx': idx, 'name': name}, ensure_ascii=False))

    win = get_window()
    if not win:
        print("❌ 找不到微信窗口")
        return 1

    print(f"🍕 {idx:03d} {name}")
    if expected > 0:
        print(f"   {expected} 条, 最多滚 {max_pages} 次")
    else:
        print(f"   自动滚到底")
    start = review_count(idx, name)
    print(f"   起点: {start} 条")
    print(f"   确认在评价页，按 Enter...", end='', flush=True)
    input()

    signal.signal(signal.SIGINT, lambda s, f: (stop_flag.set(), print(' [停]', end='', flush=True)))

    print(f"   滚动中 ", end='', flush=True)
    rounds, final = human_scroll_session(win['wid'], idx, name, max_pages)
    print(f" ({rounds} 次, +{final - start})")

    # 失败诊断
    if final == start:
        print(f"   ⚠️ 0 增长 → 可能反爬触发 / mitmdump 没截到 / 没在评价页")
        print(f"      看 mitm 日志: tail -20 /tmp/mitm_capture.log")
    else:
        print(f"   ✅ 总计 {final} 条")
    return 0


if __name__ == '__main__':
    sys.exit(main())
