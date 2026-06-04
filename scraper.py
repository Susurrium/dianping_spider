# -*- coding: utf-8 -*-
"""
大众点评 达美乐门店评论批量爬取脚本
使用 Playwright 浏览器自动化 + Cookie 认证
"""

import json
import time
import random
import re
import os
import sys
import traceback
from datetime import datetime
from urllib.parse import quote

import openpyxl
from playwright.sync_api import sync_playwright

# ============ 配置 ============
EXCEL_PATH = '/home/hetaisheng/dianping_spider/达美乐_门店爬虫.xlsx'
OUTPUT_PATH = '/home/hetaisheng/dianping_spider/达美乐_评论结果.json'
PROGRESS_PATH = '/home/hetaisheng/dianping_spider/progress.json'

COOKIE_STR = '_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72'

MIN_DELAY = 3
MAX_DELAY = 6
STORE_BATCH_SIZE = 5
STORE_BATCH_DELAY = 30


def load_stores():
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active
    stores = []
    seen = set()
    for row in ws.iter_rows(min_row=3, max_row=ws.max_row, values_only=True):
        name = row[1]
        addr = row[2]
        if name and name.strip():
            key = (name.strip(), addr.strip() if addr else '')
            if key not in seen:
                seen.add(key)
                stores.append({'name': name.strip(), 'address': addr.strip() if addr else ''})
    return stores


def load_progress():
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'completed': [], 'shop_ids': {}, 'results': []}


def save_progress(progress):
    with open(PROGRESS_PATH, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def parse_cookies(cookie_str):
    cookies = []
    for pair in cookie_str.split('; '):
        if '=' in pair:
            name, value = pair.split('=', 1)
            cookies.append({
                'name': name.strip(),
                'value': value,
                'domain': '.dianping.com',
                'path': '/'
            })
    return cookies


def random_delay(min_s=MIN_DELAY, max_s=MAX_DELAY):
    time.sleep(random.uniform(min_s, max_s))


class DianpingScraper:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def start(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        self.context = self.browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1366, 'height': 768}
        )
        self.context.add_cookies(parse_cookies(COOKIE_STR))
        self.page = self.context.new_page()
        self.page.goto('https://www.dianping.com', wait_until='domcontentloaded')
        time.sleep(2)
        print('[OK] Browser started, cookie set')

    def stop(self):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def search_and_get_shop_id(self, store_name, store_addr):
        short_name = store_name.replace('达美乐比萨(', '').replace(')', '').strip()
        keyword = f'达美乐比萨 {short_name}'
        print(f'  [search] keyword: {keyword}')

        encoded = quote(keyword)
        search_url = f'https://www.dianping.com/search/keyword/1/0_{encoded}'

        try:
            self.page.goto(search_url, wait_until='domcontentloaded', timeout=15000)
            time.sleep(2)

            if 'verify' in self.page.url:
                print('  [!] CAPTCHA! Please solve manually then press Enter...')
                input()
                self.page.goto(search_url, wait_until='domcontentloaded', timeout=15000)
                time.sleep(2)

            # Extract shop_ids from search results
            shop_ids = self.page.evaluate('''() => {
                const links = document.querySelectorAll('a[href*="/shop/"]');
                const results = [];
                const seen = new Set();
                links.forEach(link => {
                    const href = link.getAttribute('href') || '';
                    const match = href.match(/\\/shop\\/([A-Za-z0-9]+)/);
                    if (match && !seen.has(match[1])) {
                        seen.add(match[1]);
                        results.push({id: match[1], text: link.innerText.trim()});
                    }
                });
                return results;
            }''')

            if not shop_ids:
                print(f'  [!] No results found')
                return None

            # Match best store
            for s in shop_ids:
                if short_name in s['text'] and '达美乐' in s['text']:
                    print(f'  [match] {s["text"]} -> {s["id"]}')
                    return s['id']

            for s in shop_ids:
                if '达美乐' in s['text']:
                    print(f'  [~] approx: {s["text"]} -> {s["id"]}')
                    return s['id']

            print(f'  [?] first result: {shop_ids[0]["text"]} -> {shop_ids[0]["id"]}')
            return shop_ids[0]['id']

        except Exception as e:
            print(f'  [!] search error: {e}')
            return None

    def scrape_reviews(self, shop_id, store_name):
        all_reviews = []
        page_num = 1

        while True:
            if page_num == 1:
                url = f'https://www.dianping.com/shop/{shop_id}/review_all'
            else:
                url = f'https://www.dianping.com/shop/{shop_id}/review_all/p{page_num}'

            print(f'    [review] page {page_num}: {url}')

            try:
                self.page.goto(url, wait_until='domcontentloaded', timeout=20000)
                time.sleep(3)

                if 'verify' in self.page.url:
                    print('    [!] CAPTCHA! Solve manually then press Enter...')
                    input()
                    self.page.goto(url, wait_until='domcontentloaded', timeout=20000)
                    time.sleep(3)

                if 'login' in self.page.url:
                    print('    [!] Login required, cookie may be expired')
                    return all_reviews

                # Extract reviews via JS
                review_data = self.page.evaluate('''() => {
                    const reviews = [];
                    
                    // Method 1: Classic .main-review structure
                    const items = document.querySelectorAll('.reviews-items .main-review, .review-list .review-item');
                    items.forEach(item => {
                        const nameEl = item.querySelector('.name, [class*="user-name"]');
                        const timeEl = item.querySelector('.time, [class*="date"]');
                        const textEl = item.querySelector('.review-words, .review-short, [class*="review-words"]');
                        
                        let text = '';
                        if (textEl) {
                            text = textEl.innerText.replace('收起评价', '').replace(/\\s+/g, ' ').trim();
                        }
                        
                        if (text && text.length > 0) {
                            reviews.push({
                                username: nameEl ? nameEl.innerText.trim() : '',
                                time: timeEl ? timeEl.innerText.trim() : '',
                                text: text
                            });
                        }
                    });
                    
                    // Method 2: New page structure (look for review blocks with user info + text)
                    if (reviews.length === 0) {
                        const allDivs = document.querySelectorAll('div');
                        for (const div of allDivs) {
                            const cls = div.className || '';
                            if (cls.includes('review') || cls.includes('comment')) {
                                const text = div.innerText.trim();
                                if (text.length > 20 && text.length < 2000) {
                                    reviews.push({username: '', time: '', text: text});
                                }
                            }
                        }
                    }
                    
                    return reviews;
                }''')

                page_reviews = []
                for r in (review_data or []):
                    text = r.get('text', '').strip()
                    if text:
                        page_reviews.append({
                            '门店': store_name,
                            'shop_id': shop_id,
                            '发布时间': r.get('time', ''),
                            '发布人': r.get('username', ''),
                            '文字': text
                        })

                if not page_reviews:
                    print(f'    [done] No reviews on page {page_num}')
                    break

                all_reviews.extend(page_reviews)
                print(f'    [ok] page {page_num}: {len(page_reviews)} reviews')

                # Check for next page
                has_next = self.page.evaluate('''() => {
                    const links = document.querySelectorAll('.reviews-pages a, [class*="pagination"] a');
                    for (const link of links) {
                        if (link.innerText.includes('下一页') || link.classList.contains('next')) {
                            return true;
                        }
                    }
                    return false;
                }''')

                if not has_next:
                    print(f'    [done] Last page reached')
                    break

                page_num += 1
                random_delay()

            except Exception as e:
                print(f'    [!] page {page_num} error: {e}')
                traceback.print_exc()
                break

        return all_reviews


