#!/usr/bin/env python3
"""
实验：测试 3 种滚动方式的速度
1. 滚轮 click (button 5) - 当前 turbo.py 使用
2. 鼠标拖拽 (mousedown + mousemove + mouseup) - 模拟触摸滑动
3. 滚轮 click 但 tick 数减半
"""

import subprocess, time, sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from human_click import get_window, load_points, parse_coord

points = load_points()
rx, ry = parse_coord(points['review_list_anchor'])
win = get_window()
if not win:
    print("❌ 没微信窗口")
    sys.exit(1)

wid = win['wid']
abs_x = win['x'] + rx
abs_y = win['y'] + ry

# 拖拽起点和终点（在评论区内向上拖 = 滚动向下）
DRAG_FROM_Y = abs_y + 200
DRAG_TO_Y = abs_y - 200  # 向上拖 400px

def method_click(n=10):
    """方法1: 10 次滚轮 click"""
    args = ['xdotool']
    for i in range(n):
        args += ['click', '--window', str(wid), '5']
        if i < n-1:
            args += ['sleep', '0.008']
    subprocess.run(args, check=False, capture_output=True)

def method_drag():
    """方法2: 一次拖拽（模拟触摸滑动）"""
    subprocess.run([
        'xdotool', 
        'mousemove', str(abs_x), str(DRAG_FROM_Y),
        'sleep', '0.05',
        'mousedown', '1',
        'sleep', '0.03',
        'mousemove', str(abs_x), str(DRAG_TO_Y),
        'sleep', '0.02',
        'mouseup', '1'
    ], check=False, capture_output=True)

def method_click_few(n=5):
    """方法3: 少量滚轮"""
    args = ['xdotool']
    for i in range(n):
        args += ['click', '--window', str(wid), '5']
        if i < n-1:
            args += ['sleep', '0.008']
    subprocess.run(args, check=False, capture_output=True)


print(f"窗口: {win}")
print(f"鼠标位置: ({abs_x}, {abs_y})")
print()
print("将测试 3 种滚动方法，每种执行 3 次")
print("请在微信小程序的评价页就绪后，按 Enter 开始")
input()

# 把鼠标移到评论区
subprocess.run(['xdotool', 'mousemove', str(abs_x), str(abs_y)], check=False)
time.sleep(0.5)

for name, fn, args in [
    ('方法1 click×10 (当前模式)', method_click, [10]),
    ('方法2 拖拽 (mousedown+move+up)', method_drag, []),
    ('方法3 click×5 (少量)', method_click_few, [5]),
]:
    print(f"\n=== {name} ===")
    for trial in range(3):
        # 鼠标定位
        subprocess.run(['xdotool', 'mousemove', str(abs_x), str(abs_y)], check=False)
        time.sleep(0.3)
        
        t0 = time.time()
        fn(*args)
        elapsed = (time.time() - t0) * 1000
        print(f"  第{trial+1}次: {elapsed:.0f}ms")
        time.sleep(1.5)  # 让小程序加载新内容

print("\n请观察哪种方法滚动效果最好（条数增加最多/最稳定）")
