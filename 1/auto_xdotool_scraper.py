# -*- coding: utf-8 -*-
"""
Automated batch review scraper using xdotool to control WeChat mini program.
Works with dianping_interceptor.py (mitmproxy) to capture review data.

Workflow:
1. User opens Dianping mini program in WeChat
2. User navigates to search page (搜索页面)
3. Script automates: type store name → wait → scroll reviews
4. Interceptor captures all API data
5. After all stores processed, generate final JSON

Deprecated: this experimental script used desktop/browser shortcuts such as
Ctrl+F and is not the main automation path.  Use miniapp_state_machine.py, which
waits for mitmproxy API events before marking a city/search/detail/review step
successful.
"""
import json
import os
import time
import subprocess
import re
import argparse
from collections import defaultdict
from pathlib import Path
from city_utils import city_from_address
from review_exporter import export_reviews, load_stores_from_xlsx

# ============ Configuration ============
EXCEL_PATH = '/home/hetaisheng/dianping_spider/达美乐_门店爬虫.xlsx'
LOG_DIR = '/home/hetaisheng/dianping_spider/mitm_logs'
PROGRESS_FILE = '/home/hetaisheng/dianping_spider/xauto_progress.json'
OUTPUT_JSON = '/home/hetaisheng/dianping_spider/达美乐_评论结果.json'
SHOP_UUID_FILE = os.path.join(LOG_DIR, 'all_shop_uuids.json')

# Timing
SEARCH_WAIT = 3      # seconds to wait after search
CLICK_WAIT = 4       # seconds to wait after clicking store
SCROLL_WAIT = 1.5    # seconds between scrolls
SCROLL_COUNT = 15    # number of scrolls per store page
STORE_DELAY = 5      # seconds between stores

# Coordinates are based on the PC WeChat mini-program viewport in the user's
# screenshot (about 402x792). Override from the CLI if your window differs.
DEFAULT_CITY_BUTTON = (54, 38)
DEFAULT_CITY_SEARCH = (168, 89)
DEFAULT_CITY_FIRST_RESULT = (42, 176)

# ============ Helper Functions ============

def get_wechat_window_id():
    """Find the WeChat window ID"""
    try:
        result = subprocess.run(
            ['xdotool', 'search', '--name', '微信'],
            capture_output=True, text=True, timeout=5
        )
        wids = result.stdout.strip().split('\n')
        if wids and wids[0]:
            return wids[0]
    except:
        pass
    
    # Try alternative names
    for name in ['WeChat', 'wechat', 'WeChatAppEx']:
        try:
            result = subprocess.run(
                ['xdotool', 'search', '--name', name],
                capture_output=True, text=True, timeout=5
            )
            wids = result.stdout.strip().split('\n')
            if wids and wids[0]:
                return wids[0]
        except:
            pass
    
    # Try by class
    try:
        result = subprocess.run(
            ['xdotool', 'search', '--class', 'wechat'],
            capture_output=True, text=True, timeout=5
        )
        wids = result.stdout.strip().split('\n')
        if wids and wids[0]:
            return wids[0]
    except:
        pass
    
    return None


def focus_wechat(wid):
    """Focus the WeChat window"""
    subprocess.run(['xdotool', 'windowactivate', wid], timeout=5)
    subprocess.run(['xdotool', 'windowfocus', wid], timeout=5)
    time.sleep(0.5)


def clear_input():
    """Clear current input field"""
    subprocess.run(['xdotool', 'key', 'ctrl+a'], timeout=5)
    time.sleep(0.1)
    subprocess.run(['xdotool', 'key', 'BackSpace'], timeout=5)
    time.sleep(0.2)


def type_text(text):
    """Type text using xdotool"""
    # Use xclip for Chinese text (xdotool type doesn't handle Chinese well)
    try:
        proc = subprocess.run(['xclip', '-selection', 'clipboard'], input=text.encode(), timeout=5)
        subprocess.run(['xdotool', 'key', 'ctrl+v'], timeout=5)
        time.sleep(0.3)
    except FileNotFoundError:
        # Fallback: use xdotool type (might not work for Chinese)
        subprocess.run(['xdotool', 'type', '--clearmodifiers', text], timeout=10)


