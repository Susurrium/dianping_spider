# -*- coding:utf-8 -*-
import json, os, csv, re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse
from mitmproxy import http

from dianping_events import append_event, build_event

ROOT_DIR = Path(__file__).resolve().parent
CAPTURE_NAMESPACE = os.environ.get("DP_CAPTURE_NAMESPACE", "").strip().strip("/\\")
CAPTURE_APPIDS = {
    item.strip()
    for item in os.environ.get("DP_CAPTURE_APPIDS", "").split(",")
    if item.strip()
}
LOG_DIR = str(ROOT_DIR / "mitm_logs" / CAPTURE_NAMESPACE) if CAPTURE_NAMESPACE else str(ROOT_DIR / "mitm_logs")
os.makedirs(LOG_DIR, exist_ok=True)
CREDENTIALS_FILE = os.path.join(LOG_DIR, 'captured_credentials.json')

# 最新的mini程序凭证（搜索+评论）
WX_CREDS_FILE = os.path.join(LOG_DIR, 'wx_credentials.json')
REPLAY_TEMPLATE_FILE = os.path.join(LOG_DIR, 'replay_template.json')
EVENTS_FILE = os.path.join(LOG_DIR, 'events.jsonl')
SEARCH_TARGET_FILE = os.path.join(LOG_DIR, 'current_search_target.json')
SEARCH_URL_MARKERS = (
    'wxsearch/search',
    'searchshop',
    'minitakeoutsearch.bin',
    '/group/v1/deal/searchpage/hotword/',
    '/group/v1/deal/search/suggest/',
    '/group/v4/poi/search/miniprogram/',
)
REVIEW_URL_MARKERS = (
    'outsidesiftedreviewlist',
    'outsideshopreviewlist',
    'shopreview',
)


def _is_meituan_web_review_url(lower_url: str) -> bool:
    return any(
        marker in lower_url
        for marker in (
            '/web/poi/',
            '/web/deal/',
            '/brunch/applet/review',
        )
    ) and any(suffix in lower_url for suffix in ('comments', 'overallcomment', 'commenttags', 'review'))


def request(flow: http.HTTPFlow) -> None:
    if os.environ.get('DP_SEARCH_REWRITE', '').lower() not in {'1', 'true', 'yes'}:
        return
    url = flow.request.url.lower()
    if not any(marker in url for marker in SEARCH_URL_MARKERS):
        return
    target = _load_search_target()
    if not target:
        return
    keyword = str(target.get('keyword') or '').strip()
    city_id = str(target.get('cityId') or '').strip()
    if not keyword:
        return
    params = dict(flow.request.query)
    changed = apply_search_override_to_params(params, keyword, city_id)
    body_changed, request_body = apply_search_override_to_flow_body(flow, keyword, city_id)
    if not changed:
        if not body_changed:
            return
        request_body = request_body or {}
    flow.request.url = rewrite_url_query(flow.request.url, params)
    if body_changed:
        flow.request.headers['content-type'] = 'application/json'
        flow.request.text = json.dumps(request_body, ensure_ascii=False, separators=(',', ':'))
    print(f"🔁 搜索改写: keyword={keyword} cityId={city_id or flow.request.query.get('cityId', '')}")


def _load_search_target():
    try:
        data = json.loads(Path(SEARCH_TARGET_FILE).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) and data.get('enabled', True) else {}


def apply_search_override_to_params(params, keyword, city_id=''):
    if not isinstance(params, dict) or not keyword:
        return False
    params['keyword'] = keyword
    if city_id:
        params['cityId'] = city_id
    if 'categoryId' in params:
        params['categoryId'] = '0'
    if 'filterCategory' in params:
        params.pop('filterCategory', None)
    if 'start' in params:
        params['start'] = '0'
    if 'mtsiReferrer' in params:
        updates = {'keyword': keyword}
        if city_id:
            updates['cityId'] = city_id
        params['mtsiReferrer'] = rewrite_referrer_query(params.get('mtsiReferrer', ''), updates)
    return True


def apply_search_override_to_flow_body(flow, keyword, city_id=''):
    try:
        body = json.loads(flow.request.text or '{}')
    except (TypeError, ValueError):
        return False, None
    if not isinstance(body, dict):
        return False, None
    changed = apply_search_override_to_body(body, keyword, city_id)
    return changed, body


def apply_search_override_to_body(body, keyword, city_id=''):
    if not isinstance(body, dict) or not keyword:
        return False
    body['keyword'] = keyword
    if city_id:
        body['cityId'] = str(city_id)
        body['selectedCityId'] = str(city_id)
    if 'categoryId' in body:
        body['categoryId'] = '0'
    if 'filterCategory' in body:
        body.pop('filterCategory', None)
    if 'start' in body:
        body['start'] = '0'
    if 'pageIndex' in body:
        body['pageIndex'] = '0'
    if 'mtsiReferrer' in body:
        updates = {'keyword': keyword}
        if city_id:
            updates['cityId'] = city_id
        body['mtsiReferrer'] = rewrite_referrer_query(body.get('mtsiReferrer', ''), updates)
    return True


