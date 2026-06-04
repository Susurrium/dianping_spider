#!/usr/bin/env python3
"""patch_clash_extra_dianping.py — 补丁：把更多 dianping/meituan 域名加入 DP-MITM 分流。

之前只分流了 mapi.dianping.com / mapi.meituan.com / mapi.sankuai.com，
但小程序的搜索 API 实际走 catfront.dianping.com（验证：Clash 显示 catfront.dianping.com via DIRECT）。
此脚本会把 catfront.dianping.com 等关键 API 域名也分流到 DP-MITM，确保 search 事件能被 mitm 拦截。
"""

from __future__ import annotations

import re
import sys
import json
import subprocess
import time
from pathlib import Path

CLASH_CONFIG = Path("/home/hetaisheng/clash/config.yaml")

EXTRA_API_DOMAINS = [
    "catfront.dianping.com",
    "m.dianping.com",
    "rs.meituan.com",
    "lx0.meituan.com",
    "appmock.dianping.com",
]


def reload_clash() -> bool:
    try:
        result = subprocess.run(
            [
                "curl", "-sS", "-X", "PUT",
                "http://127.0.0.1:9090/configs?force=true",
                "-H", "Content-Type: application/json",
                "--data", json.dumps({"path": str(CLASH_CONFIG)}),
            ],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except subprocess.SubprocessError as exc:
        print(f"reload failed: {exc}")
        return False


def main() -> int:
    text = CLASH_CONFIG.read_text(encoding="utf-8")
    inserted = 0
    for domain in EXTRA_API_DOMAINS:
        marker = f"DOMAIN-SUFFIX,{domain},DP-MITM"
        if marker in text:
            print(f"  already present: {domain}")
            continue
        # 在最后一条 mapi.sankuai.com 后插入
        anchor = " - DOMAIN-SUFFIX,mapi.sankuai.com,DP-MITM"
        if anchor not in text:
            print(f"  ❌ anchor 不存在 (mapi.sankuai.com 规则) — 没法插入 {domain}")
            return 2
        new_line = f"\n - DOMAIN-SUFFIX,{domain},DP-MITM"
        text = text.replace(anchor, anchor + new_line, 1)
        inserted += 1
        print(f"  ✅ inserted: {domain}")

    if inserted == 0:
        print("无需变更")
        return 0

    backup = CLASH_CONFIG.with_suffix(".yaml.bak-extra-dianping-" + time.strftime("%H%M%S"))
    backup.write_text(CLASH_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  备份: {backup}")
    CLASH_CONFIG.write_text(text, encoding="utf-8")
    print(f"  写入新配置: {CLASH_CONFIG}")

    print("  reload Clash...")
    ok = reload_clash()
    if not ok:
        print("  ❌ reload 失败")
        return 3
    time.sleep(2)
    # 校验
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:9090/rules", timeout=3) as resp:
            rules = json.load(resp).get("rules", [])
    except Exception as exc:
        print(f"  ❌ 校验失败: {exc}")
        return 4

    confirmed = [r for r in rules
                 if isinstance(r, dict)
                 and "DP-MITM" in str(r.get("proxy", ""))
                 and any(d in str(r.get("payload", "")) for d in EXTRA_API_DOMAINS)]
    print(f"  Clash 已加载 {len(confirmed)} 条额外规则到 DP-MITM:")
    for r in confirmed:
        print(f"    {r.get('payload')} → {r.get('proxy')}")
    return 0 if confirmed else 5


if __name__ == "__main__":
    sys.exit(main())
