#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
优化版滚动脚本 - 基于反反爬研究的人类行为模拟

改进点（相比 scroll.py）：
1. 滚动速度/距离用正态分布+韦伯分布，不再是固定 5×10×30ms
2. 停顿时间用韦伯分布模拟人类阅读节奏（短停多、长停少）
3. 偶尔回滚（模拟人类回看）
4. 偶尔长停顿（模拟仔细看某条评论）
5. 滚动加速度曲线（sigmoid）而非匀速
6. 自适应节奏：检测到增长放缓时主动降速
7. 更智能的到底检测：区分"到底"和"被反爬"

用法:
    python3 scroll2.py 5            # 自动滚到底
    python3 scroll2.py 5 499        # 指定评论数
    python3 scroll2.py 5 --fast     # 快速模式（间隔短，风险略高）
"""

import json
import math
import os
import random
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from human_click import get_window, load_points, parse_coord
from review_exporter import load_stores_from_xlsx

XLSX = ROOT / '门店抽样.xlsx'
OUT_DIR = ROOT / 'output' / 'store_reviews'
TARGET = Path('/tmp/mitm_target.json')

stop_flag = threading.Event()


# ─── 人类行为参数 ─────────────────────────────────────────────────
# 基于研究：
# - 人类滚轮 tick 间隔: 30-150ms（非均匀，偏短）
# - 阅读停顿: 韦伯分布 shape=1.8, scale=0.6 → 中位数~0.8s, 偶尔3-5s
# - 回滚概率: 8-12%
# - 长停顿(仔细看): 每5-10次滚动出现一次, 5-15s
# - 速度变化: 40-60% variation

class HumanProfile:
    """人类滚动行为配置"""
    def __init__(self, mode='normal'):
        if mode == 'fast':
            # 快速模式：间隔短，适合评论少的店
            self.ticks_per_burst = (6, 14)      # 每次burst的tick数
            self.bursts_per_scroll = (3, 6)     # 每次滚动的burst数
            self.tick_interval = (0.02, 0.08)   # tick间隔(s)
            self.burst_gap = (0.04, 0.12)       # burst间隔(s)
            self.read_pause_shape = 1.5         # 韦伯分布shape
            self.read_pause_scale = 0.5         # 韦伯分布scale → 中位数~0.6s
            self.long_pause_every = (8, 15)     # 每N次滚动一次长停
            self.long_pause_range = (3, 8)      # 长停时间(s)
            self.scrollback_prob = 0.06         # 回滚概率
            self.scrollback_ticks = (2, 5)      # 回滚tick数
        else:
            # 正常模式：安全优先
            self.ticks_per_burst = (5, 12)
            self.bursts_per_scroll = (3, 7)
            self.tick_interval = (0.025, 0.12)
            self.burst_gap = (0.05, 0.15)
            self.read_pause_shape = 1.8
            self.read_pause_scale = 0.7         # 中位数~0.9s
            self.long_pause_every = (5, 10)
            self.long_pause_range = (5, 15)
            self.scrollback_prob = 0.10
            self.scrollback_ticks = (2, 6)


# ─── uinput 真实硬件事件（可选，需要 sudo） ──────────────────────

def try_create_uinput():
    """尝试创建 uinput 设备，失败则返回 None（fallback 到 xdotool）"""
    try:
        import fcntl
        fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
        UI_SET_EVBIT = 0x40045564
        UI_SET_RELBIT = 0x40045566
        UI_DEV_CREATE = 0x5501
        EV_REL = 0x02
        REL_WHEEL = 0x08

        fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
        fcntl.ioctl(fd, UI_SET_RELBIT, REL_WHEEL)

        name = b"human_scroll\x00" + b"\x00" * 67
        dev_struct = name + struct.pack('HHH', 0x01, 0x01, 0x01)
        dev_struct += b"\x00" * (280 - len(dev_struct))
        os.write(fd, dev_struct)
        fcntl.ioctl(fd, UI_DEV_CREATE)
        time.sleep(0.3)
        return fd
    except (PermissionError, OSError):
        return None


def uinput_tick(fd, direction=-1):
    """发送一个真实内核滚轮事件"""
    EV_REL, REL_WHEEL, EV_SYN, SYN_REPORT = 0x02, 0x08, 0x00, 0x00
    now = time.time()
    sec, usec = int(now), int((now - int(now)) * 1000000)
    os.write(fd, struct.pack('llHHi', sec, usec, EV_REL, REL_WHEEL, direction))
    os.write(fd, struct.pack('llHHi', sec, usec, EV_SYN, SYN_REPORT, 0))


def destroy_uinput(fd):
    if fd is not None:
        import fcntl
        try:
            fcntl.ioctl(fd, 0x5502)  # UI_DEV_DESTROY
        except:
            pass
        os.close(fd)


# ─── 滚动执行器 ──────────────────────────────────────────────────

def do_scroll_tick(wid, uinput_fd, direction='down'):
    """执行一个滚轮tick（优先uinput，fallback xdotool）"""
    if uinput_fd is not None:
        uinput_tick(uinput_fd, -1 if direction == 'down' else 1)
    else:
        btn = '5' if direction == 'down' else '4'
        subprocess.run(['xdotool', 'click', '--window', str(wid), btn],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sigmoid_intervals(n, base_min, base_max):
    """
    生成 sigmoid 加速度曲线的间隔序列：
    开始慢 → 中间快 → 结束慢（模拟手指滚轮的自然加减速）
    """
    intervals = []
    for i in range(n):
        # sigmoid: 中间快（间隔小），两端慢（间隔大）
        x = (i / max(n - 1, 1)) * 6 - 3  # map to [-3, 3]
        sig = 1 / (1 + math.exp(-x))
        # 反转：sig=0.5(中间)时间隔最小
        factor = 1 - 0.6 * (1 - abs(sig - 0.5) * 2)
        interval = base_min + (base_max - base_min) * factor
        # 加噪声
        interval *= random.uniform(0.8, 1.2)
        intervals.append(max(base_min * 0.8, interval))
    return intervals


# ─── 核心滚动逻辑 ─────────────────────────────────────────────────

def human_scroll_session(wid, idx, name, max_pages=200, profile=None):
    """
    人类行为模拟滚动。
    
    核心策略：
    - 每次"滚动"由多个burst组成，每个burst有多个tick
    - tick间隔用sigmoid曲线（加速→匀速→减速）
    - burst之间有微停顿
    - 滚动之间有阅读停顿（韦伯分布）
    - 偶尔回滚、偶尔长停
    - 自适应：连续无增长时降速
    """
    if profile is None:
        profile = HumanProfile('normal')

    subprocess.run(['xdotool', 'windowactivate', '--sync', str(wid)], check=False)
    time.sleep(0.3)

    points = load_points()
    rx, ry = parse_coord(points['review_list_anchor'])
    win = get_window()
    if win:
        subprocess.run(['xdotool', 'mousemove', str(win['x'] + rx), str(win['y'] + ry)],
                       check=False)
    time.sleep(0.3)

    # uinput（真实硬件事件，比 xdotool 的 XTEST 更难检测）
    uinput_fd = try_create_uinput()
    if uinput_fd:
        print('[uinput]', end=' ', flush=True)

    last_count = review_count(idx, name)
    no_growth = 0
    total = 0
    next_long_pause = random.randint(*profile.long_pause_every)
    slowdown_factor = 1.0  # 自适应降速因子

    try:
        while total < max_pages and not stop_flag.is_set():
            # ── 偶尔回滚（模拟人类回看上面的评论）──
            if random.random() < profile.scrollback_prob and total > 2:
                back_ticks = random.randint(*profile.scrollback_ticks)
                for _ in range(back_ticks):
                    do_scroll_tick(wid, uinput_fd, 'up')
                    time.sleep(random.uniform(0.04, 0.12))
                # 回看后停顿（像在重新读）
                time.sleep(random.uniform(0.8, 2.5))

            # ── 主滚动：多burst ──
            n_bursts = random.randint(*profile.bursts_per_scroll)
            for b in range(n_bursts):
                if stop_flag.is_set():
                    break
                n_ticks = random.randint(*profile.ticks_per_burst)
                # sigmoid 间隔曲线
                intervals = sigmoid_intervals(
                    n_ticks, profile.tick_interval[0], profile.tick_interval[1])
                for interval in intervals:
                    do_scroll_tick(wid, uinput_fd, 'down')
                    time.sleep(interval)
                # burst 间微停顿
                if b < n_bursts - 1:
                    time.sleep(random.uniform(*profile.burst_gap))

            total += 1

            # ── 阅读停顿（韦伯分布）──
            pause = random.weibullvariate(profile.read_pause_scale, profile.read_pause_shape)
            pause = min(pause, 4.0) * slowdown_factor  # 限制上界 + 自适应
            time.sleep(pause)

            # ── 长停顿（模拟仔细看某条评论）──
            if total >= next_long_pause:
                long_pause = random.uniform(*profile.long_pause_range) * slowdown_factor
                time.sleep(long_pause)
                next_long_pause = total + random.randint(*profile.long_pause_every)
                print('☕', end='', flush=True)

            # ── 增长检测 ──
            if total % 3 == 0:
                cur = review_count(idx, name)
                growth = cur - last_count
                last_count = cur
                if growth > 0:
                    no_growth = 0
                    slowdown_factor = max(0.8, slowdown_factor - 0.1)  # 有增长→恢复速度
                    print(f' [{cur}]', end='', flush=True)
                else:
                    no_growth += 1
                    slowdown_factor = min(2.0, slowdown_factor + 0.3)  # 无增长→降速
                    print('.', end='', flush=True)

                # 到底判定：连续无增长
                if no_growth >= 3 and total > 6:
                    # 再等一下确认（可能是网络延迟）
                    time.sleep(3)
                    final_check = review_count(idx, name)
                    if final_check == last_count:
                        print(' [到底]', end='', flush=True)
                        break
                    else:
                        # 只是延迟，继续
                        last_count = final_check
                        no_growth = 0
                        print(f' [{final_check}!]', end='', flush=True)

    finally:
        destroy_uinput(uinput_fd)

    return total, last_count


# ─── 工具函数 ─────────────────────────────────────────────────────

def review_file(idx, name):
    return OUT_DIR / f"{idx:03d}_{name.replace('/', '_')}.json"


def review_count(idx, name):
    f = review_file(idx, name)
    if not f.exists():
        return 0
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return len(d) if isinstance(d, list) else 0
    except Exception:
        return 0


# ─── 主入口 ───────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("用法: python3 scroll2.py <编号> [评论数] [--fast]")
        return 1

    fast_mode = '--fast' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('--')]

    idx = int(args[0])
    if not XLSX.exists():
        # fallback
        alt = ROOT / '达美乐_门店.xlsx'
        if alt.exists():
            stores = load_stores_from_xlsx(alt)
        else:
            print(f"❌ 找不到 {XLSX}")
            return 1
    else:
        stores = load_stores_from_xlsx(XLSX)

    if idx < 1 or idx > len(stores):
        print(f"❌ 编号超范围 1-{len(stores)}")
        return 1
    name = stores[idx - 1].name

    expected = int(args[1]) if len(args) > 1 else 0
    max_pages = (expected // 10) + 10 if expected > 0 else 300

    # 检查 mitmdump
    r = subprocess.run(['pgrep', '-f', 'mitmdump.*8080'], capture_output=True, text=True)
    if not r.stdout.strip():
        # 也检查 9092 端口的
        r2 = subprocess.run(['pgrep', '-f', 'mitmdump.*9092'], capture_output=True, text=True)
        if not r2.stdout.strip():
            print("❌ mitmdump 没在跑，先 bash start_mitm.sh")
            return 1

    # 设置目标
    TARGET.write_text(json.dumps({'idx': idx, 'name': name}, ensure_ascii=False))

    win = get_window()
    if not win:
        print("❌ 找不到微信窗口")
        return 1

    mode_str = '⚡快速' if fast_mode else '🐢安全'
    profile = HumanProfile('fast' if fast_mode else 'normal')

    print(f"🍕 {idx:03d} {name} ({mode_str})")
    start = review_count(idx, name)
    print(f"   起点: {start} 条", end='')
    if expected > 0:
        print(f" → 目标 {expected} 条")
    else:
        print(f" → 自动滚到底")

    print(f"   确认在评价页，按 Enter...", end='', flush=True)
    input()

    signal.signal(signal.SIGINT,
                  lambda s, f: (stop_flag.set(), print(' [停]', end='', flush=True)))

    t0 = time.time()
    print(f"   滚动中 ", end='', flush=True)
    rounds, final = human_scroll_session(win['wid'], idx, name, max_pages, profile)
    elapsed = time.time() - t0

    print(f"\n   {rounds} 次滚动, {elapsed:.0f}s, +{final - start} 条")

    if final == start:
        print(f"   ⚠️ 0 增长 → 检查: 1)是否在评价页 2)mitmdump日志 3)是否被反爬")
    else:
        rate = (final - start) / (elapsed / 60) if elapsed > 0 else 0
        print(f"   ✅ 总计 {final} 条 ({rate:.0f} 条/分钟)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
