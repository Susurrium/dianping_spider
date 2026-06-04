# -*- coding:utf-8 -*-
"""Build analysis-ready review JSON from mitmproxy capture files."""

from __future__ import annotations

import argparse
import html
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree as ET


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL_PATH = ROOT_DIR / "达美乐_门店.xlsx"
DEFAULT_LOG_DIR = ROOT_DIR / "mitm_logs"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "output" / "domino_reviews.json"
DEFAULT_STORE_OUTPUT_DIR = ROOT_DIR / "output" / "store_reviews"

CN_TZ = timezone(timedelta(hours=8))
HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Store:
    name: str
    address: str


@dataclass(frozen=True)
class Review:
    shop_uuid: str
    review_id: str
    publish_time: str
    publisher: str
    text: str
    user_score: str = ""
    user_subscores: Dict[str, str] | None = None
    store_name: str = ""


def _score_to_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.endswith(".0"):
        return text[:-2]
    return text


def extract_user_score(review: Mapping[str, Any]) -> str:
    for key in ("star", "score", "starScore", "rating", "userScore", "accurateStar"):
        value = review.get(key)
        if value is None:
            continue
        if key in {"star", "score", "starScore", "rating", "userScore", "accurateStar"}:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = None
            if numeric is not None and numeric > 10:
                value = numeric / 10
        text = _score_to_text(value)
        if text:
            return text
    return ""


