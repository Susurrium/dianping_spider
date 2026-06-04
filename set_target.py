#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
设置当前抓取目标店（让 mitm_dianping.py 知道把抓到的评论写到哪个文件）

用法:
    python3 set_target.py 5            # 目标设为编号 5（自动查 xlsx 拿名字）
    python3 set_target.py list          # 列出待跑的店
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from review_exporter import load_stores_from_xlsx

XLSX = ROOT / '达美乐_门店.xlsx'
TARGET = Path('/tmp/mitm_target.json')
OUT_DIR = ROOT / 'output' / 'store_reviews'


def main():
    if len(sys.argv) < 2:
        print("用法: python3 set_target.py <编号|list>")
        return 1

    stores = load_stores_from_xlsx(XLSX)

    if sys.argv[1] == 'list':
        for i, s in enumerate(stores[:50], 1):
            f = OUT_DIR / f"{i:03d}_{s.name.replace('/','_')}.json"
            cnt = 0
            if f.exists():
                try:
                    d = json.loads(f.read_text(encoding='utf-8'))
                    cnt = len(d) if isinstance(d, list) else 0
                except: pass
            tag = '✅' if cnt >= 10 else '  '
            print(f"  {tag} {i:03d} {s.name} ({cnt} 条)")
        return 0

    idx = int(sys.argv[1])
    if idx < 1 or idx > len(stores):
        print(f"❌ 编号超范围 1-{len(stores)}")
        return 1

    name = stores[idx-1].name
    TARGET.write_text(json.dumps({'idx': idx, 'name': name}, ensure_ascii=False))
    print(f"🎯 目标: {idx:03d} {name}")
    print(f"   评论会自动写入: output/store_reviews/{idx:03d}_{name.replace('/','_')}.json")
    print(f"   实时日志: tail -f /tmp/mitm_capture.log")
    return 0


if __name__ == '__main__':
    sys.exit(main())
