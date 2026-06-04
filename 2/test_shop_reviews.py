import requests, re, json
from bs4 import BeautifulSoup

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
hdrs = {'User-Agent': UA, 'Cookie': COOKIE, 'Referer': 'http://www.dianping.com/'}

test_id = 'EOeLXrY2fCUUC7ur'
r = requests.get(f'https://www.dianping.com/shop/{test_id}', headers=hdrs, timeout=10)

# Find review section and all xhrCache data
print("=== __xhrCache__ data ===")
cache_match = re.search(r'window\.__xhrCache__\s*=\s*({.*?});?\s*</script>', r.text, re.S)
if cache_match:
    try:
        cache_data = json.loads(cache_match.group(1))
        for key in cache_data:
            print(f"\nKey: {key}")
            data = cache_data[key].get('data', {})
            if isinstance(data, dict):
                print(f"  Code: {data.get('code')}")
                # Look for review data
                if 'reviewDataList' in str(data)[:500]:
                    print(f"  HAS REVIEW DATA!")
                    print(f"  Data preview: {json.dumps(data, ensure_ascii=False)[:500]}")
                else:
                    print(f"  Data keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
                    print(f"  Data preview: {json.dumps(data, ensure_ascii=False)[:200]}")
    except:
        print(f"Parse failed, raw: {cache_match.group(1)[:500]}")

# Find review count in HTML
print("\n=== Review count ===")
soup = BeautifulSoup(r.text, 'lxml')
review_count_el = soup.find(class_=re.compile(r'review.*count|comment.*count', re.I))
if review_count_el:
    print(f"Found: {review_count_el.text.strip()}")

# Check for review section
print("\n=== Review section in HTML ===")
review_section = soup.find(id=re.compile(r'review', re.I))
if review_section:
    print(f"Found id: {review_section.get('id')}")
    print(str(review_section)[:300])

# Look for all data-* attributes with review info
print("\n=== Script tags mentioning review/ajax ===")
for s in soup.find_all('script'):
    text = (s.string or '')
    if ('review' in text.lower() or 'ajax' in text.lower() or 'api' in text.lower()) and len(text) > 10:
        # Find URL patterns
        urls = re.findall(r'["\']([^"\']*(?:review|ajax|api)[^"\']*)["\']', text, re.I)
        if urls:
            for u in urls[:5]:
                print(f"  URL: {u}")

# Find total review count
print("\n=== All text containing '评论' or '条' ===")
review_patterns = re.findall(r'(\d+)\s*[条评论]', r.text)
print(f"Review count patterns: {review_patterns[:5]}")