def main():
    print('=' * 60)
    print('Dianping Domino\'s Store Review Scraper')
    print('=' * 60)

    stores = load_stores()
    print(f'\nTotal stores: {len(stores)} (deduplicated)')

    progress = load_progress()
    completed = set(progress['completed'])
    results = progress['results']

    pending = [s for s in stores if s['name'] not in completed]
    print(f'Completed: {len(completed)}, Pending: {len(pending)}\n')

    if not pending:
        print('All stores processed!')
        return

    scraper = DianpingScraper()

    try:
        scraper.start()

        for i, store in enumerate(pending):
            store_name = store['name']
            store_addr = store['address']

            print(f'\n{"="*50}')
            print(f'[{i+1}/{len(pending)}] {store_name}')
            print(f'  addr: {store_addr}')

            shop_id = scraper.search_and_get_shop_id(store_name, store_addr)

            if not shop_id:
                print(f'  [!] Skipped')
                progress['completed'].append(store_name)
                save_progress(progress)
                random_delay()
                continue

            reviews = scraper.scrape_reviews(shop_id, store_name)
            print(f'  [result] {len(reviews)} reviews')

            results.extend(reviews)
            progress['completed'].append(store_name)
            progress['shop_ids'][store_name] = shop_id
            save_progress(progress)

            with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

            if (i + 1) % STORE_BATCH_SIZE == 0:
                print(f'\n[break] {i+1} stores done, resting {STORE_BATCH_DELAY}s...')
                time.sleep(STORE_BATCH_DELAY)
            else:
                random_delay()

    except KeyboardInterrupt:
        print('\n[INTERRUPT] Saving progress...')
    except Exception as e:
        print(f'\n[ERROR] {e}')
        traceback.print_exc()
    finally:
        with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        save_progress(progress)
        scraper.stop()

    print(f'\n{"="*60}')
    print(f'Done! {len(results)} reviews collected')
    print(f'Output: {OUTPUT_PATH}')
    print(f'Progress: {PROGRESS_PATH}')


if __name__ == '__main__':
    main()
