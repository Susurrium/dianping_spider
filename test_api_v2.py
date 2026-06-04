# -*- coding:utf-8 -*-
import json
import time
import zlib
import base64
import requests
from bs4 import BeautifulSoup
import re

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
UUID = "19e45df333ac8"
TCV = "c9c33"

headers = {
    'User-Agent': USER_AGENT,
    'Cookie': COOKIE,
    'Referer': 'http://www.dianping.com/',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# Step 1: Get shop_ids from search
print("=== Step 1: Parse search results ===")
r = requests.get('http://www.dianping.com/search/keyword/2/0_%E8%BE%BE%E7%BE%8E%E4%B9%90/p1',
                 headers=headers, timeout=10)
soup = BeautifulSoup(r.text, 'lxml')

# Find shop links
shop_links = soup.select('.shoplist .tit a')
shop_ids_found = []
for link in shop_links[:3]:
    href = link.get('href', '')
    # Extract shop id from href like /shop/k51oajiNjkEwfx09
    match = re.search(r'/shop/(\w+)', href)
    if match:
        shop_ids_found.append(match.group(1))
        print(f"Found shop: {link.text.strip()} -> {match.group(1)}")

# Also look for shop IDs in other selectors
if not shop_ids_found:
    all_links = soup.find_all('a', href=True)
    for link in all_links:
        match = re.search(r'/shop/(\w+)', link['href'])
        if match:
            sid = match.group(1)
            if sid not in shop_ids_found:
                shop_ids_found.append(sid)
                print(f"Found via all links: {link.text.strip()[:30]} -> {sid}")
                if len(shop_ids_found) >= 3:
                    break

if not shop_ids_found:
    # Try another pattern - search for shop IDs in the page source
    all_ids = re.findall(r'/shop/([a-zA-Z0-9]{14,18})', r.text)
    unique_ids = list(set(all_ids))[:3]
    shop_ids_found = unique_ids
    print(f"Found {len(unique_ids)} shop IDs from regex: {unique_ids}")

print(f"\nShop IDs found: {shop_ids_found}")

# Step 2: Try review_all with different approaches
if shop_ids_found:
    test_id = shop_ids_found[0]
    print(f"\n=== Step 2: Test review for shop {test_id} ===")
    
    # Try 1: review_all with PC headers
    print("\n--- Try 1: review_all with PC UA ---")
    r = requests.get(f'http://www.dianping.com/shop/{test_id}/review_all',
                     headers=headers, timeout=10, allow_redirects=False)
    print(f"Status: {r.status_code}")
    print(f"URL: {r.url}")
    print(f"Content length: {len(r.text)}")
    if r.status_code == 302:
        print(f"Redirect to: {r.headers.get('Location', 'N/A')}")
    
    # Try 2: allReview API with correct shop format
    print("\n--- Try 2: allReview API ---")
    shop_url = f'http://www.dianping.com/shop/{test_id}'
    url = 'http://www.dianping.com/ajax/json/shopDynamic/allReview?' \
          f'shopId={test_id}&cityId=2&shopType=10&tcv={TCV}' \
          f'&_token={get_token(shop_url)}&uuid={UUID}' \
          f'&platform=1&partner=150&optimusCode=10' \
          f'&originUrl={shop_url}'
    r = requests.get(url, headers=headers, timeout=10)
    print(f"Status: {r.status_code}")
    try:
        r_json = r.json()
        print(f"JSON code: {r_json.get('code', 'N/A')}")
        if 'msg' in r_json:
            print(f"Message keys: {list(r_json['msg'].keys()) if isinstance(r_json['msg'], dict) else r_json['msg']}")
        if r_json.get('code') == 200:
            reviews = r_json.get('reviewAllDOList', [])
            print(f"Got {len(reviews)} reviews")
            if reviews:
                r0 = reviews[0]
                print(f"First review keys: {list(r0.keys())}")
    except:
        print(f"Response: {r.text[:300]}")
    
    # Try 3: basicHideInfo API
    print("\n--- Try 3: basicHideInfo API ---")
    url = 'http://www.dianping.com/ajax/json/shopDynamic/basicHideInfo?' \
          f'shopId={test_id}&_token={get_token(shop_url)}&tcv={TCV}' \
          f'&uuid={UUID}&platform=1&partner=150&optimusCode=10' \
          f'&originUrl={shop_url}'
    r = requests.get(url, headers=headers, timeout=10)
    print(f"Status: {r.status_code}")
    try:
        r_json = r.json()
        print(f"JSON code: {r_json.get('code', 'N/A')}")
        if r_json.get('code') == 200:
            shop_info = r_json.get('msg', {}).get('shopInfo', {})
            print(f"Shop name: {shop_info.get('shopName', 'N/A')}")
            print(f"Address: {shop_info.get('address', 'N/A')}")
    except:
        print(f"Response: {r.text[:300]}")

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
