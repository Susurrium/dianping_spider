# -*- coding: utf-8 -*-
"""
达美乐评论批量自动采集 v2
通过 xdotool 控制微信小程序，配合 dianping_interceptor.py 拦截数据。

使用方法：
1. 启动 mitmweb: mitmweb -s dianping_interceptor.py --listen-port 9092
2. 启动微信（带代理）
3. 打开大众点评小程序，停在搜索页面
4. 运行此脚本: python3 auto_batch.py
"""
import json
import os
import sys
import time
import subprocess
import re
from datetime import datetime
from pathlib import Path
import openpyxl

# ============ Configuration ============
EXCEL_PATH = '/home/hetaisheng/dianping_spider/达美乐_门店爬虫.xlsx'
LOG_DIR = '/home/hetaisheng/dianping_spider/mitm_logs'
PROGRESS_FILE = '/home/hetaisheng/dianping_spider/batch_progress.json'
OUTPUT_JSON = '/home/hetaisheng/dianping_spider/达美乐_评论结果.json'
CAPTURED_DIR = '/home/hetaisheng/dianping_spider/mitm_logs'

# City ID mapping for Dianping
CITY_IDS = {
    '上海': 1, '北京': 2, '广州': 7, '深圳': 74, '杭州': 5,
    '天津': 4, '南京': 6, '苏州': 12, '武汉': 16, '宁波': 389,
    '成都': 8, '厦门': 19, '西安': 13, '济南': 29, '无锡': 17,
    '福州': 21, '重庆': 9, '青岛': 26, '嘉兴': 390, '太原': 24,
    '长沙': 14, '郑州': 15, '合肥': 20, '昆明': 25, '贵阳': 30,
    '海口': 35, '兰州': 31, '石家庄': 23, '邯郸': 408,
    '襄阳': 427, '潍坊': 406, '徐州': 400, '南通': 401,
}

# ============ xdotool helpers ============

def run_xdotool(*args):
    """Run xdotool command"""
    try:
        result = subprocess.run(['xdotool'] + list(args), capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as e:
        return None

def find_wechat_window():
    """Find the main WeChat window"""
    wids = run_xdotool('search', '--name', '微信')
    if wids:
        for wid in wids.split('\n'):
            if wid.strip():
                geom = run_xdotool('getwindowgeometry', '--shell', wid.strip())
                if geom:
                    lines = dict(l.split('=') for l in geom.strip().split('\n') if '=' in l)
                    w = int(lines.get('WIDTH', 0))
                    h = int(lines.get('HEIGHT', 0))
                    if w > 500 and h > 500:  # Main window, not tiny helper
                        return wid.strip()
    return None

def focus_window(wid):
    """Bring window to front"""
    run_xdotool('windowactivate', '--sync', wid)
    run_xdotool('windowfocus', '--sync', wid)
    time.sleep(0.3)

def paste_text(text):
    """Copy text to clipboard and paste"""
    # Save current clipboard
    old_clip = subprocess.run(['xclip', '-selection', 'clipboard', '-o'], capture_output=True, text=True).stdout
    
    # Set new clipboard
    subprocess.run(['xclip', '-selection', 'clipboard'], input=text.encode(), check=True)
    time.sleep(0.1)
    
    # Paste
    run_xdotool('key', 'ctrl+v')
    time.sleep(0.2)
    
    # Restore old clipboard
    subprocess.run(['xclip', '-selection', 'clipboard'], input=old_clip.encode())

def clear_search():
    """Select all and delete text in search field"""
    run_xdotool('key', 'ctrl+a')
    time.sleep(0.1)
    run_xdotool('key', 'Delete')
    time.sleep(0.1)

def click_at(wid, x, y):
    """Click at position relative to window"""
    run_xdotool('mousemove', '--window', wid, str(x), str(y))
    time.sleep(0.1)
    run_xdotool('click', '--window', wid, '1')
    time.sleep(0.2)

def scroll_page(wid, times=1):
    """Scroll down using mouse wheel"""
    for _ in range(times):
        run_xdotool('key', 'Next')  # Page_Down
        time.sleep(0.8)

def go_back():
    """Press Escape or navigate back"""
    run_xdotool('key', 'Escape')
    time.sleep(0.5)

# ============ Data helpers ============

def load_stores():
    """Load stores from Excel"""
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active
    stores = []
    seen = set()
    for row in ws.iter_rows(min_row=3, max_row=ws.max_row, values_only=True):
        name = row[1]
        addr = row[2]
        if name and str(name).strip():
            n = str(name).strip()
            if n not in seen:
                seen.add(n)
                # Extract short name
                short = n.replace('达美乐比萨(', '').replace(')', '').strip()
                # Extract city
                city = None
                for c in sorted(CITY_IDS.keys(), key=len, reverse=True):
                    if c in str(addr) if addr else '':
                        city = c
                        break
                stores.append({
                    'name': n,
                    'address': str(addr).strip() if addr else '',
                    'short_name': short,
                    'city': city,
                })
    return stores

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'completed': [], 'failed': [], 'reviews_count': 0}

