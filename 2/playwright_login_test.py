# -*- coding: utf-8 -*-
"""
Test: Open dianping.com in visible browser for user login.
Then test if we can scrape reviews.
"""
import json
import time
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        # Launch VISIBLE browser for login
        browser = p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1366, 'height': 768}
        )
        page = context.new_page()

        # Navigate to dianping
        page.goto('https://www.dianping.com', wait_until='domcontentloaded', timeout=30000)
        time.sleep(2)

        print(f"URL: {page.url}")
        print(f"Title: {page.title()}")

        # Check if redirected to login
        if 'login' in page.url or 'account' in page.url:
            print("\n" + "="*50)
            print("请在浏览器中登录大众点评")
            print("登录完成后按回车键继续...")
            print("="*50)
            input()

        # After login, try to visit a store review page
        print("\n尝试访问评论页面...")
        page.goto('https://www.dianping.com/shop/104374870/review_all', wait_until='domcontentloaded', timeout=30000)
        time.sleep(3)

        print(f"URL: {page.url}")
        print(f"Title: {page.title()}")

        # Check if we got a review page or verification
        if 'verify' in page.url:
            print("触发了验证码，请手动完成验证后按回车...")
            input()

        # Try to extract review text
        review_text = page.evaluate('''() => {
            const reviews = document.querySelectorAll('.reviews-items .main-review');
            const results = [];
            reviews.forEach(r => {
                const name = r.querySelector('.name');
                const time = r.querySelector('.time');
                const text = r.querySelector('.review-words');
                results.push({
                    name: name ? name.innerText.trim() : '',
                    time: time ? time.innerText.trim() : '',
                    text: text ? text.innerText.trim().substring(0, 100) : ''
                });
            });
            return results;
        }''')

        print(f"\nExtracted {len(review_text)} reviews:")
        for r in review_text[:3]:
            print(f"  {r['name']} | {r['time']} | {r['text'][:50]}")

        # Save cookies for later use
        cookies = context.cookies()
        with open('/home/hetaisheng/dianping_spider/dianping_cookies.json', 'w') as f:
            json.dump(cookies, f, indent=2)
        print(f"\nSaved {len(cookies)} cookies")

        # Also check if review text is garbled (CSS font encryption)
        if review_text and review_text[0]['text']:
            text = review_text[0]['text']
            # Check if text contains common Chinese characters
            chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
            if chinese_chars < len(text) * 0.3:
                print(f"\n⚠️  Review text appears to be CSS-font encrypted!")
                print(f"  Sample: {text[:50]}")
                print(f"  Chinese ratio: {chinese_chars}/{len(text)}")
            else:
                print(f"\n✅ Review text appears to be readable!")
                print(f"  Sample: {text[:50]}")

        browser.close()

if __name__ == '__main__':
    main()
