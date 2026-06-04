import requests, re, json
from bs4 import BeautifulSoup

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
hdrs = {'User-Agent': UA, 'Cookie': COOKIE, 'Referer': 'http://www.dianping.com/'}

test_uuid = 'EOeLXrY2fCUUC7ur'
r = requests.get(f'https://www.dianping.com/shop/{test_uuid}', headers=hdrs, timeout=10)
soup = BeautifulSoup(r.text, 'lxml')

# Check the review component area
print("=== Review component ===")
review_comp = soup.select('#review-list-new-pc')
if review_comp:
    print(f"Found, HTML length: {len(str(review_comp[0]))}")
    print(f"HTML: {str(review_comp[0])[:500]}")

# Look for any review data in __xhrCache__ that might have review info
print("\n=== __xhrCache__ full analysis ===")
cache_match = re.search(r'window\.__xhrCache__\s*=\s*({.*?});?\s*</script>', r.text, re.S)
if cache_match:
    cache_data = json.loads(cache_match.group(1))
    for key, val in cache_data.items():
        data = val.get('data', {})
        # Check for any review-related data
        data_str = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)
        if 'review' in data_str.lower() or 'comment' in data_str.lower() or '点评' in data_str:
            print(f"\nKey: {key[:100]}")
            print(f"Data: {data_str[:500]}")

# Look for embedded review data in script tags
print("\n=== Embedded review data in scripts ===")
for s in soup.find_all('script'):
    text = s.string or ''
    if len(text) > 200:
        # Look for review arrays/objects
        if 'reviewAllDOList' in text or 'reviewData' in text or 'reviewList' in text:
            print(f"Found review data in script: {text[:300]}")
        # Look for shop data that might contain review count
        if 'reviewCount' in text or 'commentCount' in text:
            matches = re.findall(r'"(\w*[Rr]eview\w*Count\w*)":\s*"?(\d+)"?', text)
            if matches:
                print(f"Review counts: {matches}")

# Check all data in the unified shop API response
print("\n=== Unified shop API review info ===")
for key, val in cache_data.items():
    if 'unify' in key or 'shop.bin' in key:
        data = val.get('data', {})
        if isinstance(data, dict):
            # Look for review-related fields
            for k, v in data.items():
                if 'review' in k.lower() or 'comment' in k.lower() or 'vote' in k.lower():
                    print(f"  {k}: {v}")

# Check the review count in the page
print("\n=== Review count on page ===")
review_count_match = re.search(r'评价\((\d+)\)', r.text)
if review_count_match:
    print(f"Review count from HTML: {review_count_match.group(1)}")

# Check for any pagination-related JS
print("\n=== Review list component config ===")
review_attrs = soup.select('[shop-type], [city-id], [shop-category-id]')
for el in review_attrs:
    print(f"  Tag: {el.name}, Attrs: {dict(el.attrs)}")
