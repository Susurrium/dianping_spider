# -*- coding:utf-8 -*-
"""Batch replay captured Dianping review requests for xlsx stores."""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

from review_exporter import extract_reviews_from_capture, load_stores_from_xlsx


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL_PATH = ROOT_DIR / "达美乐_门店爬虫.xlsx"
DEFAULT_LOG_DIR = ROOT_DIR / "mitm_logs"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "output"
DEFAULT_UUID_MAP = DEFAULT_OUTPUT_DIR / "xlsx_shop_uuid_map.json"
DEFAULT_TEMPLATE = DEFAULT_LOG_DIR / "replay_template.json"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_headers(headers: Mapping[str, Any]) -> Dict[str, str]:
    cleaned: Dict[str, str] = {}
    blocked = {"host", "content-length", ":method", ":path", ":authority", ":scheme"}
    for key, value in headers.items():
        if key.lower() in blocked:
            continue
        cleaned[str(key)] = str(value)
    return cleaned


def build_requests_proxies(proxy: str) -> Dict[str, str]:
    proxy = str(proxy or "").strip()
    if not proxy:
        return {}
    return {"http": proxy, "https": proxy}


def should_verify_tls(*, insecure: bool) -> bool:
    return not insecure


def load_template(path: Path) -> Tuple[str, Dict[str, str], Dict[str, str]]:
    template = load_json(path)
    if not isinstance(template, Mapping):
        raise FileNotFoundError(f"未找到有效评论replay模板: {path}")
    base_url = str(template.get("base_url") or template.get("url") or "")
    if not base_url:
        raise ValueError("replay模板缺少 base_url/url")
    params = {str(k): str(v) for k, v in dict(template.get("params") or {}).items()}
    if not params:
        parsed = urlparse(base_url)
        params = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    headers = clean_headers(template.get("headers") or {})
    cookies = str(template.get("cookies") or "")
    if cookies and "Cookie" not in headers and "cookie" not in headers:
        headers["Cookie"] = cookies
    return base_url, params, headers


def build_params(template_params: Mapping[str, str], shop_uuid: str, start: int) -> Dict[str, str]:
    params = dict(template_params)
    if "referid" in params:
        params["referid"] = shop_uuid
    elif "shopUuid" in params:
        params["shopUuid"] = shop_uuid
    elif "shopuuid" in params:
        params["shopuuid"] = shop_uuid
    else:
        params["referid"] = shop_uuid

    if "start" in params:
        params["start"] = str(start)
    elif "offset" in params:
        params["offset"] = str(start)
    else:
        params["start"] = str(start)
    return params


def build_current_template_task(template_params: Mapping[str, str], store_name: str = "") -> Tuple[str, str]:
    shop_uuid = str(
        template_params.get("referid")
        or template_params.get("shopUuid")
        or template_params.get("shopuuid")
        or ""
    ).strip()
    if not shop_uuid:
        raise ValueError("评论replay模板缺少 referid/shopUuid/shopuuid")
    name = str(store_name or "").strip() or f"当前门店_{shop_uuid}"
    return name, shop_uuid


def build_url(base_url: str, params: Mapping[str, str]) -> str:
    return f"{base_url}?{urlencode(params)}"


def review_list_from_response(data: Any) -> List[Any]:
    if not isinstance(data, Mapping):
        return []
    payload = data.get("data", data)
    if not isinstance(payload, Mapping):
        return []
    if isinstance(payload.get("list"), list):
        return payload["list"]
    shop_review = payload.get("shopReviewInfo")
    if isinstance(shop_review, Mapping) and isinstance(shop_review.get("reviewList"), list):
        return shop_review["reviewList"]
    return []


def response_is_end(data: Any, review_count: int) -> bool:
    payload = data.get("data", data) if isinstance(data, Mapping) else {}
    if isinstance(payload, Mapping) and payload.get("isEnd") is True:
        return True
    return review_count == 0


def request_page(
    session: requests.Session,
    base_url: str,
    params: Mapping[str, str],
    timeout: int,
    proxies: Optional[Mapping[str, str]] = None,
    verify_tls: bool = True,
) -> Tuple[Optional[Mapping[str, Any]], int, str]:
    url = build_url(base_url, params)
    response = session.get(url, timeout=timeout, proxies=dict(proxies or {}), verify=verify_tls)
    text = response.text[:500]
    if response.status_code != 200:
        return None, response.status_code, text
    try:
        data = response.json()
    except ValueError:
        return None, response.status_code, text
    return data, response.status_code, text