def press_key(key):
    """Press a key"""
    subprocess.run(['xdotool', 'key', key], timeout=5)


def scroll_down(count=1, wait=0.5):
    """Scroll down in the window"""
    for _ in range(count):
        subprocess.run(['xdotool', 'key', 'Page_Down'], timeout=5)
        time.sleep(wait)


def click_at(x, y):
    """Click at specific coordinates"""
    subprocess.run(['xdotool', 'mousemove', str(x), str(y)], timeout=5)
    time.sleep(0.1)
    subprocess.run(['xdotool', 'click', '1'], timeout=5)


def parse_xy(value):
    x, y = value.split(',', 1)
    return int(x), int(y)


def load_stores():
    """Load store list from Excel"""
    stores = []
    seen = set()
    for store in load_stores_from_xlsx(Path(EXCEL_PATH)):
        if store.name in seen:
            continue
        seen.add(store.name)
        stores.append({
            'name': store.name,
            'address': store.address,
            'short_name': store.name.replace('达美乐比萨(', '').replace(')', '').strip(),
        })
    return stores


def load_progress():
    """Load progress from file"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'completed': [], 'failed': [], 'shop_uuids': {}}


def save_progress(progress):
    """Save progress to file"""
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def load_shop_uuids():
    """Load known shop UUIDs"""
    if os.path.exists(SHOP_UUID_FILE):
        with open(SHOP_UUID_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def count_new_reviews(before_files):
    """Count new review files since before_files"""
    after_files = set(f for f in os.listdir(LOG_DIR) if f.startswith('review_'))
    new_files = after_files - before_files
    return len(new_files)


def get_review_count_from_csv():
    """Get total review count from CSV"""
    csv_file = os.path.join(LOG_DIR, 'all_reviews.csv')
    if not os.path.exists(csv_file):
        return 0
    with open(csv_file, 'r', encoding='utf-8') as f:
        return sum(1 for _ in f) - 1  # subtract header


def export_current_reviews():
    """Export only xlsx-scoped reviews and return export stats."""
    return export_reviews(Path(EXCEL_PATH), Path(LOG_DIR), Path('/home/hetaisheng/dianping_spider/output/domino_reviews.json'))


def address_without_city(address, city):
    address = address or ''
    if city and address.startswith(city + '市'):
        return address[len(city) + 1:]
    if city and address.startswith(city):
        return address[len(city):]
    return re.sub(r'^[\u4e00-\u9fff]{2,6}市?', '', address, count=1)


def set_city(wid, city, city_button, city_search, city_first_result):
    """Switch Dianping mini-program city before searching stores."""
    print(f"\n🌍 切换城市: {city}")
    focus_wechat(wid)
    click_at(*city_button)
    time.sleep(1.0)
    click_at(*city_search)
    clear_input()
    type_text(city)
    time.sleep(0.8)
    press_key('Return')
    time.sleep(1.2)
    click_at(*city_first_result)
    time.sleep(2.0)
    print("  城市切换步骤已执行；如果界面未切换，请用 --city-*-xy 调整坐标。")


# ============ Main Automation ============

def search_and_browse_store(wid, store_name, short_name, address='', city=''):
    """
    Search for a store in the mini program and browse its reviews.
    Returns True if successful.
    """
    print(f"\n  🔍 Searching: {short_name}")
    
    # Focus WeChat
    focus_wechat(wid)
    time.sleep(0.5)
    
    # Click on search bar (top area of the mini program window)
    # The search bar is typically at the top of the mini program
    # We'll use keyboard shortcut to focus search
    press_key('ctrl+f')  # Try Ctrl+F for search
    time.sleep(0.5)
    
    # Clear any existing text
    clear_input()
    time.sleep(0.2)
    
    # Include an address hint to reduce same-name branch mismatches.
    address_hint = address_without_city(address, city)[:12]
    search_text = f"{store_name} {address_hint}".strip()
    type_text(search_text)
    time.sleep(0.3)
    
    # Press Enter to search
    press_key('Return')
    time.sleep(SEARCH_WAIT)
    
    return True


def browse_reviews(wid, scroll_count=SCROLL_COUNT):
    """Scroll down to load reviews"""
    focus_wechat(wid)
    time.sleep(0.5)
    
    for i in range(scroll_count):
        scroll_down(1, SCROLL_WAIT)
    
    return True


def generate_final_json():
    """Generate final JSON from all captured review data"""
    all_reviews = []
    
    # Load all review JSON files
    for fname in os.listdir(LOG_DIR):
        if not fname.startswith('review_') or not fname.endswith('.json'):
            continue
        fpath = os.path.join(LOG_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            store_name = data.get('storeName', '')
            review_data = data.get('data', {})
            
            # Extract reviews from various data structures
            reviews = []
            for path in [
                lambda d: d.get('data', {}).get('list', []) if isinstance(d.get('data'), dict) else [],
                lambda d: d.get('list', []),
                lambda d: d.get('shopReviewInfo', {}).get('reviewList', []),
            ]:
                reviews = path(review_data)
                if reviews:
                    break
            
            for r in reviews:
                if not isinstance(r, dict):
                    continue
                fu = r.get('feedUser', {})
                publisher = fu.get('userName', '') if isinstance(fu, dict) else ''
                text = r.get('text', '') or r.get('content', '')
                text = re.sub(r'<[^>]+>', '', str(text)).strip()
                if not text:
                    continue
                
                all_reviews.append({
                    'storeName': store_name or r.get('shopPoiRelevant', {}).get('title', ''),
                    'publishTime': r.get('addTime', r.get('time', '')),
                    'publisher': publisher,
                    'text': text,
                })
        except Exception as e:
            print(f"  Error processing {fname}: {e}")
    
    # Deduplicate by reviewId
    seen = set()
    unique_reviews = []
    for r in all_reviews:
        key = f"{r['storeName']}_{r['publisher']}_{r['text'][:50]}"
        if key not in seen:
            seen.add(key)
            unique_reviews.append(r)
    
    # Save
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(unique_reviews, f, ensure_ascii=False, indent=2)
    
    print(f"\n📊 Generated {OUTPUT_JSON}")
    print(f"   Total reviews: {len(unique_reviews)}")
    stores = set(r['storeName'] for r in unique_reviews)
    print(f"   Stores: {len(stores)}")
    
    return unique_reviews


def main():
    parser = argparse.ArgumentParser(description="用 xdotool 驱动 PC 微信小程序，真实触发大众点评评论请求")
    parser.add_argument("--limit", type=int, default=0, help="只处理前N家待处理门店，便于试跑")
    parser.add_argument("--start-index", type=int, default=0, help="从待处理列表的第几个开始")
    parser.add_argument("--scroll-count", type=int, default=SCROLL_COUNT)
    parser.add_argument("--no-prompt", action="store_true", help="不等待回车确认")
    parser.add_argument("--set-city", default="", help="开始前切换小程序城市，例如 上海")
    parser.add_argument("--group-by-city", action="store_true", default=True, help="按xlsx地址城市分组，逐城切换后采集")
    parser.add_argument("--no-group-by-city", dest="group_by_city", action="store_false", help="不按城市分组，只按xlsx顺序处理")
    parser.add_argument("--city-button-xy", type=parse_xy, default=DEFAULT_CITY_BUTTON, help="左上角城市按钮坐标 x,y")
    parser.add_argument("--city-search-xy", type=parse_xy, default=DEFAULT_CITY_SEARCH, help="搜索地址输入框坐标 x,y")
    parser.add_argument("--city-first-result-xy", type=parse_xy, default=DEFAULT_CITY_FIRST_RESULT, help="城市搜索结果坐标 x,y")
    args = parser.parse_args()

    print("=" * 60)
    print("🎯 达美乐评论批量采集 (xdotool自动版)")
    print("=" * 60)
    
    # Load stores
    stores = load_stores()
    print(f"\n📋 总门店数: {len(stores)}")
    
    # Load progress
    progress = load_progress()
    completed = set(progress['completed'])
    print(f"✅ 已完成: {len(completed)}")
    
    # Load known shop UUIDs
    shop_uuids = load_shop_uuids()
    print(f"🔑 已知UUID: {len(shop_uuids)}")
    
    # Find WeChat window
    print("\n🔍 查找微信窗口...")
    wid = get_wechat_window_id()
    if not wid:
        print("❌ 未找到微信窗口！请确保微信已打开。")
        print("   请打开微信 → 进入大众点评小程序 → 进入搜索页面")
        print("   然后重新运行此脚本。")
        return
    
    print(f"✅ 找到微信窗口: {wid}")

    if args.set_city:
        set_city(
            wid=wid,
            city=args.set_city,
            city_button=args.city_button_xy,
            city_search=args.city_search_xy,
            city_first_result=args.city_first_result_xy,
        )
    
    # Filter pending stores
    pending = [s for s in stores if s['name'] not in completed]
    if args.start_index:
        pending = pending[args.start_index:]
    if args.limit:
        pending = pending[:args.limit]
    print(f"\n📝 待处理: {len(pending)}")
    
    if not pending:
        print("🎉 所有门店已处理完成！")
        generate_final_json()
        return
    
    # Get initial review count
    initial_count = get_review_count_from_csv()
    
    print("\n" + "=" * 60)
    print("⚠️  请确保：")
    print("  1. 微信已打开")
    print("  2. 已进入大众点评小程序")
    print("  3. 已进入搜索页面")
    print("  4. mitmproxy正在运行（拦截脚本已加载）")
    print("=" * 60)
    if not args.no_prompt:
        input("\n按回车键开始自动采集...")
    
    if args.group_by_city:
        grouped = defaultdict(list)
        for store in pending:
            grouped[city_from_address(store.get('address', ''))].append(store)
        batches = [(city, items) for city, items in grouped.items()]
    else:
        batches = [(args.set_city or '', pending)]

    total_pending = sum(len(items) for _, items in batches)
    processed = 0

    # Process each city, then each store in that city.
    for city, city_stores in batches:
        if city and city != args.set_city:
            set_city(
                wid=wid,
                city=city,
                city_button=args.city_button_xy,
                city_search=args.city_search_xy,
                city_first_result=args.city_first_result_xy,
            )

        print(f"\n🏙️ 当前城市: {city or '不切换'} | 门店数: {len(city_stores)}")

        for store in city_stores:
            processed += 1
            store_name = store['name']
            short_name = store['short_name']

            print(f"\n{'='*50}")
            print(f"[{processed}/{total_pending}] {city} {store_name}")

            before_files = set(f for f in os.listdir(LOG_DIR) if f.startswith('review_'))

            # Search and browse
            try:
                search_and_browse_store(wid, store_name, short_name, store.get('address', ''), city)
                browse_reviews(wid, scroll_count=args.scroll_count)
            except Exception as e:
                print(f"  ❌ Error: {e}")
                progress['failed'].append(store_name)
                save_progress(progress)
                continue

            # Check for new reviews
            new_reviews = count_new_reviews(before_files)
            total_reviews = get_review_count_from_csv()

            export_stats = export_current_reviews()
            print(f"  📊 新增响应文件: {new_reviews} | CSV总计: {total_reviews} | xlsx导出评论: {export_stats['reviews_exported']}")

            # Mark as completed
            progress['completed'].append(store_name)
            save_progress(progress)

            # Delay between stores
            if processed < total_pending:
                time.sleep(STORE_DELAY)
    
    # Generate final output
    print("\n" + "=" * 60)
    print("📊 采集完成，生成最终结果...")
    stats = export_current_reviews()
    
    print(f"\n✅ 完成！")
    print(f"   处理门店: {len(progress['completed'])}")
    print(f"   失败门店: {len(progress['failed'])}")
    print(f"   xlsx导出评论: {stats['reviews_exported']}")


if __name__ == '__main__':
    main()
