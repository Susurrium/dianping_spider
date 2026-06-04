import requests, re, json
from bs4 import BeautifulSoup

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
hdrs = {'User-Agent': MOBILE_UA, 'Cookie': COOKIE}

test_uuid = 'EOeLXrY2fCUUC7ur'
numeric_id = '14878552'

# Try different pagination patterns
print("=== Trying different pagination patterns ===")
patterns = [
    f'https://m.dianping.com/shop/{test_uuid}/review_all?page=2',
    f'https://m.dianping.com/shop/{test_uuid}/review_all?nextCursor=2',
    f'https://m.dianping.com/shop/{test_uuid}/review_all?offset=5',
]
for url in patterns:
    r = requests.get(url, headers=hdrs, timeout=10, allow_redirects=True)
    has_reviews = 'review-item' in r.text
    print(f"  {url.split('?')[1]}: status={r.status_code}, reviews={has_reviews}, final={r.url}")

# Look for API in mobile page JS
print("\n=== Mobile page JS analysis ===")
r = requests.get(f'https://m.dianping.com/shop/{test_uuid}/review_all', headers=hdrs, timeout=10)

# Find all script content that might have review API
scripts = BeautifulSoup(r.text, 'lxml').find_all('script')
for s in scripts:
    text = s.string or ''
    if len(text) > 100:
        # Look for review-related API URLs
        api_urls = re.findall(r'["\']([^"\']*(?:review|ugc|comment)[^"\']*)["\']', text, re.I)
        if api_urls:
            for u in api_urls[:5]:
                if 'http' in u or '//' in u or '/api' in u or '/ajax' in u:
                    print(f"  API: {u}")

        # Look for page/cursor/offset patterns
        page_patterns = re.findall(r'["\']([^"\']*(?:page|cursor|offset|next)[^"\']*)["\']', text, re.I)
        if page_patterns:
            for p in page_patterns[:5]:
                print(f"  Page pattern: {p}")

# Also check if there's a specific mobile API for reviews
print("\n=== Mobile API endpoints ===")
mobile_apis = [
    f'https://m.dianping.com/ugclist/list?shopId={numeric_id}&type=1&page=1',
    f'https://m.dianping.com/ugclist/shopreview?shopUuid={test_uuid}&page=1',
    f'https://m.dianping.com/api/review/list?shopId={numeric_id}&page=1',
]
for api_url in mobile_apis:
    try:
        r = requests.get(api_url, headers=hdrs, timeout=10, allow_redirects=True)
        print(f"  {api_url.split('.com/')[1]}: status={r.status_code}, len={len(r.text)}")
        if r.status_code == 200 and 'review' in r.text.lower()[:200]:
            print(f"    Found review data! Preview: {r.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")

# Check for __INITIAL_STATE__ or page data
print("\n=== Page data extraction ===")
state_patterns = [
    r'window\.__INITIAL_STATE__\s*=\s*(.+?)(?:;?\s*</script>)',
    r'window\.__NEXT_DATA__\s*=\s*(.+?)(?:;?\s*</script>)',
    r'window\.pageData\s*=\s*(.+?)(?:;?\s*</script>)',
    r'window\.initialData\s*=\s*(.+?)(?:;?\s*</script>)',
    r'"pageInitData":\s*(\{.+?\})',
]
for pattern in state_patterns:
    match = re.search(pattern, r.text, re.S)
    if match:
        print(f"Found pattern: {pattern[:40]}")
        data_str = match.group(1)[:500]
        print(f"  Data: {data_str}")
        try:
            data = json.loads(match.group(1).rstrip(';'))
            print(f"  Parsed keys: {list(data.keys())[:10]}")
        except:
            pass
