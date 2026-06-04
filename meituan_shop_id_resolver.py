# -*- coding:utf-8 -*-
"""Resolve Excel stores to Meituan mini-program shop IDs from captured search responses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from auto_shop_uuid_resolver import collect_candidates, resolve_stores
from review_exporter import discover_excel_path, load_stores_from_xlsx, load_uuid_map


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL_PATH = ROOT_DIR / "达美乐_门店爬虫.xlsx"
DEFAULT_LOG_DIR = ROOT_DIR / "mitm_logs" / "meituan"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "output" / "meituan"


def main() -> int:
    parser = argparse.ArgumentParser(description="从美团小程序搜索响应中匹配 xlsx 门店 shopId")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-score", type=int, default=90)
    args = parser.parse_args()

    excel_path = discover_excel_path(args.excel)
    stores = load_stores_from_xlsx(excel_path)
    candidates = collect_candidates(args.log_dir)
    known_map = load_uuid_map(args.log_dir)
    resolved, needs_manual = resolve_stores(stores, candidates, known_map, args.min_score)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    resolved_path = args.output_dir / "meituan_shop_id_map.json"
    manual_path = args.output_dir / "meituan_needs_manual_match.json"
    resolved_path.write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8")
    manual_path.write_text(json.dumps(needs_manual, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"xlsx门店: {len(stores)}")
    print(f"Excel文件: {excel_path}")
    print(f"搜索候选: {len(candidates)}")
    print(f"已匹配shopId: {len(resolved)}")
    print(f"待人工/继续捕获: {len(needs_manual)}")
    print(f"shopId输出: {resolved_path}")
    print(f"待处理输出: {manual_path}")
    return 0 if resolved else 2


if __name__ == "__main__":
    raise SystemExit(main())
