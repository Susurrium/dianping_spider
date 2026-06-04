# -*- coding:utf-8 -*-
"""
总控：从 xlsx 读全部 389 家店，循环跑每家。
- 跳过已完成（output/store_reviews/{idx:03d}_*.json 存在且评论数 > 0）
- 按城市分组：同城连续跑，跨城自动切换
- 每家店：调 run_one_shop.py 跑端到端
- 反爬触发 → 暂停 30s（等用户处理验证码） → 继续
- Ctrl+C 优雅退出 → 已完成数据已保存

用法:
    # 全跑（4-6 小时）
    python3 run_all_stores.py

    # 只跑 5 家试水
    python3 run_all_stores.py --limit 5

    # 跳过 N 家从中间开始
    python3 run_all_stores.py --start 100

    # 只跑某城市的店
    python3 run_all_stores.py --city 上海

    # 每店滚动多少次（默认 12）
    python3 run_all_stores.py --scrolls 12
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from review_exporter import load_stores_from_xlsx, Store
from city_utils import city_from_address
from human_click import get_window
from ocr_locate import (
    screenshot_window, ocr_with_boxes, detect_captcha_in_screenshot,
)


XLSX_PATH = ROOT / '达美乐_门店.xlsx'
OUT_DIR = ROOT / 'output' / 'store_reviews'
PROGRESS_PATH = ROOT / 'output' / 'auto_run_progress.json'
KEYS_FILE = Path('/tmp/wx_keys.log')


# ----------------------------------------------------------------------
# 进度
# ----------------------------------------------------------------------

def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def save_progress(p: dict):
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(p, ensure_ascii=False, indent=2),
                             encoding='utf-8')


def is_store_done(idx: int, name: str) -> bool:
    """判断店是否已经抓好（store_reviews/ 文件存在且 reviews 数 >= 5）"""
    safe = name.replace('/', '_')
    f = OUT_DIR / f'{idx:03d}_{safe}.json'
    if not f.exists():
        return False
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        if isinstance(d, list) and len(d) >= 5:
            return True
        if isinstance(d, dict) and len(d.get('reviews', [])) >= 5:
            return True
    except Exception:
        pass
    return False


# ----------------------------------------------------------------------
# 城市切换（待实现 - 现在先用 OCR + 点击占位）
# ----------------------------------------------------------------------

def get_current_city(win) -> Optional[str]:
    """从首页左上角 OCR 读当前城市"""
    img = screenshot_window(win['wid'])
    if img is None:
        return None
    try:
        for b in ocr_with_boxes(img):
            if '市' in b['text'] and b['x'] < 150 and b['y'] < 80:
                # 例如 "上海市"
                m = re.search(r'([\u4e00-\u9fff]{2,4}市)', b['text'])
                if m:
                    return m.group(1).rstrip('市')
        return None
    finally:
        try: img.unlink()
        except OSError: pass


def switch_city(win, target_city: str) -> bool:
    """
    切换城市：
    1. 点左上"上海市 ▼"
    2. 在城市搜索框输入目标城市
    3. 点第一个匹配
    """
    from human_click import human_click, parse_coord, load_points
    from run_one_shop import human_paste, click_pos

    points = load_points()
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])
    win['base_w'] = base_w
    win['base_h'] = base_h

    print(f"  切换城市 → {target_city}")
    
    # 1. 点城市按钮
    if 'city_button' not in points:
        print("  ❌ 没录 city_button 坐标")
        return False
    cx, cy = parse_coord(points['city_button'])
    human_click(win, cx, cy, base_w=base_w, base_h=base_h)
    time.sleep(2.5)

    # 2. 在城市页面搜索框输入
    if 'city_search_input' not in points:
        print("  ❌ 没录 city_search_input 坐标")
        return False
    sx, sy = parse_coord(points['city_search_input'])
    human_click(win, sx, sy, base_w=base_w, base_h=base_h)
    time.sleep(1.0)
    human_paste(target_city)
    time.sleep(1.5)

    # 3. 点第一个匹配
    if 'city_first_result' not in points:
        # OCR 找城市名
        img = screenshot_window(win['wid'])
        if img:
            try:
                for b in ocr_with_boxes(img):
                    if target_city in b['text'] and b['y'] > 100:
                        rx, ry = b['x'] + b['w']//2, b['y'] + b['h']//2
                        human_click(win, rx, ry, base_w=base_w, base_h=base_h)
                        time.sleep(3.0)
                        return True
            finally:
                try: img.unlink()
                except OSError: pass
        return False
    fx, fy = parse_coord(points['city_first_result'])
    human_click(win, fx, fy, base_w=base_w, base_h=base_h)
    time.sleep(3.0)
    return True


# ----------------------------------------------------------------------
# 反爬等待
# ----------------------------------------------------------------------

def wait_for_human_captcha_solve(win, timeout: int = 180) -> bool:
    """检测到验证码 → 等用户手动通过 → 60s 检查一次"""
    print("\n⚠️ 检测到反爬验证码，请手动完成验证")
    print(f"  超时: {timeout}s")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(15)
        img = screenshot_window(win['wid'])
        if img is None:
            continue
        try:
            if not detect_captcha_in_screenshot(img):
                print("  ✅ 验证已通过")
                return True
        finally:
            try: img.unlink()
            except OSError: pass
    print("  ❌ 等待超时")
    return False


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def run_one(idx: int, store: Store, scrolls: int) -> int:
    """调 run_one_shop_smart.py（subprocess）跑单店"""
    cmd = [
        sys.executable, str(ROOT / 'run_one_shop_smart.py'),
        '--idx', str(idx),
        '--name', store.name,
        '--keyword', store.name,
        '--max-scrolls', str(scrolls),
    ]
    print(f"\n>>> 跑 {idx:03d} {store.name}")
    print(f"    {' '.join(cmd)}")
    try:
        rc = subprocess.call(cmd)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"    ❌ 调用失败: {e}")
        return 99
    return rc


def ensure_home(win, max_back: int = 6) -> bool:
    """确保当前在大众点评首页（用 page_detector 的 detect_state）"""
    from page_detector import detect_state, STATE_HOME, STATE_CAPTCHA, STATE_MEITUAN_DIALOG, find_dialog_cancel
    from human_click import human_click, parse_coord, load_points
    points = load_points()
    base_w = int(points['base_width'])
    base_h = int(points['base_height'])
    bx, by = parse_coord(points.get('back_button', '20,40'))
    
    for i in range(max_back):
        state, boxes = detect_state(win['wid'])
        print(f"  [{i+1}/{max_back}] 当前: {state}")
        if state == STATE_HOME:
            return True
        if state == STATE_MEITUAN_DIALOG:
            pos = find_dialog_cancel(boxes)
            if pos:
                human_click(win, pos[0], pos[1], base_w=base_w, base_h=base_h)
                time.sleep(1.5)
            continue
        if state == STATE_CAPTCHA:
            print("  ⚠️ 反爬验证码，等待 60s")
            time.sleep(60)
            continue
        # 其他状态都按返回
        print(f"  返回")
        human_click(win, bx, by, base_w=base_w, base_h=base_h)
        time.sleep(random.uniform(1.0, 1.6))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 家')
    ap.add_argument('--start', type=int, default=0, help='从第 N 家开始')
    ap.add_argument('--city', help='只跑指定城市的店')
    ap.add_argument('--scrolls', type=int, default=12)
    ap.add_argument('--retry-failed', action='store_true', help='重试之前失败的店')
    ap.add_argument('--xlsx', type=Path, default=XLSX_PATH)
    args = ap.parse_args()

    # 1. 检查环境
    win = get_window()
    if win is None:
        sys.stderr.write("❌ 找不到 PC 微信小程序窗口\n")
        return 1
    if not KEYS_FILE.exists() or KEYS_FILE.stat().st_size < 100:
        sys.stderr.write("❌ /tmp/wx_keys.log 无效\n")
        sys.stderr.write("   请用 wrapper 启动微信:\n")
        sys.stderr.write("   bash /tmp/wx_with_keylog.sh\n")
        return 1

    # 2. 读 xlsx
    print(f"读 xlsx: {args.xlsx}")
    stores = load_stores_from_xlsx(args.xlsx)
    print(f"  共 {len(stores)} 家店")

    # 3. 加载进度
    progress = load_progress()

    # 4. 排序：按 xlsx 顺序（保持原始 idx），不按城市字母排序
    stores_with_idx = list(enumerate(stores, 1))
    if args.city:
        stores_with_idx = [
            (i, s) for i, s in stores_with_idx
            if city_from_address(s.address) == args.city
        ]
    
    # 决定跑哪些（按 xlsx 顺序）
    todo = []
    for i, s in stores_with_idx:
        if i < args.start:
            continue
        if not args.retry_failed and is_store_done(i, s.name):
            continue
        todo.append((i, s))
    
    if args.limit > 0:
        todo = todo[:args.limit]
    
    print(f"  待跑: {len(todo)} 家")
    if not todo:
        print("  ✅ 全部已完成")
        return 0

    # 5. 当前城市（从 OCR 读，否则默认 上海）
    if not ensure_home(win):
        sys.stderr.write("❌ 无法回到大众点评首页，请手动回首页后重试\n")
        return 1
    current_city = get_current_city(win) or '上海'
    print(f"  当前城市: {current_city}")

    # 6. 主循环
    stats = {'success': 0, 'failed': 0, 'captcha': 0}
    try:
        for i, store in todo:
            target_city = city_from_address(store.address)
            
            # 切城市（如果跨城）
            if target_city and target_city != current_city:
                ok = switch_city(win, target_city)
                if ok:
                    current_city = target_city
                else:
                    print(f"  ⚠️ 切换城市失败，跳过 {store.name}")
                    stats['failed'] += 1
                    continue
            
            # 跑单店
            # 跑前确保在首页
            if not ensure_home(win):
                print(f"  ⚠️ 不在首页，跳过 {store.name}")
                stats['failed'] += 1
                continue
            
            rc = run_one(i, store, args.scrolls)
            
            if rc == 0:
                stats['success'] += 1
                progress.setdefault('completed', []).append(store.name)
            elif rc == 1:
                # 反爬触发，等用户处理
                stats['captcha'] += 1
                ok = wait_for_human_captcha_solve(win)
                if ok:
                    # 重试一次
                    rc = run_one(i, store, args.scrolls)
                    if rc == 0:
                        stats['success'] += 1
                        progress.setdefault('completed', []).append(store.name)
                    else:
                        stats['failed'] += 1
                        progress.setdefault('failed', []).append(store.name)
                else:
                    print("  ❌ 反爬验证未通过，停止整个 run")
                    break
            else:
                stats['failed'] += 1
                progress.setdefault('failed', []).append(store.name)
            
            # 定期保存进度
            save_progress(progress)
            
            # 每 5 家停 30s 缓和（避免触发反爬）
            if (stats['success'] + stats['failed']) % 5 == 0:
                print("  💤 缓和 30s...")
                time.sleep(30)
    except KeyboardInterrupt:
        print("\n⏹️ 用户中断")
    
    # 7. 保存进度
    save_progress(progress)
    
    print(f"\n=========================================")
    print(f"📊 跑完: 成功 {stats['success']}, 失败 {stats['failed']}, 验证码 {stats['captcha']}")
    print(f"   进度: {PROGRESS_PATH}")
    print(f"   评论: {OUT_DIR}")
    print(f"=========================================")
    return 0


if __name__ == '__main__':
    sys.exit(main())
