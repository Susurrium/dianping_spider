import requests, re

COOKIE = "_lxsdk_cuid=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _lxsdk=19e45df333ac8-046baec83fa01a-1f462c69-3e8000-19e45df333a82; _hc.v=88b2d96c-ad17-e5a2-6d0c-5d2e20c1bd63.1779288716; fspop=test; WEBDFPID=4x70y2389vx355330997125wzuwzww9u80v5397z82347958712u99w4-1779377438096-1779291037261IOMYUEKa12a6b8169ee7736639f3ec62dbf984b2807; utm_source_rg=AM%25708xNxe%25335%25TMjwSvilW.MiLLiiwWWjsvLzKyzKzzWylw.LiWjKlviTjWLljsvyWWzT; qruuid=1fa6be57-dcab-47f6-ac6d-8c3b56d3093c; dplet=b2ac0b75ddab3a6a2d056c20c4ffadf9; dper=0202a723fbea7bc1c09233c032cf45cb418bb1548c92bce28870503bfd6d210ef7603feca9e6cc3e291033e2343b76202e5ce7e72a7cc7cbbf280000000011350000eff652b3922ec5784bf0f8da23c01ef9217da05bb680e96f1616ea25f826e2b0900b3db778d33acec1cda77a6cc78246; ll=7fd06e815b796be3df069dec7836c3df; ua=P.L.M; ctu=52b268528df1375dd8a48a83401d879e5b928492a25815857c46fbf11a5a147a; logan_session_token=o20v4ueuv1q9hmqgy8qx; _lxsdk_s=19e46029caa-b20-09-3de%7C%7C72"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
hdrs = {'User-Agent': UA, 'Cookie': COOKIE, 'Referer': 'http://www.dianping.com/'}

test_uuid = 'EOeLXrY2fCUUC7ur'
r = requests.get(f'https://www.dianping.com/shop/{test_uuid}', headers=hdrs, timeout=10)

# Find ALL script src attributes (including dynamically loaded)
all_scripts = re.findall(r'<script[^>]*src="([^"]*)"', r.text)
print(f"All script srcs ({len(all_scripts)}):")
for s in all_scripts:
    print(f"  {s}")

# Find dynamic script loading patterns
dynamic_loads = re.findall(r'["\']([^"\']*(?:component|chunk|review|ugc|comment)[^"\']*\.js[^"\']*)["\']', r.text, re.I)
print(f"\nDynamic script loads:")
for d in dynamic_loads:
    print(f"  {d}")

# Find webpack chunks
chunks = re.findall(r'["\']([^"\']*chunk[^"\']*\.js[^"\']*)["\']', r.text, re.I)
print(f"\nWebpack chunks:")
for c in chunks:
    print(f"  {c}")

# Find any URL that might be the review API
print("\n=== All dianping URLs in page ===")
all_urls = re.findall(r'(//[^"\'>\s]*(?:dianping|meituan)[^"\'>\s]*)', r.text)
unique_urls = list(set([u for u in all_urls if '.js' not in u and '.css' not in u and '.png' not in u]))
for u in sorted(unique_urls)[:30]:
    print(f"  {u}")

# Look for data-component or lazy load patterns
print("\n=== Component loading patterns ===")
comp_patterns = re.findall(r'(?:load|import|require|mount)\s*\([^)]*(?:review|Review|ugc|UGC)[^)]*\)', r.text)
for p in comp_patterns:
    print(f"  {p}")

# Look for any API call pattern in the main JS
print("\n=== Main JS analysis ===")
for s in all_scripts:
    if 'dp common' in s or 'main' in s or 'app' in s or 'shop' in s:
        full_url = 'https:' + s if s.startswith('//') else s
        try:
            jr = requests.get(full_url, headers=hdrs, timeout=10)
            if jr.status_code == 200:
                text = jr.text
                # Find all API paths
                api_paths = re.findall(r'["\']/(ajax|api|mapi)/[^"\']+["\']', text)
                if api_paths:
                    print(f"\nJS: {s[:60]}")
                    for p in list(set(api_paths))[:20]:
                        print(f"  /{p}")
                # Find review-specific paths
                review_paths = re.findall(r'["\']([^"\']*review[^"\']*)["\']', text, re.I)
                if review_paths:
                    print(f"\nReview paths in {s[:60]}:")
                    for p in list(set(review_paths))[:10]:
                        print(f"  {p}")
        except:
            pass
