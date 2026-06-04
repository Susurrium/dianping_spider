#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
最终版抓取脚本 run.py

整合的有效措施（基于抓包分析 + 反爬研究）：

【速度】分批 --repeat 滚动（比串联 click 快 ~13x），事件驱动等 API
【反限流】
  1. 自适应限速：API 变慢/数据变少自动降速（真实有效）
  2. 分段冷却：每抓 N 页强制短歇，打断"连续高频"画像
  3. 会话级长停顿：模拟人类停下来读
  4. sigmoid 不均匀滚动间隔
  5. 偶尔回滚
  6. 跨店冷却提醒

【为什么不能伪造请求】
  大众点评请求带 mtgsig 签名，绑定 _lxsdk_cuid(设备) + 参数 + 时间。
  改任何参数（含 cuid/start）→ 签名失效 → 403。
  签名算法在小程序加密JS里，无法离线生成。
  所以唯一能控制的是"频率"和"节奏"，这个脚本把这两点做到最优。

用法:
    python3 run.py                        # 交互模式（默认大众点评）
    python3 run.py --platform meituan     # 美团模式入口提示
"""

import argparse
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

parser = argparse.ArgumentParser()
parser.add_argument('--platform', choices=['dianping', 'meituan'], default='dianping',
                    help='选择平台，默认大众点评')
args = parser.parse_args()

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


# ─── 参数（按评论数 + 风险偏好分档）──────────────────────────────

def calc_params(n_reviews, risk='balanced'):
    """
    risk: 'fast'(冒险快) / 'balanced'(平衡) / 'safe'(保守稳)
    """
    # 基础滚动量（保证滚过新加载内容到底部）
    base = {
        'ticks': (38, 55),       # 每轮滚轮 tick 数
        'delay_ms': (7, 13),     # tick 间隔基准
        'wait_max': 2.5,         # 等 API 上限
    }
    if risk == 'fast':
        cool = {
            'idle': (0.05, 0.15),     # 每轮后微停
            'seg_every': (40, 60),    # 每 N 轮分段冷却
            'seg_pause': (3, 6),      # 分段冷却时长
            'long_every': (15, 25),   # 长停顿频率
            'long_range': (2, 5),
            'back_prob': 0.04,
        }
    elif risk == 'safe':
        cool = {
            'idle': (0.3, 0.7),
            'seg_every': (15, 25),
            'seg_pause': (8, 15),
            'long_every': (6, 10),
            'long_range': (5, 12),
            'back_prob': 0.10,
        }
    else:  # balanced
        cool = {
            'idle': (0.15, 0.4),
            'seg_every': (25, 40),
            'seg_pause': (5, 10),
            'long_every': (10, 18),
            'long_range': (3, 8),
            'back_prob': 0.06,
        }
    return {**base, **cool}


# ─── 滚动（分批 repeat + sigmoid 速度）────────────────────────────

def scroll_burst(n_ticks, lo_ms, hi_ms, direction='down'):
    """
    分 4 batch 用 --repeat，batch 间 delay 不同 → 伪 sigmoid 加减速
    不带 --window（XTEST 异步注入，快 13x），需窗口聚焦
    """
    btn = '5' if direction == 'down' else '4'
    sizes = [n_ticks // 4 + (1 if i < n_ticks % 4 else 0) for i in range(4)]
    delays = [
        int(hi_ms * random.uniform(0.85, 1.0)),    # 慢起步
        int(lo_ms * random.uniform(1.0, 1.2)),      # 快
        int(lo_ms * random.uniform(1.0, 1.2)),      # 快
        int(hi_ms * random.uniform(0.85, 1.0)),    # 慢收尾
    ]
    args = ['xdotool']
    for i, (sz, dl) in enumerate(zip(sizes, delays)):
        if sz <= 0:
            continue
        args += ['click', '--repeat', str(sz), '--delay', str(max(2, dl)), btn]
        if i < len(sizes) - 1:
            args += ['sleep', f'{random.uniform(0.015, 0.045):.4f}']
    subprocess.run(args, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_api(idx, name, last, max_wait):
    start = time.time()
    while time.time() - start < max_wait:
        if stop_flag.is_set():
            return last, False
        cur = review_count(idx, name)
        if cur > last:
            return cur, True
        time.sleep(0.015)
    return review_count(idx, name), False


def scroll_session(wid, idx, name, n_reviews, risk):
    p = calc_params(n_reviews if n_reviews > 0 else 300, risk)
    max_rounds = (n_reviews // 8) + 50 if n_reviews > 0 else 600

    subprocess.run(['xdotool', 'windowactivate', '--sync', str(wid)], check=False)
    time.sleep(0.2)
    points = load_points()
    rx, ry = parse_coord(points['review_list_anchor'])
    win = get_window()
    if win:
        subprocess.run(['xdotool', 'mousemove', str(win['x']+rx), str(win['y']+ry)], check=False)
    time.sleep(0.15)

    last = review_count(idx, name)
    no_growth = 0
    total = 0
    next_long = random.randint(*p['long_every'])
    next_seg = random.randint(*p['seg_every'])
    api_times, growths = [], []
    safety = 1.0  # 自适应速度系数

    while total < max_rounds and not stop_flag.is_set():
        # 偶尔回滚
        if random.random() < p['back_prob'] and total > 8:
            scroll_burst(random.randint(2, 4), p['delay_ms'][0]*2, p['delay_ms'][1]*2, 'up')
            time.sleep(random.uniform(0.3, 0.8))

        # 主滚动（safety 放大间隔=降速）
        lo, hi = p['delay_ms']
        scroll_burst(random.randint(*p['ticks']), lo*safety, hi*safety)
        total += 1

        # 事件驱动等 API
        t0 = time.time()
        new, got = wait_api(idx, name, last, p['wait_max'])
        wt = time.time() - t0

        if got:
            api_times.append(wt); g = new - last; growths.append(g)
            no_growth = 0; last = new
            # 自适应：快且多→提速；慢或少→降速
            if wt < 0.6 and g >= 8:
                safety = max(0.9, safety - 0.05)
            elif wt > 1.2 or g < 5:
                safety = min(1.6, safety + 0.12)
            print(f' +{g}', end='', flush=True)
            time.sleep(random.uniform(*p['idle']) * safety)
        else:
            no_growth += 1
            safety = min(1.6, safety + 0.15)
            print(' ·', end='', flush=True)

        # 长停顿（模拟阅读）
        if total >= next_long:
            time.sleep(random.uniform(*p['long_range']))
            next_long = total + random.randint(*p['long_every'])
            print('☕', end='', flush=True)

        # 分段冷却（打断连续高频画像，关键反限流）
        if total >= next_seg:
            cd = random.uniform(*p['seg_pause'])
            print(f'❄{cd:.0f}s', end='', flush=True)
            time.sleep(cd)
            next_seg = total + random.randint(*p['seg_every'])

        # 到底/限流判定
        if no_growth >= 4 and total > 10:
            time.sleep(2)
            fin = review_count(idx, name)
            if fin == last:
                print(' [到底]', end='', flush=True)
                break
            last = fin; no_growth = 0

    if api_times:
        avg_t = sum(api_times)/len(api_times)*1000
        avg_g = sum(growths)/len(growths)
        # 限流预警
        warn = ''
        if avg_t > 1000 or (growths and growths[-1] < 5):
            warn = '  ⚠️ 响应变慢/数据变少，可能开始限流'
        print(f"\n   API {avg_t:.0f}ms | {avg_g:.1f}条/次 | 速度系数 {safety:.2f}{warn}", end='')
    return total, last


# ─── 交互 ─────────────────────────────────────────────────────────

def main():
    if args.platform == 'meituan':
        print("🟡 美团模式")
        print("  当前 run.py 不复用大众点评滚动主循环。")
        print("  先启动：")
        print("    mitmdump --listen-port 9092 --set ssl_insecure=true -s meituan_miniapp_interceptor.py")
        print("  再在微信里打开美团小程序，搜索/进店/打开评论页。")
        print("  然后执行：")
        print("    python3 meituan_shop_id_resolver.py")
        print("    python3 meituan_review_exporter.py")
        return

    stores = load_stores_from_xlsx(XLSX)
    print(f"🎯 最终版 | {len(stores)}家店")
    print("  风险档: fast(快) / balanced(默认) / safe(稳)")
    print("  list=进度 | q=退出\n")

    risk = 'balanced'
    last_store_done = 0  # 上次完成时间戳，用于跨店冷却

    while True:
        try:
            raw = input(f"🎯 编号 [{risk}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋"); break
        if raw in ('q', 'quit', 'exit'):
            break
        if raw in ('fast', 'balanced', 'safe'):
            risk = raw; print(f"  切换到 {risk}"); continue
        if raw == 'list':
            for i, s in enumerate(stores[:60], 1):
                cnt = review_count(i, s.name)
                print(f"  {'✅' if cnt>=10 else '  '} {i:03d} {s.name} ({cnt})")
            continue
        try:
            idx = int(raw)
        except ValueError:
            continue
        if idx < 1 or idx > len(stores):
            print(f"  ❌ 1-{len(stores)}"); continue

        name = stores[idx-1].name
        cur = review_count(idx, name)
        print(f"  {name} (已有{cur}条)")

        # 跨店冷却提醒
        if last_store_done:
            gap = time.time() - last_store_done
            if gap < 60:
                print(f"  ⚠️ 距上次仅 {gap:.0f}s，建议等 1-2 分钟再抓（防累积限流）")

        try:
            n_in = input("  评论数 (回车=自动): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        n_reviews = int(n_in) if n_in else 0

        if not subprocess.run(['pgrep','-f','mitmdump'], capture_output=True).stdout.strip():
            print("  ❌ mitmdump 没在跑"); continue

        TARGET.write_text(json.dumps({'idx': idx, 'name': name}, ensure_ascii=False))
        win = get_window()
        if not win:
            print("  ❌ 没找到微信窗口"); continue

        input("  确认在评价页 Enter...")
        stop_flag.clear()
        old = signal.signal(signal.SIGINT, lambda s,f:(stop_flag.set(), print(' [停]',end='',flush=True)))

        t0 = time.time()
        print("  ", end='', flush=True)
        rounds, final = scroll_session(win['wid'], idx, name, n_reviews, risk)
        el = time.time() - t0
        signal.signal(signal.SIGINT, old)
        last_store_done = time.time()

        added = final - cur
        rate = added/(el/60) if el > 5 else 0
        print(f"\n  ✅ +{added} → 总{final} | {rounds}轮 {el:.0f}s ({rate:.0f}条/分)\n")


if __name__ == '__main__':
    main()
