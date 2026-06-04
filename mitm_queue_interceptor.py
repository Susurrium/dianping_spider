# -*- coding:utf-8 -*-
"""Diagnostic mitm-side queue interceptor for low-mouse review collection.

Run this with mitmproxy, then keep the mini-program on any real review page and
scroll.  The script tries to reuse the live client request shape and advances an
xlsx store queue by rewriting review request shopuuid/start parameters.

Current Dianping mini-program review requests include mtgsig/risk context that
can be bound to the original shopuuid/start.  A 403 from this script means the
queue-rewrite route is not viable for that request shape; use
miniapp_state_machine.py as the primary capture path.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Mapping

from mitmproxy import http

from dianping_events import append_event, build_event
from review_exporter import extract_reviews_from_capture


ROOT_DIR = Path(__file__).resolve().parent
LOG_DIR = ROOT_DIR / "mitm_logs"
QUEUE_FILE = LOG_DIR / "review_queue.json"
PROGRESS_FILE = LOG_DIR / "review_queue_progress.json"
EVENTS_FILE = LOG_DIR / "events.jsonl"

REVIEW_MARKERS = ("outsideshopreviewlist", "outsidesiftedreviewlist", "shopreview")
SHOP_KEYS = ("referid", "shopuuid", "shopUuid", "shopId", "shopid")
PAGE_KEYS = ("start", "offset")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def active_target() -> dict[str, str] | None:
    queue = load_json(QUEUE_FILE)
    if not isinstance(queue, list):
        return None
    for item in queue:
        if isinstance(item, dict) and item.get("status", "pending") == "pending":
            item.setdefault("start", "0")
            return {str(k): str(v) for k, v in item.items()}
    return None


def update_target(target: Mapping[str, str], **updates: Any) -> None:
    queue = load_json(QUEUE_FILE)
    if not isinstance(queue, list):
        return
    for item in queue:
        if not isinstance(item, dict):
            continue
        if str(item.get("shopuuid")) == target.get("shopuuid") and item.get("status", "pending") == "pending":
            item.update(updates)
            break
    save_json(QUEUE_FILE, queue)


def is_review_url(url: str) -> bool:
    lower = url.lower()
    return any(marker in lower for marker in REVIEW_MARKERS)


def request(flow: http.HTTPFlow) -> None:
    if not is_review_url(flow.request.url):
        return
    target = active_target()
    if not target:
        return
    if flow.request.headers.get("mtgsig"):
        print("QUEUE diagnostic: request has mtgsig; rewritten shopuuid/start may 403 if signature-bound.")

    original = dict(flow.request.query)
    shopuuid = target["shopuuid"]
    start = target.get("start", "0")

    changed_keys = []
    if any(key in flow.request.query for key in SHOP_KEYS):
        for key in SHOP_KEYS:
            if key in flow.request.query:
                flow.request.query[key] = shopuuid
                changed_keys.append(key)
    else:
        flow.request.query["shopuuid"] = shopuuid
        changed_keys.append("shopuuid")

    if any(key in flow.request.query for key in PAGE_KEYS):
        for key in PAGE_KEYS:
            if key in flow.request.query:
                flow.request.query[key] = start
                changed_keys.append(key)
    else:
        flow.request.query["start"] = start
        changed_keys.append("start")

    flow.request.headers["x-dp-queue-target"] = shopuuid
    flow.request.headers["x-dp-queue-store"] = target.get("storeName", "")
    flow.metadata["queue_target"] = target
    flow.metadata["queue_original_query"] = original
    print(f"QUEUE rewrite {target.get('storeName')} {shopuuid} start={start} keys={','.join(changed_keys)}")


def response(flow: http.HTTPFlow) -> None:
    target = flow.metadata.get("queue_target")
    if not target or not is_review_url(flow.request.url):
        return
    try:
        data = json.loads(flow.response.text)
    except json.JSONDecodeError:
        record_failure(target, f"non-json status={flow.response.status_code}")
        return

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    shopuuid = target["shopuuid"]
    start = target.get("start", "0")
    capture = {
        "url": flow.request.url,
        "params": dict(flow.request.query),
        "data": data,
        "timestamp": timestamp,
        "storeName": target.get("storeName", ""),
        "queue_original_query": flow.metadata.get("queue_original_query", {}),
        "status": flow.response.status_code,
    }

    page_path = LOG_DIR / "queue_reviews" / shopuuid / f"page_{int(start or 0):05d}.json"
    compat_path = LOG_DIR / f"review_{shopuuid}_{timestamp}_{int(start or 0):05d}.json"
    save_json(page_path, capture)
    save_json(compat_path, capture)

    event = build_event(
        url=flow.request.url,
        method=flow.request.method,
        status=flow.response.status_code,
        params=dict(flow.request.query),
        data=data,
        source=compat_path.name,
        saved_path=str(compat_path),
        timestamp=timestamp,
    )
    if event:
        append_event(EVENTS_FILE, event)

    extracted = extract_reviews_from_capture(capture, compat_path)
    review_count = len(extracted)
    payload = data.get("data", data) if isinstance(data, Mapping) else {}
    is_end = bool(payload.get("isEnd")) if isinstance(payload, Mapping) else False
    next_start = next_start_index(payload, fallback=int(start or 0) + max(review_count, 20))

    progress = load_json(PROGRESS_FILE)
    if not isinstance(progress, dict):
        progress = {"completed": {}, "failed": {}, "pages": []}
    progress.setdefault("pages", []).append(
        {
            "storeName": target.get("storeName", ""),
            "shopuuid": shopuuid,
            "start": start,
            "reviews": review_count,
            "status": flow.response.status_code,
            "path": str(compat_path),
        }
    )

    if flow.response.status_code != 200:
        reason = f"status={flow.response.status_code}"
        if flow.response.status_code == 403:
            reason = "status=403; mtgsig/risk context is likely bound to original shopuuid/start"
        progress.setdefault("failed", {})[target.get("storeName", shopuuid)] = {
            "shopuuid": shopuuid,
            "reason": reason,
        }
        update_target(target, status="failed")
        print(f"QUEUE failed {target.get('storeName')} {reason}")
    elif is_end or review_count == 0:
        progress.setdefault("completed", {})[target.get("storeName", shopuuid)] = {
            "shopuuid": shopuuid,
            "lastStart": start,
            "reason": "end" if is_end else "empty",
        }
        update_target(target, status="done")
        print(f"QUEUE done {target.get('storeName')} reviews={review_count} isEnd={is_end}")
    else:
        update_target(target, start=str(next_start))
        print(f"QUEUE page {target.get('storeName')} +{review_count} next={next_start}")

    save_json(PROGRESS_FILE, progress)


def record_failure(target: Mapping[str, str], reason: str) -> None:
    progress = load_json(PROGRESS_FILE)
    if not isinstance(progress, dict):
        progress = {"completed": {}, "failed": {}, "pages": []}
    progress.setdefault("failed", {})[target.get("storeName", target.get("shopuuid", ""))] = {
        "shopuuid": target.get("shopuuid", ""),
        "reason": reason,
    }
    save_json(PROGRESS_FILE, progress)
    update_target(target, status="failed")


def next_start_index(payload: Any, fallback: int) -> int:
    if isinstance(payload, Mapping):
        for key in ("nextStartIndex", "nextStartIndex_bk"):
            value = payload.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    return fallback


print("=" * 60)
print("QUEUE mitm interceptor (diagnostic, not primary path)")
print(f"queue: {QUEUE_FILE}")
print("Keep Dianping mini-program on a real review page and scroll.")
print("If it returns 403, use miniapp_state_machine.py instead.")
print("=" * 60)
