#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
极限速度版 - 目标 1000 条/分钟

关键优化（相比 fast.py）：
1. xdotool --repeat：一条命令完成 N 个 tick，省 subprocess 开销
2. tick 数减到 3-5（实测最小触发 onReachBottom 的量）
3. 移除 idle_pause（API 返回即下一轮）
4. 评论数轮询 15ms（接近实时）
5. 长停顿减到每 80-150 轮一次

目标周期: 300-500ms/轮 → 一轮约 12-15 条 → 1500-3000 条/分钟

反爬权衡：
- 速度远超真实用户（人类极限 ~200条/分钟）
- 加入"自适应"：检测到响应变慢/数据变少立即放慢
- 仍保留随机性（tick 数和间隔随机、偶尔回滚）
"""

import json
import math
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

XLSX = ROOT / '门店抽样.xlsx'
if not XLSX.exists():
    XLSX = ROOT / '达美乐_门店.xlsx'
OUT_DIR = ROOT / 'output' / 'store_reviews'
TARGET = Path('/tmp/mitm_target.json')

stop_flag = threading.Event()


def review_file(idx, name):
    return OUT_DIR / f"{idx:03d}_{name.replace('/', '_')}.json"


def review_count(idx, name):
    f = review_file(idx, name)
    if not f.exists():
        return 0
    try:
        return len(json.loads(f.read_text(encoding='utf-8')))
    except:
        return 0


# ─── 极限参数 ─────────────────────────────────────────────────────

def calc_params(n_reviews):
    """关键: 每次滚动量足以穿过新加载内容到新底部"""
    if n_reviews <= 100:
        return {
            'ticks': (35, 50),
            'delay_ms': (5, 9),
            'wait_max': 1.5,
            'idle_pause': (0.0, 0.05),
            'long_every': (100, 200),
            'long_range': (1.0, 2.0),
            'back_prob': 0.02,
            'desc': '🔥极限'
        }
    elif n_reviews <= 500:
        return {
            'ticks': (38, 55),
            'delay_ms': (6, 10),
            'wait_max': 2.0,
            'idle_pause': (0.0, 0.08),
            'long_every': (80, 150),
            'long_range': (1.5, 3.0),
            'back_prob': 0.03,
            'desc': '🔥极速'
        }
    elif n_reviews <= 1000:
        return {
            'ticks': (42, 60),
            'delay_ms': (7, 12),
            'wait_max': 2.0,
            'idle_pause': (0.05, 0.12),
            'long_every': (60, 100),
            'long_range': (2.0, 4.0),
            'back_prob': 0.04,
            'desc': '🚀超快'
        }
    else:
        return {
            'ticks': (45, 65),
            'delay_ms': (8, 14),
            'wait_max': 2.5,
            'idle_pause': (0.05, 0.15),
            'long_every': (50, 80),
            'long_range': (2.5, 5.0),
            'back_prob': 0.05,
            'desc': '⚡稳定'
        }


# ─── 滚动（极限优化） ─────────────────────────────────────────────

def sigmoid_intervals(n, lo_ms, hi_ms):
    """
    sigmoid 加减速曲线（毫秒），开始慢→中间快→结束慢
    模拟人类滚轮加速度
    """
    out = []
    for i in range(n):
        x = (i / max(n-1, 1)) * 6 - 3  # [-3, 3]
        sig = 1 / (1 + math.exp(-x))
        # 中间快(间隔小)，两端慢(间隔大)
        factor = 1 - 0.5 * (1 - abs(sig - 0.5) * 2)
        iv = lo_ms + (hi_ms - lo_ms) * factor
        # 加 ±15% 噪声，避免完全规律
        iv *= random.uniform(0.85, 1.15)
        out.append(max(2.0, iv))  # 最小 2ms
    return out


def scroll_burst(wid, n_ticks, lo_ms, hi_ms, direction='down'):
    """
    分批 --repeat 方式：保持速度 + 模拟 sigmoid 加减速
    比串联 click 快 ~13倍

    把 n_ticks 分成 4 个 batch:
    - batch 1: 慢起步 (delay 接近 hi_ms)
    - batch 2-3: 中段快 (delay 接近 lo_ms)
    - batch 4: 慢收尾 (delay 接近 hi_ms)
    """
    btn = '5' if direction == 'down' else '4'

    # 把 n 分成 4 batch
    sizes = [n_ticks // 4 + (1 if i < n_ticks % 4 else 0) for i in range(4)]
    # 每个 batch 的 delay (sigmoid: 慢-快-快-慢)
    delays = [
        int(hi_ms * random.uniform(0.85, 1.0)),       # 慢起步
        int(lo_ms * random.uniform(1.0, 1.2)),         # 快
        int(lo_ms * random.uniform(1.0, 1.2)),         # 快
        int(hi_ms * random.uniform(0.85, 1.0)),       # 慢收尾
    ]

    args = ['xdotool']
    for i, (sz, dl) in enumerate(zip(sizes, delays)):
        if sz <= 0:
            continue
        args += ['click', '--repeat', str(sz), '--delay', str(dl), btn]
        # batch 间的微停顿（也是 sigmoid 自然性的一部分）
        if i < len(sizes) - 1:
            micro_sleep = random.uniform(0.015, 0.045)
            args += ['sleep', f'{micro_sleep:.4f}']

    subprocess.run(args, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_api_fast(idx, name, last_count, max_wait):
    """超快事件驱动等待 - 15ms 轮询"""
    start = time.time()
    while time.time() - start < max_wait:
        if stop_flag.is_set():
            return last_count, False
        cur = review_count(idx, name)
        if cur > last_count:
            return cur, True
        time.sleep(0.015)
    return review_count(idx, name), False


def scroll_session(wid, idx, name, n_reviews):
    p = calc_params(n_reviews if n_reviews > 0 else 500)
    max_rounds = (n_reviews // 8) + 50 if n_reviews > 0 else 800

    subprocess.run(['xdotool', 'windowactivate', '--sync', str(wid)], check=False)
    time.sleep(0.2)
    points = load_points()
    rx, ry = parse_coord(points['review_list_anchor'])
    win = get_window()
    if win:
        subprocess.run(['xdotool', 'mousemove', str(win['x']+rx), str(win['y']+ry)], check=False)
    time.sleep(0.15)

    last_count = review_count(idx, name)
    no_growth = 0
    total = 0
    next_long = random.randint(*p['long_every'])
    api_times = []
    growths = []
    safety_factor = 1.0  # 自适应：响应慢时放慢

    while total < max_rounds and not stop_flag.is_set():
        # 偶尔回滚（保持自然性）
        if random.random() < p['back_prob'] and total > 10:
            scroll_burst(wid, random.randint(2, 4),
                         p['delay_ms'][0] * 1.5, p['delay_ms'][1] * 1.5,
                         direction='up')
            time.sleep(random.uniform(0.2, 0.5))

        # 主滚动（sigmoid 不均匀，一次 subprocess 完成）
        n_ticks = random.randint(*p['ticks'])
        lo, hi = p['delay_ms']
        # safety_factor 整体放大间隔
        t_scroll = time.time()
        scroll_burst(wid, n_ticks, lo * safety_factor, hi * safety_factor)
        scroll_dur = time.time() - t_scroll
        total += 1

        # 事件驱动等 API（wait_max 固定，不被 safety_factor 拖累）
        t_wait = time.time()
        new_count, got = wait_api_fast(idx, name, last_count, p['wait_max'])
        wait_time = time.time() - t_wait

        if got:
            api_times.append(wait_time)
            grew = new_count - last_count
            growths.append(grew)
            no_growth = 0
            last_count = new_count

            # 自适应：响应快+数据多 → 维持高速；否则放慢
            if wait_time < 0.6 and grew >= 8:
                safety_factor = max(0.9, safety_factor - 0.05)
            elif wait_time > 1.2 or grew < 5:
                safety_factor = min(1.3, safety_factor + 0.1)  # 上限 1.3

            print(f' +{grew}[s{scroll_dur*1000:.0f}+w{wait_time*1000:.0f}]', end='', flush=True)

            # 极短停顿
            ip = random.uniform(*p['idle_pause']) * safety_factor
            if ip > 0:
                time.sleep(ip)
        else:
            no_growth += 1
            safety_factor = min(1.3, safety_factor + 0.1)
            print(f' ·[s{scroll_dur*1000:.0f}]', end='', flush=True)

        # 长停顿
        if total >= next_long:
            time.sleep(random.uniform(*p['long_range']))
            next_long = total + random.randint(*p['long_every'])
            print('☕', end='', flush=True)

        # 到底判定
        if no_growth >= 4 and total > 10:
            time.sleep(1.5)
            final = review_count(idx, name)
            if final == last_count:
                print(' [到底]', end='', flush=True)
                break
            last_count = final
            no_growth = 0

    # 统计
    if api_times:
        avg_t = sum(api_times) / len(api_times) * 1000
        avg_g = sum(growths) / len(growths)
        print(f"\n   API平均: {avg_t:.0f}ms | 每次: {avg_g:.1f}条 | 安全系数: {safety_factor:.2f}", end='')

    return total, last_count


# ─── 交互 ─────────────────────────────────────────────────────────

def main():
    stores = load_stores_from_xlsx(XLSX)
    print(f"🔥 极限版 | {len(stores)}家店")
    print("  目标: 1000+条/分钟 | 自适应安全系数")
    print("  list=进度 | q=退出\n")

    while True:
        try:
            raw = input("🎯 编号: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋")
            break
        if raw in ('q', 'quit', 'exit'):
            break
        if raw == 'list':
            for i, s in enumerate(stores[:60], 1):
                cnt = review_count(i, s.name)
                tag = '✅' if cnt >= 10 else '  '
                print(f"  {tag} {i:03d} {s.name} ({cnt})")
            continue
        try:
            idx = int(raw)
        except ValueError:
            continue
        if idx < 1 or idx > len(stores):
            print(f"  ❌ 1-{len(stores)}")
            continue

        name = stores[idx-1].name
        cur = review_count(idx, name)
        print(f"  {name} (已有{cur}条)")

        try:
            n_input = input("  评论数 (回车=自动): ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        n_reviews = int(n_input) if n_input else 0
        p = calc_params(n_reviews if n_reviews else 500)
        print(f"  {p['desc']} | 目标: {n_reviews or '自动'}")

        if not subprocess.run(['pgrep', '-f', 'mitmdump'], capture_output=True).stdout.strip():
            print("  ❌ mitmdump 没在跑")
            continue

        TARGET.write_text(json.dumps({'idx': idx, 'name': name}, ensure_ascii=False))
        win = get_window()
        if not win:
            print("  ❌ 没找到微信窗口")
            continue

        input("  确认在评价页 Enter...")

        stop_flag.clear()
        old_sig = signal.signal(signal.SIGINT,
            lambda s, f: (stop_flag.set(), print(' [停]', end='', flush=True)))

        t0 = time.time()
        print("  ", end='', flush=True)
        rounds, final = scroll_session(win['wid'], idx, name, n_reviews)
        elapsed = time.time() - t0
        signal.signal(signal.SIGINT, old_sig)

        added = final - cur
        rate_pm = added / (elapsed/60) if elapsed > 5 else 0
        print(f"\n  ✅ +{added}条 → 总{final}条 | {rounds}轮 {elapsed:.1f}s ({rate_pm:.0f}条/分)\n")


if __name__ == '__main__':
    main()
