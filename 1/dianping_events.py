# -*- coding:utf-8 -*-
"""Structured event extraction for Dianping mini-program captures.

The automation layer must not guess whether the mini-program did the right
thing from click timing alone.  It waits for these events, which are derived
from the actual mitmproxy responses.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, unquote, urlparse


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_LOG_DIR = ROOT_DIR / "mitm_logs"
DEFAULT_EVENTS_PATH = DEFAULT_LOG_DIR / "events.jsonl"


SEARCH_MARKERS = ("wxsearch/search", "searchshop")
TAKEOUT_SEARCH_MARKERS = (
    "minitakeoutsearch.bin",
    "/group/v1/deal/searchpage/hotword/",
    "/group/v1/deal/search/suggest/",
    "/group/v4/poi/search/miniprogram/",
)
DETAIL_MARKERS = (
    "unifyshopaggregatedump.bin",
    "/group/v1/poi/",
    "/group/v1/deal/poi/",
    "/web/poi/",
)
REVIEW_MARKERS = ("outsideshopreviewlist", "outsidesiftedreviewlist", "shopreview")
CITY_CONTEXT_MARKERS = (
    "hotsuggest.bin",
    "recommendpoi",
    "searchindexprompt.bin",
    "homeresource.bin",
    "chosenrankentry.bin",
    "wxupdatecities.bin",
)


def build_event(
    *,
    url: str,
    method: str = "GET",
    status: int = 200,
    params: Optional[Mapping[str, Any]] = None,
    request_body: Optional[Mapping[str, Any]] = None,
    data: Any = None,
    source: str = "",
    saved_path: str = "",
    timestamp: str = "",
) -> Optional[Dict[str, Any]]:
    """Return a normalized event for a relevant Dianping API response."""
    lower_url = url.lower()
    request_params = normalize_params(params or _params_from_url(url))
    body_params = normalize_params(request_body or {})
    combined_params = dict(request_params)
    combined_params.update({key: value for key, value in body_params.items() if value})
    event_time = timestamp or datetime.now().isoformat(timespec="seconds")
    base = {
        "timestamp": event_time,
        "type": "",
        "method": method,
        "status": status,
        "url": url.split("?", 1)[0],
        "source": source,
        "saved_path": saved_path,
    }

    if any(marker in lower_url for marker in SEARCH_MARKERS):
        candidates = extract_search_candidates(data)
        return {
            **base,
            "type": "search",
            "keyword": first_param(combined_params, "keyword", "q"),
            "cityId": first_param(combined_params, "cityId", "cityid", "selectedCityId"),
            "locateCityid": first_param(combined_params, "locateCityid", "locatedCityId"),
            "start": first_param(combined_params, "start", "pageIndex"),
            "candidate_count": len(candidates),
            "candidates": candidates[:20],
        }

    if any(marker in lower_url for marker in TAKEOUT_SEARCH_MARKERS):
        candidates = extract_search_candidates(data)
        return {
            **base,
            "type": "takeout_search",
            "keyword": first_param(combined_params, "keyword", "q"),
            "cityId": first_param(combined_params, "selectedCityId", "cityId", "cityid"),
            "locateCityid": first_param(combined_params, "locatedCityId", "locateCityid"),
            "start": first_param(combined_params, "pageIndex", "start"),
            "candidate_count": len(candidates),
            "candidates": candidates[:30],
        }

    if any(marker in lower_url for marker in REVIEW_MARKERS) or is_meituan_web_review_url(lower_url):
        review_items = list(iter_review_items(data))
        normalized_data = unwrap_data(data)
        event = {
            **base,
            "type": "review",
            "shopuuid": resolve_shop_uuid({"params": request_params, "data": data, "url": url}),
            "storeName": extract_review_store_name(review_items, normalized_data),
            "review_count": len(review_items),
            "reviewTotalCount": extract_review_total_count(normalized_data),
            "nextStartIndex": "",
            "isEnd": "",
            "start": first_param(request_params, "start", "offset"),
        }
        if isinstance(normalized_data, Mapping):
            event["nextStartIndex"] = str(normalized_data.get("nextStartIndex", ""))
            if "isEnd" in normalized_data:
                event["isEnd"] = bool(normalized_data.get("isEnd"))
        return event

    if any(marker in lower_url for marker in DETAIL_MARKERS):
        shop_uuid = first_param(request_params, "shopuuid", "shopUuid", "shopId", "referid")
        return {
            **base,
            "type": "detail",
            "shopuuid": shop_uuid or resolve_shop_uuid({"params": request_params, "data": data, "url": url}),
            "storeName": extract_detail_store_name(data),
            "cityId": first_param(request_params, "cityId", "cityid", "selectedCityId"),
        }

    if any(marker in lower_url for marker in CITY_CONTEXT_MARKERS):
        city_id = first_param(
            request_params,
            "cityId",
            "cityid",
            "selectedCityId",
            "locatedCityId",
            "locatecityid",
            "locateCityid",
        )
        if city_id:
            return {
                **base,
                "type": "city_context",
                "cityId": city_id,
                "locateCityid": first_param(request_params, "locateCityid", "locatedCityId"),
            }

    return None


def is_meituan_web_review_url(lower_url: str) -> bool:
    return any(
        marker in lower_url
        for marker in (
            "/web/poi/",
            "/web/deal/",
            "/brunch/applet/review",
        )
    ) and any(suffix in lower_url for suffix in ("comments", "overallcomment", "commenttags", "review"))


def append_event(path: Path, event: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(event), ensure_ascii=False, separators=(",", ":")))
        f.write("\n")


def read_events(path: Path = DEFAULT_EVENTS_PATH, offset: int = 0) -> tuple[List[Dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    events: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        f.seek(offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events, f.tell()


def normalize_params(params: Mapping[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        result[str(key)] = str(value) if value is not None else ""
    return result


def first_param(params: Mapping[str, str], *keys: str) -> str:
    for key in keys:
        value = params.get(key)
        if value:
            return str(value)
    return ""


def extract_search_candidates(data: Any) -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    seen = set()
    for index, shop_info in enumerate(iter_search_shop_infos(unwrap_response(data))):
        uuid = first_value(
            shop_info,
            ["shopUuid", "shop_uuid", "shopuuid", "shopId", "shopid", "poiId", "poiid", "id"],
        )
        if not uuid or uuid in seen:
            continue
        seen.add(uuid)
        name, inferred_branch = normalize_shop_name_and_branch(
            first_value(shop_info, ["shopName", "name", "poiName", "title"])
        )
        branch = first_value(shop_info, ["branchName"]) or inferred_branch
        schema = first_value(shop_info, ["schema", "targetUrl", "url", "jumpUrl", "targetUrlV2"])
        candidates.append(
            {
                "rank": str(index if index >= 0 else len(candidates)),
                "uuid": uuid,
                "name": name,
                "branch": branch,
                "address": first_value(shop_info, ["address", "addr", "addressText", "locationText"]),
                "region": first_value(shop_info, ["regionName", "region", "districtName"]),
                "cityId": first_value(shop_info, ["cityId", "cityid"]),
                "reviewCount": first_value(shop_info, ["reviewCount", "commentsCount"]),
                "shopId": first_value(shop_info, ["shopId", "shopid", "poiId", "poiid", "id"]),
                "poiIdStr": first_value(shop_info, ["poiIdStr", "poi_id_str", "wmPoiId", "wm_poi_id"])
                or extract_query_value(schema, "poi_id_str")
                or extract_query_value(schema, "poiIdStr")
                or extract_query_value(schema, "wmPoiId")
                or extract_query_value(schema, "mtwmpoiid"),
            }
        )
    return candidates


def iter_search_shop_infos(payload: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        if any(key in payload for key in ("shopId", "shopUuid", "shopuuid", "shopName", "name", "poiId", "poiName", "title")):
            yield payload
        shop_info = payload.get("shopInfo")
        if isinstance(shop_info, Mapping):
            yield shop_info
        for key in ("data", "result", "resultData"):
            yield from iter_search_shop_infos(payload.get(key))
        for key in ("list", "shopList", "takeoutShopList", "supplyList", "poiList", "searchResult"):
            yield from iter_search_shop_infos(payload.get(key))
    elif isinstance(payload, list):
        for item in payload:
            yield from iter_search_shop_infos(item)


def iter_review_items(data: Any) -> Iterable[Mapping[str, Any]]:
    payload = unwrap_data(data)
    if not isinstance(payload, Mapping):
        return
    shop_review_info = payload.get("shopReviewInfo")
    if isinstance(shop_review_info, Mapping):
        review_list = shop_review_info.get("reviewList")
        if isinstance(review_list, list):
            for item in review_list:
                if isinstance(item, Mapping):
                    yield item
    for key in ("reviewList", "list", "commentList", "comments"):
        items = payload.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, Mapping):
                    yield item


def unwrap_response(data: Any) -> Any:
    if isinstance(data, Mapping) and isinstance(data.get("data"), Mapping):
        return data["data"]
    return data


def unwrap_data(data: Any) -> Any:
    return unwrap_response(data)


def first_value(source: Any, keys: Sequence[str]) -> str:
    if not isinstance(source, Mapping):
        return ""
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def normalize_shop_name_and_branch(name: str) -> tuple[str, str]:
    text = str(name or "").strip().replace("（", "(").replace("）", ")")
    match = re.match(r"^(.*?)[(]([^()]*)[)]$", text)
    base = match.group(1).strip() if match else text
    branch = match.group(2).strip() if match else ""
    base = base.replace("达美乐披萨", "达美乐比萨").replace("代购", "").strip()
    branch = branch.replace("达美乐披萨", "达美乐比萨").replace("代购", "").strip()
    return base, branch


def extract_query_value(urlish: str, key: str) -> str:
    if not urlish or not key:
        return ""
    decoded = unquote(str(urlish))
    parsed = urlparse(decoded)
    values = parse_qs(parsed.query).get(str(key))
    return values[0] if values and values[0] else ""


def resolve_shop_uuid(capture: Mapping[str, Any]) -> str:
    params = capture.get("params")
    for source in (params, capture.get("data"), capture):
        if not isinstance(source, Mapping):
            continue
        value = first_value(
            source,
            [
                "shopuuid", "shopUuid", "shop_uuid",
                "shopId", "shopid",
                "referid", "referId",
                "poiIdStr", "poi_id_str",
                "mtwmpoiid", "wmPoiId", "wm_poi_id",
            ],
        )
        if value and value != "unknown":
            return value

    if isinstance(params, Mapping):
        referrer = first_value(params, ["mtsiReferrer", "referer", "referrer"])
        value = extract_shop_uuid_from_urlish(referrer)
        if value:
            return value
    return extract_shop_uuid_from_urlish(str(capture.get("url", "")))


def extract_shop_uuid_from_urlish(value: str) -> str:
    if not value:
        return ""
    decoded = unquote(str(value))
    parsed = urlparse(decoded)
    query = parse_qs(parsed.query)
    for key in (
        "shopuuid", "shopUuid",
        "shopId", "shopid",
        "referid",
        "poiIdStr", "poi_id_str",
        "mtwmpoiid", "wmPoiId", "wm_poi_id",
    ):
        values = query.get(key)
        if values and values[0]:
            return values[0]
    match = re.search(
        r"(?:shopuuid|shopUuid|shopId|shopid|referid|poiIdStr|poi_id_str|mtwmpoiid|wmPoiId|wm_poi_id)=([A-Za-z0-9_-]+)",
        decoded,
    )
    if match:
        return match.group(1)
    match = re.search(r"/shop/([A-Za-z0-9_-]+)", decoded)
    return match.group(1) if match else ""


def extract_detail_store_name(data: Any) -> str:
    payload = unwrap_data(data)
    for path in (
        ("unifyShop", "shopName"),
        ("unifyShop", "name"),
        ("shopInfo", "shopName"),
        ("shopInfo", "name"),
        ("basicInfo", "shopName"),
        ("basicInfo", "name"),
    ):
        value = nested_value(payload, path)
        if value:
            return value
    return first_value(payload, ["shopName", "name"]) if isinstance(payload, Mapping) else ""


def extract_review_store_name(items: Sequence[Mapping[str, Any]], data: Any) -> str:
    for item in items:
        poi = item.get("shopPoiRelevant")
        name = first_value(poi, ["title", "name", "shopName", "poiName"]) if isinstance(poi, Mapping) else ""
        if name:
            return name
        name = first_value(item, ["poiName", "shopName", "title"])
        if name:
            return name
    if isinstance(data, Mapping):
        return first_value(data, ["shopName", "name", "poiName", "title"])
    return ""


def extract_review_total_count(data: Any) -> str:
    if not isinstance(data, Mapping):
        return ""
    shop_review_info = data.get("shopReviewInfo")
    if isinstance(shop_review_info, Mapping):
        value = first_value(shop_review_info, ["reviewTotalCount", "totalCount", "count"])
        if value:
            return digits_from_text(value)
    value = first_value(data, ["reviewTotalCount", "totalCount", "count", "commentCount", "reviewCount"])
    if value:
        return digits_from_text(value)
    for key in ("topTitle", "bottomTitle", "title", "reviewListSchema", "bottomReviewListSchema"):
        value = first_value(data, [key])
        digits = digits_from_text(value)
        if digits:
            return digits
    return ""


def digits_from_text(value: Any) -> str:
    match = re.search(r"\d+", str(value or ""))
    return match.group(0) if match else ""


def nested_value(source: Any, path: Sequence[str]) -> str:
    current = source
    for key in path:
        if not isinstance(current, Mapping):
            return ""
        current = current.get(key)
    return str(current).strip() if current is not None else ""


def _params_from_url(url: str) -> Dict[str, str]:
    parsed = urlparse(url)
    return {key: values[0] for key, values in parse_qs(parsed.query).items() if values}


def backfill_events(log_dir: Path = DEFAULT_LOG_DIR, output: Path = DEFAULT_EVENTS_PATH) -> int:
    count = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("", encoding="utf-8")

    for path in sorted(log_dir.glob("search_*.json")) + sorted(log_dir.glob("review_*.json")):
        capture = load_json(path)
        if not isinstance(capture, Mapping):
            continue
        event = build_event(
            url=str(capture.get("url", "")),
            method=str(capture.get("method", "GET")),
            status=int(capture.get("status", 200) or 200),
            params=capture.get("params") if isinstance(capture.get("params"), Mapping) else None,
            request_body=capture.get("request_body") if isinstance(capture.get("request_body"), Mapping) else None,
            data=capture.get("data", capture),
            source=path.name,
            saved_path=str(path),
            timestamp=str(capture.get("timestamp", "")),
        )
        if event:
            append_event(output, event)
            count += 1
    return count


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="生成/检查大众点评小程序结构化事件日志")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_EVENTS_PATH)
    parser.add_argument("--backfill", action="store_true", help="从现有 search_/review_ 抓包重建 events.jsonl")
    args = parser.parse_args()

    if args.backfill:
        count = backfill_events(args.log_dir, args.output)
        print(f"events: {count}")
        print(f"output: {args.output}")
        return 0

    events, _ = read_events(args.output)
    print(f"events: {len(events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
