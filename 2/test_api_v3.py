import json, time, zlib, base64, requests, re
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

test_id = 'EOeLXrY2fCUUC7ur'

# Test review_all with allow_redirects=True
print("=== Test review_all (follow redirects) ===")
r = requests.get(f'http://www.dianping.com/shop/{test_id}/review_all', headers=hdrs, timeout=10, allow_redirects=True)
print(f"Status: {r.status_code}")
print(f"Final URL: {r.url}")
print(f"Content length: {len(r.text)}")
if 'verify' in r.url:
    print("BLOCKED: verify page")
elif 'app-m-user-growth' in r.url:
    print("REDIRECTED to app download")
elif 'review-words' in r.text or 'review-rank' in r.text:
    print("SUCCESS: Found review page!")
else:
    # Show what we got
    title_match = re.search(r'<title>(.*?)</title>', r.text)
    print(f"Title: {title_match.group(1) if title_match else 'N/A'}")
    print(f"Preview: {r.text[:200]}")

# Test allReview API with correct shop_url format
print("\n=== Test allReview API ===")
shop_url = f'http://www.dianping.com/shop/{test_id}'
url = (f'http://www.dianping.com/ajax/json/shopDynamic/allReview?'
       f'shopId={test_id}&cityId=2&shopType=10&tcv={TCV}'
       f'&_token={get_token(shop_url)}&uuid={UUID}'
       f'&platform=1&partner=150&optimusCode=10'
       f'&originUrl={shop_url}')
r = requests.get(url, headers=hdrs, timeout=10)
print(f"Status: {r.status_code}")
print(f"URL: {r.url}")
if r.status_code == 200:
    try:
        r_json = r.json()
        print(f"Code: {r_json.get('code')}")
        if r_json.get('code') == 200:
            reviews = r_json.get('reviewAllDOList', [])
            print(f"Reviews: {len(reviews)}")
            if reviews:
                rv = reviews[0]
                print(f"First review user: {rv.get('user',{}).get('userNickName','N/A')}")
                rvd = rv.get('reviewDataVO',{}).get('reviewData',{})
                print(f"First review body: {BeautifulSoup(rvd.get('reviewBody',''), 'lxml').text[:100]}")
                print(f"First review time: {rv.get('addTimeVO','N/A')}")
        else:
            print(f"Response: {json.dumps(r_json, ensure_ascii=False)[:300]}")
    except:
        print(f"Not JSON: {r.text[:300]}")

# Test basicHideInfo API
print("\n=== Test basicHideInfo API ===")
url = (f'http://www.dianping.com/ajax/json/shopDynamic/basicHideInfo?'
       f'shopId={test_id}&_token={get_token(shop_url)}&tcv={TCV}'
       f'&uuid={UUID}&platform=1&partner=150&optimusCode=10'
       f'&originUrl={shop_url}')
r = requests.get(url, headers=hdrs, timeout=10)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    try:
        r_json = r.json()
        print(f"Code: {r_json.get('code')}")
        if r_json.get('code') == 200:
            si = r_json.get('msg',{}).get('shopInfo',{})
            print(f"Name: {si.get('shopName','N/A')}")
            print(f"Address: {si.get('address','N/A')}")
            print(f"Phone: {si.get('phoneNo','N/A')}")
        else:
            print(f"Response: {json.dumps(r_json, ensure_ascii=False)[:300]}")
    except:
        print(f"Not JSON: {r.text[:300]}")

# Test shop page
print("\n=== Test shop page ===")
r = requests.get(f'https://www.dianping.com/shop/{test_id}', headers=hdrs, timeout=10, allow_redirects=True)
print(f"Status: {r.status_code}")
print(f"Final URL: {r.url}")
print(f"Content length: {len(r.text)}")
if 'verify' in r.url:
    print("BLOCKED: verify page")
elif 'shop-info' in r.text:
    print("SUCCESS: Got shop page")
else:
    title = re.search(r'<title>(.*?)</title>', r.text)
    print(f"Title: {title.group(1) if title else 'N/A'}")
