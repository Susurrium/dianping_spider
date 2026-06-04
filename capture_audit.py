# -*- coding:utf-8 -*-
"""Audit current Dianping capture coverage against the xlsx store scope."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from review_exporter import (
    DEFAULT_EXCEL_PATH,
    DEFAULT_LOG_DIR,
    DEFAULT_OUTPUT_PATH,
    build_export_rows,
    load_stores_from_xlsx,
    load_uuid_map,
)


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_PROGRESS_PATH = ROOT_DIR / "output" / "miniapp_progress.json"
DEFAULT_REPORT_PATH = ROOT_DIR / "output" / "capture_audit.json"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def progress_names(progress: Mapping[str, Any], key: str) -> list[str]:
    result: list[str] = []
    values = progress.get(key, [])
    if isinstance(values, Mapping):
        values = [{"store": name, **info} for name, info in values.items() if isinstance(info, Mapping)]
    if not isinstance(values, list):
        return result
    for item in values:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, Mapping):
            name = str(item.get("store") or item.get("storeName") or "")
            if name:
                result.append(name)
    return result


def audit(
    excel_path: Path = DEFAULT_EXCEL_PATH,
    log_dir: Path = DEFAULT_LOG_DIR,
    progress_path: Path = DEFAULT_PROGRESS_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    stores = load_stores_from_xlsx(excel_path)
    store_names = [store.name for store in stores]
    rows, stats = build_export_rows(stores=stores, log_dir=log_dir, explicit_uuid_map=load_uuid_map(log_dir))
    by_store = Counter(row["门店"] for row in rows)
    progress = load_json(progress_path)
    if not isinstance(progress, Mapping):
        progress = {}

    captured = sorted(by_store)
    complete = set(stats.get("complete_review_stores", []))
    partial = set(stats.get("partial_review_stores", []))
    missing = [name for name in store_names if name not in complete]
    failed = progress_names(progress, "failed")
    completed = progress_names(progress, "completed")

    report = {
        "excel": str(excel_path),
        "log_dir": str(log_dir),
        "output": str(output_path),
        "stats": stats,
        "captured_stores": [{"门店": name, "评论数": by_store[name]} for name in captured],
        "complete_stores": [{"门店": name, "评论数": by_store[name]} for name in sorted(complete)],
        "partial_stores": [{"门店": name, "评论数": by_store[name]} for name in sorted(partial)],
        "missing_stores": missing,
        "progress_completed": completed,
        "progress_failed": failed,
        "queue_mode_warning": queue_warning(log_dir),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def queue_warning(log_dir: Path) -> str:
    progress = load_json(log_dir / "review_queue_progress.json")
    if not isinstance(progress, Mapping):
        return ""
    failed = progress.get("failed")
    if isinstance(failed, Mapping):
        reasons = [str(value.get("reason", "")) for value in failed.values() if isinstance(value, Mapping)]
        if any("403" in reason for reason in reasons):
            return "queue改包已出现403；说明评论请求签名/风控上下文与shopuuid/start强绑定，不应作为主采集路线。"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="审计当前 xlsx 门店评论采集覆盖率")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()

    report = audit(args.excel, args.log_dir, args.progress, args.output, args.report)
    stats = report["stats"]
    print(f"xlsx门店: {stats['stores_in_excel']}")
    print(f"已导出门店: {stats['stores_with_reviews']}")
    print(f"完整门店: {stats.get('stores_with_complete_reviews', 0)}")
    print(f"部分门店: {stats.get('stores_with_partial_reviews', 0)}")
    print(f"缺失门店: {stats['stores_missing_reviews']}")
    print(f"导出评论: {stats['reviews_exported']}")
    print(f"评论响应文件: {stats['review_files']}")
    if report["captured_stores"]:
        first = report["captured_stores"][0]
        print(f"示例: {first['门店']} {first['评论数']}条")
    if report["queue_mode_warning"]:
        print(f"警告: {report['queue_mode_warning']}")
    print(f"审计报告: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
