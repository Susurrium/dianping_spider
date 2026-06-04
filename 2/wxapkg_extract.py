#!/usr/bin/env python3
import struct, sys
from pathlib import Path

def extract(pkg_path, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = Path(pkg_path).read_bytes()
    if data[0] != 0xBE:
        raise ValueError("Not wxapkg")
    info_len = struct.unpack('>I', data[5:9])[0]
    data_len = struct.unpack('>I', data[9:13])[0]
    p = 14
    n = struct.unpack('>I', data[p:p+4])[0]; p += 4
    files = []
    for _ in range(n):
        nl = struct.unpack('>I', data[p:p+4])[0]; p += 4
        name = data[p:p+nl].decode('utf-8'); p += nl
        off = struct.unpack('>I', data[p:p+4])[0]; p += 4
        ln = struct.unpack('>I', data[p:p+4])[0]; p += 4
        files.append((name, off, ln))
    for name, off, ln in files:
        f = out / name.lstrip('/')
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data[off:off+ln])
    return len(files)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("usage: wxapkg_extract.py <pkg> <out_dir>"); sys.exit(1)
    n = extract(sys.argv[1], sys.argv[2])
    print(f"Extracted {n} files")
