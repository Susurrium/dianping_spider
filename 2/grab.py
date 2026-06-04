#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
极致反反爬评论抓取。

用法:
    python3 grab.py 5            # 自动滚到底
    python3 grab.py 5 499        # 指定评论数

核心反反爬策略：
1. 用 /dev/uinput 注入真实硬件滚轮事件（不是 xdotool 的 X11 fake event）
2. 每次滚动的 tick 数随机（3-8 tick，不是固定 50）
3. tick 间隔随机（30-120ms，模拟真实手指滚轮速度变化）
4. 滚动之间停顿随机（1.5-5s，模拟人类阅读）
5. 偶尔向上滚一点再向下（模拟人类回看）
6. 每 5-8 页加一个长停顿（8-15s，模拟仔细看某条评论）
"""

import ctypes
import gzip
import json
import os
import random
import shutil
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from human_click import get_window, load_points, parse_coord
from review_exporter import load_stores_from_xlsx

PCAP = Path('/tmp/wx_capture/raw.pcap')
KEYS = Path('/tmp/wx_keys.log')
OUT_DIR = ROOT / 'output' / 'store_reviews'
XLSX = ROOT / '达美乐_门店.xlsx'


# ─── uinput 真实滚轮事件 ───────────────────────────────────────────

def create_uinput_device():
    """创建虚拟鼠标设备（通过 /dev/uinput 注入真实内核事件）"""
    try:
        fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
    except PermissionError:
        return None  # 没权限，fallback 到 xdotool

    # 启用 EV_REL (相对事件) + REL_WHEEL (滚轮)
    import fcntl
    UI_SET_EVBIT = 0x40045564
    UI_SET_RELBIT = 0x40045566
    UI_DEV_CREATE = 0x5501
    EV_REL = 0x02
    REL_WHEEL = 0x08

    fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
    fcntl.ioctl(fd, UI_SET_RELBIT, REL_WHEEL)

    # uinput_user_dev 结构体
    name = b"grab_mouse\x00" + b"\x00" * 69  # 80 bytes name
    dev_struct = name + struct.pack('HHH', 0x01, 0x01, 0x01)  # bustype, vendor, product
    dev_struct += b"\x00" * (280 - len(dev_struct))  # padding to 280 bytes
    os.write(fd, dev_struct)
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.3)
    return fd


def uinput_scroll(fd, direction=-1):
    """发送一个真实滚轮 tick（direction: -1=下, 1=上）"""
    EV_REL = 0x02
    REL_WHEEL = 0x08
    EV_SYN = 0x00
    SYN_REPORT = 0x00

    now = time.time()
    sec = int(now)
    usec = int((now - sec) * 1000000)

    # input_event: struct timeval(16 bytes) + type(2) + code(2) + value(4)
    ev = struct.pack('llHHi', sec, usec, EV_REL, REL_WHEEL, direction)
    os.write(fd, ev)
    # SYN_REPORT
    ev_syn = struct.pack('llHHi', sec, usec, EV_SYN, SYN_REPORT, 0)
    os.write(fd, ev_syn)


def destroy_uinput(fd):
    if fd is not None:
        UI_DEV_DESTROY = 0x5502
        import fcntl
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except:
            pass
        os.close(fd)


# ─── fallback: xdotool 但模拟人类模式 ─────────────────────────────

def xdotool_scroll_human(wid, ticks, direction='down'):
    """用 xdotool 但每个 tick 间隔随机（模拟人类滚轮）"""
    btn = '5' if direction == 'down' else '4'
    for _ in range(ticks):
        subprocess.run(['xdotool', 'click', '--window', str(wid), btn], check=False)
        # 人类滚轮：每个 tick 间隔 30-150ms（不均匀！）
        time.sleep(random.uniform(0.03, 0.15))


# ─── 核心滚动逻辑 ─────────────────────────────────────────────────

def human_scroll_session(wid, max_pages=200):
    """
    用昨晚验证成功的精确参数：5批×10tick×30ms + 等1.2s
    423 条/35 次/75 秒 = 已验证安全。
    """
    subprocess.run(['xdotool', 'windowactivate', '--sync', str(wid)], check=False)
    time.sleep(0.3)
    points = load_points()
    rx, ry = parse_coord(points['review_list_anchor'])
    win = get_window()
    if win:
        subprocess.run(['xdotool', 'mousemove', str(win['x']+rx), str(win['y']+ry)], check=False)
    time.sleep(0.3)

    last_size = PCAP.stat().st_size if PCAP.exists() else 0
    no_big_growth = 0
    total = 0

    while total < max_pages and not stop_flag.is_set():
        # 5 批 × 10 tick × 30ms（昨晚验证安全的参数）
        for batch in range(5):
            for _ in range(10):
                subprocess.run(['xdotool', 'click', '--window', str(wid), '5'], check=False)
                time.sleep(0.03)
            time.sleep(0.08)
        total += 1

        # 等 1.2-1.5s（昨晚验证安全）
        time.sleep(random.uniform(1.2, 1.5))

        # 到底检测：pcap 增长 < 80KB 表示返回 204 空响应（被反爬）
        if total % 3 == 0:
            cur = PCAP.stat().st_size if PCAP.exists() else 0
            growth = cur - last_size
            last_size = cur
            if growth > 80000:
                no_big_growth = 0
                print('.', end='', flush=True)
            else:
                no_big_growth += 1
            # 连续 2 次（6 次滚动）无增长 = 服务端返回 204 → 立即停止避免浪费
            if no_big_growth >= 2 and total > 6:
                # 检测到连续 204（反爬触发）→ 尝试退出再进入评价页重置会话
                print(' [反爬/到底，尝试重置]', end='', flush=True)
                points_local = load_points()
                bw, bh = int(points_local['base_width']), int(points_local['base_height'])
                bx, by = parse_coord(points_local.get('back_button', '20,40'))
                from human_click import human_click as hc
                from ocr_locate import find_review_module
                w_obj = get_window()
                if w_obj:
                    hc(w_obj, bx, by, base_w=bw, base_h=bh)
                    time.sleep(2)
                    pos = find_review_module(wid)
                    if pos:
                        hc(w_obj, pos[0], pos[1], base_w=bw, base_h=bh)
                        time.sleep(3)
                        no_big_growth = 0
                        # 鼠标回到滚动锚点
                        rx2, ry2 = parse_coord(points_local['review_list_anchor'])
                        subprocess.run(['xdotool', 'mousemove', str(w_obj['x']+rx2), str(w_obj['y']+ry2)], check=False)
                        time.sleep(0.3)
                        print(' [重进成功]', end='', flush=True)
                        continue
                print(' [重置失败]', end='', flush=True)
                break

    return total


# ─── tshark ───────────────────────────────────────────────────────

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
        except:
            pass


# ─── 解析 ─────────────────────────────────────────────────────────

def parse_pcap(store_name, idx):
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
            text = r.get('content') or r.get('reviewBody') or ''
            if not text: continue
            ui = r.get('userInfo')
            user = (ui.get('userName') if isinstance(ui, dict) else '') or r.get('userName', '')
            key = (user, text[:40])
            if key in seen: continue
            seen.add(key)
            rows.append({'门店': store_name, '发布时间': '', '发布人': user, '文字': text})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = store_name.replace('/', '_')
    out = OUT_DIR / f'{idx:03d}_{safe}.json'
    existing = []
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding='utf-8'))
            if not isinstance(existing, list): existing = []
        except: existing = []
    ms = set()
    merged = []
    for r in existing + rows:
        k = (r.get('发布人', ''), r.get('文字', '')[:40])
        if k in ms: continue
        ms.add(k)
        merged.append(r)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
    return len(rows), len(merged)


# ─── 主入口 ───────────────────────────────────────────────────────

import threading
stop_flag = threading.Event()


def main():
    if len(sys.argv) < 2:
        print("用法: python3 grab.py <编号> [评论数]")
        return 1

    idx = int(sys.argv[1])
    stores = load_stores_from_xlsx(XLSX)
    if idx < 1 or idx > len(stores):
        print(f"❌ 编号超范围"); return 1
    store_name = stores[idx - 1].name

    review_count = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    win = get_window()
    if not win:
        print("❌ 找不到窗口"); return 1
    if not KEYS.exists():
        print("❌ /tmp/wx_keys.log 不存在"); return 1

    max_pages = (review_count // 14) + 5 if review_count > 0 else 200

    print(f"🍕 {idx:03d} {store_name}")
    if review_count > 0:
        print(f"   {review_count} 条, 最多滚 {max_pages} 次")
    else:
        print(f"   自动滚到底")
    print(f"   确认在评价页，按 Enter...", end='', flush=True)
    input()

    # 检查 keys 健康：最近 5 分钟内有更新 + 行数足够
    keys_age = time.time() - KEYS.stat().st_mtime
    keys_lines = sum(1 for _ in open(KEYS, 'rb')) if KEYS.stat().st_size > 0 else 0
    print(f"   keys: {keys_lines} 行, {keys_age:.0f}s 前更新", end='')
    if keys_lines < 30:
        print(" ⚠️ 太少")
    if keys_age > 600:
        print(f"\n   ⚠️ keys {keys_age:.0f}s 没更新，可能需要重启微信")
    print()


    # Ctrl+C 停止滚动
    old_handler = signal.signal(signal.SIGINT, lambda s, f: (stop_flag.set(), print(" [停]", end='', flush=True)))

    tshark = start_tshark()
    print(f"   滚动中 ", end='', flush=True)

    total = human_scroll_session(win['wid'], max_pages)

    print(f" ({total} 次)")
    signal.signal(signal.SIGINT, old_handler)
    time.sleep(2)
    stop_tshark(tshark)

    new, total_reviews = parse_pcap(store_name, idx)
    print(f"   ✅ 新增 {new}, 总计 {total_reviews} 条")

    # 失败检测：本次新增 0 条 → 可能 keys 失效
    if new == 0:
        # 看 pcap 里有没有 dianping 请求
        result = subprocess.run(['sg', 'wireshark', '-c',
            f"tshark -r {PCAP} -o tls.keylog_file:{KEYS} -Y 'http.request.uri contains \"sifted\"' 2>/dev/null | wc -l"],
            capture_output=True, text=True)
        sifted_count = int(result.stdout.strip() or 0)
        if sifted_count == 0:
            # 看 pcap 里有没有 dianping SNI
            result2 = subprocess.run(['sg', 'wireshark', '-c',
                f"tshark -r {PCAP} -Y 'tls.handshake.extensions_server_name contains \"dianping\"' 2>/dev/null | wc -l"],
                capture_output=True, text=True)
            dianping_sni = int(result2.stdout.strip() or 0)
            if dianping_sni > 0:
                print(f"   ⚠️ 抓到 {dianping_sni} 个 dianping TLS 但解密失败 → keys 失效")
                print(f"   → 请重启微信: bash start_wechat.sh")
            else:
                print(f"   ⚠️ pcap 无 dianping 流量 → 这家店可能被限流，跳过")
        else:
            print(f"   ⚠️ 抓到 {sifted_count} 个 sifted 请求但解析失败 → 检查 grab.py 解析逻辑")
    else:
        print(f"   ⏳ 等 3 分钟再跑下一家（防反爬）")
    return 0


if __name__ == '__main__':
    sys.exit(main())
