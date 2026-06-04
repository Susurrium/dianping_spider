import requests, re, json
from bs4 import BeautifulSoup

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
hdrs = {'User-Agent': UA, 'Cookie': COOKIE, 'Referer': 'http://www.dianping.com/'}

test_id = 'EOeLXrY2fCUUC7ur'
r = requests.get(f'https://www.dianping.com/shop/{test_id}', headers=hdrs, timeout=10)
soup = BeautifulSoup(r.text, 'lxml')

# 1. Check shop page for review data
print("=== Shop page title ===")
print(soup.title.string if soup.title else 'N/A')

# 2. Look for review sections in the shop page
print("\n=== Review sections ===")
review_items = soup.select('.review-item, .reviews-items, .review-list, .brief-review')
print(f"Review items found: {len(review_items)}")

# 3. Look for review data in script tags
print("\n=== Script tags with data ===")
scripts = soup.find_all('script')
for s in scripts:
    text = s.string or ''
    if 'review' in text.lower() and len(text) > 50:
        print(f"Script with 'review': {text[:200]}...")
        print("---")

# 4. Look for any ajax/API endpoint references
print("\n=== AJAX endpoint references ===")
all_text = r.text
api_refs = re.findall(r'(ajax/[a-zA-Z/]+)', all_text)
print(f"API references: {list(set(api_refs))[:20]}")

# 5. Look for review section HTML
print("\n=== Review HTML samples ===")
review_section = soup.select('.reviews-items')
if review_section:
    print(f"Found reviews-items: {len(review_section)}")
    print(str(review_section[0])[:500])
else:
    # Try other selectors
    for sel in ['.review-list', '.review-list-ul', '.reviews-container', '#review-list', '.review-wrapper']:
        items = soup.select(sel)
        if items:
            print(f"Found {sel}: {len(items)} elements")
            print(str(items[0])[:300])
            break

# 6. Look for review link
review_links = re.findall(r'href="([^"]*review[^"]*)"', r.text)
print(f"\nReview links: {review_links[:5]}")

# 7. Check what's actually on the page
print("\n=== Main content sections ===")
for cls in ['shop-info', 'shop-header', 'review', 'comment', '评分', '点评']:
    elements = soup.find_all(class_=re.compile(cls, re.I))
    if elements:
        print(f"Found class matching '{cls}': {len(elements)} elements")

# 8. Look for data in JSON-LD or meta tags
json_ld = soup.select('script[type="application/ld+json"]')
for jl in json_ld:
    try:
        data = json.loads(jl.string)
        print(f"\nJSON-LD: {json.dumps(data, ensure_ascii=False)[:300]}")
    except:
        pass
