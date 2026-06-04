# -*- coding:utf-8 -*-
"""Extract independent Meituan mini-program API traces from local WeChat logs."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import unquote, urlparse


DEFAULT_APPID = "wxde8ac0a21135c07d"
DEFAULT_LOG_ROOT = Path.home() / ".xwechat" / "radium" / "Applet"

URL_RE = re.compile(r"\{(https%3A%2F%2F[^}]+)\}")
STATUS_RE = re.compile(r"request:\s+(\d+);")
POI_ID_RE = re.compile(r"/(?:poi|deal|shelf|popup|recommendDishList|merchantDishList)/(\d+)")


def iter_log_files(root: Path, appid: str) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob(f"local/{appid}/usr/miniprogramLog/log*"))


def parse_log_text(text: str) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    for line in text.splitlines():
        match = URL_RE.search(line)
        if not match:
            continue
        url = unquote(match.group(1))
        status_match = STATUS_RE.search(line)
        status = status_match.group(1) if status_match else ""
        path = urlparse(url).path
        poi_match = POI_ID_RE.search(path)
        poi_id = poi_match.group(1) if poi_match else ""
        records.append(
            {
                "url": url,
                "path": path,
                "status": status,
                "poi_id": poi_id,
            }
        )
    return records


def collect_records(root: Path, appid: str) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for path in iter_log_files(root, appid):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        results.extend(parse_log_text(text))
    return results


def summarize_records(records: List[Dict[str, str]]) -> Dict[str, object]:
    by_path = Counter(record["path"] for record in records)
    by_status = Counter(record["status"] for record in records if record["status"])
    poi_ids = sorted({record["poi_id"] for record in records if record["poi_id"]})
    return {
        "total_records": len(records),
        "paths": [{"path": path, "count": count} for path, count in by_path.most_common()],
        "status_codes": dict(by_status),
        "poi_ids": poi_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="从本机微信日志提取独立美团小程序 API 轨迹")
    parser.add_argument("--appid", default=DEFAULT_APPID, help="目标小程序 appid")
    parser.add_argument("--log-root", type=Path, default=DEFAULT_LOG_ROOT, help="微信 Applet 日志根目录")
    parser.add_argument("--output", type=Path, default=None, help="可选输出 JSON 文件")
    args = parser.parse_args()

    records = collect_records(args.log_root, args.appid)
    summary = summarize_records(records)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"output: {args.output}")

    print(f"appid: {args.appid}")
    print(f"records: {summary['total_records']}")
    print(f"status_codes: {summary['status_codes']}")
    print("top_paths:")
    for item in summary["paths"][:20]:
        print(f"  {item['count']:>4}  {item['path']}")
    print("poi_ids:")
    for poi_id in summary["poi_ids"][:20]:
        print(f"  {poi_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
