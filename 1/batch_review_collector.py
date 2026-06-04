# -*- coding:utf-8 -*-
"""
批量采集大众点评评论
使用方法：
1. 运行此脚本
2. 在微信小程序中搜索并进入店铺
3. 脚本会自动捕获shopUuid和评论数据
"""
import json
import os
import csv
import time
from datetime import datetime
from pathlib import Path

# 配置
LOG_DIR = Path(__file__).parent / 'mitm_logs'
OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

# 店铺UUID映射
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


def save_results(stores_data, output_file):
    """保存结果到JSON"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(stores_data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存到: {output_file}")


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
    print("\n=== 当前状态 ===")
    for uuid, reviews in uuid_reviews.items():
        print(f"  {uuid}: {len(reviews)} 条评论")

    # 提示用户
    print("\n" + "="*60)
    print("📌 使用说明:")
    print("1. 保持mitmweb运行 (端口9092)")
    print("2. 在微信小程序中搜索并进入店铺")
    print("3. 进入评论页面并向下滚动")
    print("4. 评论会自动保存到 mitm_logs/ 目录")
    print("5. 运行此脚本可以查看已采集的数据")
    print("="*60)

    # 询问用户是否要继续采集
    print("\n请选择操作:")
    print("1. 查看已采集的数据")
    print("2. 开始新的采集（需要手动操作小程序）")
    print("3. 退出")

    choice = input("\n请输入选择 (1/2/3): ").strip()

    if choice == '1':
        # 显示已采集的数据
        if uuid_reviews:
            print(f"\n=== 已采集的数据 ===")
            for uuid, reviews in uuid_reviews.items():
                print(f"\n店铺UUID: {uuid}")
                print(f"  评论数量: {len(reviews)}")
                if reviews:
                    print(f"  最新评论: {reviews[0].get('text', '')[:50]}...")
        else:
            print("\n暂无数据")

    elif choice == '2':
        # 开始新的采集
        print("\n请在小程序中搜索并进入店铺，然后进入评论页面并向下滚动")
        print("按Ctrl+C停止采集")

        try:
            last_count = len(list(LOG_DIR.glob('review_*.json')))
            while True:
                current_count = len(list(LOG_DIR.glob('review_*.json')))
                if current_count > last_count:
                    # 扫描新文件
                    new_uuid_reviews = scan_existing_reviews()
                    for uuid, reviews in new_uuid_reviews.items():
                        if uuid not in uuid_reviews:
                            uuid_reviews[uuid] = []
                        uuid_reviews[uuid].extend(reviews)

                    print(f"  📝 新增评论，总计 {sum(len(r) for r in uuid_reviews.values())} 条")
                    last_count = current_count

                time.sleep(2)

        except KeyboardInterrupt:
            print("\n\n采集已停止")

    # 保存最终结果
    if uuid_reviews:
        output_data = []
        for uuid, reviews in uuid_reviews.items():
            for review in reviews:
                output_data.append({
                    'shopUuid': uuid,
                    'publishTime': review.get('addTime', ''),
                    'publisher': review.get('userName', ''),
                    'text': review.get('text', ''),
                })

        save_results(output_data, OUTPUT_DIR / 'reviews_final.json')
        print(f"\n📊 共 {len(output_data)} 条评论")


if __name__ == '__main__':
    main()