def extract_user_subscores(review: Mapping[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key in ("scoreDetail", "scoreMap", "subScores", "userScoreDetail"):
        value = review.get(key)
        if not isinstance(value, Mapping):
            continue
        for sub_key, sub_value in value.items():
            text = _score_to_text(sub_value)
            if text:
                result[str(sub_key)] = text
    return result


def load_stores_from_xlsx(path: Path) -> List[Store]:
    """Read store names and addresses from a simple xlsx without openpyxl."""
    if not path.exists():
        path = discover_excel_path(path)
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as zf:
        shared_strings = _read_shared_strings(zf, ns)
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        first_sheet = workbook.find(".//a:sheet", ns)
        if first_sheet is None:
            return []

        rel_id = first_sheet.attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        sheet_path = _resolve_sheet_path(zf, rel_id) if rel_id else "xl/worksheets/sheet1.xml"
        sheet = ET.fromstring(zf.read(sheet_path))

    stores: List[Store] = []
    for row in sheet.findall(".//a:sheetData/a:row", ns):
        row_number = int(row.attrib.get("r", "0") or 0)
        if row_number < 3:
            continue

        cells: Dict[str, str] = {}
        for cell in row.findall("a:c", ns):
            ref = cell.attrib.get("r", "")
            column = re.sub(r"\d+", "", ref)
            cells[column] = _cell_value(cell, shared_strings, ns).strip()

        name = cells.get("B", "")
        address = cells.get("C", "")
        if name and address:
            stores.append(Store(name=name, address=address))

    return stores


def discover_excel_path(preferred: Path = DEFAULT_EXCEL_PATH) -> Path:
    """Find the real store workbook while ignoring temporary office lock files."""
    if preferred.exists() and not preferred.name.startswith(".~"):
        return preferred
    patterns = ("达美乐_门店*.xlsx", "门店*.xlsx", "*.xlsx")
    candidates = []
    seen = set()
    for pattern in patterns:
        for path in sorted(ROOT_DIR.glob(pattern)):
            if path.name.startswith(".~") or not path.is_file():
                continue
            if path in seen:
                continue
            seen.add(path)
            candidates.append(path)
    return candidates[0] if candidates else preferred


def load_uuid_map(log_dir: Path) -> Dict[str, str]:
    """Merge known store-name to shop UUID maps captured by previous scripts."""
    mapping: Dict[str, str] = {}
    for filename in ("all_shop_uuids.json", "shop_uuid_map.json"):
        path = log_dir / filename
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            for key, value in data.items():
                if key and value:
                    mapping[str(key)] = str(value)
    return mapping


def build_search_uuid_map(log_dir: Path) -> Dict[str, str]:
    """Extract store-name to shop UUID hints from captured search API responses."""
    mapping: Dict[str, str] = {}
    for path in sorted(log_dir.glob("search_*.json")):
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        payload = data.get("data", data)
        for shop_info in _iter_search_shop_infos(payload):
            uuid = _first_str(shop_info, ["shopUuid", "shop_uuid", "shopuuid", "shopId"])
            if not uuid:
                continue
            name = _build_store_name(shop_info)
            if name:
                mapping.setdefault(name, uuid)
    return mapping


def resolve_shop_uuid(capture: Mapping[str, Any]) -> str:
    """Find the shop UUID in known request/response locations."""
    params = capture.get("params")
    for source in (params, capture.get("data"), capture):
        if not isinstance(source, Mapping):
            continue
        uuid = _first_str(
            source,
            [
                "shopUuid",
                "shopuuid",
                "shop_uuid",
                "shopId",
                "shopid",
                "referid",
                "referId",
                "poiIdStr",
                "poi_id_str",
                "mtwmpoiid",
                "wmPoiId",
                "wm_poi_id",
            ],
        )
        if uuid and uuid != "unknown":
            return uuid

    if isinstance(params, Mapping):
        referrer = _first_str(params, ["mtsiReferrer", "referer", "referrer"])
        uuid = _extract_uuid_from_urlish(referrer)
        if uuid:
            return uuid

    url = str(capture.get("url", ""))
    return _extract_uuid_from_urlish(url)


def extract_review_text(review: Mapping[str, Any]) -> str:
    for key in ("content", "text", "comment", "publicReviewText", "reviewBody", "reviewTitle", "commentContent"):
        value = review.get(key)
        text = _text_from_value(value)
        if text:
            return _clean_text(text)
    return ""


def extract_reviews_from_capture(capture: Mapping[str, Any], source_path: Path) -> List[Review]:
    data = capture.get("data", capture)
    if isinstance(data, Mapping) and isinstance(data.get("data"), Mapping):
        data = data["data"]
    if not isinstance(data, Mapping):
        return []

    shop_uuid = resolve_shop_uuid(capture)
    if not shop_uuid:
        shop_uuid = _first_str(
            data,
            [
                "shopUuid", "shopuuid", "shop_uuid",
                "shopId", "shopid",
                "referid",
                "poiIdStr", "poi_id_str",
                "mtwmpoiid", "wmPoiId", "wm_poi_id",
            ],
        )
    if not shop_uuid or shop_uuid == "unknown":
        shop_uuid = _shop_uuid_from_filename(source_path)
    if not shop_uuid or shop_uuid == "unknown":
        return []

    reviews: List[Review] = []
    for item in _iter_review_items(data):
        review = _review_from_item(item, shop_uuid)
        if review:
            reviews.append(review)
    return reviews


def capture_is_full_review(capture: Mapping[str, Any]) -> bool:
    """True only for the paginated all-review endpoint, not the detail 3-review module."""
    return "outsidesiftedreviewlist" in str(capture.get("url", "")).lower()


def capture_is_end(capture: Mapping[str, Any]) -> bool:
    data = capture.get("data", capture)
    if isinstance(data, Mapping) and isinstance(data.get("data"), Mapping):
        data = data["data"]
    return isinstance(data, Mapping) and data.get("isEnd") is True


def build_export_rows(
    stores: Sequence[Store],
    log_dir: Path,
    explicit_uuid_map: Optional[Mapping[str, str]] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    uuid_map = dict(explicit_uuid_map or {})
    uuid_map.update({k: v for k, v in build_search_uuid_map(log_dir).items() if k not in uuid_map})
    uuid_to_store = _uuid_to_store_name(stores, uuid_map)

    rows: List[Dict[str, str]] = []
    seen = set()
    review_files = 0
    skipped_unknown_uuid = 0
    skipped_non_excel = 0
    stores_seen: set[str] = set()
    stores_with_full_pages: set[str] = set()
    stores_with_full_end: set[str] = set()

    for path in sorted(log_dir.glob("review_*.json")):
        capture = _load_json(path)
        if not isinstance(capture, dict):
            continue
        extracted = extract_reviews_from_capture(capture, path)
        if not extracted:
            if _shop_uuid_from_filename(path) == "unknown":
                skipped_unknown_uuid += 1
            continue
        review_files += 1
        is_full_capture = capture_is_full_review(capture)
        is_end_capture = capture_is_end(capture)

        capture_store = _clean_text(str(capture.get("storeName", "")))
        data = capture.get("data")
        data_store = _first_str(data, ["shopName"]) if isinstance(data, Mapping) else ""

        for review in extracted:
            store_name = _resolve_export_store_name(
                review=review,
                stores=stores,
                uuid_to_store=uuid_to_store,
                capture_store=capture_store,
                data_store=data_store,
            )
            if not store_name:
                skipped_non_excel += 1
                continue
            stores_seen.add(store_name)
            if is_full_capture:
                stores_with_full_pages.add(store_name)
                if is_end_capture:
                    stores_with_full_end.add(store_name)
            key = (
                store_name,
                review.review_id or review.shop_uuid,
                review.publish_time,
                review.publisher,
                review.text,
            )
            if key in seen or not review.text:
                continue
            seen.add(key)
            rows.append(
                {
                    "门店": store_name,
                    "发布时间": review.publish_time,
                    "发布人": review.publisher,
                    "顾客评分": review.user_score,
                    "评分": review.user_score,
                    "文字": review.text,
                }
            )

    rows.sort(key=lambda item: (item["门店"], item["发布时间"], item["发布人"], item["文字"]))
    stores_with_reviews = {row["门店"] for row in rows}
    stores_with_complete_reviews = stores_with_full_end
    partial_review_stores = sorted(stores_seen - stores_with_complete_reviews)
    stats = {
        "stores_in_excel": len(stores),
        "stores_with_reviews": len(stores_with_reviews),
        "stores_with_complete_reviews": len(stores_with_complete_reviews),
        "stores_with_full_review_pages": len(stores_with_full_pages),
        "stores_with_partial_reviews": len(partial_review_stores),
        "stores_missing_reviews": max(len(stores) - len(stores_with_complete_reviews), 0),
        "uuid_mappings": len(uuid_map),
        "review_files": review_files,
        "reviews_exported": len(rows),
        "unknown_uuid_files": skipped_unknown_uuid,
        "reviews_skipped_non_excel": skipped_non_excel,
        "partial_review_stores": partial_review_stores,
        "complete_review_stores": sorted(stores_with_complete_reviews),
    }
    return rows, stats


def _resolve_export_store_name(
    review: Review,
    stores: Sequence[Store],
    uuid_to_store: Mapping[str, str],
    capture_store: str,
    data_store: str,
) -> str:
    mapped = uuid_to_store.get(review.shop_uuid, "")
    if stores:
        return (
            _match_store_by_name(mapped, stores)
            or _match_store_by_name(review.store_name, stores)
            or _match_store_by_name(capture_store, stores)
            or _match_store_by_name(data_store, stores)
        )
    return mapped or review.store_name or capture_store or data_store or review.shop_uuid


def export_reviews(
    excel_path: Path = DEFAULT_EXCEL_PATH,
    log_dir: Path = DEFAULT_LOG_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    per_store_dir: Optional[Path] = None,
) -> Dict[str, int]:
    excel_path = discover_excel_path(excel_path)
    stores = load_stores_from_xlsx(excel_path)
    uuid_map = load_uuid_map(log_dir)
    rows, stats = build_export_rows(stores=stores, log_dir=log_dir, explicit_uuid_map=uuid_map)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if per_store_dir:
        export_per_store_json(rows, stores, per_store_dir)
    return stats


def export_per_store_json(rows: Sequence[Mapping[str, str]], stores: Sequence[Store], output_dir: Path) -> Dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    grouped: Dict[str, List[Mapping[str, str]]] = {store.name: [] for store in stores}
    for row in rows:
        store_name = str(row.get("门店", ""))
        if store_name in grouped:
            grouped[store_name].append(row)

    manifest = []
    for index, store in enumerate(stores, start=1):
        filename = f"{index:03d}_{safe_filename(store.name)}.json"
        path = output_dir / filename
        store_rows = list(grouped.get(store.name, []))
        path.write_text(json.dumps(store_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append(
            {
                "index": index,
                "store": store.name,
                "address": store.address,
                "file": filename,
                "reviews": len(store_rows),
            }
        )
    (output_dir / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {str(item["store"]): int(item["reviews"]) for item in manifest}


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\\s]+", "_", str(value).strip())
    value = value.strip("._")
    return value[:120] or "store"


def main() -> int:
    parser = argparse.ArgumentParser(description="导出大众点评门店评论为分析用 JSON")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH, help="门店 xlsx 文件")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR, help="mitm 捕获日志目录")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="输出 JSON 文件")
    parser.add_argument("--per-store-dir", type=Path, default=DEFAULT_STORE_OUTPUT_DIR, help="每个门店一个 JSON 的输出目录")
    parser.add_argument("--no-per-store", action="store_true", help="只输出总 JSON，不输出每店 JSON")
    args = parser.parse_args()

    stats = export_reviews(args.excel, args.log_dir, args.output, None if args.no_per_store else args.per_store_dir)
    print(f"门店数: {stats['stores_in_excel']}")
    print(f"已有评论门店: {stats['stores_with_reviews']}")
    print(f"待采集门店: {stats['stores_missing_reviews']}")
    print(f"UUID映射: {stats['uuid_mappings']}")
    print(f"评论响应文件: {stats['review_files']}")
    print(f"导出评论: {stats['reviews_exported']}")
    if stats["reviews_skipped_non_excel"]:
        print(f"跳过非Excel门店评论: {stats['reviews_skipped_non_excel']}")
    if stats["unknown_uuid_files"]:
        print(f"跳过未知UUID响应: {stats['unknown_uuid_files']}")
    print(f"输出: {args.output}")
    return 0


def _read_shared_strings(zf: zipfile.ZipFile, ns: Mapping[str, str]) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values: List[str] = []
    for item in root.findall("a:si", ns):
        parts = [node.text or "" for node in item.findall(".//a:t", ns)]
        values.append("".join(parts))
    return values


def _resolve_sheet_path(zf: zipfile.ZipFile, rel_id: str) -> str:
    rels_path = "xl/_rels/workbook.xml.rels"
    if rels_path not in zf.namelist():
        return "xl/worksheets/sheet1.xml"
    root = ET.fromstring(zf.read(rels_path))
    for rel in root:
        if rel.attrib.get("Id") != rel_id:
            continue
        target = rel.attrib.get("Target", "worksheets/sheet1.xml")
        if target.startswith("/"):
            return target.lstrip("/")
        return f"xl/{target}"
    return "xl/worksheets/sheet1.xml"


def _cell_value(cell: ET.Element, shared_strings: Sequence[str], ns: Mapping[str, str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//a:t", ns))

    value_node = cell.find("a:v", ns)
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return ""
    return raw


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _first_str(source: Any, keys: Sequence[str]) -> str:
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


def _extract_uuid_from_urlish(value: str) -> str:
    if not value:
        return ""
    decoded = unquote(value)
    parsed = urlparse(decoded)
    query = parse_qs(parsed.query)
    for key in (
        "shopUuid", "shopuuid",
        "shopId", "shopid",
        "referid",
        "poiIdStr", "poi_id_str",
        "mtwmpoiid", "wmPoiId", "wm_poi_id",
    ):
        values = query.get(key)
        if values and values[0]:
            return values[0]

    match = re.search(r"/shop/([A-Za-z0-9_-]+)", decoded)
    if match:
        return match.group(1)

    match = re.search(
        r"(?:shopUuid|shopuuid|shopId|shopid|referid|poiIdStr|poi_id_str|mtwmpoiid|wmPoiId|wm_poi_id)=([A-Za-z0-9_-]+)",
        decoded,
    )
    return match.group(1) if match else ""


def _iter_search_shop_infos(payload: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        if any(key in payload for key in ("shopId", "shopUuid", "shopuuid", "shopName", "name", "poiId", "poiName", "title")):
            yield payload
        shop_info = payload.get("shopInfo")
        if isinstance(shop_info, Mapping):
            yield shop_info
        for key in ("data", "result"):
            yield from _iter_search_shop_infos(payload.get(key))
        for key in ("list", "shopList", "takeoutShopList", "searchResult"):
            yield from _iter_search_shop_infos(payload.get(key))
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_search_shop_infos(item)


def _build_store_name(shop_info: Mapping[str, Any]) -> str:
    name, inferred_branch = _normalize_shop_name_and_branch(_first_str(shop_info, ["shopName", "name", "poiName", "title"]))
    branch = _clean_text(_first_str(shop_info, ["branchName"])) or inferred_branch
    if name and branch:
        return f"{name}({branch})"
    return name or branch


def _uuid_to_store_name(stores: Sequence[Store], uuid_map: Mapping[str, str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    store_names = {store.name for store in stores}
    for name, uuid in uuid_map.items():
        if not uuid:
            continue
        matched_name = name if name in store_names else _match_store_by_name(name, stores)
        if matched_name:
            result.setdefault(str(uuid), matched_name)
        else:
            result.setdefault(str(uuid), str(name))
    return result


def _match_store_by_name(name: str, stores: Sequence[Store]) -> str:
    clean_name = _normalize_store_name(name)
    if not clean_name:
        return ""
    for store in stores:
        if _normalize_store_name(store.name) == clean_name:
            return store.name
    for store in stores:
        normalized = _normalize_store_name(store.name)
        if clean_name in normalized or normalized in clean_name:
            return store.name
    return ""


def _normalize_store_name(name: str) -> str:
    name = _clean_text(name)
    name, branch = _normalize_shop_name_and_branch(name)
    normalized = f"{name}({branch})" if name and branch else (name or branch)
    return re.sub(r"\s+", "", normalized)


def _normalize_shop_name_and_branch(name: str) -> tuple[str, str]:
    text = _clean_text(name).replace("（", "(").replace("）", ")")
    match = re.match(r"^(.*?)[(]([^()]*)[)]$", text)
    base = match.group(1).strip() if match else text
    branch = match.group(2).strip() if match else ""
    base = base.replace("达美乐披萨", "达美乐比萨").replace("代购", "").strip()
    branch = branch.replace("达美乐披萨", "达美乐比萨").replace("代购", "").strip()
    return base, branch


def _iter_review_items(data: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    shop_review_info = data.get("shopReviewInfo")
    if isinstance(shop_review_info, Mapping):
        review_list = shop_review_info.get("reviewList")
        if isinstance(review_list, list):
            for item in review_list:
                if isinstance(item, Mapping):
                    yield item

    for key in ("reviewList", "list", "commentList", "comments"):
        items = data.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, Mapping):
                    yield item


def _review_from_item(item: Mapping[str, Any], shop_uuid: str) -> Optional[Review]:
    text = extract_review_text(item)
    if not text:
        return None

    feed_user = item.get("feedUser")
    publisher = ""
    if isinstance(feed_user, Mapping):
        publisher = _first_str(feed_user, ["userName", "nickName", "userNickName", "name"])
    publisher = publisher or _first_str(item, ["userName", "userNickName", "nickName", "nickname", "authorName"])

    poi = item.get("shopPoiRelevant")
    store_name = _first_str(poi, ["title", "name", "shopName", "poiName"]) if isinstance(poi, Mapping) else ""
    store_name = store_name or _first_str(item, ["poiName", "shopName", "title"])

    return Review(
        shop_uuid=_first_str(item, ["shopUuid", "shopuuid", "shop_uuid"]) or shop_uuid,
        review_id=_first_str(item, ["reviewId", "mainId", "mixReviewId", "noteId", "commentId", "id"]),
        publish_time=_format_time(_first_str(item, ["addTime", "addTimeStr", "lastTimeStr", "time", "commentTime", "createTime"])),
        publisher=publisher or "匿名用户",
        text=text,
        user_score=extract_user_score(item),
        user_subscores=extract_user_subscores(item),
        store_name=store_name,
    )


def _text_from_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        if isinstance(value.get("text"), str):
            return value["text"]
        parts = [_text_from_value(child) for child in value.get("children", []) if child is not None]
        return "".join(parts)
    if isinstance(value, list):
        return "".join(_text_from_value(item) for item in value)
    return str(value)


def _clean_text(text: str) -> str:
    text = html.unescape(HTML_TAG_RE.sub("", text))
    text = SPACE_RE.sub(" ", text)
    return text.strip()


def _format_time(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    if re.fullmatch(r"\d{10,13}", value):
        timestamp = int(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp // 1000
        return datetime.fromtimestamp(timestamp, tz=CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*Z", value):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(CN_TZ)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return value
    return value


def _shop_uuid_from_filename(path: Path) -> str:
    match = re.match(r"review_(.+?)_\d{8}_\d{6}\.json$", path.name)
    if match:
        return match.group(1)
    match = re.match(r"review_(.+?)(?:_\d+)?\.json$", path.name)
    return match.group(1) if match else ""


if __name__ == "__main__":
    raise SystemExit(main())
