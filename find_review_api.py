import requests, re

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
hdrs = {'User-Agent': UA, 'Cookie': COOKIE, 'Referer': 'http://www.dianping.com/'}

test_uuid = 'EOeLXrY2fCUUC7ur'
r = requests.get(f'https://www.dianping.com/shop/{test_uuid}', headers=hdrs, timeout=10)

# Find all JS bundle URLs
js_urls = re.findall(r'src="(//[^"]*\.js[^"]*)"', r.text)
print(f"Found {len(js_urls)} JS files")

# Filter for review/component related JS
for url in js_urls:
    full_url = 'https:' + url if url.startswith('//') else url
    # Download and search for review API
    try:
        jr = requests.get(full_url, headers=hdrs, timeout=10)
        if jr.status_code == 200:
            text = jr.text
            # Look for review API patterns
            review_apis = re.findall(r'["\']([^"\']*(?:review|Review)[^"\']*)["\']', text)
            if review_apis:
                # Filter for API-like URLs
                api_like = [a for a in review_apis if ('/' in a and len(a) < 200) or 'api' in a.lower() or 'ajax' in a.lower()]
                if api_like:
                    print(f"\nJS: {url[:80]}")
                    for a in api_like[:10]:
                        print(f"  {a}")
            
            # Also look for fetch/axios calls with review
            fetch_calls = re.findall(r'(?:fetch|axios|get|post)\s*\(\s*["\']([^"\']*(?:review|ugc|comment)[^"\']*)["\']', text, re.I)
            if fetch_calls:
                print(f"\nFetch calls in {url[:60]}:")
                for f in fetch_calls[:5]:
                    print(f"  {f}")
    except:
        pass

# Also look for the review component specifically
print("\n=== Looking for component-review-list-v2 ===")
for url in js_urls:
    full_url = 'https:' + url if url.startswith('//') else url
    try:
        jr = requests.get(full_url, headers=hdrs, timeout=10)
        if 'review-list' in jr.text or 'reviewList' in jr.text or 'ReviewList' in jr.text:
            print(f"\nFound review component in: {url[:80]}")
            # Extract API endpoints
            apis = re.findall(r'["\']([^"\']*(?:\/ajax\/|\/api\/|\/mapi\/)[^"\']*(?:review|ugc|comment)[^"\']*)["\']', jr.text, re.I)
            if apis:
                for a in apis[:10]:
                    print(f"  API: {a}")
            # Also find base URLs
            bases = re.findall(r'["\']([^"\']*(?:dianping|meituan)[^"\']*(?:review|ugc)[^"\']*)["\']', jr.text, re.I)
            if bases:
                for b in bases[:10]:
                    print(f"  Base: {b}")
    except:
        pass
