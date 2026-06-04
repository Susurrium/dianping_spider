# -*- coding:utf-8 -*-
"""
单店端到端：搜索 → 进店 → 进评价 → 滚动 + tshark 后台抓 + 解析 + 写 store_reviews/

整个流程在 1 个进程内完成，避免 SIGTERM 杀后台 tshark 问题。

用法:
    # 跑 1 家店（已知 xlsx 编号 + 店名）
    python3 run_one_shop.py --idx 6 --name '达美乐比萨(拱秀路店)' --scrolls 8

    # 直接给关键词 + 输出文件名
    python3 run_one_shop.py --keyword '达美乐比萨拱秀路店' --out output/store_reviews/006_达美乐比萨\(拱秀路店\).json --scrolls 8
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from human_click import (
    get_window, parse_coord, human_click, human_scroll, load_points
)
from ocr_locate import (
    screenshot_window, ocr_with_boxes, find_review_module,
    detect_meituan_dialog, detect_captcha_in_screenshot,
)


PCAP_FILE = Path('/tmp/wx_capture/raw.pcap')
KEYS_FILE = Path('/tmp/wx_keys.log')
DIAG_DIR = ROOT / 'mitm_logs' / 'diagnostic'
DIAG_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = ROOT / 'mitm_logs'


# ----------------------------------------------------------------------
# 截图与反爬检测
# ----------------------------------------------------------------------

def shot(wid: int, label: str) -> Path:
    ts = datetime.now().strftime('%H%M%S')
    path = DIAG_DIR / f'auto_{ts}_{label}.png'
    subprocess.run(['import', '-window', str(wid), str(path)],
                   check=False, stderr=subprocess.DEVNULL)
    return path


def has_dialog_meituan(wid: int) -> Tuple[bool, Optional[Path]]:
    img = screenshot_window(wid)
    if img is None:
        return False, None
    return (detect_meituan_dialog(img), img)


def has_captcha(wid: int) -> Tuple[bool, Optional[Path]]:
    img = screenshot_window(wid)
    if img is None:
        return False, None
    return (detect_captcha_in_screenshot(img), img)


# ----------------------------------------------------------------------
# 输入工具
# ----------------------------------------------------------------------

def human_paste(text: str):
    """xclip → ctrl+v 粘贴，绕过 fcitx 输入法"""
    if shutil.which('xclip'):
        subprocess.run(['xclip', '-selection', 'clipboard', '-i'],
                       input=text.encode('utf-8'), check=True)
        time.sleep(random.uniform(0.10, 0.20))
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+v'], check=False)
        time.sleep(random.uniform(0.20, 0.40))
    else:
        for ch in text:
            subprocess.run(['xdotool', 'type', '--delay', '0', ch], check=False)
            time.sleep(random.uniform(0.05, 0.18))


def click_pos(win, rel_x: int, rel_y: int):
    base_w = win.get('base_w', win['w'])
    base_h = win.get('base_h', win['h'])
    human_click(win, rel_x, rel_y, base_w=base_w, base_h=base_h)


def scroll_pos(win, rel_x: int, rel_y: int, dy: int = -400):
    base_w = win.get('base_w', win['w'])
    base_h = win.get('base_h', win['h'])
    human_scroll(win, rel_x, rel_y, dy=dy, base_w=base_w, base_h=base_h)


# ----------------------------------------------------------------------
# tshark 子进程管理
# ----------------------------------------------------------------------

def start_tshark(duration: int = 0) -> subprocess.Popen:
    """启动 tshark 后台抓包。duration=0 表示无限制（手动 terminate）。"""
    PCAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PCAP_FILE.exists():
        PCAP_FILE.unlink()
    cmd_str = f"tshark -i wlp2s0 -f 'tcp port 443' -w {PCAP_FILE}"
    if duration > 0:
        cmd_str += f" -a duration:{duration}"
    proc = subprocess.Popen(
        ['sg', 'wireshark', '-c', cmd_str],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid  # 独立 process group
    )
    # 等启动
    for _ in range(8):
        time.sleep(0.5)
        if PCAP_FILE.exists():
            return proc
    return proc


def stop_tshark(proc: subprocess.Popen):
    if proc is None:
        return
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass


# ----------------------------------------------------------------------
# 业务流程
# ----------------------------------------------------------------------

def click_via_ocr(win, target_text: str, max_scrolls: int = 0,
                  scroll_anchor_key: str = 'detail_scroll_anchor',
                  scroll_dy: int = -350) -> bool:
    """OCR 找含 target_text 的 box 点击。可选先滚动 N 次。"""
    points = load_points()
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])
    win['base_w'] = base_w
    win['base_h'] = base_h
    
    for attempt in range(max_scrolls + 1):
        img = screenshot_window(win['wid'])
        if img is None:
            time.sleep(0.5)
            continue
        try:
            for b in ocr_with_boxes(img):
                if target_text in b['text']:
                    rel_x = b['x'] + b['w'] // 2
                    rel_y = b['y'] + b['h'] // 2
                    print(f"  ✅ OCR 找到 '{target_text}' at ({rel_x},{rel_y})")
                    human_click(win, rel_x, rel_y, base_w=base_w, base_h=base_h)
                    return True
        finally:
            try:
                img.unlink()
            except OSError:
                pass
        # 没找到，滚动重试
        if attempt < max_scrolls:
            print(f"  ⏬ 没找到 '{target_text}'，滚动 ({attempt+1}/{max_scrolls})")
            ax, ay = parse_coord(points.get(scroll_anchor_key, '200,400'))
            human_scroll(win, ax, ay, dy=scroll_dy, base_w=base_w, base_h=base_h)
            time.sleep(random.uniform(1.5, 2.5))
    return False


def handle_meituan_dialog(win) -> bool:
    """如果弹了美团对话框，OCR 点取消；返回是否处理过"""
    is_meituan, img = has_dialog_meituan(win['wid'])
    if not is_meituan:
        if img:
            try: img.unlink()
            except OSError: pass
        return False
    print("  ⚠️ 美团对话框，自动点'取消'")
    try:
        for b in ocr_with_boxes(img):
            if '取消' in b['text']:
                rel_x = b['x'] + b['w']//2
                rel_y = b['y'] + b['h']//2
                human_click(win, rel_x, rel_y, base_w=win['w'], base_h=win['h'])
                time.sleep(1.0)
                return True
    finally:
        try: img.unlink()
        except OSError: pass
    return False


def back_to_home(win, max_back: int = 5):
    """按返回到大众点评首页（识别底部 tab '首页' 出现即认为到了）"""
    points = load_points()
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])
    bx, by = parse_coord(points.get('back_button', '20,40'))
    for i in range(max_back):
        # 检查是否在首页（OCR 看到底部 "首页 找优惠 看榜单 我的"）
        img = screenshot_window(win['wid'])
        if img:
            text_all = ' '.join(b['text'] for b in ocr_with_boxes(img))
            try: img.unlink()
            except OSError: pass
            if '找优惠' in text_all and '看榜单' in text_all:
                return True
        human_click(win, bx, by, base_w=base_w, base_h=base_h)
        time.sleep(random.uniform(1.0, 1.8))
    return False


def run_search_to_review_scroll(win, keyword: str, scrolls: int) -> int:
    """
    全自动单店流程，返回:
      0: 成功
      1: 反爬触发
      2: 找不到评价模块
      3: 其它失败
    """
    points = load_points()
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])
    win['base_w'] = base_w
    win['base_h'] = base_h

    # Step 1: 激活窗口 + 验证当前在首页
    print("\n▶ 激活窗口 + 验证首页")
    subprocess.run(['xdotool', 'windowactivate', '--sync', str(win['wid'])], check=False)
    time.sleep(random.uniform(0.5, 0.9))
    
    # 校验当前是首页：必须看到底部 tab "找优惠 看榜单"
    img = screenshot_window(win['wid'])
    if img:
        text_all = ' '.join(b['text'] for b in ocr_with_boxes(img))
        try: img.unlink()
        except OSError: pass
        if not ('找优惠' in text_all and '看榜单' in text_all):
            print(f"❌ 不在大众点评首页，请先手动按 < 返回")
            shot(win['wid'], '00_not_home')
            return 4

    # Step 2: 点搜索框
    print(f"\n▶ 搜索 '{keyword}'")
    click_pos(win, *parse_coord(points['home_search_input']))
    time.sleep(random.uniform(0.8, 1.3))
    
    # 清空 + 粘贴
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+a'], check=False)
    time.sleep(0.2)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Delete'], check=False)
    time.sleep(0.3)
    human_paste(keyword)
    time.sleep(random.uniform(0.6, 1.0))
    shot(win['wid'], '01_keyword_pasted')

    # Step 3: 按 Enter 触发搜索
    print("\n▶ 按 Enter 搜索")
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Return'], check=False)
    time.sleep(4.0)
    img = shot(win['wid'], '02_search_result')
    if detect_captcha_in_screenshot(img):
        print("❌ 搜索后触发反爬")
        return 1

    # Step 4: 点第一家店
    print("\n▶ 点第一家店")
    click_pos(win, *parse_coord(points['first_shop_result']))
    time.sleep(4.5)
    img = shot(win['wid'], '03_detail_page')
    if detect_captcha_in_screenshot(img):
        print("❌ 详情页触发反爬")
        return 1

    # Step 5: 处理美团弹窗（可能会弹）
    handle_meituan_dialog(win)
    time.sleep(0.5)

    # Step 6: 自适应找"评价 (N) 查看全部 >" 模块（需要在详情页滚动直到看到）
    print("\n▶ OCR 自适应找评价模块")
    review_count = None
    for attempt in range(7):
        # 关掉可能的弹窗
        if attempt > 0:
            handle_meituan_dialog(win)
        # 在 OCR 同一帧里，先读评论总数（在 click 前抓）
        if review_count is None:
            tmp_img = screenshot_window(win['wid'])
            if tmp_img:
                try:
                    for b in ocr_with_boxes(tmp_img):
                        if '评价' in b['text'] and b['y'] < 700:
                            # 同行右边找数字
                            same_row = [bb for bb in ocr_with_boxes(tmp_img)
                                       if abs(bb['y']-b['y'])<15 and bb['x']>b['x']]
                            for bb in same_row[:5]:
                                m = re.search(r'(\d+)', bb['text'])
                                if m:
                                    n = int(m.group(1))
                                    if 1 <= n <= 50000:
                                        review_count = n
                                        break
                            if review_count:
                                break
                finally:
                    try: tmp_img.unlink()
                    except OSError: pass
        # 找评价模块 click 位置
        pos = find_review_module(win['wid'])
        if pos is not None:
            print(f"  ✅ 评价模块 at ({pos[0]},{pos[1]}) (尝试 {attempt})")
            if review_count:
                print(f"  📊 评论总数: {review_count} → 估算 {review_count // 14 + 1} 页")
            human_click(win, pos[0], pos[1], base_w=base_w, base_h=base_h)
            time.sleep(random.uniform(0.5, 1.0))
            break
        # 滚详情页
        ax, ay = parse_coord(points.get('detail_scroll_anchor', '200,400'))
        human_scroll(win, ax, ay, dy=-350, base_w=base_w, base_h=base_h)
        time.sleep(random.uniform(1.5, 2.5))
    else:
        print("❌ 找不到评价模块")
        shot(win['wid'], '03b_no_review')
        return 2

    # 自适应 scrolls：根据 review_count 算实际需要滚的次数
    # 每次滚 1000px ≈ 1 页 14 条；加 5 次 buffer
    if review_count and review_count > 0:
        adaptive_scrolls = min(scrolls + 50, max(8, (review_count // 14) + 5))
        if adaptive_scrolls != scrolls:
            print(f"  🎯 调整滚动次数 {scrolls} → {adaptive_scrolls}")
            scrolls = adaptive_scrolls

    # Step 7: 等评价页加载
    time.sleep(5.0)
    img = shot(win['wid'], '04_review_page')
    if detect_captcha_in_screenshot(img):
        print("❌ 评价页触发反爬")
        return 1

    # Step 8: 滚评价页 - 每次滚 1000px（约 2-3 条评论），间隔 0.8-1.3s
    # 大众点评每次滚动一定距离触发下一页 14 条评论加载
    # 平均评论卡片约 300px，1000px ≈ 3 张卡片 = 接近 1 页（避免 spam 但也不浪费时间）
    print(f"\n▶ 评价页滚动 {scrolls} 次（每次 1000px，间隔 1s）")
    rev_x, rev_y = parse_coord(points['review_list_anchor'])
    
    for i in range(1, scrolls + 1):
        human_scroll(win, rev_x, rev_y, dy=-1000, base_w=base_w, base_h=base_h)
        time.sleep(random.uniform(0.8, 1.3))
        # 每 5 次截图查反爬（OCR 慢，不能每次跑）
        if i % 5 == 0:
            print(f"   已滚动 {i}/{scrolls}")
            img = shot(win['wid'], f'05_scroll_{i}')
            if detect_captcha_in_screenshot(img):
                print(f"  ❌ 滚到 {i} 触发反爬")
                return 1
    
    shot(win['wid'], '06_final')
    return 0


# ----------------------------------------------------------------------
# 解析 pcap → 整理评论 → 写 store_reviews/{idx}_{name}.json
# ----------------------------------------------------------------------

def parse_pcap_and_save(idx: int, store_name: str, since_ts: float,
                        out_dir: Path) -> int:
    """
    解析 pcap 用 sslkey_collector，找新增的 review_*.json，
    整理为 store_reviews 标准格式（list[{门店, 发布时间, 发布人, 文字}]）。
    返回评论数。
    """
    print("\n▶ 解析 pcap")
    if not PCAP_FILE.exists() or PCAP_FILE.stat().st_size < 1000:
        print("  ⚠️ pcap 太小，跳过解析")
        return 0
    try:
        from sslkey_collector import run_offline
        run_offline(PCAP_FILE, KEYS_FILE)
    except Exception as e:
        print(f"  ⚠️ collector 失败: {e}")
    
    # 找新增 review_*.json
    new_files = []
    for f in LOG_DIR.glob('review_*.json'):
        if f.stat().st_mtime >= since_ts - 5:
            new_files.append(f)
    print(f"  本店新增 review JSON: {len(new_files)}")
    
    # 整理成 store_reviews 标准格式
    rows = []
    seen = set()
    for f in new_files:
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        data = d.get('data', {})
        review_list = []
        if isinstance(data, dict):
            inner = data.get('data') if isinstance(data.get('data'), dict) else data
            if isinstance(inner, dict):
                review_list = inner.get('list', [])
        if not isinstance(review_list, list):
            continue
        for r in review_list:
            if not isinstance(r, dict):
                continue
            text = (r.get('reviewBody') or r.get('reviewText') or
                    r.get('content') or '')
            if not text:
                continue
            user = ''
            ui = r.get('userInfo')
            if isinstance(ui, dict):
                user = ui.get('userName') or ''
            user = user or r.get('userName', '')
            # 时间
            pub_time = ''
            ri = r.get('reviewIndexes')
            if isinstance(ri, dict):
                pub_time = ri.get('addTime') or ''
            if not pub_time:
                pub_time = (r.get('createDateString') or
                            r.get('createTime') or
                            r.get('addTimeStr') or '')
            rid = r.get('reviewId') or r.get('reviewID') or ''
            key = (rid, user, text[:40])
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                '门店': store_name,
                '发布时间': pub_time,
                '发布人': user,
                '文字': text,
            })
    
    # 写 output/store_reviews/{idx:03d}_{store_name}.json
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = store_name.replace('/', '_')
    out_path = out_dir / f'{idx:03d}_{safe_name}.json'
    
    # 如果已存在数据，merge（去重）
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
        key = (r.get('发布人', ''), r.get('发布时间', ''), r.get('文字', '')[:40])
        if key in merged_seen:
            continue
        merged_seen.add(key)
        merged.append(r)
    
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    print(f"  💾 {out_path} ({len(merged)} 条评论, 本次新增 {len(rows)})")
    return len(merged)


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--idx', type=int, default=0, help='xlsx 编号')
    ap.add_argument('--name', help='店铺名（用作输出文件名）')
    ap.add_argument('--keyword', help='搜索关键词（默认 = name）')
    ap.add_argument('--scrolls', type=int, default=10, help='评价页滚动次数')
    ap.add_argument('--out-dir', type=Path,
                    default=ROOT / 'output' / 'store_reviews')
    ap.add_argument('--duration', type=int, default=0,
                    help='tshark 抓包时长上限秒（0=自动判断）')
    args = ap.parse_args()

    keyword = args.keyword or args.name
    if not keyword:
        sys.stderr.write("❌ 必须指定 --keyword 或 --name\n")
        return 1
    
    # 检查环境
    win = get_window()
    if win is None:
        sys.stderr.write("❌ 找不到 PC 微信小程序窗口\n")
        return 1
    if not KEYS_FILE.exists() or KEYS_FILE.stat().st_size < 100:
        sys.stderr.write("❌ /tmp/wx_keys.log 无效（微信没带 SSLKEYLOGFILE 启动？）\n")
        return 1
    
    print(f"店铺: idx={args.idx} name={args.name}")
    print(f"窗口: wid={win['wid']} {win['w']}x{win['h']}")
    print(f"关键词: {keyword}")
    
    since_ts = time.time()
    
    # 启动 tshark
    duration = args.duration if args.duration > 0 else (
        30 + args.scrolls * 4 + 30  # 估算: 流程 30s + 每滚 4s + 30s 余量
    )
    print(f"\n▶ 启动 tshark (限时 {duration}s)")
    tshark = start_tshark(duration)
    
    rc = 99
    try:
        rc = run_search_to_review_scroll(win, keyword, args.scrolls)
    finally:
        stop_tshark(tshark)
    
    if rc == 0:
        # 解析 + 存
        n = parse_pcap_and_save(args.idx, args.name or keyword,
                                since_ts, args.out_dir)
        # 返回首页
        try:
            back_to_home(win)
        except Exception:
            pass
        print(f"\n✅ 完成（{n} 条评论）")
        return 0
    else:
        print(f"\n❌ 失败 rc={rc}")
        return rc


if __name__ == '__main__':
    sys.exit(main())
