# -*- coding: utf-8 -*-
"""Extract WeChat mini-program .wxapkg archives.

The Linux WeChat cache stores plain wxapkg packages.  This small extractor is
kept local so we can inspect page routes and handlers without adding a
dependency or relying on a global unpacker.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def read_u32_be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def extract_wxapkg(package_path: Path, output_dir: Path) -> int:
    data = package_path.read_bytes()
    if len(data) < 18 or data[0] != 0xBE:
        raise ValueError(f"not a supported wxapkg: {package_path}")
    info_len = read_u32_be(data, 5)
    data_len = read_u32_be(data, 9)
    if data[13] != 0xED:
        raise ValueError(f"bad wxapkg marker at byte 13: {package_path}")
    expected_size = 14 + info_len + data_len
    if expected_size != len(data):
        raise ValueError(f"unexpected size for {package_path}: expected {expected_size}, got {len(data)}")

    cursor = 14
    file_count = read_u32_be(data, cursor)
    cursor += 4
    output_dir.mkdir(parents=True, exist_ok=True)

    for _ in range(file_count):
        name_len = read_u32_be(data, cursor)
        cursor += 4
        name = data[cursor : cursor + name_len].decode("utf-8")
        cursor += name_len
        offset = read_u32_be(data, cursor)
        cursor += 4
        size = read_u32_be(data, cursor)
        cursor += 4
        if name.startswith("/"):
            name = name.lstrip("/")
        payload_start = offset
        payload_end = payload_start + size
        if payload_end > len(data):
            raise ValueError(f"file entry exceeds package bounds: {name}")
        target = output_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data[payload_start:payload_end])
    return file_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract plain Linux WeChat wxapkg files")
    parser.add_argument("packages", nargs="+", type=Path)
    parser.add_argument("-o", "--output-dir", type=Path, required=True)
    args = parser.parse_args()

    total = 0
    for package in args.packages:
        package_output = args.output_dir / package.stem
        count = extract_wxapkg(package, package_output)
        total += count
        print(f"{package.name}: {count} files -> {package_output}")
    print(f"total files: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
