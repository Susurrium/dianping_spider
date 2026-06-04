# -*- coding: utf-8 -*-
"""
Test: Use Playwright to visit mobile Dianping and intercept API responses.
Goal: Find review API endpoints that return clean JSON (no CSS font encryption).
"""
import json
import time
from playwright.sync_api import sync_playwright

TEST_SHOP_ID = "G7GQQl9QkeAbbSoZ"  # 江汉路步行街店

captured_responses = []

def handle_response(response):
    url = response.url
    if any(d in url for d in ['dianping.com', 'meituan.com']):
        if any(ext in url for ext in ['.png', '.jpg', '.css', '.js', '.woff', '.svg', '.ico', '.webp']):
            return
        try:
            ct = response.headers.get('content-type', '')
            if 'json' in ct or 'text' in ct:
                body = response.text()
                if body.startswith('{') or body.startswith('['):
                    captured_responses.append({
                        'url': url[:300],
                        'status': response.status,
                        'content_type': ct,
                        'body_preview': body[:500],
                        'body_len': len(body),
                    })
                    print(f"  [API] [{response.status}] {url[:120]}")
        except:
            pass

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy={'server': 'http://127.0.0.1:9092'},
            args=['--ignore-certificate-errors']
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
            viewport={'width': 390, 'height': 844},
            is_mobile=True,
        )
        page = context.new_page()
        page.on('response', handle_response)

        # Test 1: Mobile web shop page
        print("\n=== Test 1: m.dianping.com shop page ===")
        captured_responses.clear()
        try:
            page.goto(f'https://m.dianping.com/shop/{TEST_SHOP_ID}', wait_until='networkidle', timeout=30000)
            time.sleep(2)
            print(f"  URL: {page.url}")
            print(f"  Title: {page.title()}")
            print(f"  Captured {len(captured_responses)} API responses")
        except Exception as e:
            print(f"  Error: {e}")

        # Test 2: Mobile web review page
        print("\n=== Test 2: m.dianping.com review page ===")
        captured_responses.clear()
        try:
            page.goto(f'https://m.dianping.com/shop/{TEST_SHOP_ID}/review_all', wait_until='networkidle', timeout=30000)
            time.sleep(2)
            print(f"  URL: {page.url}")
            print(f"  Captured {len(captured_responses)} API responses")
            for r in captured_responses:
                print(f"    [{r['status']}] {r['url'][:100]} (len={r['body_len']})")
                if 'review' in r['url'].lower() or 'comment' in r['url'].lower():
                    print(f"      Preview: {r['body_preview'][:300]}")
        except Exception as e:
            print(f"  Error: {e}")

        # Test 3: Try desktop web
        print("\n=== Test 3: www.dianping.com review page ===")
        captured_responses.clear()
        context2 = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1366, 'height': 768},
        )
        page2 = context2.new_page()
        page2.on('response', handle_response)
        try:
            page2.goto(f'https://www.dianping.com/shop/{TEST_SHOP_ID}/review_all', wait_until='networkidle', timeout=30000)
            time.sleep(2)
            print(f"  URL: {page2.url}")
            print(f"  Captured {len(captured_responses)} API responses")
            for r in captured_responses:
                print(f"    [{r['status']}] {r['url'][:100]} (len={r['body_len']})")
        except Exception as e:
            print(f"  Error: {e}")

        # Test 4: Search
        print("\n=== Test 4: Search for 达美乐 ===")
        captured_responses.clear()
        try:
            page2.goto('https://www.dianping.com/search/keyword/1/0_%E8%BE%BE%E7%BE%8E%E4%B9%90', wait_until='networkidle', timeout=30000)
            time.sleep(2)
            print(f"  URL: {page2.url}")
            print(f"  Captured {len(captured_responses)} API responses")
            shops = page2.evaluate('''() => {
                const links = document.querySelectorAll('a[href*="/shop/"]');
                const results = [];
                const seen = new Set();
                links.forEach(link => {
                    const href = link.getAttribute('href') || '';
                    const match = href.match(/\\/shop\\/([A-Za-z0-9]+)/);
                    if (match && !seen.has(match[1])) {
                        seen.add(match[1]);
                        results.push({id: match[1], text: link.innerText.trim().substring(0, 50)});
                    }
                });
                return results.slice(0, 10);
            }''')
            print(f"  Found shops: {json.dumps(shops, ensure_ascii=False, indent=2)}")
        except Exception as e:
            print(f"  Error: {e}")

        browser.close()

if __name__ == '__main__':
    main()
