# -*- coding:utf-8 -*-
"""
达美乐门店评论爬虫 - 基于大众点评移动端网页
每家门店可获取约5条评论（网页端限制）
"""
import requests
import re
import json
import time
import random
import openpyxl
from bs4 import BeautifulSoup

COOKIE = ""  # 需要填入你的cookie
UA_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
UA_PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def load_stores(excel_path):
    """从Excel加载门店列表"""
    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active
    stores = []
    for row in range(3, ws.max_row + 1):
        name = ws.cell(row, 2).value
        addr = ws.cell(row, 3).value
        if name:
            stores.append({'name': name.strip(), 'address': (addr or '').strip()})
    return stores


def search_shop(name, cookie):
    """在大众点评搜索店铺，返回shop_uuid"""
    headers = {
        'User-Agent': UA_PC,
        'Cookie': cookie,
        'Referer': 'http://www.dianping.com/',
    }
    # 从店名提取关键词搜索（去掉"达美乐比萨"前缀，用括号里的分店名）
    match = re.search(r'[（(](.+?)[）)]', name)
    keyword = match.group(1) if match else name
    
    # 搜索北京的达美乐
    search_url = f'http://www.dianping.com/search/keyword/2/0_达美乐_{keyword}/p1'
    try:
        r = requests.get(search_url, headers=headers, timeout=10)
        if r.status_code == 200 and '达美乐' in r.text:
            soup = BeautifulSoup(r.text, 'lxml')
            # 找到搜索结果中的店铺链接
            links = soup.find_all('a', href=True)
            for link in links:
                href = link.get('href', '')
                match_uuid = re.search(r'/shop/([a-zA-Z0-9]{14,20})', href)
                if match_uuid:
                    # 验证店名是否匹配
                    link_text = link.get_text(strip=True)
                    if keyword in link_text or name in link_text:
                        return match_uuid.group(1)
            # 如果精确匹配失败，返回第一个达美乐店铺
            for link in links:
                href = link.get('href', '')
                match_uuid = re.search(r'/shop/([a-zA-Z0-9]{14,20})', href)
                if match_uuid:
                    return match_uuid.group(1)
    except Exception as e:
        print(f"  搜索失败: {e}")
    return None


def get_reviews_mobile(shop_uuid, cookie):
    """从移动端网页获取评论（最多5条）"""
    headers = {
        'User-Agent': UA_MOBILE,
        'Cookie': cookie,
    }
    url = f'https://m.dianping.com/shop/{shop_uuid}/review_all'
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        
        soup = BeautifulSoup(r.text, 'lxml')
        reviews = []
        
        for item in soup.select('.review-item'):
            # 用户名
            username_el = item.select_one('.seed-user-name')
            username = username_el.text.strip() if username_el else '-'
            
            # 发布时间
            time_el = item.select_one('.seed-add-time')
            pub_time = time_el.text.strip() if time_el else '-'
            
            # 评论文字
            text_el = item.select_one('.seed-feed-content-txt')
            text = text_el.get_text(strip=True) if text_el else '-'
            
            if text and text != '-':
                reviews.append({
                    '发布时间': pub_time,
                    '发布人': username,
                    '文字': text,
                })
        
        return reviews
    except Exception as e:
        print(f"  获取评论失败: {e}")
        return []


def scrape_all(excel_path, cookie, output_path='reviews.json'):
    """主流程"""
    stores = load_stores(excel_path)
    print(f"共 {len(stores)} 家门店")
    
    all_results = []
    success_count = 0
    
    for i, store in enumerate(stores):
        print(f"\n[{i+1}/{len(stores)}] {store['name']}")
        
        # 搜索店铺UUID
        shop_uuid = search_shop(store['name'], cookie)
        if not shop_uuid:
            print(f"  ❌ 未找到店铺")
            all_results.append({
                '门店': store['name'],
                '地址': store['address'],
                '评论': [],
                'error': '未找到店铺'
            })
            continue
        
        print(f"  UUID: {shop_uuid}")
        
        # 获取评论
        reviews = get_reviews_mobile(shop_uuid, cookie)
        print(f"  获取到 {len(reviews)} 条评论")
        
        all_results.append({
            '门店': store['name'],
            '地址': store['address'],
            'shop_uuid': shop_uuid,
            '评论': reviews,
        })
        
        if reviews:
            success_count += 1
        
        # 随机延迟，避免被ban
        time.sleep(random.uniform(1, 3))
    
    # 保存结果
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*50}")
    print(f"完成！成功获取评论的门店: {success_count}/{len(stores)}")
    print(f"结果保存至: {output_path}")
    
    # 统计
    total_reviews = sum(len(r['评论']) for r in all_results)
    print(f"总评论数: {total_reviews}")
    print(f"\n⚠️ 注意: 大众点评网页端限制每店最多显示约5条评论")
    print(f"   如需获取更多评论，需要通过手机APP抓包获取API接口")


if __name__ == '__main__':
    import sys
    cookie = COOKIE
    if not cookie:
        print("请先设置cookie！")
        print("在脚本顶部的 COOKIE 变量中填入你的大众点评cookie")
        sys.exit(1)
    scrape_all('达美乐_门店爬虫.xlsx', cookie)
