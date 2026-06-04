#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Test if the allReview API endpoint still works
"""
import json
import zlib
import base64
import time
import requests

# User's cookie
COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=0e88dab8-20260520-132248.1747737768398.1747737768398; s_ViewType=10; fspop=test; cy=2; cye=shanghai; dplet=a3a7734797ee59bace9d6fe248c7f30b; dper=665166c0ead3c5873a134ea90649396f77272e3363c85fa5e42fe6f3d0dea9f462e3541c2359850489fa3b22dc6cd6da92e7635f2d0271eb83b1b252a2e5e7ce3fa523e58455691cbbee9c9a445332be7bbaed8c4c0707d0605732e6dca5984f; ll=7fd06e815b796be3df069dec7836c3df; ua=15001794136; _lxsdk_s=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333ac8%7C%7C5; _dp.ac.v=01cb5830-383f-456c-86e6-d9b3b3f3d195"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"

def get_token(shop_url):
    ts = int(time.time() * 1000)
    cts = ts - 600
    tokens = str({"rId": '100041', "ver": "1.0.6", "ts": ts, "cts": cts, "brVD": [1920, 186],
                  "brR": [[1920, 1080], [1920, 1040], 24, 24], "bI": [shop_url, shop_url],
                  "mT": ["1244,588"], "kT": [], "aT": [], "tT": [], "aM": "",
                  "sign": "eJxTKs7IL/BMsTU2NTAwMLVUAgApvgRP"}).encode()
    _token = zlib.compress(tokens)
    token = base64.b64encode(_token).decode()
    return token

# Test with a known shop_id - 达美乐门店
shop_id = "H5BIJ8PN64Rmywap"  # sample from project
shop_url = f'http://www.dianping.com/shopold/pc?shopuuid={shop_id}'

# First, try to search and find a 达美乐 shop_id
search_url = "http://www.dianping.com/search/keyword/2/0_%E8%BE%BE%E7%BE%8E%E4%B9%90/p1"
headers = {
    'User-Agent': UA,
    'Cookie': COOKIE,
}

print("=== Test 1: Search page ===")
try:
    r = requests.get(search_url, headers=headers, timeout=10)
    print(f"Status: {r.status_code}")
    print(f"URL: {r.url}")
    if 'verify' in r.url:
        print("CAPTCHA triggered!")
    elif r.status_code == 200:
        print(f"Content length: {len(r.text)}")
        # Try to find shop_ids
        import re
        shop_ids = re.findall(r'data-shopid="([^"]+)"', r.text)
        print(f"Found {len(shop_ids)} shop_ids: {shop_ids[:3]}")
    else:
        print(f"Content: {r.text[:200]}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Test 2: Shop page ===")
try:
    r = requests.get(f"http://www.dianping.com/shop/{shop_id}", headers=headers, timeout=10)
    print(f"Status: {r.status_code}")
    print(f"URL: {r.url}")
    if r.status_code == 200:
        print(f"Content length: {len(r.text)}")
        # Check if review data is present
        if 'review' in r.text.lower():
            print("Review data found in page")
        # Look for font CSS
        css_match = re.findall(r'href="(//s3plus\.meituan\.net/v1/.*?)"', r.text)
        print(f"Font CSS files: {css_match}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Test 3: allReview API ===")
token = get_token(shop_url)
api_url = (f"http://www.dianping.com/ajax/json/shopDynamic/allReview?"
           f"shopId={shop_id}&cityId=2&shopType=10&tcv=test123"
           f"&_token={token}&uuid=test-uuid"
           f"&platform=1&partner=150&optimusCode=10&originUrl={shop_url}")
try:
    r = requests.get(api_url, headers=headers, timeout=10)
    print(f"Status: {r.status_code}")
    print(f"URL: {r.url}")
    if r.status_code == 200:
        print(f"Content: {r.text[:500]}")
    else:
        print(f"Content: {r.text[:300]}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Test 4: review_all page ===")
try:
    r = requests.get(f"http://www.dianping.com/shop/{shop_id}/review_all", headers=headers, timeout=10, allow_redirects=False)
    print(f"Status: {r.status_code}")
    print(f"URL: {r.url}")
    if r.status_code == 302:
        print(f"Redirect to: {r.headers.get('Location', 'N/A')}")
    elif r.status_code == 200:
        print(f"Content length: {len(r.text)}")
        print(f"Content type: {r.headers.get('Content-Type', 'N/A')}")
        # Check if it's actual HTML or a font file
        if r.text.startswith('<!DOCTYPE') or r.text.startswith('<html'):
            print("Got HTML!")
        else:
            print(f"Content start: {r.text[:100]}")
except Exception as e:
    print(f"Error: {e}")
