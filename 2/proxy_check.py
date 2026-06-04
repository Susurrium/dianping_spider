# -*- coding:utf-8 -*-
"""Read-only diagnostics for the mitmproxy based Dianping capture flow."""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_LOG_DIR = ROOT_DIR / "mitm_logs"


def port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def template_status(log_dir: Path) -> Mapping[str, Any]:
    template = load_json(log_dir / "replay_template.json")
    if not isinstance(template, dict):
        return {"exists": False}

    base_url = str(template.get("base_url", ""))
    params = template.get("params") if isinstance(template.get("params"), dict) else {}
    headers = template.get("headers") if isinstance(template.get("headers"), dict) else {}
    return {
        "exists": True,
        "base_url": base_url,
        "has_referid": bool(params.get("referid") or params.get("shopUuid") or params.get("shopuuid")),
        "has_start": "start" in params,
        "has_mtgsig": "mtgsig" in headers or "Mtgsig" in headers,
        "has_cookie": bool(template.get("cookies") or headers.get("Cookie") or headers.get("cookie")),
    }


def captured_status(log_dir: Path) -> Mapping[str, int]:
    return {
        "search_files": len(list(log_dir.glob("search_*.json"))),
        "review_files": len(list(log_dir.glob("review_*.json"))),
        "shop_uuid_maps": sum(1 for name in ("shop_uuid_map.json", "all_shop_uuids.json") if (log_dir / name).exists()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 mitmproxy/小程序评论抓取前置条件")
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", type=int, default=9092)
    parser.add_argument("--web-port", type=int, default=9093)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    args = parser.parse_args()

    proxy_ok = port_open(args.proxy_host, args.proxy_port)
    web_ok = port_open(args.proxy_host, args.web_port)
    tmpl = template_status(args.log_dir)
    captured = captured_status(args.log_dir)

    print(f"mitm 代理端口 {args.proxy_host}:{args.proxy_port}: {'OK' if proxy_ok else '未监听'}")
    print(f"mitm Web端口 {args.proxy_host}:{args.web_port}: {'OK' if web_ok else '未监听'}")
    print(f"搜索响应文件: {captured['search_files']}")
    print(f"评论响应文件: {captured['review_files']}")
    print(f"UUID映射文件: {captured['shop_uuid_maps']}")
    if tmpl["exists"]:
        print(f"评论replay模板: OK ({tmpl['base_url']})")
        print(f"  referid/shopUuid: {'OK' if tmpl['has_referid'] else '缺失'}")
        print(f"  start分页参数: {'OK' if tmpl['has_start'] else '缺失'}")
        print(f"  mtgsig签名头: {'有' if tmpl['has_mtgsig'] else '无'}")
        print(f"  Cookie: {'有' if tmpl['has_cookie'] else '无'}")
    else:
        print("评论replay模板: 缺失 mitm_logs/replay_template.json")

    if not proxy_ok:
        print("下一步: 启动 mitmweb，例如 mitmweb -s dianping_interceptor.py --listen-port 9092 --web-port 9093")
        return 2
    if not tmpl["exists"]:
        print("下一步: 先在 PC 微信大众点评小程序进入任意店铺评论页并滚动一次，让拦截器捕获评论接口模板。")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
