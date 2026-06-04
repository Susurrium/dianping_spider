# -*- coding:utf-8 -*-
"""
半自动批量采集大众点评评论
用户只需在小程序中搜索店铺，脚本自动捕获数据
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

# 配置
LOG_DIR = Path(__file__).parent / 'mitm_logs'
OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

SHOP_UUID_MAP_FILE = LOG_DIR / 'shop_uuid_map.json'


def load_shop_uuid_map():
    """加载店铺UUID映射"""
    if SHOP_UUID_MAP_FILE.exists():
        with open(SHOP_UUID_MAP_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_shop_uuid_map(mapping):
    """保存店铺UUID映射"""
    with open(SHOP_UUID_MAP_FILE, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def load_stores_from_excel(excel_path):
    """从Excel加载店铺列表"""
    import openpyxl
    wb = openpyxl.load_workbook(excel_path)
    ws = wb.active

    stores = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        if row[1] and row[2]:  # 店铺名和地址都不为空
            stores.append({'name': row[1], 'address': row[2]})

    return stores


def extract_reviews(data):
    """从API响应中提取评论"""
    reviews = []

    # 模式1: shopReviewInfo
    review_list = data.get('shopReviewInfo', {}).get('reviewList', [])
    if review_list:
        for r in review_list:
            reviews.append({
                'reviewId': r.get('reviewId', r.get('mainId', '')),
                'userName': r.get('userName', r.get('userNickName', '')),
                'text': extract_text(r),
                'addTime': r.get('addTime', r.get('addTimeStr', r.get('time', ''))),
                'star': r.get('star', 0),
            })
        return reviews

    # 模式2: list (outsideshopreviewlist)
    review_list = data.get('list', [])
    if review_list:
        for r in review_list:
            feed_user = r.get('feedUser', {})
            user_name = ''
            if isinstance(feed_user, dict):
                user_name = feed_user.get('userName', feed_user.get('nickName', ''))

            reviews.append({
                'reviewId': r.get('mainId', r.get('reviewId', '')),
                'userName': user_name or r.get('userName', ''),
                'text': extract_text(r),
                'addTime': r.get('addTime', r.get('time', '')),
                'star': r.get('star', 0),
            })
        return reviews

    return reviews


def extract_text(review):
    """提取评论文字"""
    for key in ['content', 'text', 'reviewBody', 'publicReviewText']:
        val = review.get(key, '')
        if val and isinstance(val, str):
            return val.strip()
    return ''


def scan_existing_reviews():
    """扫描已有的评论文件，提取shopUuid和评论"""
    uuid_reviews = {}

    for filepath in LOG_DIR.glob('review_*.json'):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            params = data.get('params', {})
            shop_uuid = params.get('referid', params.get('shopId', params.get('shopUuid', '')))

            if not shop_uuid or shop_uuid == 'unknown':
                continue

            reviews = extract_reviews(data.get('data', {}))

            if shop_uuid not in uuid_reviews:
                uuid_reviews[shop_uuid] = []

            uuid_reviews[shop_uuid].extend(reviews)

        except Exception as e:
            pass

    return uuid_reviews


def wait_for_new_reviews(last_count, timeout=180):
    """等待新的评论文件"""
    start_time = time.time()
    new_reviews = []

    while time.time() - start_time < timeout:
        current_count = len(list(LOG_DIR.glob('review_*.json')))
        if current_count > last_count:
            # 扫描新文件
            new_files = sorted(LOG_DIR.glob('review_*.json'))[last_count:]

            for filepath in new_files:
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    params = data.get('params', {})
                    shop_uuid = params.get('referid', params.get('shopId', params.get('shopUuid', '')))

                    if shop_uuid and shop_uuid != 'unknown':
                        reviews = extract_reviews(data.get('data', {}))
                        if reviews:
                            new_reviews.append({
                                'shop_uuid': shop_uuid,
                                'reviews': reviews,
                            })
                except Exception as e:
                    pass

            last_count = current_count

            # 等待一段时间看是否有新数据
            time.sleep(3)
            current_count = len(list(LOG_DIR.glob('review_*.json')))
            if current_count == last_count:
                break

        time.sleep(2)

    return new_reviews, last_count


def main():
    """主函数"""
    excel_path = Path(__file__).parent / '达美乐_门店爬虫.xlsx'

    # 加载店铺列表
    stores = load_stores_from_excel(excel_path)
    print(f"📊 共 {len(stores)} 家门店需要采集")

    # 加载已有的UUID映射
    uuid_map = load_shop_uuid_map()
    print(f"📋 已有 {len(uuid_map)} 家店铺的UUID映射")

    # 扫描已有评论
    uuid_reviews = scan_existing_reviews()
    print(f"📝 已扫描到 {len(uuid_reviews)} 个店铺的评论数据")

    # 显示当前状态
    print("\n=== 当前已采集的店铺 ===")
    for uuid, reviews in uuid_reviews.items():
        store_name = None
        for name, uid in uuid_map.items():
            if uid == uuid:
                store_name = name
                break

        if store_name:
            print(f"  ✅ {store_name}: {len(reviews)} 条评论")
        else:
            print(f"  ❓ 未知店铺 ({uuid}): {len(reviews)} 条评论")

    # 找出还未采集的店铺
    uncaptured_stores = []
    for store in stores:
        if store['name'] not in uuid_map:
            uncaptured_stores.append(store)

    print(f"\n📋 还有 {len(uncaptured_stores)} 家店铺未采集")

    # 主循环
    print("\n" + "="*60)
    print("📌 半自动采集模式")
    print("="*60)
    print("操作步骤:")
    print("1. 在小程序中搜索店铺名")
    print("2. 进入店铺，点击'评价'")
    print("3. 向下滚动加载评论")
    print("4. 等待脚本自动捕获数据")
    print("="*60)

    last_count = len(list(LOG_DIR.glob('review_*.json')))

    while True:
        print("\n请选择操作:")
        print("1. 开始采集下一个店铺")
        print("2. 查看已采集的数据")
        print("3. 保存并退出")

        choice = input("\n请输入选择 (1/2/3): ").strip()

        if choice == '1':
            if not uncaptured_stores:
                print("\n✅ 所有店铺都已采集完成！")
                break

            store = uncaptured_stores[0]
            print(f"\n📍 请在小程序中搜索: {store['name']}")
            print(f"   进入店铺后，点击'评价'并向下滚动")
            print(f"   等待脚本自动捕获数据...")

            # 等待新数据
            new_reviews, last_count = wait_for_new_reviews(last_count, timeout=180)

            if new_reviews:
                for item in new_reviews:
                    shop_uuid = item['shop_uuid']
                    reviews = item['reviews']

                    # 保存映射
                    uuid_map[store['name']] = shop_uuid
                    save_shop_uuid_map(uuid_map)

                    # 保存评论
                    if shop_uuid not in uuid_reviews:
                        uuid_reviews[shop_uuid] = []
                    uuid_reviews[shop_uuid].extend(reviews)

                    print(f"\n✅ 已采集: {store['name']}")
                    print(f"   shopUuid: {shop_uuid}")
                    print(f"   评论数: {len(reviews)}")

                    # 从未采集列表中移除
                    uncaptured_stores = [s for s in uncaptured_stores if s['name'] != store['name']]
            else:
                print(f"\n❌ 未能捕获数据，请重试")

        elif choice == '2':
            # 显示已采集的数据
            print(f"\n=== 已采集的数据 ===")
            for uuid, reviews in uuid_reviews.items():
                store_name = None
                for name, uid in uuid_map.items():
                    if uid == uuid:
                        store_name = name
                        break

                print(f"\n店铺: {store_name or '未知'}")
                print(f"  UUID: {uuid}")
                print(f"  评论数量: {len(reviews)}")
                if reviews:
                    print(f"  最新评论: {reviews[0].get('text', '')[:50]}...")

        elif choice == '3':
            # 保存并退出
            break

        else:
            print("无效选择，请重试")

    # 保存最终结果
    output_data = []
    for uuid, reviews in uuid_reviews.items():
        store_name = None
        for name, uid in uuid_map.items():
            if uid == uuid:
                store_name = name
                break

        for review in reviews:
            output_data.append({
                'storeName': store_name or '未知',
                'shopUuid': uuid,
                'publishTime': review.get('addTime', ''),
                'publisher': review.get('userName', ''),
                'text': review.get('text', ''),
            })

    output_file = OUTPUT_DIR / 'reviews_final.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"🎉 采集完成！")
    print(f"  总评论数: {len(output_data)}")
    print(f"  结果文件: {output_file}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
