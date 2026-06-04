# -*- coding:utf-8 -*-
"""
批量评论抓取脚本 - 使用mitmproxy捕获的凭证replay请求
工作流程：
1. 用户在微信小程序中浏览1家店铺的评论 → mitmproxy自动捕获凭证
2. 运行本脚本 → 用捕获的凭证自动抓取全部364家店铺的评论
"""
import json
import os
import time
import random
import requests
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mitm_logs')
CREDENTIALS_FILE = os.path.join(LOG_DIR, 'captured_credentials.json')
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'all_reviews_final.json')
PROGRESS_FILE = os.path.join(LOG_DIR, 'replay_progress.json')

# Clash代理
PROXIES = {
    'http': 'http://127.0.0.1:7890',
    'https': 'http://127.0.0.1:7890',
}


def load_credentials():
    """加载捕获的请求凭证"""
    if not os.path.exists(CREDENTIALS_FILE):
        print("❌ 未找到捕获的凭证文件！")
        print("请先在微信小程序中浏览一家店铺的评论，让mitmproxy捕获请求")
        return None
    with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
        creds = json.load(f)
    print(f"✅ 已加载凭证 (捕获于 {creds.get('timestamp', 'unknown')})")
    print(f"   URL: {creds.get('url_pattern', 'unknown')}")
    return creds


def build_session(creds):
    """构建requests会话，使用捕获的headers"""
    session = requests.Session()
    
    headers = creds.get('headers', {})
    # 移除一些不需要的头
    for key in ['host', ':method', ':path', ':authority', ':scheme']:
        headers.pop(key, None)
        headers.pop(key.title(), None)
    
    session.headers.update(headers)
    session.proxies = PROXIES
    return session


def search_shop_uuid(session, shop_name, city_id=16):
    """通过大众点评搜索API查找店铺UUID"""
    # 方法1: 使用m.dianping.com搜索页面的JSON API
    search_url = "https://m.dianping.com/searchshop/1"
    params = {
        'keyword': shop_name,
        'cityId': city_id,
        'from': 'm',
    }
    try:
        resp = session.get(search_url, params=params, timeout=15)
        if resp.status_code == 200:
            text = resp.text
            # 尝试从HTML中提取shopId/UUID
            import re
            # 查找类似 /shop/G7GQQl9QkeAbbSoZ 的模式
            uuids = re.findall(r'/shop/([A-Za-z0-9]+)', text)
            if uuids:
                return uuids[0]
            
            # 尝试JSON
            try:
                data = resp.json()
                if 'shopList' in str(data):
                    shops = data.get('shopList', data.get('data', {}).get('shopList', []))
                    if isinstance(shops, list) and shops:
                        return shops[0].get('shopId', shops[0].get('shopUuid', ''))
            except:
                pass
    except Exception as e:
        print(f"  搜索失败: {e}")
    
    # 方法2: 尝试大众点评mobile API搜索
    try:
        api_url = "https://m.dianping.com/searchshop/search"
        params2 = {
            'keyword': shop_name,
            'cityId': city_id,
            'page': 1,
        }
        resp2 = session.get(api_url, params=params2, timeout=15)
        if resp2.status_code == 200:
            try:
                data2 = resp2.json()
                shops = data2.get('result', {}).get('shopList', [])
                if isinstance(shops, list) and shops:
                    return shops[0].get('shopId', shops[0].get('shopUuid', ''))
            except:
                pass
    except:
        pass
    
    return None


def fetch_reviews(session, shop_uuid, max_pages=50, delay=2.0):
    """抓取单个店铺的所有评论"""
    all_reviews = []
    start = 0
    page = 0
    
    base_url = "https://mapi.dianping.com/mapi/review/outsidesiftedreviewlist.bin"
    
    while page < max_pages:
        params = {
            'optimus_code': '10',
            'optimus_partner': '76',
            'optimus_risk_level': '71',
            'reqsource': '1',
            'filterid': '800',
            'merge': '1',
            'needfilter': '1',
            'referid': shop_uuid,
            'refertype': '0',
            'start': str(start),
            'yodaReady': 'h5',
            'csecplatform': '4',
            'csecversion': '4.2.0',
        }
        
        try:
            resp = session.get(base_url, params=params, timeout=15)
            
            if resp.status_code == 403:
                print(f"  ⚠️ 403 Forbidden - 凭证可能已过期")
                break
            elif resp.status_code != 200:
                print(f"  ⚠️ HTTP {resp.status_code}")
                break
            
            data = resp.json()
            
            # 提取评论列表
            review_list = data.get('data', {}).get('list', [])
            if not review_list:
                review_list = data.get('list', [])
            if not review_list:
                print(f"  📄 第{page+1}页: 无更多评论")
                break
            
            # 提取店铺名
            if not all_reviews and review_list:
                poi = review_list[0].get('shopPoiRelevant', {})
                store_name = poi.get('title', '') if isinstance(poi, dict) else ''
            
            for r in review_list:
                if isinstance(r, dict):
                    feed_user = r.get('feedUser', {})
                    user_name = ''
                    if isinstance(feed_user, dict):
                        user_name = feed_user.get('userName', feed_user.get('nickName', ''))
                    
                    text = r.get('text', '') or r.get('content', '') or r.get('reviewBody', '')
                    import re
                    text = re.sub(r'<[^>]+>', '', str(text)).strip()
                    
                    all_reviews.append({
                        'reviewId': r.get('reviewId', r.get('mainId', '')),
                        'userName': user_name,
                        'text': text,
                        'addTime': r.get('addTime', r.get('time', '')),
                        'star': r.get('star', r.get('starRating', '')),
                    })
            
            page += 1
            start += len(review_list)
            print(f"  📄 第{page}页: {len(review_list)}条评论 (累计{len(all_reviews)})")
            
            # 如果返回数量不足一页（通常每页20条），说明没有更多了
            if len(review_list) < 15:
                break
            
            # 随机延迟
            time.sleep(delay + random.uniform(0.5, 1.5))
            
        except requests.exceptions.RequestException as e:
            print(f"  ❌ 请求失败: {e}")
            break
        except json.JSONDecodeError:
            print(f"  ❌ JSON解析失败")
            break
    
    return all_reviews


