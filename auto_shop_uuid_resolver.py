# -*- coding:utf-8 -*-
"""Resolve xlsx stores to Dianping shop UUIDs from captured mini-program search responses."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from city_utils import expected_city_ids
from review_exporter import Store, load_stores_from_xlsx, load_uuid_map


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL_PATH = ROOT_DIR / "达美乐_门店爬虫.xlsx"
DEFAULT_LOG_DIR = ROOT_DIR / "mitm_logs"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "output"


@dataclass(frozen=True)
class Candidate:
    uuid: str
    name: str
    branch: str
    address_hint: str
    city_id: str
    region: str
    review_count: str
    source: str


def normalize(text: str) -> str:
    text = str(text or "")
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("达美乐披萨", "达美乐比萨")
    text = text.replace("代购", "")
    return re.sub(r"[\s,，。.:：;；、\-_/]+", "", text)


def branch_from_name(name: str) -> str:
    match = re.search(r"[（(](.*?)[）)]", name)
    return match.group(1).strip() if match else name


def normalize_candidate_name(name: str) -> tuple[str, str]:
    text = str(name or "").strip().replace("（", "(").replace("）", ")")
    match = re.match(r"^(.*?)[(]([^()]*)[)]$", text)
    base = match.group(1).strip() if match else text
    branch = match.group(2).strip() if match else ""
    base = base.replace("达美乐披萨", "达美乐比萨").replace("代购", "").strip()
    branch = branch.replace("达美乐披萨", "达美乐比萨").replace("代购", "").strip()
    return base, branch


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def iter_search_shop_infos(payload: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        if any(key in payload for key in ("shopId", "shopUuid", "shopuuid", "shopName", "name", "poiId", "poiName", "title")):
            yield payload
        shop_info = payload.get("shopInfo")
        if isinstance(shop_info, Mapping):
            yield shop_info
        for key in ("data", "result"):
            yield from iter_search_shop_infos(payload.get(key))
        for key in ("list", "shopList", "takeoutShopList", "searchResult"):
            yield from iter_search_shop_infos(payload.get(key))
    elif isinstance(payload, list):
        for item in payload:
            yield from iter_search_shop_infos(item)


def first_str(source: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = source.get(key)
        if value:
            return str(value).strip()
    return ""


def collect_candidates(log_dir: Path) -> List[Candidate]:
    candidates: Dict[str, Candidate] = {}
    for path in sorted(log_dir.glob("search_*.json")):
        data = load_json(path)
        if not isinstance(data, Mapping):
            continue
        for shop_info in iter_search_shop_infos(data.get("data", data)):
            uuid = first_str(shop_info, ["shopUuid", "shop_uuid", "shopuuid", "shopId", "shopid", "poiId", "poiid", "id"])
            if not uuid:
                continue
            raw_name = first_str(shop_info, ["shopName", "name", "poiName", "title"])
            name, inferred_branch = normalize_candidate_name(raw_name)
            branch = first_str(shop_info, ["branchName"]) or inferred_branch
            address_hint = first_str(shop_info, ["address", "addr", "addressText", "locationText"])
            region = first_str(shop_info, ["regionName", "region", "districtName"])
            city_id = first_str(shop_info, ["cityId"])
            review_count = first_str(shop_info, ["reviewCount", "commentsCount"])
            candidates.setdefault(
                uuid,
                Candidate(
                    uuid=uuid,
                    name=name,
                    branch=branch,
                    address_hint=address_hint,
                    city_id=city_id,
                    region=region,
                    review_count=review_count,
                    source=path.name,
                ),
            )
    return list(candidates.values())


def score_candidate(store: Store, candidate: Candidate) -> int:
    expected_cities = expected_city_ids(store.address)
    if expected_cities and candidate.city_id and candidate.city_id not in expected_cities:
        return 0

    store_name = normalize(store.name)
    store_branch = normalize(branch_from_name(store.name))
    store_address = normalize(store.address)
    candidate_name, inferred_branch = normalize_candidate_name(candidate.name)
    candidate_branch_raw = candidate.branch or inferred_branch
    candidate_full_name = normalize(f"{candidate_name}({candidate_branch_raw})" if candidate_branch_raw else candidate_name)
    candidate_branch = normalize(candidate_branch_raw)
    candidate_region = normalize(candidate.region)
    candidate_address = normalize(candidate.address_hint)

    score = 0
    if store_name == candidate_full_name:
        score += 100
    if store_branch and candidate_branch and store_branch == candidate_branch:
        score += 80
    elif store_branch and (
        store_branch in candidate_full_name or (candidate_branch and candidate_branch in store_name)
    ):
        score += 45
    if candidate_region and candidate_region in store_address:
        score += 20
    if candidate_address and candidate_address in store_address:
        score += 40
    if "达美乐" in normalize(candidate.name):
        score += 10
    return score


def resolve_stores(
    stores: Sequence[Store],
    candidates: Sequence[Candidate],
    known_map: Mapping[str, str],
    min_score: int,
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    resolved: Dict[str, str] = {}
    needs_manual: List[Dict[str, Any]] = []
    by_uuid = {candidate.uuid: candidate for candidate in candidates}

    for store in stores:
        known_uuid = known_map.get(store.name)
        known_candidate = by_uuid.get(known_uuid, None) if known_uuid else None
        known_score = score_candidate(store, known_candidate) if known_candidate else 0
        if known_uuid and (known_score >= min_score or not candidates):
            resolved[store.name] = known_uuid
            continue

        ranked = sorted(
            ((score_candidate(store, candidate), candidate) for candidate in candidates),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, best = ranked[0] if ranked else (0, None)
        if best is not None and best_score >= min_score:
            resolved[store.name] = best.uuid
            continue

        needs_manual.append(
            {
                "门店": store.name,
                "地址": store.address,
                "best_score": best_score,
                "candidates": [
                    {"score": score, **asdict(candidate)}
                    for score, candidate in ranked[:5]
                    if score > 0
                ],
            }
        )

    return resolved, needs_manual


def main() -> int:
    parser = argparse.ArgumentParser(description="从 mitm 搜索响应中匹配 xlsx 门店 shopUuid")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-score", type=int, default=90)
    args = parser.parse_args()

    stores = load_stores_from_xlsx(args.excel)
    candidates = collect_candidates(args.log_dir)
    known_map = load_uuid_map(args.log_dir)
    resolved, needs_manual = resolve_stores(stores, candidates, known_map, args.min_score)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    resolved_path = args.output_dir / "xlsx_shop_uuid_map.json"
    manual_path = args.output_dir / "needs_manual_match.json"
    resolved_path.write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8")
    manual_path.write_text(json.dumps(needs_manual, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"xlsx门店: {len(stores)}")
    print(f"搜索候选: {len(candidates)}")
    print(f"已匹配UUID: {len(resolved)}")
    print(f"待人工/继续捕获: {len(needs_manual)}")
    print(f"UUID输出: {resolved_path}")
    print(f"待处理输出: {manual_path}")
    return 0 if resolved else 2


if __name__ == "__main__":
    raise SystemExit(main())
