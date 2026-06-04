#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
交互式评论抓取 - 自动检测 mitm/keylog 模式，输入评论数动态调参

用法:
    python3 go.py
"""

import gzip
import json
import math
import os
import random
import shutil
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
PCAP = Path('/tmp/wx_capture/raw.pcap')
KEYS = Path('/tmp/wx_keys.log')

stop_flag = threading.Event()


# ─── 模式选择 ─────────────────────────────────────────────────────

def choose_mode():
    """启动时让用户选模式"""
    print("  1) mitm   - mitmdump拦截，自动落库")
    print("  2) keylog - tshark抓包，滚完解密")
    while True:
        c = input("  选模式 (1/2): ").strip()
        if c in ('1', 'mitm'):
            return 'mitm'
        if c in ('2', 'keylog'):
            return 'keylog'


# ─── 文件操作 ─────────────────────────────────────────────────────

def review_file(idx, name):
    return OUT_DIR / f"{idx:03d}_{name.replace('/', '_')}.json"


def review_count(idx, name):
    f = review_file(idx, name)
    if not f.exists():
        return 0
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return len(d) if isinstance(d, list) else 0
    except:
        return 0


# ─── 动态参数 ─────────────────────────────────────────────────────

def calc_params(n_reviews):
    """根据评论数动态调参"""
    if n_reviews <= 50:
        return {
            'ticks': (8, 14), 'bursts': (4, 6),
            'tick_iv': (0.02, 0.06), 'burst_gap': (0.03, 0.08),
            'pause_scale': 0.4, 'pause_shape': 1.5,
            'long_every': (10, 20), 'long_range': (2, 5),
            'back_prob': 0.05, 'desc': '⚡快速'
        }
    elif n_reviews <= 200:
        return {
            'ticks': (6, 12), 'bursts': (3, 6),
            'tick_iv': (0.025, 0.10), 'burst_gap': (0.05, 0.12),
            'pause_scale': 0.6, 'pause_shape': 1.8,
            'long_every': (7, 12), 'long_range': (4, 10),
            'back_prob': 0.08, 'desc': '⚖️平衡'
        }
    elif n_reviews <= 500:
        return {
            'ticks': (5, 10), 'bursts': (3, 5),
            'tick_iv': (0.03, 0.12), 'burst_gap': (0.06, 0.15),
            'pause_scale': 0.7, 'pause_shape': 1.8,
            'long_every': (5, 9), 'long_range': (5, 15),
            'back_prob': 0.10, 'desc': '🐢保守'
        }
    else:
        return {
            'ticks': (4, 9), 'bursts': (3, 5),
            'tick_iv': (0.03, 0.13), 'burst_gap': (0.07, 0.18),
            'pause_scale': 0.8, 'pause_shape': 2.0,
            'long_every': (4, 7), 'long_range': (8, 20),
            'back_prob': 0.12, 'desc': '🛡️极保守'
        }


# ─── 滚动引擎 ─────────────────────────────────────────────────────

def do_tick(wid, direction='down'):
    btn = '5' if direction == 'down' else '4'
    subprocess.run(['xdotool', 'click', '--window', str(wid), btn],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sigmoid_intervals(n, lo, hi):
    out = []
    for i in range(n):
        x = (i / max(n-1, 1)) * 6 - 3
        factor = 1 - 0.5 * (1 - abs(1/(1+math.exp(-x)) - 0.5) * 2)
        out.append((lo + (hi-lo)*factor) * random.uniform(0.8, 1.2))
    return out


def scroll_session(wid, idx, name, n_reviews, mode):
    """统一滚动逻辑，两种模式共用"""
    p = calc_params(n_reviews if n_reviews > 0 else 200)
    max_pages = (n_reviews // 10) + 15 if n_reviews > 0 else 300

    subprocess.run(['xdotool', 'windowactivate', '--sync', str(wid)], check=False)
    time.sleep(0.3)
    points = load_points()
    rx, ry = parse_coord(points['review_list_anchor'])
    win = get_window()
    if win:
        subprocess.run(['xdotool', 'mousemove', str(win['x']+rx), str(win['y']+ry)], check=False)
    time.sleep(0.3)

    # mitm模式看文件增长，keylog模式看pcap增长
    if mode == 'mitm':
        get_progress = lambda: review_count(idx, name)
    else:
        get_progress = lambda: PCAP.stat().st_size if PCAP.exists() else 0

    last_progress = get_progress()
    no_growth = 0
    total = 0
    next_long = random.randint(*p['long_every'])
    slow = 1.0

    while total < max_pages and not stop_flag.is_set():
        # 偶尔回滚
        if random.random() < p['back_prob'] and total > 2:
            for _ in range(random.randint(2, 5)):
                do_tick(wid, 'up')
                time.sleep(random.uniform(0.04, 0.10))
            time.sleep(random.uniform(0.6, 2.0))

        # 主滚动
        for b in range(random.randint(*p['bursts'])):
            if stop_flag.is_set():
                break
            for iv in sigmoid_intervals(random.randint(*p['ticks']), *p['tick_iv']):
                do_tick(wid, 'down')
                time.sleep(iv)
            time.sleep(random.uniform(*p['burst_gap']))

        total += 1

        # 阅读停顿（韦伯分布）
        time.sleep(min(random.weibullvariate(p['pause_scale'], p['pause_shape']), 4.0) * slow)

        # 长停顿
        if total >= next_long:
            time.sleep(random.uniform(*p['long_range']) * slow)
            next_long = total + random.randint(*p['long_every'])
            print('☕', end='', flush=True)

        # 增长检测
        if total % 3 == 0:
            cur = get_progress()
            if mode == 'mitm':
                grew = cur > last_progress
            else:
                grew = (cur - last_progress) > 50000  # pcap增长>50KB算有数据

            if grew:
                no_growth = 0
                slow = max(0.8, slow - 0.1)
                if mode == 'mitm':
                    print(f' [{cur}]', end='', flush=True)
                else:
                    print('.', end='', flush=True)
            else:
                no_growth += 1
                slow = min(2.0, slow + 0.3)
                print('·', end='', flush=True)
            last_progress = cur

            if no_growth >= 3 and total > 6:
                time.sleep(3)
                final = get_progress()
                if final == last_progress:
                    print(' [到底]', end='', flush=True)
                    break
                last_progress = final
                no_growth = 0

    return total


# ─── keylog 模式：解析 pcap ───────────────────────────────────────

def _gx_richtext(node):
    out = []
    if isinstance(node, dict):
        if isinstance(node.get('text'), str):
            out.append(node['text'])
        for v in node.values():
            if isinstance(v, (dict, list)):
                out.append(_gx_richtext(v))
    elif isinstance(node, list):
        for x in node:
            out.append(_gx_richtext(x))
    return ''.join(out)


def _gx_text(r):
    c = r.get('content')
    if isinstance(c, str) and c:
        return c
    rb = r.get('reviewBody')
    if isinstance(rb, str) and rb:
        return rb
    if isinstance(rb, dict):
        return _gx_richtext(rb)
    return ''


def _gx_time(r):
    import re as _re
    for k in ('time', 'lastTimeStr'):
        t = r.get(k)
        if isinstance(t, str) and t.strip():
            return t.strip()
    iso = r.get('addTime') or r.get('lastTime')
    if isinstance(iso, str):
        m = _re.match(r'(\d{4})-(\d{2})-(\d{2})', iso)
        if m:
            return f"{int(m.group(2))}月{int(m.group(3))}日"
    return ''


def parse_pcap_to_file(idx, name):
    """tshark 解密 pcap 并提取评论写入文件"""
    dump = Path('/tmp/wx_dump/g')
    if dump.exists():
        shutil.rmtree(dump)
    dump.mkdir(parents=True)
    subprocess.run(['sg', 'wireshark', '-c',
        f"tshark -r {PCAP} -o tls.keylog_file:{KEYS} --export-objects http,{dump} -q"],
        check=False, capture_output=True)

    rows, seen = [], set()
    for f in dump.iterdir():
        if 'siftedreviewlist' not in f.name:
            continue
        raw = f.read_bytes()
        try: raw = gzip.decompress(raw)
        except: pass
        try: d = json.loads(raw)
        except: continue
        lst = d.get('list') or (d.get('data', {}).get('list') if isinstance(d.get('data'), dict) else []) or []
        for r in lst:
            if not isinstance(r, dict): continue
            text = _gx_text(r)
            if not text: continue
            ui = r.get('userInfo')
            user = (ui.get('userName') if isinstance(ui, dict) else '') or r.get('userName', '')
            key = (user, text[:40])
            if key in seen: continue
            seen.add(key)
            rows.append({'门店': name, '发布时间': _gx_time(r), '发布人': user, '文字': text})

    # 合并写入
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = review_file(idx, name)
    existing = []
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding='utf-8'))
            if not isinstance(existing, list): existing = []
        except: existing = []

    ms = set((r.get('发布人',''), r.get('文字','')[:40]) for r in existing)
    for r in rows:
        k = (r.get('发布人',''), r.get('文字','')[:40])
        if k not in ms:
            ms.add(k)
            existing.append(r)

    out.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
    return len(rows), len(existing)


# ─── keylog 模式：启动 tshark ─────────────────────────────────────

def start_tshark():
    PCAP.parent.mkdir(parents=True, exist_ok=True)
    if PCAP.exists():
        PCAP.unlink()
    proc = subprocess.Popen(
        ['sg', 'wireshark', '-c', f"tshark -i any -f 'tcp port 443' -w {PCAP}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, preexec_fn=os.setsid)
    time.sleep(2)
    return proc


def stop_tshark(proc):
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except: pass


# ─── 交互主循环 ───────────────────────────────────────────────────

def main():
    stores = load_stores_from_xlsx(XLSX)
    print(f"📋 {len(stores)} 家店")
    mode = choose_mode()

    if mode == 'mitm':
        print("  🟢 mitmdump 模式")
    else:
        print("  🔵 keylog 模式")

    print(f"   list=查看进度  q=退出\n")

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
            if len(stores) > 60:
                print(f"  ... 共{len(stores)}家")
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
            print("\n👋")
            break

        n_reviews = int(n_input) if n_input else 0
        p = calc_params(n_reviews if n_reviews else 200)
        print(f"  {p['desc']} | 目标: {n_reviews or '自动'}")

        win = get_window()
        if not win:
            print("  ❌ 没找到微信窗口")
            continue

        # mitm模式设置目标文件
        if mode == 'mitm':
            TARGET.write_text(json.dumps({'idx': idx, 'name': name}, ensure_ascii=False))

        input("  确认在评价页 Enter...")

        # keylog模式启动tshark
        tshark_proc = None
        if mode == 'keylog':
            tshark_proc = start_tshark()

        stop_flag.clear()
        old_sig = signal.signal(signal.SIGINT,
            lambda s, f: (stop_flag.set(), print(' [停]', end='', flush=True)))

        t0 = time.time()
        print("  ", end='', flush=True)
        rounds = scroll_session(win['wid'], idx, name, n_reviews, mode)
        elapsed = time.time() - t0

        signal.signal(signal.SIGINT, old_sig)

        # keylog模式：停tshark + 解析
        if mode == 'keylog':
            time.sleep(2)
            stop_tshark(tshark_proc)
            new, total = parse_pcap_to_file(idx, name)
            print(f"\n  ✅ 解密得到 +{new}条 → 总{total}条 | {rounds}次 {elapsed:.0f}s")
        else:
            final = review_count(idx, name)
            added = final - cur
            print(f"\n  ✅ +{added}条 → 总{final}条 | {rounds}次 {elapsed:.0f}s")

        print()


if __name__ == '__main__':
    sys.exit(main() or 0)
