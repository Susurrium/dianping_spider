import requests, re
from bs4 import BeautifulSoup

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
hdrs = {'User-Agent': MOBILE_UA, 'Cookie': COOKIE}

test_uuid = 'EOeLXrY2fCUUC7ur'
r = requests.get(f'https://m.dianping.com/shop/{test_uuid}/review_all', headers=hdrs, timeout=10)
soup = BeautifulSoup(r.text, 'lxml')

# Print first review item's HTML in detail
reviews = soup.select('.review-item')
if reviews:
    print("=== First review item HTML (formatted) ===")
    print(reviews[0].prettify()[:2000])
    
    print("\n=== Second review item HTML ===")
    if len(reviews) > 1:
        print(reviews[1].prettify()[:2000])

# Look for pagination/load-more patterns in the JS
print("\n=== Pagination patterns in HTML ===")
# Look for any link or button that loads more
all_elements = soup.find_all(['a', 'button', 'div'], attrs={'class': True})
for el in all_elements:
    classes = ' '.join(el.get('class', []))
    if 'page' in classes.lower() or 'next' in classes.lower() or 'more' in classes.lower() or 'load' in classes.lower():
        print(f"  Tag: {el.name}, Class: {classes}, Text: {el.text.strip()[:50]}, Href: {el.get('href', 'N/A')}")

# Look for JS that handles pagination
scripts = soup.find_all('script')
for s in scripts:
    text = s.string or ''
    if 'page' in text.lower() and ('review' in text.lower() or 'load' in text.lower()):
        # Extract relevant portions
        page_patterns = re.findall(r'[\'"]([^"\']*(?:page|load|more)[^"\']*)[\'"]', text, re.I)
        if page_patterns:
            print(f"\nJS page patterns: {page_patterns[:10]}")
            break
