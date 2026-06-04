# -*- coding:utf-8 -*-
"""
大众点评评论全自动抓取脚本
工作流程：
1. 先让 mitmproxy 捕获一次搜索 + 评论浏览的完整请求
2. 本脚本自动使用捕获的凭证抓取所有364家店铺的评论
"""
import json
import os
import re
import csv
import time
import random
import requests
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'mitm_logs')
CREDENTIALS_FILE = os.path.join(LOG_DIR, 'captured_credentials.json')
OUTPUT_FILE = os.path.join(BASE_DIR, 'all_reviews_final.json')
PROGRESS_FILE = os.path.join(LOG_DIR, 'scraper_progress.json')

PROXIES = {
    'http': 'http://127.0.0.1:7890',
    'https': 'http://127.0.0.1:7890',
}


def load_credentials():
    """加载捕获的凭证"""
    if not os.path.exists(CREDENTIALS_FILE):
        print("❌ 未找到凭证文件！请先在微信小程序中浏览一家店铺的评论")
        return None
    with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
        creds = json.load(f)
    print(f"✅ 凭证加载成功 (捕获于 {creds.get('timestamp', 'N/A')})")
    return creds


def build_session(creds):
    """构建请求会话"""
    session = requests.Session()
    headers = creds.get('headers', {})
    # 清理不需要的头部
    for key in ['host', ':method', ':path', ':authority', ':scheme', 'Host']:
        headers.pop(key, None)
    session.headers.update(headers)
    session.proxies = PROXIES
    return session


