# -*- coding: utf-8 -*-
"""
Discover Dianping web API endpoints by intercepting XHR/fetch responses.
Uses visible browser for one-time login, then tests API access.
"""
import json
import time
import re
from playwright.sync_api import sync_playwright

CAPTURE_FILE = '/home/hetaisheng/dianping_spider/web_api_captures.json'
COOKIE_FILE = '/home/hetaisheng/dianping_spider/dianping_cookies.json'

all_captures = []

def on_response(response):
    url = response.url
    if not any(d in url for d in ['dianping.com', 'meituan.com']):
        return
    if any(ext in url for ext in ['.png', '.jpg', '.css', '.woff', '.svg', '.ico', '.webp', '.gif']):
        return
    
    try:
        ct = response.headers.get('content-type', '')
        status = response.status
        
        # Capture JSON responses
        if 'json' in ct or 'javascript' in ct:
            body = response.text()
            if body and (body.startswith('{') or body.startswith('[')):
                all_captures.append({
                    'url': url[:500],
                    'status': status,
                    'ct': ct,
                    'body_len': len(body),
                    'body_preview': body[:1000],
                })
                if 'review' in url.lower() or 'comment' in url.lower() or 'shop' in url.lower():
                    print(f"  📡 [{status}] {url[:150]}")
                    print(f"     Preview: {body[:200]}")
        
        # Also capture HTML responses that might contain review data
        elif 'text/html' in ct and status == 200:
            body = response.text()
            if 'review' in body[:5000].lower():
                all_captures.append({
                    'url': url[:500],
                    'status': status,
                    'ct': ct,
                    'body_len': len(body),
                    'type': 'html_with_review',
                })
                print(f"  📄 [{status}] HTML with review data: {url[:100]} (len={len(body)})")
    except:
        pass

def load_cookies(context):
    try:
        with open(COOKIE_FILE, 'r') as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        print(f"Loaded {len(cookies)} cookies")
        return True
    except:
        return False

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1366, 'height': 768}
        )
        
        # Try loading saved cookies
        has_cookies = load_cookies(context)
        
        page = context.new_page()
        page.on('response', on_response)
        
        # Step 1: Navigate to dianping
        print("\n=== Step 1: Navigate to dianping.com ===")
        page.goto('https://www.dianping.com', wait_until='domcontentloaded', timeout=30000)
        time.sleep(3)
        print(f"URL: {page.url}")
        
        # Check if login needed
        if 'login' in page.url or 'account' in page.url:
            print("\n" + "="*50)
            print("请在浏览器中登录大众点评（扫码或账号密码）")
            print("登录完成后，在此终端按回车键继续...")
            print("="*50)
            input()
            
            # Save cookies after login
            cookies = context.cookies()
            with open(COOKIE_FILE, 'w') as f:
                json.dump(cookies, f, indent=2)
            print(f"Saved {len(cookies)} cookies")
        
        # Step 2: Search for a test store
        print("\n=== Step 2: Search for 达美乐 江汉路 ===")
        all_captures.clear()
        page.goto('https://www.dianping.com/search/keyword/1/0_%E8%BE%BE%E7%BE%8E%E4%B9%90%20%E6%B1%9F%E6%B1%89%E8%B7%AF', 
                  wait_until='networkidle', timeout=30000)
        time.sleep(3)
        print(f"URL: {page.url}")
        
        if 'verify' in page.url:
            print("⚠️  触发验证码，请手动完成验证后按回车...")
            input()
        
        # Extract shop links from search results
        shops = page.evaluate('''() => {
            const links = document.querySelectorAll('a[href*="/shop/"]');
            const results = [];
            const seen = new Set();
            links.forEach(link => {
                const href = link.getAttribute('href') || '';
                const match = href.match(/\\/shop\\/([A-Za-z0-9]+)/);
                if (match && !seen.has(match[1])) {
                    seen.add(match[1]);
                    const text = link.innerText.trim();
                    if (text.length > 0 && text.length < 100) {
                        results.push({id: match[1], text: text});
                    }
                }
            });
            return results.slice(0, 10);
        }''')
        print(f"Found {len(shops)} shop links:")
        for s in shops:
            print(f"  {s['id']} -> {s['text']}")
        
        # Step 3: Visit a store review page
        test_shop = shops[0]['id'] if shops else '104374870'
        print(f"\n=== Step 3: Visit shop {test_shop} reviews ===")
        all_captures.clear()
        
        # Monitor XHR specifically
        xhr_captures = []
        def on_xhr(response):
            url = response.url
            if any(d in url for d in ['dianping.com', 'meituan.com']):
                if any(ext in url for ext in ['.png', '.jpg', '.css', '.js', '.woff', '.svg', '.ico']):
                    return
                try:
                    ct = response.headers.get('content-type', '')
                    body = response.text()
                    xhr_captures.append({
                        'url': url[:300],
                        'status': response.status,
                        'ct': ct,
                        'body_len': len(body),
                        'body_preview': body[:500],
                    })
                except:
                    pass
        
        page2 = context.new_page()
        page2.on('response', on_xhr)
        
        try:
            page2.goto(f'https://www.dianping.com/shop/{test_shop}/review_all', 
                      wait_until='networkidle', timeout=30000)
            time.sleep(5)
            print(f"URL: {page2.url}")
            print(f"Title: {page2.title()}")
            
            # Check for verification
            if 'verify' in page2.url:
                print("⚠️  触发验证码，请手动完成验证后按回车...")
                input()
            
            print(f"\nCaptured {len(xhr_captures)} XHR responses:")
            for r in xhr_captures:
                print(f"  [{r['status']}] {r['url'][:100]} ({r['body_len']} bytes)")
                if r['body_len'] > 100:
                    print(f"    Preview: {r['body_preview'][:200]}")
            
            # Try to extract review text from DOM
            reviews = page2.evaluate('''() => {
                const items = document.querySelectorAll('.reviews-items .main-review');
                const results = [];
                items.forEach(item => {
                    const name = item.querySelector('.name');
                    const time = item.querySelector('.time');
                    const words = item.querySelector('.review-words');
                    const stars = item.querySelector('.sml-rank-stars');
                    results.push({
                        name: name ? name.innerText.trim() : '',
                        time: time ? time.innerText.trim() : '',
                        text: words ? words.innerText.trim().substring(0, 200) : '',
                        stars: stars ? stars.className : '',
                    });
                });
                return results;
            }''')
            
            print(f"\nExtracted {len(reviews)} reviews from DOM:")
            for r in reviews[:5]:
                print(f"  [{r['name']}] {r['time']} | {r['text'][:80]}")
                
        except Exception as e:
            print(f"Error: {e}")
        
        # Save all captures
        with open(CAPTURE_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_captures + xhr_captures, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(all_captures) + len(xhr_captures)} captures to {CAPTURE_FILE}")
        
        browser.close()

if __name__ == '__main__':
    main()