def replay_store(
    session: requests.Session,
    store_name: str,
    shop_uuid: str,
    base_url: str,
    template_params: Mapping[str, str],
    log_dir: Path,
    max_pages: int,
    page_size_hint: int,
    delay: Tuple[float, float],
    timeout: int,
    proxies: Optional[Mapping[str, str]],
    verify_tls: bool,
    dry_run: bool,
) -> Tuple[int, str]:
    total = 0
    start = 0
    safe_store = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]+", "_", store_name)[:80]

    for page in range(max_pages):
        params = build_params(template_params, shop_uuid, start)
        if dry_run:
            print(f"[DRY] {store_name} start={start} url={build_url(base_url, params)[:240]}")
            return 0, "dry-run"

        data, status, preview = request_page(session, base_url, params, timeout, proxies, verify_tls)
        if data is None:
            return total, f"HTTP/JSON失败 status={status} preview={preview[:120]}"

        reviews = review_list_from_response(data)
        review_count = len(reviews)
        capture = {
            "url": build_url(base_url, params),
            "params": params,
            "data": data,
            "timestamp": time.strftime("%Y%m%d_%H%M%S"),
            "storeName": store_name,
        }
        page_path = log_dir / "reviews_by_shop" / shop_uuid / f"page_{start:05d}.json"
        compat_path = log_dir / f"review_{shop_uuid}_{time.strftime('%Y%m%d_%H%M%S')}_{start:05d}.json"
        save_json(page_path, capture)
        save_json(compat_path, capture)

        extracted = extract_reviews_from_capture(capture, compat_path)
        total += len(extracted)
        print(f"  {safe_store} start={start}: 原始{review_count}条, 可解析{len(extracted)}条, 累计{total}")

        if response_is_end(data, review_count):
            return total, "end"

        next_start = None
        payload = data.get("data", data) if isinstance(data, Mapping) else {}
        if isinstance(payload, Mapping):
            for key in ("nextStartIndex", "nextStartIndex_bk"):
                value = payload.get(key)
                if isinstance(value, int):
                    next_start = value
                    break
                if isinstance(value, str) and value.isdigit():
                    next_start = int(value)
                    break
        start = next_start if next_start is not None and next_start > start else start + max(review_count, page_size_hint)
        time.sleep(random.uniform(*delay))

    return total, "max-pages"


def main() -> int:
    parser = argparse.ArgumentParser(description="用已捕获评论接口模板批量抓取 xlsx 门店评论")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH)
    parser.add_argument("--uuid-map", type=Path, default=DEFAULT_UUID_MAP)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--page-size-hint", type=int, default=20)
    parser.add_argument("--delay-min", type=float, default=2.0)
    parser.add_argument("--delay-max", type=float, default=4.5)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--proxy", default="", help="requests 使用的 HTTP 代理，例如 http://127.0.0.1:7890")
    parser.add_argument("--insecure", action="store_true", help="关闭 TLS 证书校验，用于请求经 mitm 9092 的测试")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--current-template-only", action="store_true", help="只补采当前 replay_template 里的门店，不需要 xlsx UUID 映射")
    parser.add_argument("--store-name", default="", help="current-template-only 模式下写入日志的门店名")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base_url, template_params, headers = load_template(args.template)
    session = requests.Session()
    session.headers.update(headers)
    proxies = build_requests_proxies(args.proxy)
    verify_tls = should_verify_tls(insecure=args.insecure)

    if args.current_template_only:
        stores = []
        tasks = [build_current_template_task(template_params, args.store_name)]
    else:
        stores = load_stores_from_xlsx(args.excel)
        uuid_map = load_json(args.uuid_map)
        if not isinstance(uuid_map, Mapping):
            raise FileNotFoundError(f"缺少 xlsx 门店UUID映射: {args.uuid_map}，先运行 auto_shop_uuid_resolver.py")
        tasks = [(store.name, str(uuid_map[store.name])) for store in stores if store.name in uuid_map]
    if args.limit:
        tasks = tasks[: args.limit]

    print(f"xlsx门店: {len(stores) if stores else '未使用'}")
    print(f"有UUID门店: {len(tasks)}")
    print(f"评论接口: {base_url}")
    print(f"模式: {'dry-run' if args.dry_run else '真实请求'}")

    progress_path = args.log_dir / "replay_progress_xlsx.json"
    progress = load_json(progress_path)
    if not isinstance(progress, dict):
        progress = {"completed": {}, "failed": {}}

    for index, (store_name, shop_uuid) in enumerate(tasks, start=1):
        if store_name in progress.get("completed", {}):
            print(f"[{index}/{len(tasks)}] 跳过已完成: {store_name}")
            continue
        print(f"[{index}/{len(tasks)}] {store_name} {shop_uuid}")
        count, status = replay_store(
            session=session,
            store_name=store_name,
            shop_uuid=shop_uuid,
            base_url=base_url,
            template_params=template_params,
            log_dir=args.log_dir,
            max_pages=args.max_pages,
            page_size_hint=args.page_size_hint,
            delay=(args.delay_min, args.delay_max),
            timeout=args.timeout,
            proxies=proxies,
            verify_tls=verify_tls,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            break
        if count > 0 or status == "end":
            progress.setdefault("completed", {})[store_name] = {"shopUuid": shop_uuid, "reviews": count, "status": status}
        else:
            progress.setdefault("failed", {})[store_name] = {"shopUuid": shop_uuid, "status": status}
        save_json(progress_path, progress)

    print(f"进度: {progress_path}")
    print("最后导出: python3 review_exporter.py --output output/domino_reviews.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
