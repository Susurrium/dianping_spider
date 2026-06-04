# -*- coding:utf-8 -*-
"""
用 OCR 在截图里找"评价 (N)"模块的位置（坐标自适应于不同店铺）。

使用:
    from ocr_locate import find_review_module
    win = get_window()
    pos = find_review_module(win)  # → (rel_x, rel_y) or None
    if pos: human_click(win, pos[0], pos[1])
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent


def _check():
    if not shutil.which('tesseract'):
        sys.stderr.write("❌ 未装 tesseract\n")
        return False
    return True


def screenshot_window(wid: int) -> Optional[Path]:
    f = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    f.close()
    path = Path(f.name)
    r = subprocess.run(['import', '-window', str(wid), str(path)],
                       check=False, stderr=subprocess.DEVNULL)
    if r.returncode != 0 or path.stat().st_size < 1000:
        return None
    return path


def ocr_with_boxes(image_path: Path, lang: str = 'chi_sim+eng',
                   upscale: int = 2) -> List[dict]:
    """
    用 tesseract 输出 TSV 含每个词的 bbox。
    返回列表，每项 {text, x, y, w, h, conf}。
    
    upscale: 截图先放大 N 倍再 OCR（小程序 412x798 字小，2x 提高识别率）。
             返回的 x/y/w/h 自动除回原始尺度。
    """
    if not _check():
        return []
    
    src = image_path
    if upscale and upscale != 1:
        # 先用 ImageMagick 放大
        try:
            scaled = image_path.with_suffix('.scaled.png')
            r = subprocess.run(
                ['convert', str(image_path), '-resize', f'{upscale*100}%', str(scaled)],
                check=False, stderr=subprocess.DEVNULL, timeout=8
            )
            if r.returncode == 0 and scaled.exists():
                src = scaled
        except Exception:
            pass
    
    try:
        out = subprocess.check_output([
            'tesseract', str(src), '-',
            '-l', lang, '--psm', '6', 'tsv'
        ], text=True, stderr=subprocess.DEVNULL, timeout=20)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    finally:
        if src != image_path:
            try: src.unlink()
            except OSError: pass
    
    results = []
    lines = out.split('\n')
    if not lines:
        return results
    header = lines[0].split('\t')
    if 'text' not in header:
        return results
    idx = {k: header.index(k) for k in header}
    for line in lines[1:]:
        parts = line.split('\t')
        if len(parts) < len(header):
            continue
        text = parts[idx['text']].strip()
        if not text:
            continue
        try:
            conf = float(parts[idx['conf']])
        except ValueError:
            conf = 0.0
        if conf < 30:
            continue
        try:
            x = int(parts[idx['left']])
            y = int(parts[idx['top']])
            w = int(parts[idx['width']])
            h = int(parts[idx['height']])
        except ValueError:
            continue
        # 坐标除回原始尺度
        if upscale and upscale != 1:
            x = x // upscale
            y = y // upscale
            w = w // upscale
            h = h // upscale
        results.append({
            'text': text, 'x': x, 'y': y, 'w': w, 'h': h, 'conf': conf,
        })
    return results


def find_text(image_path: Path, target_text: str) -> List[dict]:
    """OCR + 找包含 target_text 的词块。"""
    boxes = ocr_with_boxes(image_path)
    return [b for b in boxes if target_text in b['text']]


def find_review_module(wid: int) -> Optional[Tuple[int, int]]:
    """
    在当前截图里找"评价 (N)"模块（详情页里能进评价详情页的那个 entry）。
    返回相对窗口坐标 (rel_x, rel_y)。
    优先点"查看全部"链接（在"评价"右侧），其次点"评价 (N)"两字。
    
    注意：必须排除底部 tab "写评价"（y > 700）—— 那个 click 后会进写评论页。
    必须含数字才认为是"评价(449)"模块（区分"写评价"按钮）。
    """
    import re as _re
    img = screenshot_window(wid)
    if img is None:
        return None
    try:
        all_boxes = ocr_with_boxes(img)
        if not all_boxes:
            return None

        # 候选: 含"评价" 的 box，排除底部 tab 区域（y >= 700 大概是 412x798 单栏的底部 tab）
        review_candidates = []
        for b in all_boxes:
            if '评价' not in b['text']:
                continue
            if b['y'] >= 700:  # 底部 tab "写评价" 排除
                continue
            # 必须紧邻数字（"评价(N)" 或 "评价 N条"）
            text = b['text']
            if _re.search(r'\d', text):
                review_candidates.append(b)
                continue
            # OCR 可能把 "评价 (449)" 拆成两块，看同行右边有没有数字
            same_row_right = [bb for bb in all_boxes
                              if abs(bb['y'] - b['y']) < 15
                              and bb['x'] > b['x']
                              and bb['x'] < b['x'] + 200]
            if any(_re.search(r'\d', bb['text']) for bb in same_row_right):
                review_candidates.append(b)

        if not review_candidates:
            return None

        # 取 y 最小（最靠上）的"评价(N)"模块
        review = sorted(review_candidates, key=lambda b: b['y'])[0]

        # 在同一行找 "查看全部" 或 "全部" 或 "查看" 或 ">" 等
        # OCR 经常把"查看全部"拆成"查看"和"全部"两块
        same_row = [b for b in all_boxes
                    if abs(b['y'] - review['y']) < 25
                    and b['x'] > review['x']]
        view_all_keywords = ['查看全部', '查看', '全部', '》', '〉', '>']
        view_all = []
        for b in same_row:
            for kw in view_all_keywords:
                if kw in b['text']:
                    view_all.append(b)
                    break

        if view_all:
            # 取最右边的 box（>箭头通常在最右），扩大点击范围到末端
            target = max(view_all, key=lambda b: b['x'] + b['w'])
            # 点中心，但向右偏（覆盖整个"查看全部 >"按钮）
            click_x = target['x'] + target['w'] // 2
            # 如果 box 是"查看"，向右扩展（"全部 >"在右边）
            if '查看' in target['text'] and '>' not in target['text'] and '》' not in target['text']:
                click_x += 25  # 向右偏移到"全部 >"区域
            click_y = target['y'] + target['h'] // 2
            return (click_x, click_y)
        else:
            # 没找到查看全部，点"评价(N)"标题（通常也是可点击的）
            return (review['x'] + review['w'] // 2, review['y'] + review['h'] // 2)
    finally:
        try:
            img.unlink()
        except OSError:
            pass


def find_back_button(wid: int) -> Optional[Tuple[int, int]]:
    """通常 < 按钮在左上角 (~20, ~40)，OCR 不一定能识别 < 字符。
    退化为固定位置。"""
    return (20, 40)


def find_dialog_cancel(wid: int) -> Optional[Tuple[int, int]]:
    """找弹窗里的"取消"按钮位置。"""
    img = screenshot_window(wid)
    if img is None:
        return None
    try:
        boxes = ocr_with_boxes(img)
        for b in boxes:
            if '取消' in b['text']:
                return (b['x'] + b['w'] // 2, b['y'] + b['h'] // 2)
        return None
    finally:
        try:
            img.unlink()
        except OSError:
            pass


def detect_captcha_in_screenshot(image_path: Path) -> bool:
    """检测反爬验证码：截图含'身份核实'/'安全验证'等。"""
    boxes = ocr_with_boxes(image_path)
    keywords = ['身份核实', '安全验证', '请依次点击', '点击下图', '请按顺序', '人机验证']
    text_all = ' '.join(b['text'] for b in boxes)
    for kw in keywords:
        if kw in text_all:
            return True
    return False


def detect_meituan_dialog(image_path: Path) -> bool:
    """检测美团小程序跳转对话框。"""
    boxes = ocr_with_boxes(image_path)
    text_all = ' '.join(b['text'] for b in boxes)
    return '美团' in text_all and ('打开' in text_all or '允许' in text_all)


# ----------------------------------------------------------------------
# CLI 测试
# ----------------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['boxes', 'review', 'cancel', 'captcha', 'meituan'])
    ap.add_argument('--image', type=Path)
    ap.add_argument('--wid', type=int)
    args = ap.parse_args()

    img = args.image
    if img is None and args.wid:
        img = screenshot_window(args.wid)
    if img is None:
        sys.stderr.write("❌ 没指定 --image 或 --wid\n")
        sys.exit(1)

    if args.cmd == 'boxes':
        for b in ocr_with_boxes(img):
            print(f"  ({b['x']:3d},{b['y']:3d}) {b['w']:3d}x{b['h']:3d} conf={b['conf']:.0f} text={b['text']}")
    elif args.cmd == 'review':
        boxes = [b for b in ocr_with_boxes(img) if '评价' in b['text']]
        for b in boxes:
            print(f"  评价位置: ({b['x']},{b['y']}) {b['w']}x{b['h']} text={b['text']}")
    elif args.cmd == 'cancel':
        boxes = [b for b in ocr_with_boxes(img) if '取消' in b['text']]
        for b in boxes:
            print(f"  取消位置: ({b['x']},{b['y']}) text={b['text']}")
    elif args.cmd == 'captcha':
        print(f"  反爬: {detect_captcha_in_screenshot(img)}")
    elif args.cmd == 'meituan':
        print(f"  美团弹窗: {detect_meituan_dialog(img)}")