def load_progress():
    """加载进度"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'completed': [], 'results': {}}


def save_progress(progress):
    """保存进度"""
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def load_store_list():
    """从Excel加载店铺列表"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(os.path.join(os.path.dirname(os.path.abspath(__file__)), '达美乐_门店爬虫.xlsx'))
        ws = wb.active
        stores = []
        for row in ws.iter_rows(min_row=3, values_only=True):
            name = row[1] if len(row) > 1 and row[1] else None
            addr = row[2] if len(row) > 2 and row[2] else None
            if name:
                stores.append({'name': str(name).strip(), 'address': str(addr).strip() if addr else ''})
        return stores
    except Exception as e:
        print(f"❌ 读取Excel失败: {e}")
        return []


def main():
    print("=" * 60)
    print("🔄 大众点评评论批量抓取工具")
    print("=" * 60)
    
    # 加载凭证
    creds = load_credentials()
    if not creds:
        return
    
    # 构建会话
    session = build_session(creds)
    
    # 加载店铺列表
    stores = load_store_list()
    if not stores:
        print("❌ 无店铺数据")
        return
    print(f"📋 共{len(stores)}家店铺待处理")
    
    # 加载已有进度
    progress = load_progress()
    completed = progress.get('completed', [])
    results = progress.get('results', {})
    print(f"✅ 已完成: {len(completed)}家")
    
    # 步骤1: 先通过搜索找到所有店铺的UUID
    print("\n" + "=" * 60)
    print("📍 步骤1: 查找店铺UUID")
    print("=" * 60)
    
    uuid_file = os.path.join(LOG_DIR, 'shop_uuid_map.json')
    uuid_map = {}
    if os.path.exists(uuid_file):
        with open(uuid_file, 'r', encoding='utf-8') as f:
            uuid_map = json.load(f)
    
    need_search = [s for s in stores if s['name'] not in uuid_map]
    print(f"需要搜索: {len(need_search)}家 (已有{len(uuid_map)}家)")
    
    for i, store in enumerate(need_search):
        name = store['name']
        print(f"\n[{i+1}/{len(need_search)}] 搜索: {name}")
        uuid = search_shop_uuid(session, name)
        if uuid:
            uuid_map[name] = uuid
            print(f"  ✅ UUID: {uuid}")
            # 保存进度
            with open(uuid_file, 'w', encoding='utf-8') as f:
                json.dump(uuid_map, f, ensure_ascii=False, indent=2)
        else:
            print(f"  ❌ 未找到")
        time.sleep(1.5 + random.uniform(0.5, 1.0))
    
    # 步骤2: 批量抓取评论
    print("\n" + "=" * 60)
    print("📝 步骤2: 批量抓取评论")
    print("=" * 60)
    
    total_reviews = 0
    for i, store in enumerate(stores):
        name = store['name']
        uuid = uuid_map.get(name)
        
        if not uuid:
            print(f"\n[{i+1}/{len(stores)}] ⏭️ {name} - 无UUID，跳过")
            continue
        
        if name in completed:
            count = len(results.get(name, []))
            total_reviews += count
            print(f"\n[{i+1}/{len(stores)}] ⏭️ {name} - 已完成({count}条)")
            continue
        
        print(f"\n[{i+1}/{len(stores)}] 🔄 {name} (UUID: {uuid})")
        
        reviews = fetch_reviews(session, uuid)
        if reviews:
            results[name] = reviews
            completed.append(name)
            total_reviews += len(reviews)
            print(f"  ✅ 获取{len(reviews)}条评论")
        else:
            print(f"  ⚠️ 未获取到评论")
            completed.append(name)  # 标记为已处理（避免重试）
        
        # 保存进度
        progress['completed'] = completed
        progress['results'] = results
        save_progress(progress)
        
        # 随机延迟，避免封IP
        time.sleep(3 + random.uniform(1.0, 3.0))
    
    # 输出最终结果
    print("\n" + "=" * 60)
    print(f"🎉 完成! 共{len(completed)}家店铺, {total_reviews}条评论")
    print("=" * 60)
    
    # 保存为最终JSON
    output = []
    for store_name, reviews in results.items():
        store_entry = next((s for s in stores if s['name'] == store_name), {'name': store_name, 'address': ''})
        for r in reviews:
            output.append({
                'storeName': store_name,
                'publishTime': r.get('addTime', ''),
                'publisher': r.get('userName', ''),
                'text': r.get('text', ''),
            })
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"💾 结果已保存: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
