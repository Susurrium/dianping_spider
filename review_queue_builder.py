# -*- coding:utf-8 -*-
"""Build a mitm-side review capture queue for xlsx stores."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from review_exporter import DEFAULT_EXCEL_PATH, DEFAULT_LOG_DIR, Store, load_stores_from_xlsx, load_uuid_map


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_UUID_MAP = ROOT_DIR / "output" / "xlsx_shop_uuid_map.json"
DEFAULT_QUEUE = DEFAULT_LOG_DIR / "review_queue.json"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_queue(stores: list[Store], uuid_map: Mapping[str, Any], limit: int = 0) -> list[dict[str, str]]:
    queue = []
    for store in stores:
        uuid = uuid_map.get(store.name)
        if not uuid:
            continue
        queue.append(
            {
                "storeName": store.name,
                "address": store.address,
                "shopuuid": str(uuid),
                "start": "0",
                "status": "pending",
            }
        )
        if limit and len(queue) >= limit:
            break
    return queue


def main() -> int:
    parser = argparse.ArgumentParser(description="为 mitm 队列式评论采集生成门店队列")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH)
    parser.add_argument("--uuid-map", type=Path, default=DEFAULT_UUID_MAP)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    uuid_map = load_json(args.uuid_map)
    if not isinstance(uuid_map, Mapping):
        raise FileNotFoundError(f"缺少UUID映射: {args.uuid_map}，先运行 auto_shop_uuid_resolver.py")
    merged_map = dict(load_uuid_map(args.log_dir))
    merged_map.update({str(k): str(v) for k, v in uuid_map.items()})
    queue = build_queue(load_stores_from_xlsx(args.excel), merged_map, args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"队列门店: {len(queue)}")
    print(f"输出: {args.output}")
    if queue:
        print(f"第一家: {queue[0]['storeName']} {queue[0]['shopuuid']}")
    return 0 if queue else 2


if __name__ == "__main__":
    raise SystemExit(main())
