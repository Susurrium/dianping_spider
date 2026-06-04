# -*- coding:utf-8 -*-
"""
Test script to check if API endpoints work with requests + cookie
"""
import json
import time
import zlib
import base64
import requests

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

UUID = "19e45df333ac8"
TCV = "c9c33"


def get_token(shop_url):
    ts = int(time.time() * 1000)
    cts = int(time.time() * 1000) - 600
    tokens = str({"rId": '100041', "ver": "1.0.6", "ts": ts, "cts": cts, "brVD": [1920, 186],
                  "brR": [[1920, 1080], [1920, 1040], 24, 24], "bI": [shop_url, shop_url],
                  "mT": ["1244,588"], "kT": [], "aT": [], "tT": [], "aM": "",
                  "sign": "eJxTKs7IL/BMsTU2NTAwMLVUAgApvgRP"}).encode()
    _token = zlib.compress(tokens)
    token = base64.b64encode(_token).decode()
    return token


headers = {
    'User-Agent': USER_AGENT,
    'Cookie': COOKIE,
}

# Test 1: Search page
print("=== Test 1: Search page ===")
try:
    r = requests.get('http://www.dianping.com/search/keyword/2/0_%E8%BE%BE%E7%BE%8E%E4%B9%90/p1',
                     headers=headers, timeout=10)
    print(f"Status: {r.status_code}")
    print(f"URL: {r.url}")
    print(f"Content length: {len(r.text)}")
    if 'verify' in r.url:
        print("BLOCKED: Redirected to verify page")
    elif '达美乐' in r.text:
        print("SUCCESS: Found search results")
    elif 'login' in r.url.lower():
        print("BLOCKED: Redirected to login page")
    else:
        print(f"Unknown: {r.text[:200]}")
except Exception as e:
    print(f"Error: {e}")

print()

# Test 2: Review all page (HTML)
print("=== Test 2: Review all page (HTML) ===")
test_shop_id = 'k51oajiNjkEwfx09'
try:
    r = requests.get(f'http://www.dianping.com/shop/{test_shop_id}/review_all',
                     headers=headers, timeout=10)
    print(f"Status: {r.status_code}")
    print(f"URL: {r.url}")
    print(f"Content length: {len(r.text)}")
    if 'verify' in r.url:
        print("BLOCKED: Redirected to verify page")
    elif 'review-words' in r.text:
        print("SUCCESS: Found review content")
    elif 'login' in r.url.lower():
        print("BLOCKED: Redirected to login page")
    elif r.status_code == 403:
        print("BLOCKED: 403 Forbidden")
    else:
        print(f"Response preview: {r.text[:300]}")
except Exception as e:
    print(f"Error: {e}")

print()

# Test 3: allReview API
print("=== Test 3: allReview API ===")
shop_url = 'http://www.dianping.com/shopold/pc?shopuuid=' + test_shop_id
url = 'http://www.dianping.com/ajax/json/shopDynamic/allReview?' \
      'shopId=' + test_shop_id + \
      '&cityId=19' \
      '&shopType=10' \
      '&tcv=' + TCV + \
      '&_token=' + str(get_token(shop_url)) + \
      '&uuid=' + UUID + \
      '&platform=1' \
      '&partner=150' \
      '&optimusCode=10' \
      '&originUrl=' + shop_url

try:
    r = requests.get(url, headers=headers, timeout=10)
    print(f"Status: {r.status_code}")
    print(f"URL: {r.url}")
    if 'verify' in r.url:
        print("BLOCKED: Redirected to verify page")
    elif r.status_code == 200:
        try:
            r_json = r.json()
            print(f"JSON code: {r_json.get('code', 'N/A')}")
            if r_json.get('code') == 200:
                print(f"Review count: {len(r_json.get('reviewAllDOList', []))}")
                print("SUCCESS: API returned data")
            else:
                print(f"API response: {json.dumps(r_json, ensure_ascii=False)[:500]}")
        except:
            print(f"Response preview: {r.text[:300]}")
    elif r.status_code == 403:
        print("BLOCKED: 403 Forbidden")
    else:
        print(f"Response preview: {r.text[:300]}")
except Exception as e:
    print(f"Error: {e}")
