# -*- coding:utf-8 -*-
"""
人类化鼠标点击：贝塞尔曲线轨迹 + 随机抖动 + 自然延迟。

核心策略（绕过反爬）:
1. 鼠标先飘到目标附近（带轨迹），不是瞬间瞬移
2. 轨迹用贝塞尔曲线 + 高斯噪声扰动，避免直线
3. 每段移动有微秒级随机延迟（10-30ms 一段）
4. 到达目标后停顿 200-400ms（人类反应时间）再点击
5. 点击位置随机抖动 ±2-5px（不是像素完美）
6. 点击后再停顿 300-800ms（避免连续点击）

使用:
    from human_click import human_click, human_scroll, load_points
    
    points = load_points()
    win = get_window_geometry()
    human_click(win, points['detail_review_count_entry'])
    human_scroll(win, points['review_list_anchor'], dy=-300)
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / 'miniapp_points_single_col.json'


# ----------------------------------------------------------------------
# 窗口和鼠标
# ----------------------------------------------------------------------

def get_window(win_name: str = '大众点评') -> Optional[dict]:
    try:
        out = subprocess.check_output(
            ['xdotool', 'search', '--name', win_name],
            text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        return None
    best = None
    for wid in out.split('\n'):
        if not wid.strip():
            continue
        try:
            geo = subprocess.check_output(
                ['xdotool', 'getwindowgeometry', wid],
                text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            continue
        pos = re.search(r'Position: (\d+),(\d+)', geo)
        size = re.search(r'Geometry: (\d+)x(\d+)', geo)
        if not (pos and size):
            continue
        w, h = int(size.group(1)), int(size.group(2))
        if w < 100 or h < 100:
            continue
        if best is None or w * h > best['w'] * best['h']:
            best = {
                'wid': int(wid),
                'x': int(pos.group(1)),
                'y': int(pos.group(2)),
                'w': w, 'h': h,
            }
    return best


def get_mouse_pos() -> Tuple[int, int]:
    out = subprocess.check_output(['xdotool', 'getmouselocation', '--shell'], text=True)
    x = int(re.search(r'X=(\d+)', out).group(1))
    y = int(re.search(r'Y=(\d+)', out).group(1))
    return x, y


# ----------------------------------------------------------------------
# 坐标转换
# ----------------------------------------------------------------------

def parse_coord(s: str) -> Tuple[int, int]:
    """'172,290' → (172, 290)"""
    parts = s.split(',')
    return int(parts[0]), int(parts[1])


def rel_to_screen(window: dict, rel_x: int, rel_y: int,
                  base_w: int = None, base_h: int = None) -> Tuple[int, int]:
    """窗口相对坐标 → 屏幕坐标，可选按 base 比例缩放。"""
    if base_w and base_h and (base_w != window['w'] or base_h != window['h']):
        rel_x = round(rel_x * window['w'] / base_w)
        rel_y = round(rel_y * window['h'] / base_h)
    return window['x'] + rel_x, window['y'] + rel_y


# ----------------------------------------------------------------------
# 贝塞尔轨迹 + 人类化点击
# ----------------------------------------------------------------------

def _quad_bezier(p0, p1, p2, t):
    return (
        (1-t)*(1-t)*p0[0] + 2*(1-t)*t*p1[0] + t*t*p2[0],
        (1-t)*(1-t)*p0[1] + 2*(1-t)*t*p1[1] + t*t*p2[1],
    )


def human_move(target_x: int, target_y: int, *,
               n_steps_min: int = 18, n_steps_max: int = 32,
               step_delay_min: float = 0.010, step_delay_max: float = 0.025,
               jitter_sigma: float = 2.5):
    """从当前鼠标位置贝塞尔轨迹移到 (target_x, target_y)，途中带高斯噪声。"""
    cx, cy = get_mouse_pos()
    if cx == target_x and cy == target_y:
        return
    # 控制点：在直线中点附近偏移，让轨迹弯曲
    dx, dy = target_x - cx, target_y - cy
    dist = math.hypot(dx, dy)
    if dist < 5:
        # 短距离不用贝塞尔，直接线性
        n_steps = max(3, int(dist))
    else:
        # 距离越长步数越多
        n_steps = random.randint(
            max(n_steps_min, int(dist / 30)),
            max(n_steps_max, int(dist / 15)))
    # 控制点偏移：垂直于直线方向 + 随机距离
    perp_x = -dy / max(dist, 1)
    perp_y = dx / max(dist, 1)
    offset = random.uniform(-dist*0.3, dist*0.3)
    ctrl_x = (cx + target_x) / 2 + perp_x * offset
    ctrl_y = (cy + target_y) / 2 + perp_y * offset

    p0 = (cx, cy)
    p1 = (ctrl_x, ctrl_y)
    p2 = (target_x, target_y)

    for i in range(1, n_steps + 1):
        t = i / n_steps
        # 缓动：起步慢、中间快、终点慢（ease-in-out）
        eased = t * t * (3 - 2*t)  # smoothstep
        x, y = _quad_bezier(p0, p1, p2, eased)
        # 加高斯噪声
        x += random.gauss(0, jitter_sigma)
        y += random.gauss(0, jitter_sigma)
        subprocess.run(['xdotool', 'mousemove', str(int(x)), str(int(y))],
                       check=False)
        time.sleep(random.uniform(step_delay_min, step_delay_max))


def human_click(window: dict, target_rel_x: int, target_rel_y: int, *,
                base_w: int = None, base_h: int = None,
                target_jitter: int = 3,
                hover_delay_min: float = 0.20, hover_delay_max: float = 0.50,
                post_click_delay_min: float = 0.30, post_click_delay_max: float = 0.80):
    """人类化点击：贝塞尔轨迹 + hover 停顿 + 抖动 + 后置延迟。"""
    sx, sy = rel_to_screen(window, target_rel_x, target_rel_y, base_w, base_h)
    # 加随机抖动到目标点
    sx += random.randint(-target_jitter, target_jitter)
    sy += random.randint(-target_jitter, target_jitter)

    # 1. 移动
    human_move(sx, sy)
    # 2. 到达后停顿
    time.sleep(random.uniform(hover_delay_min, hover_delay_max))
    # 3. 点击 + 微抖
    sx2 = sx + random.randint(-1, 1)
    sy2 = sy + random.randint(-1, 1)
    subprocess.run(['xdotool', 'mousemove', str(sx2), str(sy2)], check=False)
    time.sleep(random.uniform(0.04, 0.10))
    subprocess.run(['xdotool', 'click', '1'], check=False)
    # 4. 点完停顿
    time.sleep(random.uniform(post_click_delay_min, post_click_delay_max))


def human_scroll(window: dict, anchor_rel_x: int, anchor_rel_y: int, *,
                 dy: int = -300, base_w: int = None, base_h: int = None,
                 chunks: int = 4):
    """
    人类化滚动：把鼠标移到 anchor 位置，按 button 5（向下滚）若干次。
    dy 是希望"页面向上滚多少像素"的近似值（每个 wheel tick ≈ 100px）。
    chunks: 拆成多次小滚动，模拟人类滚轮动作。
    """
    sx, sy = rel_to_screen(window, anchor_rel_x, anchor_rel_y, base_w, base_h)
    sx += random.randint(-3, 3)
    sy += random.randint(-3, 3)
    human_move(sx, sy)
    time.sleep(random.uniform(0.15, 0.30))

    button = 5 if dy < 0 else 4  # 5=向下滚, 4=向上滚
    abs_dy = abs(dy)
    ticks = max(1, abs_dy // 100)
    per_chunk = max(1, ticks // chunks)
    remaining = ticks
    while remaining > 0:
        chunk_ticks = min(per_chunk + random.randint(-1, 1), remaining)
        chunk_ticks = max(1, chunk_ticks)
        for _ in range(chunk_ticks):
            subprocess.run(['xdotool', 'click', str(button)], check=False)
            time.sleep(random.uniform(0.05, 0.12))
        remaining -= chunk_ticks
        time.sleep(random.uniform(0.20, 0.50))  # 每段间停顿


# ----------------------------------------------------------------------
# CLI 测试
# ----------------------------------------------------------------------

def load_points(path: Path = DEFAULT_CONFIG) -> dict:
    if not path.exists():
        sys.stderr.write(f"❌ 配置文件不存在: {path}\n  先跑 coord_recorder.py 录制坐标\n")
        sys.exit(1)
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p1 = sub.add_parser('click', help='测试点击 1 个录好的点')
    p1.add_argument('key', help='坐标 key (e.g. detail_review_count_entry)')
    p2 = sub.add_parser('scroll', help='测试滚动')
    p2.add_argument('--anchor', default='review_list_anchor')
    p2.add_argument('--dy', type=int, default=-300)
    p3 = sub.add_parser('info', help='显示窗口信息')
    args = ap.parse_args()

    win = get_window()
    if win is None:
        sys.stderr.write("❌ 找不到 PC 微信小程序窗口（请确保'大众点评'在打开）\n")
        return 1
    print(f"窗口: wid={win['wid']} 位置=({win['x']},{win['y']}) 大小={win['w']}x{win['h']}")
    if args.cmd == 'info':
        return 0

    points = load_points()
    base_w = int(points.get('base_width', win['w']))
    base_h = int(points.get('base_height', win['h']))

    if args.cmd == 'click':
        if args.key not in points:
            sys.stderr.write(f"❌ 没录过 {args.key}\n")
            return 1
        rx, ry = parse_coord(points[args.key])
        print(f"点击 {args.key} = ({rx},{ry}) [base {base_w}x{base_h}]")
        human_click(win, rx, ry, base_w=base_w, base_h=base_h)
    elif args.cmd == 'scroll':
        if args.anchor not in points:
            sys.stderr.write(f"❌ 没录过 {args.anchor}\n")
            return 1
        rx, ry = parse_coord(points[args.anchor])
        print(f"滚动 {args.anchor} dy={args.dy}")
        human_scroll(win, rx, ry, dy=args.dy, base_w=base_w, base_h=base_h)
    return 0


if __name__ == '__main__':
    sys.exit(main())
