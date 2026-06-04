#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
半自动评论采集：你手动进评价页，脚本自动滚动 + tshark 抓包 + 解析存 JSON。

用法:
    python3 grab_reviews.py --name '达美乐比萨(民京路店)' --idx 4

流程:
    1. 你手动操作 PC 微信小程序：搜索 → 进店 → 点"评价"→ 进入评价详情页
    2. 跑这个脚本
    3. 脚本自动：启动 tshark → 滚动评价页到底 → 停 tshark → 解析 → 存 JSON
    4. 完成后你手动按返回回首页，进下一家店

前置条件:
    - PC 微信用 SSLKEYLOGFILE 启动（/tmp/wx_keys.log 存在）
    - 大众点评小程序已打开，当前在评价详情页（能看到"全部/最新/差评/中评"tab）
    - tshark 已装，用户在 wireshark 组
"""

import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from human_click import get_window, human_scroll, load_points, parse_coord

KEYS = Path('/tmp/wx_keys.log')
PCAP = Path('/tmp/wx_capture/raw.pcap')
LOG_DIR = ROOT / 'mitm_logs'
OUT_DIR = ROOT / 'output' / 'store_reviews'


def start_tshark(duration: int) -> subprocess.Popen:
    PCAP.parent.mkdir(parents=True, exist_ok=True)
    if PCAP.exists():
        PCAP.unlink()
    # 抓 wlp2s0 所有 443 流量（跟 5/23 成功时一样的配置）
    cmd = f"tshark -i wlp2s0 -f 'tcp port 443' -w {PCAP} -a duration:{duration}"
    proc = subprocess.Popen(
        ['sg', 'wireshark', '-c', cmd],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )
    for _ in range(10):
        time.sleep(0.5)
        if PCAP.exists():
            return proc
    return proc


def stop_tshark(proc):
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=8)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass


def scroll_review_page(win, scrolls: int):
    """
    极速滚动评价页。
    不用 human_scroll（太慢），直接发 xdotool wheel 事件。
    鼠标先移到评价列表中央一次，之后不再移动。
    """
    points = load_points()
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])
    rx, ry = parse_coord(points['review_list_anchor'])
    
    # 算屏幕坐标
    sx = win['x'] + rx
    sy = win['y'] + ry
    
    # 先把鼠标移到评价列表中央 + 确保窗口 focus
    subprocess.run(['xdotool', 'windowactivate', '--sync', str(win['wid'])], check=False)
    time.sleep(0.3)
    subprocess.run(['xdotool', 'mousemove', '--window', str(win['wid']), str(rx), str(ry)], check=False)
    time.sleep(0.3)

    for i in range(1, scrolls + 1):
        # 分 5 批 × 10 tick = 50 tick ≈ 5000px（一整页评论高度）
        # 每批间隔 100ms，总共 500ms 完成滚动（不会闪退）
        for _ in range(5):
            subprocess.run(['xdotool', 'click', '--window', str(win['wid']),
                            '--repeat', '10', '--delay', '30', '5'], check=False)
            time.sleep(0.1)
        # 等 API 触发 + 响应（实测 API 响应 ~500ms）
        time.sleep(random.uniform(1.2, 1.5))
        if i % 5 == 0:
            print(f"  已滚动 {i}/{scrolls} 页")
    
    # 滚完等最后的 API 响应
    print("  等待最后的 API 响应...")
    time.sleep(3)


def parse_and_save(idx: int, store_name: str, since: float):
    if not PCAP.exists() or PCAP.stat().st_size < 1000:
        print("  ⚠️ pcap 太小，无数据")
        return 0

    print("  解析 pcap...")
    # 用 tshark --export-objects 直接导出 HTTP 响应 body
    import gzip
    dump_dir = Path('/tmp/wx_dump/grab')
    if dump_dir.exists():
        import shutil
        shutil.rmtree(dump_dir)
    dump_dir.mkdir(parents=True)

    subprocess.run(
        ['sg', 'wireshark', '-c',
         f"tshark -r {PCAP} -o tls.keylog_file:{KEYS} --export-objects http,{dump_dir} -q"],
        check=False, capture_output=True
    )

    # 解析所有 outsidesiftedreviewlist 响应
    rows = []
    seen = set()
    review_files = 0
    for f in dump_dir.iterdir():
        if 'outsidesiftedreviewlist' not in f.name and 'outsideshopreviewlist' not in f.name:
            continue
        raw = f.read_bytes()
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        try:
            d = json.loads(raw)
        except Exception:
            continue
        review_files += 1
        review_list = d.get('list', [])
        if not review_list and isinstance(d.get('data'), dict):
            review_list = d['data'].get('list', [])
        for r in review_list:
            if not isinstance(r, dict):
                continue
            text = r.get('content') or r.get('reviewBody') or r.get('reviewText') or ''
            if not text:
                continue
            ui = r.get('userInfo')
            user = (ui.get('userName') if isinstance(ui, dict) else '') or r.get('userName', '')
            pub = ''
            ri = r.get('reviewIndexes')
            if isinstance(ri, dict):
                pub = ri.get('addTime') or ''
            pub = pub or r.get('createDateString') or r.get('addTimeStr') or ''
            key = (user, text[:40])
            if key in seen:
                continue
            seen.add(key)
            rows.append({'门店': store_name, '发布时间': pub, '发布人': user, '文字': text})

    print(f"  API 响应: {review_files} 个, 评论: {len(rows)} 条")

    # 合并已有数据
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = store_name.replace('/', '_')
    out_path = OUT_DIR / f'{idx:03d}_{safe}.json'
    existing = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding='utf-8'))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    merged_seen = set()
    merged = []
    for r in existing + rows:
        key = (r.get('发布人', ''), r.get('文字', '')[:40])
        if key in merged_seen:
            continue
        merged_seen.add(key)
        merged.append(r)

    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  💾 {out_path.name}: {len(merged)} 条 (本次新增 {len(rows)})")
    return len(merged)


def main():
    import argparse
    ap = argparse.ArgumentParser(description='你进评价页后跑这个，自动滚动+抓取')
    ap.add_argument('--name', required=True, help='店铺名')
    ap.add_argument('--idx', type=int, default=0, help='xlsx 编号')
    ap.add_argument('--scrolls', type=int, default=0,
                    help='滚动次数（0=自动估算，需手动输入评论数）')
    args = ap.parse_args()

    # 检查环境
    if not KEYS.exists() or KEYS.stat().st_size < 100:
        print("❌ /tmp/wx_keys.log 无效，微信没带 SSLKEYLOGFILE 启动")
        print("   请重启微信: bash /tmp/wx_with_keylog.sh")
        return 1
    # 验证 keys 文件最近有更新（防止闪退后 key 不匹配）
    keys_age = time.time() - KEYS.stat().st_mtime
    if keys_age > 300:
        print(f"⚠️ keys 文件 {keys_age:.0f}s 没更新，可能需要重启微信")
        print("   如果刚才微信闪退过，请重启: bash /tmp/wx_with_keylog.sh")
    win = get_window()
    if win is None:
        print("❌ 找不到大众点评窗口")
        return 1

    print(f"店铺: {args.idx:03d} {args.name}")
    print(f"窗口: wid={win['wid']} {win['w']}x{win['h']}")

    # 确定滚动次数
    scrolls = args.scrolls
    if scrolls <= 0:
        try:
            n = int(input("评价页显示的评论总数（如 449）: "))
            scrolls = (n // 14) + 5  # 1:1 比率 + buffer
        except (ValueError, EOFError):
            scrolls = 80
    est_time = scrolls * 2 + 5
    print(f"滚动次数: {scrolls} (预计 {est_time:.0f} 秒 ≈ {est_time/60:.1f} 分钟)")

    input("\n确认当前在评价详情页（能看到全部/最新/差评 tab），按 Enter 开始...")

    since = time.time()
    # tshark 时长 = 滚动次数 × 2.5s + 30s buffer
    duration = int(scrolls * 2.5 + 30)
    if duration < 60:
        duration = 60

    # 启动 tshark
    print(f"\n▶ 启动 tshark ({duration}s)")
    tshark = start_tshark(duration)
    time.sleep(2)

    # 滚动
    print(f"▶ 开始滚动 ({scrolls} 次)")
    try:
        scroll_review_page(win, scrolls)
    except KeyboardInterrupt:
        print("\n  中断滚动")
    finally:
        print("▶ 停止 tshark")
        stop_tshark(tshark)

    # 解析
    print("▶ 解析评论")
    n = parse_and_save(args.idx, args.name, since)
    print(f"\n✅ 完成: {n} 条评论")
    print("  现在你可以按返回回首页，进下一家店")
    return 0


if __name__ == '__main__':
    sys.exit(main())
