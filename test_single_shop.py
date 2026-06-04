# -*- coding:utf-8 -*-
"""
单店全自动（OCR 自适应版）：
1. 搜索 → 进店
2. 详情页用 OCR 找"评价"按钮（每个店位置不一样，固定坐标不可靠）
3. 滚动若干次详情页直到"评价"出现，点击进评价页
4. 评价页滚动 N 次

每步带截图+反爬检测+美团对话框处理。
"""

from __future__ import annotations

import argparse
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from human_click import (
    get_window, parse_coord, human_click, human_scroll, load_points
)
from ocr_locate import (
    screenshot_window, ocr_with_boxes, find_review_module,
    detect_meituan_dialog, detect_captcha_in_screenshot
)


DIAG_DIR = ROOT / 'mitm_logs' / 'diagnostic'
DIAG_DIR.mkdir(parents=True, exist_ok=True)


def shot(wid: int, label: str) -> Path:
    ts = datetime.now().strftime('%H%M%S')
    path = DIAG_DIR / f'auto_{ts}_{label}.png'
    subprocess.run(['import', '-window', str(wid), str(path)], check=False,
                   stderr=subprocess.DEVNULL)
    return path


def human_paste(text: str):
    if shutil.which('xclip'):
        subprocess.run(['xclip', '-selection', 'clipboard', '-i'],
                       input=text.encode('utf-8'), check=True)
        time.sleep(random.uniform(0.10, 0.20))
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+v'], check=False)
        time.sleep(random.uniform(0.20, 0.40))


def find_meituan_cancel(wid: int):
    """找弹窗'取消'按钮位置。"""
    img = screenshot_window(wid)
    if img is None:
        return None
    try:
        for b in ocr_with_boxes(img):
            if '取消' in b['text']:
                return (b['x'] + b['w']//2, b['y'] + b['h']//2)
        return None
    finally:
        try:
            img.unlink()
        except OSError:
            pass


def handle_meituan_dialog(win):
    """如果弹了美团对话框，点取消。"""
    img = screenshot_window(win['wid'])
    if img is None:
        return False
    try:
        if not detect_meituan_dialog(img):
            return False
        print("  ⚠️ 美团对话框，自动点'取消'")
        for b in ocr_with_boxes(img):
            if '取消' in b['text']:
                rx, ry = b['x'] + b['w']//2, b['y'] + b['h']//2
                human_click(win, rx, ry, base_w=win['w'], base_h=win['h'])
                time.sleep(1.0)
                return True
        return False
    finally:
        try:
            img.unlink()
        except OSError:
            pass


def click_review_module(win, max_scrolls: int = 6, scroll_dy: int = -350) -> bool:
    """
    在详情页找"评价"模块并点击。
    详情页很长，"评价"在中下部，先滚 0-N 次直到 OCR 看到"评价"。
    """
    points = load_points()
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])
    
    for attempt in range(max_scrolls + 1):
        # 处理美团对话框
        handle_meituan_dialog(win)
        
        # 用 OCR 找"评价"模块
        pos = find_review_module(win['wid'])
        if pos is not None:
            print(f"  ✅ OCR 找到评价模块: rel=({pos[0]},{pos[1]}) (尝试 {attempt})")
            human_click(win, pos[0], pos[1], base_w=base_w, base_h=base_h)
            time.sleep(random.uniform(0.5, 1.0))
            return True
        # 没找到，滚动详情页
        if attempt < max_scrolls:
            print(f"  ⏬ 详情页向下滚动 (尝试 {attempt+1}/{max_scrolls})")
            anchor_x, anchor_y = parse_coord(points.get('detail_scroll_anchor', '200,400'))
            human_scroll(win, anchor_x, anchor_y, dy=scroll_dy,
                         base_w=base_w, base_h=base_h)
            time.sleep(random.uniform(1.5, 2.5))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keyword', required=True)
    ap.add_argument('--scrolls', type=int, default=8, help='评价页滚动次数')
    ap.add_argument('--scroll-dy', type=int, default=-400)
    ap.add_argument('--max-detail-scrolls', type=int, default=6)
    args = ap.parse_args()

    win = get_window()
    if win is None:
        sys.stderr.write("❌ 找不到 PC 微信小程序窗口\n")
        return 1
    print(f"窗口: wid={win['wid']} ({win['x']},{win['y']}) {win['w']}x{win['h']}")

    points = load_points()
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])

    def click(key):
        rx, ry = parse_coord(points[key])
        human_click(win, rx, ry, base_w=base_w, base_h=base_h)

    def scroll(key, dy=args.scroll_dy):
        rx, ry = parse_coord(points[key])
        human_scroll(win, rx, ry, dy=dy, base_w=base_w, base_h=base_h)

    # 0. 初始截图
    shot(win['wid'], '00_initial')

    # 1. 激活窗口
    print("\n▶ 1. 激活窗口")
    subprocess.run(['xdotool', 'windowactivate', '--sync', str(win['wid'])], check=False)
    time.sleep(random.uniform(0.5, 0.8))

    # 2. 点搜索框 + 输入
    print(f"\n▶ 2. 搜索 '{args.keyword}'")
    click('home_search_input')
    time.sleep(random.uniform(0.8, 1.2))
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+a'], check=False)
    time.sleep(0.2)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Delete'], check=False)
    time.sleep(0.3)
    human_paste(args.keyword)
    time.sleep(random.uniform(0.6, 1.0))
    shot(win['wid'], '01_keyword_pasted')

    # 3. 触发搜索（按 Enter，比 click 搜索按钮稳）
    print("\n▶ 3. 按 Enter 搜索")
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Return'], check=False)
    time.sleep(4.0)
    img = shot(win['wid'], '02_search_result')
    if detect_captcha_in_screenshot(img):
        print("❌ 触发反爬验证码")
        return 2

    # 4. 点第一家店
    print("\n▶ 4. 点第一家店 (first_shop_result)")
    click('first_shop_result')
    time.sleep(4.5)
    img = shot(win['wid'], '03_detail_page')
    if detect_captcha_in_screenshot(img):
        print("❌ 详情页触发反爬")
        return 2

    # 5. 处理可能弹窗 + OCR 找评价模块
    print("\n▶ 5. 自适应找'评价'模块并点击")
    handle_meituan_dialog(win)
    time.sleep(0.5)
    if not click_review_module(win, max_scrolls=args.max_detail_scrolls):
        print("❌ 找不到'评价'模块（详情页结构可能特殊）")
        shot(win['wid'], '03b_no_review_module')
        return 3
    
    # 等评价页加载
    time.sleep(5.0)
    img = shot(win['wid'], '04_review_page')
    if detect_captcha_in_screenshot(img):
        print("❌ 评价页触发反爬")
        return 2

    # 6. 滚动评价
    print(f"\n▶ 6. 评价页滚动 {args.scrolls} 次")
    for i in range(1, args.scrolls + 1):
        print(f"   滚动 {i}/{args.scrolls}")
        scroll('review_list_anchor')
        time.sleep(random.uniform(2.0, 3.0))
        if i % 3 == 0:
            img = shot(win['wid'], f'05_scroll_{i}')
            if detect_captcha_in_screenshot(img):
                print(f"❌ 滚动到第 {i} 次触发反爬")
                return 2
    shot(win['wid'], '06_finished')

    print("\n✅ 单店流程完成")
    return 0


if __name__ == '__main__':
    sys.exit(main())
