#!/usr/bin/env python3
"""测 xdotool 不同方式的实际耗时"""
import subprocess, time, sys
sys.path.insert(0, '.')
from human_click import get_window

win = get_window()
if not win:
    print("没找到微信窗口，但可以测无窗口模式")
    wid = None
else:
    wid = win['wid']
    print(f"微信窗口 ID: {wid}")

print("\n警告: 测试会发送大量 wheel 事件到当前聚焦窗口")
print("请把焦点切到一个空白浏览器或桌面（不要在大众点评！）")
print("3 秒后开始...")
for i in range(3, 0, -1):
    print(f"  {i}...")
    time.sleep(1)


def test(label, args_builder, n=47):
    args = args_builder(n)
    t0 = time.time()
    subprocess.run(args, check=False, capture_output=True)
    elapsed = (time.time() - t0) * 1000
    print(f"  {label}: {elapsed:.0f}ms (n={n})")


# 测试 1: 47 click + sleep 0.008 串联，不带 --window
def builder_a(n):
    args = ['xdotool']
    for i in range(n):
        args += ['click', '5']
        if i < n-1:
            args += ['sleep', '0.008']
    return args

# 测试 2: 47 click + sleep 0.008 串联，带 --window
def builder_b(n):
    if not wid:
        return None
    args = ['xdotool']
    for i in range(n):
        args += ['click', '--window', str(wid), '5']
        if i < n-1:
            args += ['sleep', '0.008']
    return args

# 测试 3: --repeat 47 --delay 8
def builder_c(n):
    return ['xdotool', 'click', '--repeat', str(n), '--delay', '8', '5']

# 测试 4: --repeat 47 --delay 8 --window
def builder_d(n):
    if not wid:
        return None
    return ['xdotool', 'click', '--repeat', str(n), '--delay', '8', '--window', str(wid), '5']

# 测试 5: 纯 sleep（基线）
def builder_e(n):
    args = ['xdotool']
    for i in range(n):
        args += ['sleep', '0.008']
    return args


print("\n=== 滚动耗时测试 (47 ticks × 8ms) ===")
print("理论最低: 47 × 8ms = 376ms")
print()

for label, builder in [
    ('5. 纯sleep基线         ', builder_e),
    ('1. click 5 (无window)  ', builder_a),
    ('3. --repeat 5 (无window)', builder_c),
    ('2. click 5 --window    ', builder_b),
    ('4. --repeat 5 --window ', builder_d),
]:
    args = builder(47)
    if args is None:
        print(f"  {label}: 跳过（无窗口）")
        continue
    test(label, lambda n, a=args: a, 47)
    time.sleep(0.5)

print("\n如果带 --window 的明显比不带的慢 → xdotool 在等窗口响应")