def save_progress(progress):
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

def count_captured_reviews():
    """Count total reviews captured by interceptor"""
    csv_file = os.path.join(LOG_DIR, 'all_reviews.csv')
    if not os.path.exists(csv_file):
        return 0
    with open(csv_file, 'r', encoding='utf-8') as f:
        return sum(1 for _ in f) - 1

def count_review_files():
    """Count review JSON files"""
    return len([f for f in os.listdir(LOG_DIR) if f.startswith('review_') and f.endswith('.json')])

def generate_final_json():
    """Generate final output JSON from all captured data"""
    all_reviews = []
    
    for fname in os.listdir(LOG_DIR):
        if not fname.startswith('review_') or not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(LOG_DIR, fname), 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            store_name = data.get('storeName', '')
            review_data = data.get('data', {})
            
            reviews = []
            for getter in [
                lambda d: d.get('data', {}).get('list', []) if isinstance(d.get('data'), dict) else [],
                lambda d: d.get('list', []),
                lambda d: d.get('shopReviewInfo', {}).get('reviewList', []),
            ]:
                reviews = getter(review_data)
                if reviews:
                    break
            
            for r in reviews:
                if not isinstance(r, dict):
                    continue
                fu = r.get('feedUser', {})
                text = r.get('text', '') or r.get('content', '')
                text = re.sub(r'<[^>]+>', '', str(text)).strip()
                if text:
                    all_reviews.append({
                        'storeName': store_name or r.get('shopPoiRelevant', {}).get('title', ''),
                        'publishTime': r.get('addTime', r.get('time', '')),
                        'publisher': fu.get('userName', '') if isinstance(fu, dict) else '',
                        'text': text,
                    })
        except:
            pass
    
    # Deduplicate
    seen = set()
    unique = []
    for r in all_reviews:
        key = f"{r['storeName']}|{r['publisher']}|{r['text'][:80]}"
        if key not in seen:
            seen.add(key)
            unique.append(r)
    
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    
    return unique

# ============ Main automation ============

