# -*- coding:utf-8 -*-
"""
页面状态识别 + 元素定位

用 OCR 看当前页面是什么状态（首页/搜索建议/搜索结果/详情/评价/弹窗/反爬），
然后定位关键元素位置（搜索框/返回/评价入口/取消等）。

核心原则：永远不假设当前在某个页面，每个动作前先 detect_state 看一下。
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from ocr_locate import ocr_with_boxes, screenshot_window


# ----------------------------------------------------------------------
# 页面状态枚举
# ----------------------------------------------------------------------

STATE_HOME = 'home'                # 大众点评首页
STATE_SEARCH_SUGGEST = 'search_suggest'   # 搜索建议页
STATE_SEARCH_RESULT = 'search_result'     # 搜索结果页
STATE_SEARCH_LOADING = 'search_loading'   # 搜索结果加载中（"正在加载中"）
STATE_SEARCH_EMPTY = 'search_empty'       # 搜索结果为空
STATE_SHOP_DETAIL = 'shop_detail'         # 店铺详情页
STATE_REVIEW_PAGE = 'review_page'         # 评价详情页
STATE_MEITUAN_DIALOG = 'meituan_dialog'   # "即将打开美团小程序"
STATE_CAPTCHA = 'captcha'                 # 反爬验证码
STATE_LOGIN = 'login'                     # 登录页
STATE_CITY_PAGE = 'city_page'             # 选城市页面
STATE_UNKNOWN = 'unknown'


# ----------------------------------------------------------------------
# 状态识别
# ----------------------------------------------------------------------

def detect_state(wid: int, *, return_boxes: bool = False) -> Tuple[str, list]:
    """
    返回 (state, boxes)
    boxes 是 OCR 给的所有 box（含 text, x, y, w, h），
    供后续 find_xxx 使用避免重复 OCR。
    """
    img = screenshot_window(wid)
    if img is None:
        return STATE_UNKNOWN, []
    try:
        boxes = ocr_with_boxes(img)
    finally:
        try:
            img.unlink()
        except OSError:
            pass

    # 拼接所有 OCR 文字（去掉空格便于子串匹配）
    text_all = ''.join(b['text'] for b in sorted(boxes, key=lambda b: (b['y'], b['x'])))
    text_all_norm = re.sub(r'\s', '', text_all)
    
    # 分区域文字
    top_text = ''.join(b['text'] for b in boxes if b['y'] < 70)
    bottom_text = ''.join(b['text'] for b in boxes if b['y'] > 740)
    middle_text = ''.join(b['text'] for b in boxes if 100 < b['y'] < 700)

    # 反爬最优先识别（不能再操作）
    if any(kw in text_all for kw in ['身份核实', '请依次点击', '安全验证', '人机验证']):
        return STATE_CAPTCHA, boxes
    if '依次点击' in text_all_norm or '请按顺序' in text_all_norm:
        return STATE_CAPTCHA, boxes

    # 美团对话框
    if '美团' in text_all and ('打开' in text_all or '允许' in text_all):
        return STATE_MEITUAN_DIALOG, boxes

    # 登录页
    if any(kw in top_text for kw in ['扫码', '二维码']):
        return STATE_LOGIN, boxes

    # 城市选择页（顶部"选择城市"或包含一系列城市名）
    if '选择城市' in text_all_norm or ('选择' in top_text and '城市' in text_all_norm):
        return STATE_CITY_PAGE, boxes

    # 评价详情页：tab 栏（"全部 最新 差评 中评 带图视频"）
    review_tab_words = sum(1 for w in ['全部', '最新', '差评', '中评', '带图', '视频', '图文']
                            if w in text_all_norm)
    if review_tab_words >= 3:
        return STATE_REVIEW_PAGE, boxes

    # 店铺详情页：典型有"推荐菜"、"营业中"、"网友推荐"
    detail_words = sum(1 for w in ['推荐菜', '营业中', '网友推荐', '推荐', '菜单', '点评清单']
                       if w in text_all_norm)
    if detail_words >= 2:
        return STATE_SHOP_DETAIL, boxes
    # 详情页或评价模块（"评价(N) 查看全部"）
    if ('评价' in text_all_norm and '查看' in text_all_norm and
        any(re.search(r'\d', b['text']) for b in boxes if '评价' in b['text'] or
            (any(abs(b['y']-bb['y'])<15 for bb in boxes if '评价' in bb['text'])))):
        return STATE_SHOP_DETAIL, boxes

    # 首页特征（多重宽松判断）：
    # 1. 底部 tab 含 "找" 或 "优惠" 或 "榜"
    # 2. 中间含多个分类（"美食"+"玩乐"/"酒店"/"打车"）
    home_signals = 0
    if any(w in bottom_text for w in ['找', '优惠', '榜', '看榜', '我的']):
        home_signals += 2
    if '美食' in middle_text and ('玩乐' in middle_text or '酒店' in middle_text or '打车' in middle_text):
        home_signals += 2
    if any(w in top_text for w in ['市', '上海', '北京', '广州', '深圳', '杭州', '成都', '武汉', '南京']):
        home_signals += 1
    # 顶部有搜索图标 + 搜索按钮
    has_search_btn = any('搜索' in b['text'] and b['x'] > 250 and b['y'] < 120 for b in boxes)
    if has_search_btn:
        home_signals += 1
    if home_signals >= 3:
        return STATE_HOME, boxes

    # 搜索结果页 + 中间态：检测"商户/评价/笔记/外卖" tab（这是搜索结果页特有的）
    has_search_tabs = sum(1 for w in ['商户', '笔记', '外卖'] if w in text_all_norm) >= 2
    
    # 加载中：含"正在加载"
    if '正在加载' in text_all_norm or '加载中' in text_all_norm:
        return STATE_SEARCH_LOADING, boxes
    
    # 搜索为空：有"商户/笔记/外卖"tab + "暂无相关搜索结果"/"未找到"
    if has_search_tabs and any(kw in text_all_norm for kw in
                               ['暂无相关', '没有找到', '未找到', '没有相关', '抱歉']):
        return STATE_SEARCH_EMPTY, boxes

    # 搜索结果页：多个店铺卡片（每个有 ¥价格 + km 距离）
    # OCR 经常把 4.4 识别成 44，但 ¥ 和 km 比较稳定
    price_count = sum(1 for b in boxes
                      if ('¥' in b['text'] or '¥' in b['text'] or '￥' in b['text'])
                      and 100 < b['y'] < 750)
    distance_count = sum(1 for b in boxes
                         if (re.search(r'\d+\.?\d*\s*km', b['text']) or
                             re.search(r'\d+\s*m\b', b['text']) or
                             'km' in b['text'].lower())
                         and 100 < b['y'] < 750)
    score_count = sum(1 for b in boxes
                      if re.search(r'[1-5]\.\d', b['text']) and 100 < b['y'] < 700)
    # 任一条件成立: 价格 >= 2 + 距离 >= 2; 或 评分 >= 2 + 距离 >= 1; 或有商户tab + 距离 >= 1
    if (price_count >= 2 and distance_count >= 2) or \
       (score_count >= 2 and distance_count >= 1) or \
       (has_search_tabs and distance_count >= 1):
        return STATE_SEARCH_RESULT, boxes

    # 搜索建议页：右上"取消" + 中部建议列表
    has_cancel_topright = any('取消' in b['text'] and b['x'] > 300 and b['y'] < 80 for b in boxes)
    if has_cancel_topright:
        return STATE_SEARCH_SUGGEST, boxes
    
    return STATE_UNKNOWN, boxes


def state_label(state: str) -> str:
    """中文标签便于日志"""
    labels = {
        STATE_HOME: '首页',
        STATE_SEARCH_SUGGEST: '搜索建议',
        STATE_SEARCH_RESULT: '搜索结果',
        STATE_SEARCH_LOADING: '搜索加载中',
        STATE_SEARCH_EMPTY: '搜索为空',
        STATE_SHOP_DETAIL: '店铺详情',
        STATE_REVIEW_PAGE: '评价详情',
        STATE_MEITUAN_DIALOG: '美团弹窗',
        STATE_CAPTCHA: '反爬验证码',
        STATE_LOGIN: '登录页',
        STATE_CITY_PAGE: '城市选择',
        STATE_UNKNOWN: '未知',
    }
    return labels.get(state, state)


# ----------------------------------------------------------------------
# 元素定位（基于已 OCR 的 boxes）
# ----------------------------------------------------------------------

def find_search_input(boxes: list) -> Optional[Tuple[int, int]]:
    """
    首页搜索框位置：多重 fallback 策略。
    1. 找右侧"搜索"按钮 → 输入框在它左边
    2. 找左侧"Q"放大镜图标 → 输入框 = Q 右边
    3. 找 y < 100 区域的 placeholder（推荐店铺名）
    4. fallback 录制的 (71, 83)
    """
    # 1. "搜索"按钮（右侧）
    for b in boxes:
        if '搜索' in b['text'] and b['y'] < 120 and b['x'] > 250:
            return (75, b['y'] + b['h'] // 2)
    # 2. "Q"/搜索图标（左侧）
    for b in boxes:
        if (b['text'] in ('Q', 'q') or '搜' in b['text']) and b['y'] < 110 and b['x'] < 60:
            return (75, b['y'] + b['h'] // 2)
    # 3. 顶部 y=70-110 的 placeholder 文字（任意非空 box）
    placeholder_candidates = [
        b for b in boxes
        if 65 < b['y'] < 110 and b['x'] > 40 and b['x'] < 250
    ]
    if placeholder_candidates:
        first = sorted(placeholder_candidates, key=lambda b: (b['y'], b['x']))[0]
        return (75, first['y'] + first['h'] // 2)
    # 4. fallback 录制坐标
    return (71, 83)


def find_back_button(boxes: list) -> Tuple[int, int]:
    """左上角 < 返回按钮（OCR 通常识别不了 < 字符，固定坐标）"""
    return (20, 36)


def find_search_cancel(boxes: list) -> Optional[Tuple[int, int]]:
    """搜索建议页右上"取消"按钮"""
    for b in boxes:
        if '取消' in b['text'] and b['x'] > 300 and b['y'] < 80:
            return (b['x'] + b['w']//2, b['y'] + b['h']//2)
    return None


def find_first_shop_in_search_result(boxes: list, store_name: str = '') -> Optional[Tuple[int, int]]:
    """
    搜索结果页第一家店位置。
    搜索结果页布局（412x798 单栏）：
      y=0-50:   标题栏
      y=60-110:  搜索框
      y=120-160: tab 栏（商户/评价/笔记/外卖）
      y=165-200: 筛选栏（全城/全部分类/智能排序/筛选）
      y=220+:    第一家店铺卡片（图片+店名+评分+价格）
    
    策略：直接点 y=280, x=200（第一家店铺卡片中央，最稳定）
    """
    # 尝试 OCR 精确匹配店名
    if store_name:
        for b in sorted(boxes, key=lambda x: x['y']):
            if b['y'] < 200:  # 跳过 tab/筛选区域
                continue
            if store_name in b['text'] and b['y'] < 500:
                return (b['x'] + b['w']//2, b['y'] + b['h']//2)
        # 前缀匹配
        m = re.match(r'^([^\(（]+)', store_name)
        prefix = (m.group(1) if m else store_name).strip()
        if len(prefix) >= 3:
            for b in sorted(boxes, key=lambda x: x['y']):
                if b['y'] < 200:
                    continue
                if prefix in b['text'] and b['y'] < 500:
                    return (b['x'] + b['w']//2, b['y'] + b['h']//2)
    
    # fallback: 第一家店铺卡片中央（y=280 是最安全的位置）
    return (200, 290)


def find_first_in_search_suggest(boxes: list, store_name: str = '') -> Optional[Tuple[int, int]]:
    """
    搜索建议页找第一条建议。
    搜索建议页布局（412x798）：
      y=0-50:   标题栏
      y=60-100:  搜索框（含已输入文字）+ 右侧"取消"
      y=110-140: 第一条建议
      y=140-180: 第二条建议
      ...每条约 40-50px 高
    
    策略：直接点第一条建议 (200, 130)。
    因为搜索的是完整店名，第一条建议就是目标店。
    """
    # 尝试 OCR 精确匹配
    if store_name:
        prefix = store_name[:4]  # "达美乐比" 前 4 字
        for b in sorted(boxes, key=lambda x: x['y']):
            if b['y'] < 100:  # 跳过搜索框
                continue
            if b['y'] > 600:  # 太靠下不是建议
                break
            if prefix in b['text'] or store_name in b['text']:
                return (b['x'] + b['w']//2, b['y'] + b['h']//2)
    
    # fallback: 第一条建议固定位置
    return (200, 130)


def find_review_module_smart(boxes: list) -> Optional[Tuple[int, int]]:
    """
    详情页找"评价 (N) 查看全部 >" 的查看按钮位置。
    必须含"评价"+ 同行附近有数字 + 同行右侧有"查看全部"或">"。
    排除底部 tab "写评价"（y > 700）。
    """
    review_with_num = []
    for b in boxes:
        if '评价' not in b['text']:
            continue
        if b['y'] >= 700:
            continue
        if re.search(r'\d', b['text']):
            review_with_num.append(b)
            continue
        # 同行右边 200px 内找数字
        same_row_right = [bb for bb in boxes
                          if abs(bb['y'] - b['y']) < 15
                          and bb['x'] > b['x']
                          and bb['x'] < b['x'] + 200
                          and re.search(r'\d', bb['text'])]
        if same_row_right:
            review_with_num.append(b)
    
    if not review_with_num:
        return None
    
    review = sorted(review_with_num, key=lambda b: b['y'])[0]
    
    # 同行找"查看"/"全部"/">"
    same_row = [b for b in boxes
                if abs(b['y'] - review['y']) < 25
                and b['x'] > review['x']]
    keywords = ['查看全部', '查看', '全部', '》', '〉', '>']
    matches = [b for b in same_row
               if any(kw in b['text'] for kw in keywords)]
    
    if matches:
        # 取最右边的（》箭头通常在最右）
        target = max(matches, key=lambda b: b['x'] + b['w'])
        cx = target['x'] + target['w']//2
        cy = target['y'] + target['h']//2
        # 如果是"查看"两字，向右偏移到"全部 >"位置
        if '查看' in target['text'] and '>' not in target['text'] and '》' not in target['text']:
            cx += 30
        return (cx, cy)
    return None


def find_dialog_cancel(boxes: list) -> Optional[Tuple[int, int]]:
    """美团弹窗里的"取消"按钮"""
    for b in boxes:
        if '取消' in b['text'] and b['y'] > 200:  # 弹窗在页面中间，y > 200
            return (b['x'] + b['w']//2, b['y'] + b['h']//2)
    return None


def get_review_count_from_detail(boxes: list) -> Optional[int]:
    """详情页 OCR 评价模块 → 评论总数"""
    for b in boxes:
        if '评价' not in b['text']:
            continue
        if b['y'] >= 700:
            continue
        # 直接看 box 内有数字
        m = re.search(r'(\d+)', b['text'])
        if m:
            n = int(m.group(1))
            if 1 <= n <= 50000:
                return n
        # 同行右边找数字
        same_row = [bb for bb in boxes
                    if abs(bb['y'] - b['y']) < 15
                    and bb['x'] > b['x']
                    and bb['x'] < b['x'] + 200]
        for bb in same_row:
            m = re.search(r'(\d+)', bb['text'])
            if m:
                n = int(m.group(1))
                if 1 <= n <= 50000:
                    return n
    return None


# ----------------------------------------------------------------------
# 等待状态变化
# ----------------------------------------------------------------------

def wait_for_state(wid: int, target_states: List[str],
                   timeout: int = 15, poll: float = 1.0) -> Tuple[str, list]:
    """
    阻塞等到 detect_state 返回 target_states 之一，或超时。
    返回 (state, boxes)。
    """
    deadline = time.time() + timeout
    last_state = STATE_UNKNOWN
    last_boxes = []
    while time.time() < deadline:
        state, boxes = detect_state(wid)
        last_state = state
        last_boxes = boxes
        if state in target_states:
            return state, boxes
        time.sleep(poll)
    return last_state, last_boxes


# ----------------------------------------------------------------------
# CLI 调试
# ----------------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['state', 'find', 'monitor'])
    ap.add_argument('--target', help='find 子命令的目标元素')
    ap.add_argument('--win', help='窗口名', default='大众点评')
    args = ap.parse_args()
    
    out = subprocess.check_output(['xdotool', 'search', '--name', args.win], text=True).strip()
    if not out:
        print(f"❌ 找不到 '{args.win}' 窗口")
        sys.exit(1)
    wid = int(out.split('\n')[0])
    
    if args.cmd == 'state':
        state, boxes = detect_state(wid)
        print(f"当前状态: {state} ({state_label(state)})")
        print(f"OCR boxes: {len(boxes)}")
        # 显示关键 box
        for b in sorted(boxes, key=lambda x: x['y'])[:30]:
            print(f"  ({b['x']:3d},{b['y']:3d}) {b['w']:3d}x{b['h']:3d} '{b['text']}'")
    elif args.cmd == 'monitor':
        # 持续监控状态变化
        last = None
        while True:
            state, _ = detect_state(wid)
            if state != last:
                print(f"[{time.strftime('%H:%M:%S')}] {state} ({state_label(state)})")
                last = state
            time.sleep(1)
    elif args.cmd == 'find':
        state, boxes = detect_state(wid)
        print(f"状态: {state}")
        finders = {
            'search_input': find_search_input,
            'back': find_back_button,
            'cancel': find_search_cancel,
            'first_shop': find_first_shop_in_search_result,
            'review': find_review_module_smart,
            'dialog_cancel': find_dialog_cancel,
        }
        for name, fn in finders.items():
            try:
                pos = fn(boxes)
            except TypeError:
                pos = fn(boxes)
            print(f"  {name}: {pos}")
