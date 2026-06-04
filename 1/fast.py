#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
极速版抓取 - 事件驱动滚动

核心策略：
1. 每次只滚刚好触发 onReachBottom 的最小量（5-10 tick）
2. 滚完立即监测 API 响应（评论数变化），不固定等待
3. API 一返回就下一轮（响应时间 200-800ms，比固定等 1.5s 快 2-7 倍）
4. 仍保留自然性：随机间隔、偶尔回滚、偶尔短暂停顿
5. 自适应：连续无响应才放慢；正常响应就保持高速

预期速度：旧版 ~30 条/分钟 → 新版 ~150-300 条/分钟
反爬控制：
- API 调用间隔 1-2.5s（接近真实用户快速浏览的节奏）
- 滚动 tick 间隔 25-80ms（人类滚轮范围）
- 仍有 sigmoid 加减速、随机回滚
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


# ─── 极速参数 ─────────────────────────────────────────────────────

def calc_params(n_reviews):
    """根据评论数动态调参，比 go.py 激进 5-10 倍"""
    if n_reviews <= 50:
        return {
            'ticks': (4, 8),           # 一次滚 4-8 tick（足够触发加载）
            'tick_iv': (0.02, 0.05),   # tick 间隔 20-50ms
            'wait_max': 2.0,           # 等 API 最多 2s
            'idle_pause': (0.1, 0.3),  # API 返回后再停 100-300ms
            'long_every': (40, 60),    # 极少长停
            'long_range': (1.5, 3.5),
            'back_prob': 0.03,
            'desc': '⚡极速'
        }
    elif n_reviews <= 200:
        return {
            'ticks': (5, 9),
            'tick_iv': (0.025, 0.06),
            'wait_max': 2.5,
            'idle_pause': (0.15, 0.4),
            'long_every': (30, 50),
            'long_range': (2, 4),
            'back_prob': 0.05,
            'desc': '🚀快速'
        }
    elif n_reviews <= 500:
        return {
            'ticks': (5, 10),
            'tick_iv': (0.025, 0.07),
            'wait_max': 3.0,
            'idle_pause': (0.2, 0.5),
            'long_every': (25, 40),
            'long_range': (3, 6),
            'back_prob': 0.06,
            'desc': '⚡平衡'
        }
    else:
        # >500 评论：略微保守，但仍然比旧版快 5x
        return {
            'ticks': (5, 9),
            'tick_iv': (0.03, 0.08),
            'wait_max': 3.0,
            'idle_pause': (0.25, 0.6),
            'long_every': (20, 35),
            'long_range': (4, 8),
            'back_prob': 0.08,
            'desc': '🛡️稳速'
        }


# ─── 滚动 ────────────────────────────────────────────────────────

def do_tick(wid, direction='down'):
    btn = '5' if direction == 'down' else '4'
    subprocess.run(['xdotool', 'click', '--window', str(wid), btn],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sigmoid_intervals(n, lo, hi):
    """sigmoid 加减速曲线（保留人类特征但速度优化）"""
    out = []
    for i in range(n):
        x = (i / max(n-1, 1)) * 4 - 2  # 范围比之前窄，更紧凑
        factor = 1 - 0.4 * (1 - abs(1/(1+math.exp(-x)) - 0.5) * 2)
        out.append((lo + (hi-lo)*factor) * random.uniform(0.85, 1.15))
    return out


def wait_for_api(idx, name, last_count, max_wait):
    """
    事件驱动：等 API 响应（评论数变化）
    最多等 max_wait 秒，提前返回
    """
    start = time.time()
    poll_iv = 0.05  # 50ms 轮询，几乎实时
    while time.time() - start < max_wait:
        if stop_flag.is_set():
            return last_count, False
        cur = review_count(idx, name)
        if cur > last_count:
            # 收到数据，再等极短时间确保完整（同一API可能分多次写）
            time.sleep(0.1)
            cur2 = review_count(idx, name)
            return cur2, True
        time.sleep(poll_iv)
    return review_count(idx, name), False


def scroll_session(wid, idx, name, n_reviews):
    p = calc_params(n_reviews if n_reviews > 0 else 200)
    max_rounds = (n_reviews // 8) + 30 if n_reviews > 0 else 500

    subprocess.run(['xdotool', 'windowactivate', '--sync', str(wid)], check=False)
    time.sleep(0.3)
    points = load_points()
    rx, ry = parse_coord(points['review_list_anchor'])
    win = get_window()
    if win:
        subprocess.run(['xdotool', 'mousemove', str(win['x']+rx), str(win['y']+ry)], check=False)
    time.sleep(0.2)

    last_count = review_count(idx, name)
    no_growth = 0
    total = 0
    next_long = random.randint(*p['long_every'])
    api_response_times = []  # 记录 API 响应时间

    while total < max_rounds and not stop_flag.is_set():
        # 偶尔回滚（保持自然性）
        if random.random() < p['back_prob'] and total > 5:
            for _ in range(random.randint(2, 4)):
                do_tick(wid, 'up')
                time.sleep(random.uniform(0.03, 0.08))
            time.sleep(random.uniform(0.3, 0.8))

        # 滚动（最小量，刚够触发加载）
        n_ticks = random.randint(*p['ticks'])
        for iv in sigmoid_intervals(n_ticks, *p['tick_iv']):
            do_tick(wid, 'down')
            time.sleep(iv)

        total += 1

        # 事件驱动等 API
        t_wait_start = time.time()
        new_count, got_data = wait_for_api(idx, name, last_count, p['wait_max'])
        wait_time = time.time() - t_wait_start

        if got_data:
            api_response_times.append(wait_time)
            no_growth = 0
            grew = new_count - last_count
            last_count = new_count
            print(f' +{grew}({wait_time*1000:.0f}ms)', end='', flush=True)
            # API 返回后短暂停顿（模拟人看到新内容的反应）
            time.sleep(random.uniform(*p['idle_pause']))
        else:
            no_growth += 1
            print(' ·', end='', flush=True)

        # 长停顿（极少，不影响整体速度）
        if total >= next_long:
            time.sleep(random.uniform(*p['long_range']))
            next_long = total + random.randint(*p['long_every'])
            print('☕', end='', flush=True)

        # 到底/被反爬判定
        if no_growth >= 4 and total > 10:
            time.sleep(2)
            final = review_count(idx, name)
            if final == last_count:
                print(' [到底]', end='', flush=True)
                break
            last_count = final
            no_growth = 0

    # 输出统计
    if api_response_times:
        avg = sum(api_response_times) / len(api_response_times)
        print(f"\n   API 平均响应: {avg*1000:.0f}ms ({len(api_response_times)}次)", end='')

    return total, last_count


# ─── 交互 ─────────────────────────────────────────────────────────

def main():
    stores = load_stores_from_xlsx(XLSX)
    print(f"⚡ 极速版 | {len(stores)}家店")
    print("  事件驱动：API响应即下一轮，速度提升5-10倍")
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
        p = calc_params(n_reviews if n_reviews else 200)
        print(f"  {p['desc']} | 目标: {n_reviews or '自动'}")

        if not pgrep_check():
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
        print(f"\n  ✅ +{added}条 → 总{final}条 | {rounds}轮 {elapsed:.0f}s ({rate_pm:.0f}条/分)\n")


def pgrep_check():
    r = subprocess.run(['pgrep', '-f', 'mitmdump'], capture_output=True, text=True)
    return bool(r.stdout.strip())


if __name__ == '__main__':
    main()
