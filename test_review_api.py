import requests, re, json, time, zlib, base64
from bs4 import BeautifulSoup

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
UUID = "19e45df333ac8"
TCV = "c9c33"

def get_token(shop_url):
    ts = int(time.time() * 1000)
    cts = ts - 600
    tokens = json.dumps({"rId":"100041","ver":"1.0.6","ts":ts,"cts":cts,"brVD":[1920,186],
        "brR":[[1920,1080],[1920,1040],24,24],"bI":[shop_url,shop_url],
        "mT":["1244,588"],"kT":[],"aT":[],"tT":[],"aM":"",
        "sign":"eJxTKs7IL/BMsTU2NTAwMLVUAgApvgRP"}).encode()
    return base64.b64encode(zlib.compress(tokens)).decode()

hdrs = {'User-Agent': UA, 'Cookie': COOKIE, 'Referer': 'http://www.dianping.com/'}

test_uuid = 'EOeLXrY2fCUUC7ur'
numeric_id = '14878552'

# Try allReview with numeric shop ID
print("=== allReview with numeric ID ===")
shop_url = f'http://www.dianping.com/shop/{test_uuid}'
for sid in [numeric_id, test_uuid]:
    for city_id in ['2', '19']:
        url = (f'http://www.dianping.com/ajax/json/shopDynamic/allReview?'
               f'shopId={sid}&cityId={city_id}&shopType=10&tcv={TCV}'
               f'&_token={get_token(shop_url)}&uuid={UUID}'
               f'&platform=1&partner=150&optimusCode=10'
               f'&originUrl={shop_url}')
        r = requests.get(url, headers=hdrs, timeout=10, allow_redirects=False)
        print(f"  shopId={sid}, cityId={city_id}: status={r.status_code}, url={r.url}")
        if r.status_code == 200:
            try:
                j = r.json()
                print(f"    code={j.get('code')}, keys={list(j.keys())[:5]}")
            except:
                print(f"    Not JSON, len={len(r.text)}")

# Try the mobile API for reviews
print("\n=== Mobile review APIs ===")
# m.dianping.com API for reviews
review_apis = [
    f'https://m.dianping.com/shop/{test_uuid}/review_all',
    f'https://m.dianping.com/shop/review/list?shopId={numeric_id}&cityId=2&page=1',
    f'https://m.dianping.com/review/shop/{numeric_id}?page=1',
]
for api_url in review_apis:
    try:
        r = requests.get(api_url, headers={**hdrs, 'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'}, timeout=10, allow_redirects=True)
        print(f"  URL: {api_url}")
        print(f"  Status: {r.status_code}, Final: {r.url}, Len: {len(r.text)}")
        if 'review' in r.text.lower()[:500]:
            print(f"  FOUND REVIEW DATA")
    except Exception as e:
        print(f"  Error: {e}")

# Try the PC review component API
print("\n=== PC review component API ===")
pc_review_apis = [
    f'https://www.dianping.com/ajax/json/shopDynamic/reviewAll?shopId={numeric_id}&cityId=2&shopType=10',
    f'https://www.dianping.com/ajax/json/shopDynamic/reviewList?shopId={numeric_id}&cityId=2',
    f'https://www.dianping.com/shop/{test_uuid}/review_all',
]
for api_url in pc_review_apis:
    try:
        r = requests.get(api_url, headers=hdrs, timeout=10, allow_redirects=True)
        print(f"  URL: {api_url}")
        print(f"  Status: {r.status_code}, Final: {r.url}, Len: {len(r.text)}")
        if r.status_code == 200:
            try:
                j = r.json()
                print(f"  JSON code: {j.get('code')}, keys: {list(j.keys())[:5]}")
            except:
                pass
    except Exception as e:
        print(f"  Error: {e}")

# Try to find review API from the page JS
print("\n=== Search for review API in shop page ===")
r = requests.get(f'https://www.dianping.com/shop/{test_uuid}', headers=hdrs, timeout=10)
# Find all JS file URLs
js_urls = re.findall(r'src="(https?://[^"]*\.js[^"]*)"', r.text)
print(f"Found {len(js_urls)} JS files")
# Look for review-related JS
review_js = [u for u in js_urls if 'review' in u.lower() or 'comment' in u.lower() or 'ugc' in u.lower()]
print(f"Review-related JS: {review_js[:5]}")

# Look for review component configuration
review_config = re.findall(r'reviewList|reviewAll|review_api|reviewUrl|commentList', r.text)
print(f"Review config references: {list(set(review_config))}")
