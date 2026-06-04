#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
快速切店：输入店名，自动搜索→进店→进评价页。你只需等它完成后跑 grab.py。

用法:
    python3 goto_review.py '达美乐比萨(胜竹路店)'

完成后你会看到评价详情页（全部/最新/差评 tab），然后跑:
    python3 grab.py '达美乐比萨(胜竹路店)' 5
"""

import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from human_click import get_window, human_click, human_scroll, parse_coord, load_points
from ocr_locate import find_review_module


def paste(text):
    subprocess.run(['xclip', '-selection', 'clipboard', '-i'],
                   input=text.encode('utf-8'), check=True)
    time.sleep(0.15)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+v'], check=False)
    time.sleep(0.3)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 goto_review.py '店名'")
        return 1

    store_name = sys.argv[1]
    win = get_window()
    if not win:
        print("❌ 找不到窗口"); return 1

    points = load_points()
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])

    def click(key):
        rx, ry = parse_coord(points[key])
        human_click(win, rx, ry, base_w=base_w, base_h=base_h)

    # 1. 搜索
    print(f"🔍 搜索: {store_name}")
    subprocess.run(['xdotool', 'windowactivate', '--sync', str(win['wid'])], check=False)
    time.sleep(0.5)
    click('home_search_input')
    time.sleep(1.0)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+a'], check=False)
    time.sleep(0.15)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Delete'], check=False)
    time.sleep(0.2)
    paste(store_name)
    time.sleep(0.8)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Return'], check=False)
    print("   等搜索结果...")
    time.sleep(5)

    # 2. 点第一家店
    print("🏪 进店")
    click('first_shop_result')
    time.sleep(5)

    # 3. 找评价入口
    print("⭐ 找评价入口...")
    for attempt in range(8):
        pos = find_review_module(win['wid'])
        if pos:
            print(f"   找到! 点击...")
            human_click(win, pos[0], pos[1], base_w=base_w, base_h=base_h)
            time.sleep(4)
            print(f"✅ 已进入评价页，现在跑:")
            print(f"   python3 grab.py '{store_name}' <编号>")
            return 0
        # 滚详情页
        rx, ry = parse_coord(points['detail_scroll_anchor'])
        human_scroll(win, rx, ry, dy=-400, base_w=base_w, base_h=base_h)
        time.sleep(2)

    print("❌ 找不到评价入口")
    return 1


if __name__ == '__main__':
    sys.exit(main())