def main():
    print("=" * 60)
    print("🍕 达美乐评论批量自动采集 v2")
    print("=" * 60)
    
    # Load data
    stores = load_stores()
    progress = load_progress()
    completed = set(progress['completed'])
    pending = [s for s in stores if s['name'] not in completed]
    
    print(f"\n📋 门店总数: {len(stores)}")
    print(f"✅ 已完成: {len(completed)}")
    print(f"📝 待采集: {len(pending)}")
    
    # Check interceptor is running
    csv_count = count_captured_reviews()
    print(f"📊 已捕获评论: {csv_count} 条")
    
    # Find WeChat window
    wid = find_wechat_window()
    if not wid:
        print("\n❌ 未找到微信窗口！")
        print("请确保微信已打开，然后重新运行此脚本。")
        return
    
    print(f"\n✅ 找到微信窗口: {wid}")
    
    if not pending:
        print("\n🎉 所有门店已处理完成！")
        reviews = generate_final_json()
        print(f"📊 最终结果: {len(reviews)} 条评论 → {OUTPUT_JSON}")
        return
    
    print("\n" + "=" * 60)
    print("⚠️  请先完成以下操作：")
    print("  1. 在微信中打开大众点评小程序")
    print("  2. 点进搜索页面（能看到搜索框）")
    print("  3. 确保 mitmproxy 正在运行")
    print("=" * 60)
    
    input("\n按回车键开始自动采集...")
    
    # Get window dimensions
    geom = run_xdotool('getwindowgeometry', '--shell', wid)
    if geom:
        lines = dict(l.split('=') for l in geom.strip().split('\n') if '=' in l)
        win_w = int(lines.get('WIDTH', 1550))
        win_h = int(lines.get('HEIGHT', 1350))
        win_x = int(lines.get('X', 0))
        win_y = int(lines.get('Y', 0))
    else:
        win_w, win_h, win_x, win_y = 1550, 1350, 385, 96
    
    print(f"\n📐 窗口: {win_w}x{win_h} at ({win_x},{win_y})")
    
    # Calculate positions (relative to window)
    # Search bar is typically at top center of mini program
    search_x = win_w // 2
    search_y = 80  # Approximate Y position of search bar
    
    # First search result is below the search bar
    result_x = win_w // 2
    result_y = 250  # Approximate Y position of first result
    
    batch_size = 0
    initial_reviews = count_captured_reviews()
    
    for i, store in enumerate(pending):
        name = store['name']
        short = store['short_name']
        city = store['city']
        
        print(f"\n{'─'*50}")
        print(f"[{i+1}/{len(pending)}] {name}")
        if city:
            print(f"  📍 {city}")
        
        before_files = count_review_files()
        
        try:
            # 1. Focus WeChat
            focus_window(wid)
            time.sleep(0.3)
            
            # 2. Click on search bar area
            click_at(wid, search_x, search_y)
            time.sleep(0.5)
            
            # 3. Clear existing text
            clear_search()
            time.sleep(0.2)
            
            # 4. Type search keyword
            search_text = f"达美乐 {short}"
            paste_text(search_text)
            time.sleep(0.3)
            
            # 5. Press Enter to search
            run_xdotool('key', 'Return')
            time.sleep(3)  # Wait for search results
            
            # 6. Click on first result
            click_at(wid, result_x, result_y)
            time.sleep(4)  # Wait for store page to load
            
            # 7. Scroll down to load reviews
            print(f"  📜 滚动加载评论...")
            scroll_page(wid, 15)
            
            # 8. Go back to search
            go_back()
            time.sleep(1)
            
            # Check results
            after_files = count_review_files()
            new_files = after_files - before_files
            total_reviews = count_captured_reviews()
            
            if new_files > 0:
                print(f"  ✅ 捕获 {new_files} 个新评论文件 | 总计: {total_reviews} 条")
            else:
                print(f"  ⚠️  无新评论捕获 | 总计: {total_reviews} 条")
            
            # Mark completed
            progress['completed'].append(name)
            save_progress(progress)
            
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            progress['failed'].append(name)
            save_progress(progress)
        
        # Delay between stores
        batch_size += 1
        if batch_size >= 5:
            print(f"\n  ⏸️  每5个门店休息10秒...")
            time.sleep(10)
            batch_size = 0
        else:
            time.sleep(3)
    
    # Generate final output
    print("\n" + "=" * 60)
    print("📊 采集完成，生成最终结果...")
    reviews = generate_final_json()
    
    total_captured = count_captured_reviews()
    print(f"\n{'='*60}")
    print(f"🎉 采集完成！")
    print(f"   已处理门店: {len(progress['completed'])}")
    print(f"   失败门店: {len(progress['failed'])}")
    print(f"   拦截器捕获评论: {total_captured} 条")
    print(f"   最终输出: {len(reviews)} 条 → {OUTPUT_JSON}")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