def load_stores():
    """从Excel加载店铺列表"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(os.path.join(BASE_DIR, '达美乐_门店爬虫.xlsx'))
        ws = wb.active
        stores = []
        for row in ws.iter_rows(min_row=3, values_only=True):
            name = row[1] if len(row) > 1 and row[1] else None
            addr = row[2] if len(row) > 2 and row[2] else None
            if name:
                stores.append({
                    'name': str(name).strip(),
                    'address': str(addr).strip() if addr else ''
                })
        return stores
    except Exception as e:
        print(f"❌ 读取Excel失败: {e}")
        return []


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'completed_uuid': {}, 'completed_review': [], 'results': {}}


def save_progress(progress):
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def search_shop_uuid(session, store_name, city_id=None):
    """搜索店铺获取shopUuid
    
    使用捕获的搜索API进行搜索，返回最匹配的shopUuid
    """
    # 尝试多种搜索API
    search_methods = [
        lambda: _search_via_mapi(session, store_name, city_id),
        lambda: _search_via_web(session, store_name),
    ]
    
    for method in search_methods:
        try:
            result = method()
            if result:
                return result
        except:
            pass
    return None


def _search_via_mapi(session, store_name, city_id=None):
    """通过MAPI搜索"""
    # 这是小程序常用的搜索API
    url = "https://mapi.dianping.com/mapi/shop/searchshop.bin"
    params = {
        'keyword': store_name,
        'cityId': str(city_id or 16),  # 默认武汉
        'page': '1',
    }
    resp = session.get(url, params=params, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        shops = data.get('data', {}).get('shopList', data.get('shopList', []))
        if shops and isinstance(shops, list):
            # 返回第一个匹配的
            return shops[0].get('shopId', shops[0].get('shopUuid', ''))
    return None


def _search_via_web(session, store_name):
    """通过网页搜索"""
    url = f"https://m.dianping.com/shoplist/1/search"
    params = {'keyword': store_name}
    resp = session.get(url, params=params, timeout=15)
    if resp.status_code == 200:
        # 从HTML中提取shopUuid
        uuids = re.findall(r'/shop/([A-Za-z0-9]{10,20})', resp.text)
        if uuids:
            return uuids[0]
    return None


def fetch_all_reviews(session, shop_uuid, max_pages=100):
    """抓取单个店铺的所有评论（分页）"""
    all_reviews = []
    start = 0
    
    base_url = "https://mapi.dianping.com/mapi/review/outsidesiftedreviewlist.bin"
    
    for page in range(max_pages):
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
                print(f"    ⚠️ 403 - 凭证可能已过期，请重新在微信中浏览一家店铺")
                break
            elif resp.status_code != 200:
                print(f"    ⚠️ HTTP {resp.status_code}")
                break
            
            data = resp.json()
            review_list = data.get('data', {}).get('list', [])
            if not review_list:
                break
            
            for r in review_list:
                if isinstance(r, dict):
                    feed_user = r.get('feedUser', {})
                    user_name = feed_user.get('userName', feed_user.get('nickName', '')) if isinstance(feed_user, dict) else ''
                    
                    text = r.get('text', '') or r.get('content', '') or r.get('reviewBody', '')
                    text = re.sub(r'<[^>]+>', '', str(text)).strip()
                    
                    all_reviews.append({
                        'reviewId': r.get('reviewId', r.get('mainId', '')),
                        'userName': user_name,
                        'text': text,
                        'addTime': r.get('addTime', r.get('time', '')),
                        'star': r.get('star', r.get('starRating', '')),
                    })
            
            start += len(review_list)
            
            if len(review_list) < 15:
                break
            
            time.sleep(2 + random.uniform(0.5, 1.5))
            
        except Exception as e:
            print(f"    ❌ 请求异常: {e}")
            break
    
    return all_reviews


def main():
    print("=" * 60)
    print("🔄 达美乐评论全自动抓取")
    print("=" * 60)
    
    creds = load_credentials()
    if not creds:
        return
    
    session = build_session(creds)
    stores = load_stores()
    if not stores:
        return
    print(f"📋 共 {len(stores)} 家店铺")
    
    progress = load_progress()
    completed_uuid = progress.get('completed_uuid', {})
    completed_review = progress.get('completed_review', [])
    results = progress.get('results', {})
    
    print(f"已完成UUID: {len(completed_uuid)}, 已完成评论: {len(completed_review)}")
    
    # 步骤1: 查找所有店铺UUID
    print("\n" + "=" * 60)
    print("📍 步骤1: 查找店铺UUID")
    print("=" * 60)
    
    uuid_file = os.path.join(LOG_DIR, 'shop_uuid_map.json')
    uuid_map = {}
    if os.path.exists(uuid_file):
        with open(uuid_file, 'r', encoding='utf-8') as f:
            uuid_map = json.load(f)
    
    need_search = [s for s in stores if s['name'] not in uuid_map and s['name'] not in completed_uuid]
    print(f"需搜索: {len(need_search)}家")
    
    for i, store in enumerate(need_search):
        name = store['name']
        print(f"[{i+1}/{len(need_search)}] 🔍 {name}")
        uuid = search_shop_uuid(session, name)
        if uuid:
            uuid_map[name] = uuid
            completed_uuid[name] = uuid
            print(f"  ✅ UUID: {uuid}")
            with open(uuid_file, 'w', encoding='utf-8') as f:
                json.dump(uuid_map, f, ensure_ascii=False, indent=2)
            progress['completed_uuid'] = completed_uuid
            save_progress(progress)
        else:
            print(f"  ❌ 未找到")
        time.sleep(1.5 + random.uniform(0.5, 1.0))
    
    # 步骤2: 批量抓取评论
    print("\n" + "=" * 60)
    print("📝 步骤2: 批量抓取评论")
    print("=" * 60)
    
    total_reviews = 0
    skipped = 0
    failed = 0
    
    for i, store in enumerate(stores):
        name = store['name']
        uuid = uuid_map.get(name) or completed_uuid.get(name)
        
        if not uuid:
            skipped += 1
            continue
        
        if name in completed_review:
            count = len(results.get(name, []))
            total_reviews += count
            continue
        
        print(f"\n[{i+1}/{len(stores)}] 📝 {name} ({uuid})")
        
        reviews = fetch_all_reviews(session, uuid)
        if reviews:
            results[name] = reviews
            completed_review.append(name)
            total_reviews += len(reviews)
            print(f"  ✅ {len(reviews)}条评论")
        else:
            print(f"  ⚠️ 无评论")
            completed_review.append(name)
            failed += 1
        
        progress['completed_review'] = completed_review
        progress['results'] = results
        save_progress(progress)
        
        # 检查是否需要重新获取凭证
        if failed >= 3:
            print("\n⚠️ 连续失败3次，凭证可能已过期")
            print("请在微信小程序中重新浏览一家店铺的评论，然后重新运行本脚本")
            break
        
        time.sleep(3 + random.uniform(1.0, 3.0))
    
    # 输出最终JSON
    print("\n" + "=" * 60)
    print(f"🎉 完成!")
    print(f"  店铺: {len(completed_review)}/{len(stores)}")
    print(f"  评论: {total_reviews}条")
    print(f"  跳过: {skipped}家 (无UUID)")
    print(f"  失败: {failed}家")
    print("=" * 60)
    
    output = []
    for store_name, reviews in results.items():
        for r in reviews:
            output.append({
                'storeName': store_name,
                'publishTime': r.get('addTime', ''),
                'publisher': r.get('userName', ''),
                'text': r.get('text', ''),
            })
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 结果已保存: {OUTPUT_FILE}")
    print(f"   共 {len(output)} 条记录")


if __name__ == '__main__':
    main()
