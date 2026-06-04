# -*- coding:utf-8 -*-
"""Export Meituan mini-program review captures into analysis-ready JSON."""

from __future__ import annotations

import argparse
from pathlib import Path

from review_exporter import discover_excel_path, export_reviews


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL_PATH = ROOT_DIR / "达美乐_门店爬虫.xlsx"
DEFAULT_LOG_DIR = ROOT_DIR / "mitm_logs" / "meituan"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "output" / "meituan_reviews.json"
DEFAULT_STORE_OUTPUT_DIR = ROOT_DIR / "output" / "meituan_store_reviews"


def main() -> int:
    parser = argparse.ArgumentParser(description="导出美团小程序门店评论为分析用 JSON")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH, help="门店 xlsx 文件")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR, help="美团 mitm 捕获日志目录")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="输出 JSON 文件")
    parser.add_argument(
        "--per-store-dir",
        type=Path,
        default=DEFAULT_STORE_OUTPUT_DIR,
        help="每个门店一个 JSON 的输出目录",
    )
    parser.add_argument("--no-per-store", action="store_true", help="只输出总 JSON，不输出每店 JSON")
    args = parser.parse_args()

    excel_path = discover_excel_path(args.excel)
    stats = export_reviews(
        excel_path=excel_path,
        log_dir=args.log_dir,
        output_path=args.output,
        per_store_dir=None if args.no_per_store else args.per_store_dir,
    )
    print(f"门店数: {stats['stores_in_excel']}")
    print(f"Excel文件: {excel_path}")
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


if __name__ == "__main__":
    raise SystemExit(main())
