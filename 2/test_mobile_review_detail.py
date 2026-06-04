import requests, re, json
from bs4 import BeautifulSoup

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
hdrs = {'User-Agent': MOBILE_UA, 'Cookie': COOKIE, 'Referer': 'https://m.dianping.com/'}

test_uuid = 'EOeLXrY2fCUUC7ur'

# Get page 1
r = requests.get(f'https://m.dianping.com/shop/{test_uuid}/review_all', headers=hdrs, timeout=10)
soup = BeautifulSoup(r.text, 'lxml')

print("=== Review Items ===")
reviews = soup.select('.review-item')
print(f"Found {len(reviews)} reviews\n")

for i, review in enumerate(reviews[:5]):
    print(f"--- Review {i+1} ---")
    # Username
    username_el = review.select('.seed-author-name, .name, .userName')
    username = username_el[0].text.strip() if username_el else 'N/A'
    print(f"  Username: {username}")
    
    # Review text
    text_el = review.select('.review-words, .seed-feed-content, .desc, .content')
    text = text_el[0].text.strip() if text_el else 'N/A'
    print(f"  Text: {text[:100]}")
    
    # Publish time
    time_el = review.select('.time, .publish-time, .date, .seed-time')
    pub_time = time_el[0].text.strip() if time_el else 'N/A'
    print(f"  Time: {pub_time}")
    
    # Star rating
    star_el = review.select('.star, .rating, .score')
    star = star_el[0].text.strip() if star_el else 'N/A'
    print(f"  Star: {star}")
    
    # Print all text in the review item
    all_text = review.get_text(separator=' | ', strip=True)
    print(f"  Full text: {all_text[:200]}")
    print()

# Check pagination
print("\n=== Pagination ===")
page_links = soup.select('.page a, .pagination a, [class*="page"] a')
print(f"Page links found: {len(page_links)}")
for link in page_links[:10]:
    print(f"  {link.text.strip()}: {link.get('href', 'N/A')}")

# Check for load more button
load_more = soup.select('.load-more, .more-btn, [class*="loadMore"], [class*="more"]')
print(f"\nLoad more elements: {len(load_more)}")
for lm in load_more:
    print(f"  {lm.get('class')}: {lm.text.strip()[:50]}")

# Try page 2
print("\n=== Page 2 ===")
r2 = requests.get(f'https://m.dianping.com/shop/{test_uuid}/review_all/p2', headers=hdrs, timeout=10)
print(f"Status: {r2.status_code}, Final URL: {r2.url}, Len: {len(r2.text)}")
if r2.status_code == 200 and 'review-item' in r2.text:
    soup2 = BeautifulSoup(r2.text, 'lxml')
    reviews2 = soup2.select('.review-item')
    print(f"Page 2 reviews: {len(reviews2)}")
    if reviews2:
        r0 = reviews2[0]
        username = r0.select('.seed-author-name')
        text = r0.select('.seed-feed-content, .desc')
        print(f"  First review username: {username[0].text.strip() if username else 'N/A'}")
        print(f"  First review text: {text[0].text.strip()[:100] if text else 'N/A'}")
