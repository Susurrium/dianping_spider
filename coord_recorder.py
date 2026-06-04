# -*- coding:utf-8 -*-
"""
单栏布局坐标录制器：

让用户把鼠标 hover 到 PC 微信小程序里关键位置，按 Enter 记录坐标。
不依赖鼠标点击事件捕获（避免 xinput 复杂度）。

使用方式:
    python3 coord_recorder.py             # 录制完整单栏配置
    python3 coord_recorder.py --only home_search_input  # 只录制 1 个点
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / 'miniapp_points_single_col.json'

# 默认窗口名（PC 微信小程序）
DEFAULT_WIN_NAME = '大众点评'


# 单栏布局下需要录制的关键点
# 顺序遵循"流程": 启动 → 搜索 → 选店 → 进评价 → 滚动 → 返回
STEPS = [
    # (key, 中文提示, 当前页面)
    ("back_button",                 "左上角返回箭头 <",                              "任意页面"),
    ("home_search_input",           "首页顶部搜索框（空文本输入区）",                  "小程序首页"),
    ("home_search_button",          "首页搜索按钮（搜索框右边那个'搜索'按钮）",        "小程序首页"),
    ("city_button",                 "左上角城市选择按钮（'上海'等城市文字）",          "小程序首页"),
    ("first_shop_result",           "搜索结果第一家店（店名行的中央）",                "搜索结果页"),
    ("result_row_height_ref_2",     "搜索结果第二家店（店名行的中央，用来算行高）",     "搜索结果页"),
    ("detail_review_count_entry",   "详情页里'评价(929)'标题文字",                    "店铺详情页"),
    ("detail_review_view_all",      "详情页里'查看全部 >'按钮",                       "店铺详情页"),
    ("detail_scroll_anchor",        "详情页正中间空白处（用于滚动起点）",              "店铺详情页"),
    ("review_tab_all",              "评价页'全部'tab 按钮",                           "评价页"),
    ("review_tab_latest",           "评价页'最新'tab",                                "评价页"),
    ("review_list_anchor",          "评价页第一条评论卡片中央（滚动起点）",            "评价页"),
]


def get_window_geometry(win_name: str):
    """返回 (wid, x, y, w, h)"""
    try:
        out = subprocess.check_output(
            ['xdotool', 'search', '--name', win_name],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        return None
    if not out:
        return None
    # 取最大尺寸的窗口（避免被小占位窗口干扰）
    best = None
    for wid in out.split('\n'):
        try:
            geo = subprocess.check_output(
                ['xdotool', 'getwindowgeometry', wid],
                text=True, stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            continue
        pos = re.search(r'Position: (\d+),(\d+)', geo)
        size = re.search(r'Geometry: (\d+)x(\d+)', geo)
        if not (pos and size):
            continue
        w, h = int(size.group(1)), int(size.group(2))
        if w < 100 or h < 100:
            continue
        if best is None or w * h > best[3] * best[4]:
            best = (wid, int(pos.group(1)), int(pos.group(2)), w, h)
    return best


def get_mouse_position():
    """当前鼠标屏幕坐标"""
    out = subprocess.check_output(['xdotool', 'getmouselocation', '--shell'], text=True)
    x = int(re.search(r'X=(\d+)', out).group(1))
    y = int(re.search(r'Y=(\d+)', out).group(1))
    return x, y


def record(only: str = None):
    print("=" * 70)
    print(" PC 微信小程序单栏布局 - 坐标录制器")
    print("=" * 70)

    # 找窗口
    geom = get_window_geometry(DEFAULT_WIN_NAME)
    if geom is None:
        sys.stderr.write(f"❌ 找不到窗口 '{DEFAULT_WIN_NAME}'，请打开 PC 微信小程序\n")
        return 1
    wid, win_x, win_y, win_w, win_h = geom
    print(f"✅ 找到窗口 wid={wid} 位置=({win_x},{win_y}) 大小={win_w}x{win_h}")

    # 加载已有配置
    if CONFIG_PATH.exists():
        existing = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    else:
        existing = {}
    existing['base_width'] = str(win_w)
    existing['base_height'] = str(win_h)

    steps = STEPS if only is None else [s for s in STEPS if s[0] == only]
    if only and not steps:
        sys.stderr.write(f"❌ 未知坐标 key: {only}\n")
        return 1

    print()
    print(f"将录制 {len(steps)} 个点。")
    print("窗口位置可能在录制中变化——录制器每次都重新读窗口位置。")
    print()
    input("准备好了？按 Enter 开始 ...")
    print()

    for idx, (key, desc, page) in enumerate(steps, 1):
        # 重新读窗口位置（用户可能拖窗口）
        cur_geom = get_window_geometry(DEFAULT_WIN_NAME)
        if cur_geom is None:
            sys.stderr.write("❌ 窗口消失了\n")
            return 1
        cur_wid, win_x, win_y, win_w, win_h = cur_geom
        existing['base_width'] = str(win_w)
        existing['base_height'] = str(win_h)

        prev = existing.get(key, '')
        prev_str = f" [现有: {prev}]" if prev else ''
        print(f"[{idx}/{len(steps)}] 当前页面: {page}")
        print(f"        要录制: {key}")
        print(f"        位置:  {desc}{prev_str}")
        print("        ▶ 把鼠标 hover 到目标位置（不需要点击）然后按 Enter，")
        print("          按 's' + Enter 跳过这个点，按 'q' + Enter 退出录制。")
        choice = input("        > ").strip().lower()
        if choice == 'q':
            print("退出录制")
            break
        if choice == 's':
            print(f"        ⏭️  跳过 {key}")
            continue

        x, y = get_mouse_position()
        rel_x = x - win_x
        rel_y = y - win_y
        if rel_x < 0 or rel_y < 0 or rel_x > win_w or rel_y > win_h:
            print(f"        ⚠️  鼠标 ({x},{y}) 不在窗口内 ({win_x},{win_y},{win_w},{win_h})，请重试")
            # 重做这个点
            continue
        existing[key] = f"{rel_x},{rel_y}"
        print(f"        ✅ {key} = {rel_x},{rel_y}")
        print()

    # 保存
    CONFIG_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
    print()
    print(f"💾 已保存到 {CONFIG_PATH}")
    print()
    print("当前配置:")
    for k, v in existing.items():
        print(f"  {k:35s} = {v}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='只录制单个 key（默认录制全部）')
    args = ap.parse_args()
    return record(args.only)


if __name__ == '__main__':
    sys.exit(main())
