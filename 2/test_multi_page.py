import requests, time
from bs4 import BeautifulSoup

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
hdrs = {'User-Agent': MOBILE_UA, 'Cookie': COOKIE}

test_uuid = 'EOeLXrY2fCUUC7ur'

def extract_reviews(html):
    soup = BeautifulSoup(html, 'lxml')
    reviews = soup.select('.review-item')
    results = []
    for r in reviews:
        username = r.select_one('.seed-user-name')
        time_el = r.select_one('.seed-add-time')
        text_el = r.select_one('.seed-feed-content-txt')
        star_el = r.select('.seed-star_icon .seed-star')
        
        # Get star rating from class
        star = ''
        if star_el:
            star_class = star_el[0].get('class', [])
            for c in star_class:
                if 'seed-star_' in c:
                    star = c.replace('seed-star_', '').replace('_', '.')
                    break
        
        results.append({
            'username': username.text.strip() if username else '-',
            'time': time_el.text.strip() if time_el else '-',
            'text': text_el.text.strip() if text_el else '-',
            'star': star
        })
    return results

# Test pages 1-3
for page in [1, 2, 3]:
    url = f'https://m.dianping.com/shop/{test_uuid}/review_all?page={page}' if page > 1 else f'https://m.dianping.com/shop/{test_uuid}/review_all'
    r = requests.get(url, headers=hdrs, timeout=10)
    reviews = extract_reviews(r.text)
    print(f"\n=== Page {page} ({len(reviews)} reviews) ===")
    for i, rev in enumerate(reviews):
        print(f"  {i+1}. [{rev['time']}] {rev['username']}: {rev['text'][:60]}...")
    time.sleep(0.5)

# Find max pages
print("\n=== Finding max page ===")
for page in [50, 100, 200, 300, 500]:
    url = f'https://m.dianping.com/shop/{test_uuid}/review_all?page={page}'
    r = requests.get(url, headers=hdrs, timeout=10)
    reviews = extract_reviews(r.text)
    print(f"  Page {page}: {len(reviews)} reviews")
    if len(reviews) == 0:
        # Binary search for max page
        low, high = page // 2, page
        while low < high:
            mid = (low + high + 1) // 2
            url = f'https://m.dianping.com/shop/{test_uuid}/review_all?page={mid}'
            r = requests.get(url, headers=hdrs, timeout=10)
            reviews = extract_reviews(r.text)
            if len(reviews) > 0:
                low = mid
            else:
                high = mid - 1
            time.sleep(0.3)
        print(f"  Max page with reviews: {low}")
        break
    time.sleep(0.3)
