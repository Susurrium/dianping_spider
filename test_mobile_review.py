import requests, re, json
from bs4 import BeautifulSoup

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
hdrs_mobile = {'User-Agent': MOBILE_UA, 'Cookie': COOKIE, 'Referer': 'https://m.dianping.com/'}

test_uuid = 'EOeLXrY2fCUUC7ur'

# Get mobile review page
print("=== Mobile review_all page ===")
r = requests.get(f'https://m.dianping.com/shop/{test_uuid}/review_all', headers=hdrs_mobile, timeout=10)
print(f"Status: {r.status_code}, Len: {len(r.text)}")

# Check for embedded JSON data
print("\n=== Embedded JSON/window data ===")
# Look for window.__INITIAL_STATE__ or similar
json_patterns = [
    r'window\.__INITIAL_STATE__\s*=\s*({.*?});?\s*</script>',
    r'window\.__NEXT_DATA__\s*=\s*({.*?});?\s*</script>',
    r'window\.__NUXT__\s*=\s*({.*?});?\s*</script>',
    r'window\.__data__\s*=\s*({.*?});?\s*</script>',
    r'window\.initialData\s*=\s*({.*?});?\s*</script>',
    r'window\.__shopData__\s*=\s*({.*?});?\s*</script>',
]
for pattern in json_patterns:
    match = re.search(pattern, r.text, re.S)
    if match:
        print(f"Found: {pattern[:40]}")
        try:
            data = json.loads(match.group(1))
            print(f"Keys: {list(data.keys())[:10]}")
            print(f"Preview: {json.dumps(data, ensure_ascii=False)[:300]}")
        except:
            print(f"Parse failed, len={len(match.group(1))}")

# Look for review data in any format
print("\n=== Review content patterns ===")
# Check for JSON data embedded in the page
all_json_blocks = re.findall(r'<script[^>]*>({[^<]*"review[^<]*})</script>', r.text, re.I)
print(f"JSON blocks with 'review': {len(all_json_blocks)}")
for block in all_json_blocks[:2]:
    print(f"  {block[:200]}")

# Parse the HTML for review elements
soup = BeautifulSoup(r.text, 'lxml')
print("\n=== HTML analysis ===")
# Look for review items
review_selectors = ['.review-item', '.review-list-item', '.comment-item', 
                     '[class*="review"]', '[class*="comment"]', '.list-wrapper li']
for sel in review_selectors:
    items = soup.select(sel)
    if items:
        print(f"Found {sel}: {len(items)} items")
        if len(items) > 0:
            first = items[0]
            print(f"  First item HTML: {str(first)[:300]}")

# Check for any data attributes
print("\n=== Data attributes ===")
data_elements = soup.find_all(attrs={"data-review-id": True})
print(f"Elements with data-review-id: {len(data_elements)}")
data_elements2 = soup.find_all(attrs={"data-id": True})
print(f"Elements with data-id: {len(data_elements2)}")

# Look for the page title and key text
print(f"\nTitle: {soup.title.string if soup.title else 'N/A'}")

# Check for __xhrCache__ in mobile version
print("\n=== __xhrCache__ ===")
cache_match = re.search(r'window\.__xhrCache__\s*=\s*({.*?});?\s*</script>', r.text, re.S)
if cache_match:
    try:
        cache_data = json.loads(cache_match.group(1))
        for key in cache_data:
            if 'review' in key.lower():
                print(f"\nReview key: {key}")
                print(f"  Data: {json.dumps(cache_data[key], ensure_ascii=False)[:500]}")
            else:
                print(f"Key: {key[:80]}")
    except:
        print("Parse failed")
else:
    print("No __xhrCache__ found")
    # Try other patterns
    for pattern in [r'reviewAllDOList', r'reviewList', r'reviewData']:
        matches = re.findall(pattern, r.text)
        if matches:
            print(f"Found '{pattern}' {len(matches)} times")