def rewrite_referrer_query(referrer, updates):
    decoded = unquote(str(referrer or ''))
    if '?' not in decoded:
        return quote(decoded, safe='')
    path, query = decoded.split('?', 1)
    parsed = parse_qs(query, keep_blank_values=True)
    for key, value in updates.items():
        parsed[key] = [str(value)]
    rewritten_query = urlencode(parsed, doseq=True)
    return quote(f'{path}?{rewritten_query}', safe='%')


def rewrite_url_query(url, updates):
    parsed = urlparse(str(url))
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in updates.items():
        query[str(key)] = [str(value)]
    rewritten_query = urlencode(query, doseq=True)
    return parsed._replace(query=rewritten_query).geturl()

def response(flow: http.HTTPFlow) -> None:
    url = flow.request.url
    if not any(domain in url for domain in ['dianping.com', 'meituan.com']):
        return
    if CAPTURE_APPIDS:
        appid = flow.request.query.get("csecappid", "")
        if appid not in CAPTURE_APPIDS:
            return
    if any(ext in url for ext in ['.png','.jpg','.jpeg','.gif','.css','.js','.woff','.svg','.ico','.webp']):
        return

    # 保存所有dianping请求的完整凭证
    headers = dict(flow.request.headers)
    cookies = flow.request.headers.get('cookie', '')
    
    # 保存最新的凭证
    creds = {
        'headers': headers,
        'cookies': cookies,
        'url': url[:500],
        'method': flow.request.method,
        'timestamp': datetime.now().isoformat(),
    }
    
    # 如果是小程序请求（包含wx相关参数），保存到wx凭证文件
    if 'yodaReady=wx' in url or 'csecappid' in url:
        with open(WX_CREDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(creds, f, ensure_ascii=False, indent=2)
        print(f"🔑 WX凭证已更新: {url[:80]}")
    
    # 总是更新通用凭证
    with open(CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
        json.dump(creds, f, ensure_ascii=False, indent=2)

    # 解析JSON响应
    try:
        ct = flow.response.headers.get('content-type', '')
        if 'json' not in ct and 'text' not in ct:
            return
        resp_text = flow.response.text
        if not (resp_text.startswith('{') or resp_text.startswith('[')):
            return
        resp_json = json.loads(resp_text)

        saved_path = ''

        # 评论API
        if any(marker in url.lower() for marker in REVIEW_URL_MARKERS) or _is_meituan_web_review_url(url.lower()):
            data_obj = resp_json.get('data', resp_json) if isinstance(resp_json, dict) else None
            if data_obj and isinstance(data_obj, dict) and 'list' in data_obj:
                _save_replay_template(url, flow.request.query, headers, cookies)
                saved_path = _save_review(url, resp_json, flow.request.query, headers, cookies)

        elif 'shopreview' in url.lower():
            if 'shopReviewInfo' in str(resp_json)[:3000]:
                saved_path = _save_review(url, resp_json, flow.request.query, headers, cookies)

        # 搜索API
        if any(marker in url.lower() for marker in SEARCH_URL_MARKERS):
            print(f"\n🔍 搜索API: {url[:150]}")
            search_file = os.path.join(LOG_DIR, f"search_{datetime.now().strftime('%H%M%S')}.json")
            request_body = _parse_request_body(flow)
            with open(search_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'url': url, 'params': dict(flow.request.query),
                    'request_body': request_body,
                    'data': resp_json,
                    'request_headers': headers, 'request_cookies': cookies,
                }, f, ensure_ascii=False, indent=2)
            print(f"  💾 搜索结果已保存")
            saved_path = search_file

        event = build_event(
            url=url,
            method=flow.request.method,
            status=flow.response.status_code,
            params=dict(flow.request.query),
            request_body=_parse_request_body(flow),
            data=resp_json,
            saved_path=saved_path,
        )
        if event:
            append_event(Path(EVENTS_FILE), event)
            print(f"  📌 事件: {event.get('type')} {event.get('shopuuid') or event.get('keyword') or event.get('cityId')}")

    except Exception as exc:
        print(f"⚠️ 拦截处理失败: {exc}")


def _parse_request_body(flow):
    try:
        body = json.loads(flow.request.text or '{}')
    except (TypeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _save_replay_template(url, params, headers, cookies):
    base_url = url.split('?', 1)[0]
    with open(REPLAY_TEMPLATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'base_url': base_url,
            'params': dict(params),
            'headers': headers,
            'cookies': cookies,
            'captured_at': datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)
    print(f"  🔁 replay模板已更新: {base_url}")


def _save_review(url, data, params, headers, cookies):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    shop_id = _resolve_shop_id(url, params, data)
    
    store_name = ''
    list_data = data.get('data', data)
    if isinstance(list_data, dict):
        list_data = list_data.get('list', [])
    if isinstance(list_data, list):
        for item in list_data:
            if isinstance(item, dict):
                poi = item.get('shopPoiRelevant', {})
                if isinstance(poi, dict) and poi.get('title'):
                    store_name = poi['title']
                    break

    filename = os.path.join(LOG_DIR, f"review_{shop_id}_{timestamp}.json")
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump({
            'url': url, 'params': dict(params), 'data': data,
            'timestamp': timestamp, 'storeName': store_name,
            'request_headers': headers, 'request_cookies': cookies,
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n🎯 评论API: {url[:120]}")
    print(f"  💾 {filename}")
    
    if store_name and shop_id != 'unknown':
        map_file = os.path.join(LOG_DIR, 'shop_uuid_map.json')
        mapping = {}
        if os.path.exists(map_file):
            with open(map_file, 'r') as f:
                mapping = json.load(f)
        if store_name not in mapping:
            mapping[store_name] = shop_id
            with open(map_file, 'w', encoding='utf-8') as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
            print(f"  📍 {store_name} → {shop_id}")
    
    # 保存到CSV
    _save_csv(shop_id, store_name, data)
    return filename


def _resolve_shop_id(url, params, data):
    """Resolve shop identifier across Dianping and Meituan mini-program variants."""
    for source in (params, data):
        if isinstance(source, dict):
            for key in (
                'referid', 'referId',
                'shopUuid', 'shopuuid', 'shop_uuid',
                'shopId', 'shopid',
                'poiIdStr', 'poi_id_str',
                'mtwmpoiid', 'wmPoiId', 'wm_poi_id',
            ):
                value = source.get(key)
                if value and value != 'unknown':
                    return str(value)

    if isinstance(params, dict):
        referrer = params.get('mtsiReferrer') or params.get('referer') or params.get('referrer')
        shop_id = _extract_shop_id_from_urlish(referrer)
        if shop_id:
            return shop_id

    shop_id = _extract_shop_id_from_urlish(url)
    return shop_id or 'unknown'


def _extract_shop_id_from_urlish(value):
    if not value:
        return ''
    decoded = unquote(str(value))
    parsed = urlparse(decoded)
    query = parse_qs(parsed.query)
    for key in (
        'referid',
        'shopUuid', 'shopuuid',
        'shopId', 'shopid',
        'poiIdStr', 'poi_id_str',
        'mtwmpoiid', 'wmPoiId', 'wm_poi_id',
    ):
        values = query.get(key)
        if values and values[0]:
            return values[0]
    match = re.search(r'/shop/([A-Za-z0-9_-]+)', decoded)
    if match:
        return match.group(1)
    match = re.search(
        r'(?:referid|shopUuid|shopuuid|shopId|shopid|poiIdStr|poi_id_str|mtwmpoiid|wmPoiId|wm_poi_id)=([A-Za-z0-9_-]+)',
        decoded,
    )
    return match.group(1) if match else ''


def _save_csv(shop_id, store_name, data):
    csv_file = os.path.join(LOG_DIR, 'all_reviews.csv')
    reviews = []
    for path in [
        lambda d: d.get('data', {}).get('list', []) if isinstance(d.get('data'), dict) else [],
        lambda d: d.get('list', []),
        lambda d: d.get('shopReviewInfo', {}).get('reviewList', []),
    ]:
        reviews = path(data)
        if reviews: break
    if not reviews: return

    fieldnames = ['shopId','storeName','reviewId','userName','text','addTime','star']
    write_header = not os.path.exists(csv_file)
    with open(csv_file, 'a+', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header: writer.writeheader()
        for r in reviews:
            if isinstance(r, dict):
                fu = r.get('feedUser', {})
                un = fu.get('userName','') if isinstance(fu, dict) else ''
                text = _extract_text(r)
                writer.writerow({
                    'shopId': shop_id,
                    'storeName': store_name or r.get('shopPoiRelevant',{}).get('title',''),
                    'reviewId': r.get('reviewId', r.get('mainId','')),
                    'userName': un, 'text': text,
                    'addTime': r.get('addTime', r.get('time','')),
                    'star': r.get('star',''),
                })
    print(f"  📝 CSV: {len(reviews)}条")


def _extract_text(review):
    for key in ('content', 'text', 'publicReviewText', 'reviewBody'):
        value = review.get(key, '')
        text = _text_from_value(value)
        text = re.sub(r'<[^>]+>', '', str(text)).strip()
        if text:
            return text
    return ''


def _text_from_value(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get('text'), str):
            return value['text']
        return ''.join(_text_from_value(child) for child in value.get('children', []) if child is not None)
    if isinstance(value, list):
        return ''.join(_text_from_value(item) for item in value)
    return '' if value is None else str(value)


def load(loader):
    print("=" * 60)
    print("🎯 大众点评拦截脚本 v4")
    print(f"📁 {LOG_DIR}")
    print("🔑 捕获所有微信小程序API凭证")
    print("=" * 60)
