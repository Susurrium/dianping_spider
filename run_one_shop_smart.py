# -*- coding:utf-8 -*-
"""
单店智能流程：状态机驱动，每步 OCR 看页面状态再决定动作。

不再线性 click → click → click，而是循环：
1. detect_state(win)
2. 根据状态选动作（点哪、滚动、等待、退出）
3. 执行动作
4. 等状态变化（OCR 看到预期状态）
5. 循环

支持的状态转换:
    HOME → 搜索 → SEARCH_SUGGEST or SEARCH_RESULT
    SEARCH_SUGGEST → 点匹配建议 → SEARCH_RESULT or SHOP_DETAIL
    SEARCH_RESULT → 点第一家 → SHOP_DETAIL
    SHOP_DETAIL → 滚到看到评价 + 点查看全部 → REVIEW_PAGE
    REVIEW_PAGE → 滚动 N 次
    任意 → MEITUAN_DIALOG → 点取消 → 上一状态
    任意 → CAPTCHA → 等用户处理
    任意 → 按返回 → 上一级（最终回 HOME）
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

from human_click import get_window, human_click, human_scroll, parse_coord, load_points
from page_detector import (
    detect_state, state_label, wait_for_state,
    find_search_input, find_back_button, find_search_cancel,
    find_first_shop_in_search_result, find_first_in_search_suggest,
    find_review_module_smart, find_dialog_cancel,
    get_review_count_from_detail,
    STATE_HOME, STATE_SEARCH_SUGGEST, STATE_SEARCH_RESULT,
    STATE_SEARCH_LOADING, STATE_SEARCH_EMPTY,
    STATE_SHOP_DETAIL, STATE_REVIEW_PAGE,
    STATE_MEITUAN_DIALOG, STATE_CAPTCHA, STATE_LOGIN, STATE_CITY_PAGE,
    STATE_UNKNOWN,
)

PCAP_FILE = Path('/tmp/wx_capture/raw.pcap')
KEYS_FILE = Path('/tmp/wx_keys.log')
DIAG_DIR = ROOT / 'mitm_logs' / 'diagnostic'
DIAG_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = ROOT / 'mitm_logs'


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def shot(wid: int, label: str) -> Path:
    ts = datetime.now().strftime('%H%M%S')
    path = DIAG_DIR / f'smart_{ts}_{label}.png'
    subprocess.run(['import', '-window', str(wid), str(path)],
                   check=False, stderr=subprocess.DEVNULL)
    return path


def click_at(win, rel_x: int, rel_y: int):
    base_w = win.get('base_w', win['w'])
    base_h = win.get('base_h', win['h'])
    human_click(win, rel_x, rel_y, base_w=base_w, base_h=base_h)


def scroll_at(win, rel_x: int, rel_y: int, dy: int = -1000):
    base_w = win.get('base_w', win['w'])
    base_h = win.get('base_h', win['h'])
    human_scroll(win, rel_x, rel_y, dy=dy, base_w=base_w, base_h=base_h)


def paste_text(text: str):
    if shutil.which('xclip'):
        subprocess.run(['xclip', '-selection', 'clipboard', '-i'],
                       input=text.encode('utf-8'), check=True)
        time.sleep(random.uniform(0.10, 0.25))
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+v'], check=False)
        time.sleep(random.uniform(0.20, 0.40))


# ----------------------------------------------------------------------
# tshark 子进程
# ----------------------------------------------------------------------

def start_tshark(duration: int = 0) -> subprocess.Popen:
    PCAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PCAP_FILE.exists():
        PCAP_FILE.unlink()
    cmd_str = f"tshark -i wlp2s0 -f 'tcp port 443' -w {PCAP_FILE}"
    if duration > 0:
        cmd_str += f" -a duration:{duration}"
    proc = subprocess.Popen(
        ['sg', 'wireshark', '-c', cmd_str],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )
    for _ in range(8):
        time.sleep(0.5)
        if PCAP_FILE.exists():
            return proc
    return proc


def stop_tshark(proc):
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
# 状态驱动动作
# ----------------------------------------------------------------------

def handle_meituan_dialog(win, boxes) -> bool:
    """美团弹窗 → 找取消并点击。返回是否处理"""
    pos = find_dialog_cancel(boxes)
    if pos is None:
        return False
    log(f"  → 美团弹窗 取消@{pos}")
    click_at(win, pos[0], pos[1])
    time.sleep(random.uniform(1.0, 1.5))
    return True


def wait_captcha_solve(win, timeout: int = 180) -> bool:
    """检测到反爬 → 等用户手动处理"""
    log(f"  ⚠️ 反爬验证码！请手动处理（{timeout}s 超时）")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(15)
        state, _ = detect_state(win['wid'])
        if state != STATE_CAPTCHA:
            log(f"  ✅ 反爬已通过 → {state_label(state)}")
            return True
    return False


def go_back(win):
    """点左上 < 返回"""
    pos = find_back_button([])  # 固定 (20, 36)
    click_at(win, pos[0], pos[1])
    time.sleep(random.uniform(1.0, 1.5))


def ensure_home(win, max_iter: int = 8) -> bool:
    """循环按返回直到看到首页"""
    log("→ 确保在首页")
    for i in range(max_iter):
        state, boxes = detect_state(win['wid'])
        log(f"  [{i+1}] 当前: {state_label(state)}")
        if state == STATE_HOME:
            return True
        if state == STATE_CAPTCHA:
            if not wait_captcha_solve(win):
                return False
            continue
        if state == STATE_MEITUAN_DIALOG:
            handle_meituan_dialog(win, boxes)
            continue
        if state == STATE_LOGIN:
            log(f"  ❌ 登录失效")
            return False
        # 其他状态都按返回
        go_back(win)
    return False


def search_keyword(win, keyword: str) -> bool:
    """首页 → 搜索"""
    state, boxes = detect_state(win['wid'])
    if state != STATE_HOME:
        log(f"  ❌ search 必须在首页，当前 {state_label(state)}")
        return False
    
    # 找搜索框
    pos = find_search_input(boxes)
    if pos is None:
        log("  ❌ 找不到搜索框")
        return False
    log(f"  click 搜索框@{pos}")
    click_at(win, pos[0], pos[1])
    time.sleep(random.uniform(0.8, 1.2))
    
    # 清空 + 粘贴
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+a'], check=False)
    time.sleep(0.2)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Delete'], check=False)
    time.sleep(0.3)
    paste_text(keyword)
    time.sleep(random.uniform(0.6, 1.0))
    
    # 按 Enter
    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Return'], check=False)
    return True


def click_first_shop_smart(win, store_name: str) -> bool:
    """搜索后 → 进店。可能是搜索建议页 / 搜索结果页 / 加载中 / 空结果"""
    # 等更长时间：搜索结果可能正在加载
    state, boxes = wait_for_state(
        win['wid'],
        [STATE_SEARCH_RESULT, STATE_SEARCH_SUGGEST, STATE_SHOP_DETAIL,
         STATE_SEARCH_EMPTY, STATE_SEARCH_LOADING,
         STATE_CAPTCHA, STATE_MEITUAN_DIALOG],
        timeout=15, poll=2.0
    )
    log(f"  搜索后状态: {state_label(state)}")
    
    # 加载中 → 再多等（最多 15 秒）
    if state == STATE_SEARCH_LOADING:
        log("  ⏳ 搜索结果加载中，等 15s")
        for _ in range(5):
            time.sleep(3)
            state, boxes = detect_state(win['wid'])
            if state != STATE_SEARCH_LOADING:
                log(f"  加载完: {state_label(state)}")
                break
        else:
            log(f"  ⚠️ 搜索一直在加载中，跳过")
            shot(win['wid'], 'fail_loading_stuck')
            return False
    
    # 反爬
    if state == STATE_CAPTCHA:
        if not wait_captcha_solve(win):
            return False
        state, boxes = detect_state(win['wid'])
    
    # 美团弹窗
    if state == STATE_MEITUAN_DIALOG:
        handle_meituan_dialog(win, boxes)
        state, boxes = detect_state(win['wid'])
    
    # 直接进了详情页
    if state == STATE_SHOP_DETAIL:
        log("  ✅ 已进入店铺详情页（一次跳转完成）")
        return True
    
    # 搜索结果为空
    if state == STATE_SEARCH_EMPTY:
        log(f"  ⚠️ 搜索结果为空：'{store_name}' 在大众点评里搜不到")
        shot(win['wid'], 'fail_search_empty')
        return False
    
    # 持续加载中（说明搜索请求挂死）
    if state == STATE_SEARCH_LOADING:
        log(f"  ⚠️ 搜索一直在加载中，跳过 '{store_name}'")
        shot(win['wid'], 'fail_loading_stuck')
        return False
    
    # 搜索建议页
    if state == STATE_SEARCH_SUGGEST:
        # 找第一条匹配建议 click
        pos = parse_coord(points.get('first_shop_result', '194,231'))  # 用录制的第一家店坐标
        if pos is None:
            log("  ⚠️ 搜索建议页找不到匹配，按 Enter 强制提交")
            shot(win['wid'], 'suggest_no_match')
            subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Return'], check=False)
            time.sleep(4.0)
            # 再次检测状态（可能加载中）
            for _ in range(3):
                state2, boxes2 = detect_state(win['wid'])
                log(f"  Enter 后: {state_label(state2)}")
                if state2 == STATE_SEARCH_LOADING:
                    time.sleep(4)
                    continue
                break
            if state2 == STATE_SEARCH_RESULT:
                pos = (200, 280)  # 第一家店铺卡片固定位置
                if pos is None:
                    log("  ❌ 搜索结果页找不到第一家店")
                    shot(win['wid'], 'fail_no_first_shop')
                    return False
                log(f"  click 第一家店@{pos}")
                click_at(win, pos[0], pos[1])
                time.sleep(random.uniform(2.0, 3.0))
                return True
            elif state2 == STATE_SHOP_DETAIL:
                log("  ✅ 直接进入详情页")
                return True
            elif state2 == STATE_SEARCH_EMPTY or state2 == STATE_SEARCH_LOADING:
                log(f"  ⚠️ 搜索无结果")
                shot(win['wid'], 'fail_empty_after_enter')
                return False
            else:
                log(f"  ❌ Enter 后状态不对: {state_label(state2)}")
                shot(win['wid'], 'fail_after_enter')
                return False
        log(f"  click 搜索建议@{pos}")
        click_at(win, pos[0], pos[1])
        time.sleep(random.uniform(2.0, 3.0))
        return True
    
    # 搜索结果页
    if state == STATE_SEARCH_RESULT:
        pts = load_points()
        pos = parse_coord(pts.get('first_shop_result', '194,231'))
        log(f"  click 第一家店@{pos}")
        click_at(win, pos[0], pos[1])
        time.sleep(random.uniform(3.0, 4.0))
        return True
    
    log(f"  ❌ 搜索后到了未知状态 {state_label(state)}")
    shot(win['wid'], 'fail_after_search')
    return False


def enter_review_page(win) -> Tuple[bool, Optional[int]]:
    """
    在详情页：滚动直到看到"评价 (N) 查看全部 >"，然后 click 进评价页。
    返回 (是否成功, 评论总数)。
    """
    log("→ 找评价模块")
    review_count = None
    for attempt in range(8):
        state, boxes = detect_state(win['wid'])
        log(f"  [{attempt+1}] 当前: {state_label(state)}")
        
        if state == STATE_MEITUAN_DIALOG:
            handle_meituan_dialog(win, boxes)
            continue
        
        if state == STATE_CAPTCHA:
            if not wait_captcha_solve(win):
                return False, None
            continue
        
        if state == STATE_REVIEW_PAGE:
            log("  ✅ 已经在评价页（可能误进了）")
            return True, None
        
        if state != STATE_SHOP_DETAIL:
            # OCR 不稳定，unknown 也可能是详情页
            # 只有明确是搜索结果/首页/反爬才放弃
            if state in (STATE_SEARCH_RESULT, STATE_HOME, STATE_LOGIN):
                log(f"  ❌ 不在详情页 ({state_label(state)})")
                return False, None
            # unknown 或其他状态 → 继续尝试滚动找评价
            log(f"  ⚠️ 状态={state_label(state)}，尝试滚动找评价")
        
        # 详情页 → 看是否能找到评价模块
        if review_count is None:
            review_count = get_review_count_from_detail(boxes)
            if review_count:
                log(f"  📊 评论总数: {review_count}")
        
        pos = find_review_module_smart(boxes)
        if pos is not None:
            log(f"  click 评价 查看全部@{pos}")
            click_at(win, pos[0], pos[1])
            time.sleep(random.uniform(2.0, 3.0))
            # 等到评价页
            new_state, _ = wait_for_state(
                win['wid'], [STATE_REVIEW_PAGE], timeout=8)
            if new_state == STATE_REVIEW_PAGE:
                return True, review_count
            else:
                log(f"  ⚠️ click 后没进评价页（{state_label(new_state)}），重试")
                continue
        
        # 找不到评价模块 → 滚动详情页
        log("  ⏬ 详情页向下滚")
        # 用窗口中间偏上做滚动锚点
        scroll_at(win, win['w'] // 2, win['h'] // 3, dy=-500)
        time.sleep(random.uniform(1.5, 2.5))
    
    log("  ❌ 8 次后还没找到评价模块")
    return False, review_count


def scroll_review_to_end(win, review_count: Optional[int],
                        max_scrolls: int = 60,
                        scroll_dy: int = -1000) -> int:
    """
    评价页滚动直到加载完，返回实际滚动次数。
    """
    # 估算所需滚动次数
    if review_count and review_count > 0:
        target_scrolls = min(max_scrolls, max(5, (review_count // 14) + 8))
        log(f"  目标滚动 {target_scrolls} 次（{review_count} 评论 / 14 一页 + 8 buffer）")
    else:
        target_scrolls = max_scrolls
    
    log(f"→ 评价页滚动")
    # 滚动锚点：评价列表中央
    anchor_x = win['w'] // 2
    anchor_y = win['h'] // 2
    
    for i in range(1, target_scrolls + 1):
        scroll_at(win, anchor_x, anchor_y, dy=scroll_dy)
        time.sleep(random.uniform(0.8, 1.3))
        
        # 每 5 次检测一次状态，看是否还在评价页
        if i % 5 == 0:
            state, _ = detect_state(win['wid'])
            log(f"  [{i}/{target_scrolls}] 状态: {state_label(state)}")
            if state == STATE_CAPTCHA:
                wait_captcha_solve(win)
            elif state != STATE_REVIEW_PAGE:
                log(f"  ⚠️ 离开评价页，停止滚动")
                return i
    return target_scrolls


# ----------------------------------------------------------------------
# 解析 pcap → store_reviews
# ----------------------------------------------------------------------

def parse_and_save(idx: int, store_name: str, since_ts: float,
                   out_dir: Path) -> int:
    if not PCAP_FILE.exists() or PCAP_FILE.stat().st_size < 1000:
        log("  ⚠️ pcap 太小")
        return 0
    log("→ collector 解析 pcap")
    try:
        from sslkey_collector import run_offline
        run_offline(PCAP_FILE, KEYS_FILE)
    except Exception as e:
        log(f"  ⚠️ collector 失败: {e}")
    
    new_files = [f for f in LOG_DIR.glob('review_*.json')
                 if f.stat().st_mtime >= since_ts - 5]
    log(f"  新增 review JSON: {len(new_files)}")
    
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
            pub_time = ''
            ri = r.get('reviewIndexes')
            if isinstance(ri, dict):
                pub_time = ri.get('addTime') or ''
            pub_time = pub_time or r.get('createDateString') or r.get('addTimeStr') or ''
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
    
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = store_name.replace('/', '_')
    out_path = out_dir / f'{idx:03d}_{safe}.json'
    
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
        key = (r.get('发布人',''), r.get('发布时间',''), r.get('文字','')[:40])
        if key in merged_seen:
            continue
        merged_seen.add(key)
        merged.append(r)
    
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    log(f"  💾 {out_path}: {len(merged)} 条 (本次新增 {len(rows)})")
    return len(merged)


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--idx', type=int, default=0)
    ap.add_argument('--name', help='店名（用作输出文件名 & 搜索关键词）')
    ap.add_argument('--keyword', help='搜索关键词（默认 = name）')
    ap.add_argument('--max-scrolls', type=int, default=60)
    ap.add_argument('--out-dir', type=Path,
                    default=ROOT / 'output' / 'store_reviews')
    args = ap.parse_args()
    
    keyword = args.keyword or args.name
    if not keyword:
        sys.stderr.write("❌ 必须指定 --name 或 --keyword\n")
        return 1
    
    win = get_window()
    if win is None:
        sys.stderr.write("❌ 找不到窗口\n")
        return 1
    if not KEYS_FILE.exists() or KEYS_FILE.stat().st_size < 100:
        sys.stderr.write("❌ keys 文件无效\n")
        return 1
    
    points = load_points()
    win['base_w'] = int(points['base_width'])
    win['base_h'] = int(points['base_height'])
    
    log(f"店铺: idx={args.idx} {args.name}")
    log(f"窗口: wid={win['wid']} {win['w']}x{win['h']}")
    
    # 1. 激活窗口
    subprocess.run(['xdotool', 'windowactivate', '--sync', str(win['wid'])], check=False)
    time.sleep(0.5)
    
    # 2. 确保在首页
    if not ensure_home(win):
        log("❌ 无法回到首页")
        return 1
    
    since_ts = time.time()
    
    # 3. 启动 tshark
    duration = 90 + (args.max_scrolls // 5) * 6
    log(f"启动 tshark (限时 {duration}s)")
    tshark = start_tshark(duration)
    
    rc = 99
    try:
        # 4. 搜索
        if not search_keyword(win, keyword):
            log("❌ 搜索失败")
            rc = 3
        else:
            # 5. 进店
            if not click_first_shop_smart(win, args.name or keyword):
                log("❌ 进店失败")
                rc = 3
            else:
                # 6. 进评价页
                ok, review_count = enter_review_page(win)
                if not ok:
                    log("❌ 进评价页失败")
                    rc = 2
                else:
                    # 7. 滚动
                    scroll_review_to_end(win, review_count, args.max_scrolls)
                    rc = 0
    finally:
        stop_tshark(tshark)
    
    # 8. 解析
    if rc == 0:
        n = parse_and_save(args.idx, args.name or keyword, since_ts, args.out_dir)
        log(f"✅ 完成 ({n} 条评论)")
        # 回首页
        try: ensure_home(win, max_iter=4)
        except Exception: pass
        return 0
    else:
        log(f"❌ 失败 rc={rc}")
        return rc


if __name__ == '__main__':
    sys.exit(main())
