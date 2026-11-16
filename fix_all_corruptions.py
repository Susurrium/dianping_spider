#!/usr/bin/env python3
"""Fix all remaining corruptions in miniapp_state_machine.py."""
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / 'miniapp_state_machine.py'

with open(TARGET, 'rb') as f:
    data = bytearray(f.read())

FFFD = b'\xef\xbf\xbd'  # UTF-8 encoding of U+FFFD

def swap(old_str: str, new_str: str):
    """Replace old_str (matched as bytes) with new_str (encoded as UTF-8)."""
    global data
    old_bytes = old_str.encode('utf-8')
    new_bytes = new_str.encode('utf-8')
    if old_bytes in data and old_bytes != new_bytes:
        data[:] = data.replace(old_bytes, new_bytes)
        return True
    return False

count = 0

# ===== classify_ui_snapshot return block =====
if swap(
    'elif left_home_search:\n   (    state = "home"\n    return UiSnapshot(\n        state=state,        "width=width,       height=height,\n        left_home_search=left_home_search,\n        right_loading=right_loading,\n        right_results=right_results,\n        right_blank=right_blank,\n        city_page=city_page,\n        left_detail_like=left_detail_like,\n        right_detail_like=right_detail_like,\n        search_button_orange=search_button_orange,\n        right_tab_orange=right_tab_orange,\n        right_center_orange=right_center_orange,\n        right_white=right_white,\n        right_gray=right_gray,\n    )',
    'elif left_home_search:\n        state = "home"\n    return UiSnapshot(\n        state=state,\n        width=width,\n        height=height,\n        left_home_search=left_home_search,\n        right_loading=right_loading,\n        right_results=right_results,\n        right_blank=right_blank,\n        city_page=city_page,\n        left_detail_like=left_detail_like,\n        right_detail_like=right_detail_like,\n        search_button_orange=search_button_orange,\n        right_tab_orange=right_tab_orange,\n        right_center_orange=right_center_orange,\n        right_white=right_white,\n        right_gray=right_gray,\n    )'
): count += 1; print('FIXED classify_ui_snapshot return')

# ===== rel_box =====
for old_sig in [
    'def rel_box(width: int, height: int, x1: float, y1: float, x2: float, y2: float) -> Tuple[int, int, int, int]:\n    return (\n        max(0, min(width, round(width * x1))),\n        max(0, min(height, round(height * y1))),\n        max(0, min(width, round(width * x2))),\n        max(0, min(height, round(height * y2))),\n    )',
]:
    pass  # Check if this already exists clean

# Find corrupted rel_box by searching for the corrupted bytes
idx = data.find(b'f rel_box')
if idx >= 0:
    # Find full corrupted function
    start = data.rfind(b'\n', 0, idx) + 1
    end_idx = data.find(b'\n\ndef orange_ratio', start + 10)
    if end_idx > 0:
        new_bytes = b'def rel_box(width: int, height: int, x1: float, y1: float, x2: float, y2: float) -> Tuple[int, int, int, int]:\n    return (\n        max(0, min(width, round(width * x1))),\n        max(0, min(height, round(height * y1))),\n        max(0, min(width, round(width * x2))),\n        max(0, min(height, round(height * y2))),\n    )'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED rel_box ({end_idx-start} bytes)')

# ===== white_ratio =====
idx = data.find(b'white_ratio')
if idx >= 0:
    chunk = data[idx:idx+200]
    if FFFD in chunk or b'ret}vl' in chunk:
        start = data.rfind(b'\ndef', 0, idx)
        if start < 0:
            start = data.rfind(b'\n\x0bdef', 0, idx)
        if start < 0:
            start = data.rfind(b'\n', 0, idx)
        start += 1
        end_idx = data.find(b'\n\ndef gray_ratio', start + 10)
        if end_idx < 0:
            end_idx = data.find(b'\ndef(gray_ratio', start + 10)
        if end_idx > 0:
            new_bytes = b'def white_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:\n    return color_ratio(img, box, lambda r, g, b: r > 245 and g > 245 and b > 245)'
            if data[start:end_idx] != new_bytes:
                data[start:end_idx] = new_bytes
                count += 1
                print(f'FIXED white_ratio')

# ===== gray_ratio =====
idx = data.find(b'def(gray_ratio')
if idx >= 0:
    start = idx
    end_idx = data.find(b'\n\ndef color_ratio', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\ndef color_ratio8', start + 10)
    if end_idx > 0:
        new_bytes = b'def gray_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:\n    return color_ratio(img, box, lambda r, g, b: abs(r - g) < 10 and abs(g - b) < 10 and 17 <= r <= 245)'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED gray_ratio')

# ===== color_ratio =====
idx = data.find(b'def color_ratio8img')
if idx >= 0:
    start = idx
    end_idx = data.find(b'\n\ndef search_paths', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\nd%f', start + 10)
    if end_idx > 0:
        new_bytes = b'def color_ratio(img: Any, box: Tuple[int, int, int, int], predicate: Callable[[int, int, int], bool]) -> float:\n    x1, y1, x2, y2 = box\n    if x2 <= x1 or y2 <= y1:\n        return 0.0\n    crop = img.crop((x1, y1, x2, y2)).resize((64, 64))\n    pixels = list(crop.getdata())\n    if not pixels:\n        return 0.0\n    return sum(1 for r, g, b in pixels if predicate(r, g, b)) / len(pixels)'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED color_ratio')

# ===== search_paths_for_snapshot =====
idx = data.find(b'search_paths_for_snapshot')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = data.rfind(b'\n', 0, idx) + 1
    end_idx = data.find(b'\n\ndef should_open', start + 10)
    if end_idx > 0:
        new_bytes = b'def search_paths_for_snapshot(snapshot: Optional[UiSnapshot]) -> List[str]:\n    if snapshot is None:\n        return list(SEARCH_PATH_ORDER)\n    if snapshot.city_page:\n        return ["right", "suggestion", "left_result", "home", "current"]\n    if snapshot.can_search_from_results:\n        return ["right", "suggestion", "left_result", "home", "current"]\n    if snapshot.right_loading:\n        return ["right", "suggestion", "left_result", "home", "current"]\n    if snapshot.can_search_from_home:\n        return ["right", "suggestion", "left_result", "home", "current"]\n    return list(SEARCH_PATH_ORDER)'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED search_paths_for_snapshot')

# ===== should_open_right_search_panel =====
idx = data.find(b'should_open_right_search_panel')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = data.rfind(b'\n', 0, idx) + 1
    end_idx = data.find(b'\n\ndef should_exit', start + 10)
    if end_idx > 0:
        new_bytes = b'def should_open_right_search_panel(snapshot: Optional[UiSnapshot]) -> bool:\n    if snapshot is None:\n        return False\n    if snapshot.city_page or snapshot.can_search_from_results:\n        return False\n    return snapshot.can_search_from_home or snapshot.right_blank or snapshot.right_loading'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED should_open_right_search_panel')

# ===== should_click_search_cancel_button =====
idx = data.find(b'should_click_search_cancel_button')
if idx >= 0 and FFFD in data[idx:idx+100]:
    start = data.rfind(b'\n', 0, idx) + 1
    end_idx = data.find(b'\n\ndef write_search', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\n\x02def wfite', start + 10)
    if end_idx > 0:
        new_bytes = b'def should_click_search_cancel_button() -> bool:\n    return False'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED should_click_search_cancel_button')

# ===== write_search_target =====
idx = data.find(b'write_search_target')
if idx < 0:
    idx = data.find(b'wfite_search_target')
if idx >= 0 and FFFD in data[idx:idx+100]:
    start = data.rfind(b'\n', 0, idx) + 1
    end_idx = data.find(b'\n\ndef clear_search', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\n\x0bdef clear', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def write_search_target(path: Path, store: Store, keyword: str, city_ids: set[str]) -> None:\n'
            b'    city_id = sorted(city_ids)[0] if city_ids else ""\n'
            b'    path.parent.mkdir(parents=True, exist_ok=True)\n'
            b'    path.write_text(\n'
            b'        json.dumps(\n'
            b'            {\n'
            b'                "enabled": True,\n'
            b'                "store": store.name,\n'
            b'                "address": store.address,\n'
            b'                "keyword": keyword,\n'
            b'                "cityId": city_id,\n'
            b'                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),\n'
            b'            },\n'
            b'            ensure_ascii=False,\n'
            b'            indent=2,\n'
            b'        ),\n'
            b'        encoding="utf-8",\n'
            b'    )'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED write_search_target')

# ===== run_xdotool =====
idx = data.find(b'run_xdot/ol')
if idx >= 0:
    start = data.rfind(b'\n', 0, idx) + 1
    end_idx = data.find(b'\n\nGNOME_PROXY_KEYS', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\nGNOME_PROXY_KEYS', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def run_xdotool(args: Sequence[str], *, input_text: str = "") -> subprocess.CompletedProcess:\n'
            b'    env = os.environ.copy()\n'
            b'    env.setdefault("DISPLAY", ":0")\n'
            b'    env.setdefault("XAUTHORITY", f"/run/user/{os.getuid()}/gdm/Xauthority")\n'
            b'    return subprocess.run(\n'
            b'        ["xdotool", *args],\n'
            b'        input=input_text if input_text else None,\n'
            b'        capture_output=True,\n'
            b'        text=True,\n'
            b'        timeout=15,\n'
            b'        check=False,\n'
            b'        env=env,\n'
            b'    )'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED run_xdotool')

# ===== GNOME_PROXY_KEYS =====
idx = data.find(b'GNOME_PROXY_KEYS = {')
if idx >= 0 and FFFD in data[idx:idx+300]:
    start = idx
    end_idx = data.find(b'\n\ndef gsettings', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'GNOME_PROXY_KEYS = {\n'
            b'    "mode": ("org.gnome.system.proxy", "mode"),\n'
            b'    "http_host": ("org.gnome.system.proxy.http", "host"),\n'
            b'    "http_port": ("org.gnome.system.proxy.http", "port"),\n'
            b'    "https_host": ("org.gnome.system.proxy.https", "host"),\n'
            b'    "https_port": ("org.gnome.system.proxy.https", "port"),\n'
            b'}'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED GNOME_PROXY_KEYS')

# ===== gsettings_get + snapshot_gnome_proxy =====
idx = data.find(b'def gsettings_get')
if idx >= 0 and FFFD in data[idx:idx+300]:
    start = idx
    end_idx = data.find(b'\n\ndef build_gsettings_proxy', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def gsettings_get(schema: str, key: str) -> str:\n'
            b'    result = subprocess.run(\n'
            b'        ["gsettings", "get", schema, key],\n'
            b'        capture_output=True,\n'
            b'        text=True,\n'
            b'        timeout=5,\n'
            b'        check=False,\n'
            b'    )\n'
            b'    return result.stdout.strip() if result.returncode == 0 else ""\n'
            b'\n'
            b'def snapshot_gnome_proxy() -> Dict[str, str]:\n'
            b'    return {name: gsettings_get(schema, key) for name, (schema, key) in GNOME_PROXY_KEYS.items()}'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED gsettings_get + snapshot_gnome_proxy')

# ===== build_gsettings_proxy_commands =====
idx = data.find(b'def build_gsettings_proxy_commands')
if idx >= 0 and FFFD in data[idx:idx+500]:
    start = idx
    end_idx = data.find(b'\n\ndef run_commands', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def build_gsettings_proxy_commands(\n'
            b'    host: str,\n'
            b'    port: int,\n'
            b'    snapshot: Mapping[str, str],\n'
            b') -> tuple[List[List[str]], List[List[str]]]:\n'
            b'    set_cmds = [\n'
            b'        ["gsettings", "set", "org.gnome.system.proxy", "mode", "\'manual\'"],\n'
            b'        ["gsettings", "set", "org.gnome.system.proxy.http", "host", f"\'{host}\'"],\n'
            b'        ["gsettings", "set", "org.gnome.system.proxy.http", "port", str(port)],\n'
            b'        ["gsettings", "set", "org.gnome.system.proxy.https", "host", f"\'{host}\'"],\n'
            b'        ["gsettings", "set", "org.gnome.system.proxy.https", "port", str(port)],\n'
            b'    ]\n'
            b'    restore_cmds: List[List[str]] = []\n'
            b'    for name, (schema, key) in GNOME_PROXY_KEYS.items():\n'
            b'        value = str(snapshot.get(name, ""))\n'
            b'        if value:\n'
            b'            restore_cmds.append(["gsettings", "set", schema, key, value])\n'
            b'    return set_cmds, restore_cmds'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED build_gsettings_proxy_commands')

# ===== build_mitmdump_command =====
idx = data.find(b'def build_mitmdump_command')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = idx
    end_idx = data.find(b'\n\ndef build_clash_mitm', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\ndef build_clash', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def build_mitmdump_command(proxy_port: int, upstream_proxy: str = DEFAULT_UPSTREAM_PROXY) -> List[str]:\n'
            b'    cmd = [\n'
            b'        "mitmdump",\n'
            b'        "--listen-port",\n'
            b'        str(proxy_port),\n'
            b'        "--set",\n'
            b'        "ssl_insecure=true",\n'
            b'        "-s",\n'
            b'        str(ROOT_DIR / "dianping_interceptor.py"),\n'
            b'    ]\n'
            b'    if upstream_proxy:\n'
            b'        cmd.extend(["--mode", f"upstream:{upstream_proxy}"])\n'
            b'    return cmd'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED build_mitmdump_command')

# ===== build_clash_mitm_patch =====
idx = data.find(b'def build_clash_mitm_patch')
if idx >= 0 and FFFD in data[idx:idx+700]:
    start = idx
    end_idx = data.find(b'\n\ndef build_mitmdump_env', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def build_clash_mitm_patch(\n'
            b'    proxy_name: str = "DP-MITM",\n'
            b'    proxy_port: int = 9092,\n'
            b'    *,\n'
            b'    include_search_domains: bool = True,\n'
            b') -> str:\n'
            b'    # Keep the default split narrow. Routing whole page os metric domains\n'
            b'    rule_lines = [\n'
            b'        f"  - DOMAIN-SUFFIX,mapi.dianping.com,{proxy_name}",\n'
            b'        f"  - DOMAIN-SUFFIX,mapi.meituan.com,{proxy_name}",\n'
            b'        f"  - DOMAIN-SUFFIX,mapi.sankuai.com,{proxy_name}",\n'
            b'    ]\n'
            b'    if include_search_domains:\n'
            b'        # Keyword search API actually at m.dianping.com (wxmapi/wxsearch/search)\n'
            b'        # catfront/rs/lx0/appmock are result-page related API/ad domains.\n'
            b'        rule_lines += [\n'
            b'            f"  - DOMAIN-SUFFIX,m.dianping.com,{proxy_name}",\n'
            b'            f"  - DOMAIN-SUFFIX,catfront.dianping.com,{proxy_name}",\n'
            b'            f"  - DOMAIN-SUFFIX,rs.meituan.com,{proxy_name}",\n'
            b'            f"  - DOMAIN-SUFFIX,lx0.meituan.com,{proxy_name}",\n'
            b'            f"  - DOMAIN-SUFFIX,appmock.meituan.com,{proxy_name}",\n'
            b'        ]\n'
            b'    return "\\n".join(\n'
            b'        [\n'
            b'            "rules:",\n'
            b'            "  - type: http",\n'
            b'            *rule_lines,\n'
            b'        ]\n'
            b'    )'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED build_clash_mitm_patch')

# ===== build_mitmdump_env =====
idx = data.find(b'def build_mitmdump_env')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = idx
    end_idx = data.find(b'\n\ndef resolve_proxy', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def build_mitmdump_env(\n'
            b'    base_env: Optional[Mapping[str, str]] = None,\n'
            b'    *,\n'
            b'    search_rewrite: bool = False,\n'
            b') -> Dict[str, str]:\n'
            b'    env = dict(base_env or os.environ)\n'
            b'    for key in PROXY_ENV_KEYS:\n'
            b'        env.pop(key, None)\n'
            b'    # Request mutation is useful for offline experiments, but it marks where\n'
            b'    # the frontend actually typed the xlsx store into the correct search box.\n'
            b'    env["DP_SEARCH_REWRITE"] = "1" if search_rewrite else "0"\n'
            b'    return env'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED build_mitmdump_env')

# ===== resolve_proxy_mode =====
idx = data.find(b'def resolve_proxy_mode')
if idx >= 0 and FFFD in data[idx:idx+300]:
    start = idx
    end_idx = data.find(b'\n\ndef start_mitm', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def resolve_proxy_mode(proxy_mode: str, upstream_proxy: str, set_system_proxy: bool) -> Dict[str, Any]:\n'
            b'    if proxy_mode == "split":\n'
            b'        return {\n'
            b'            "upstream_proxy": "",\n'
            b'            "set_system_proxy": False,\n'
            b'            "message": "Clash \xe5\x88\x86\xe6\xb5\x81\xe6\xa8\xa1\xe5\xbc\x8f: \xe7\xb3\xbb\xe7\xbb\x9f\xe4\xbb\xa3\xe7\x90\x86\xe4\xbf\x9d\xe6\x8c\x81 7890\xef\xbc\x8c\xe8\xaf\xb7\xe8\xae\xa9 Clash \xe6\x8a\x8a\xe5\xa4\xa7\xe4\xbc\x97\xe7\x82\xb9\xe8\xaf\x84\xe5\x9f\x9f\xe5\x90\x8d\xe8\xbd\xac\xe5\x8f\x91\xe5\x88\xb0 9092\xef\xbc\x8cmitm \xe4\xb8\x8d\xe5\x86\x8d\xe4\xb8\x8a\xe6\xb8\xb8\xe5\x88\xb0 7890\xe3\x80\x82",\n'
            b'        }\n'
            b'    return {\n'
            b'        "upstream_proxy": upstream_proxy,\n'
            b'        "set_system_proxy": set_system_proxy,\n'
            b'        "message": "",\n'
            b'    }'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED resolve_proxy_mode')

# ===== start_mitm_if_needed =====
idx = data.find(b'def start_mitm_if_need')
if idx >= 0 and FFFD in data[idx:idx+400]:
    start = idx
    end_idx = data.find(b'\n\ndef active_mitmdump', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def start_mitm_if_needed(\n'
            b'    proxy_port: int,\n'
            b'    upstream_proxy: str = DEFAULT_UPSTREAM_PROXY,\n'
            b'    search_rewrite: bool = False,\n'
            b') -> Optional[subprocess.Popen]:\n'
            b'    if port_open("127.0.0.1", proxy_port):\n'
            b'        command = active_mitmdump_command(proxy_port)\n'
            b'        if command and not mitmdump_env_is_safe(command, require_search_rewrite=search_rewrite):\n'
            b'            print(f"mitm \xe5\xb7\xb2\xe7\x9b\x91\xe5\x90\xac\xe4\xbd\x86\xe6\x9c\xaa\xe5\xbc\x80\xe5\x90\xaf\xe6\x90\x9c\xe7\xb4\xa2\xe6\x94\xb9\xe5\x86\x99\xef\xbc\x8c\xe9\x87\x8d\xe5\x90\xaf 127.0.0.1:{proxy_port}")\n'
            b'            stop_mitmdump_on_port(proxy_port)\n'
            b'        else:\n'
            b'            print(f"mitm \xe5\xb7\xb2\xe7\x9b\x91\xe5\x90\xac: 127.0.0.1:{proxy_port}")\n'
            b'            return None\n'
            b'    cmd = build_mitmdump_command(proxy_port, upstream_proxy)\n'
            b'    log_path = DEFAULT_LOG_DIR / "mitmdump_auto.log"\n'
            b'    log_path.parent.mkdir(parents=True, exist_ok=True)\n'
            b'    log_file = log_path.open("a", encoding="utf-8")\n'
            b'    process = subprocess.Popen(\n'
            b'        cmd,\n'
            b'        stdout=log_file,\n'
            b'        stderr=subprocess.STDOUT,\n'
            b'        text=True,\n'
            b'        env=build_mitmdump_env(search_rewrite=search_rewrite),\n'
            b'    )\n'
            b'    deadline = time.time() + 10\n'
            b'    while time.time() < deadline:\n'
            b'        if process.poll() is not None:\n'
            b'            raise RuntimeError(f"mitmdump exited early with code {process.returncode}; see {log_path}")\n'
            b'        if port_open("127.0.0.1", proxy_port):\n'
            b'            print(f"mitm \xe4\xbb\xa3\xe7\x90\x86\xe5\xb7\xb2\xe5\x90\xaf\xe5\x8a\xa8: 127.0.0.1:{proxy_port} | log={log_path}")\n'
            b'            return process\n'
            b'        time.sleep(0.2)\n'
            b'    process.terminate()\n'
            b'    raise RuntimeError(f"mitmdump did not listen on 127.0.0.1:{proxy_port}; see {log_path}")'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED start_mitm_if_needed')

# ===== mitmdump_pid_from_command =====
idx = data.find(b'def mitmdump_pid_from_command')
if idx >= 0 and FFFD in data[idx:idx+100]:
    start = idx
    end_idx = data.find(b'\n\ndef mitmdump_has_search', start + 10)
    if end_idx > 0:
        new_bytes = b'def mitmdump_pid_from_command(command: str) -> str:\n    first = str(command or "").split(maxsplit=1)[0]\n    return first if first.isdigit() else ""'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED mitmdump_pid_from_command')

# ===== mitmdump_has_search_rewrite_env =====
idx = data.find(b'def mitmdump_has_search_rewrite_env')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = idx
    end_idx = data.find(b'\n\ndef mitmdump_env_is', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\n\x02def mitmdump_env', start + 10)
    if end_idx > 0:
        new_bytes = b'def mitmdump_has_search_rewrite_env(command: str) -> bool:\n    pid = mitmdump_pid_from_command(command)\n    if not pid:\n        return False\n    try:\n        environ = (Path("/proc") / pid / "environ").read_bytes()\n    except OSError:\n        return False\n    return b"DP_SEARCH_REWRITE=1" in environ.split(b"\\0")'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED mitmdump_has_search_rewrite_env')

# ===== mitmdump_env_is_safe =====
idx = data.find(b'def mitmdump_env_is_saf')
if idx >= 0 and FFFD in data[idx:idx+300]:
    start = idx
    end_idx = data.find(b'\n\ndef stop_mitmdump', start + 10)
    if end_idx > 0:
        new_bytes = b'def mitmdump_env_is_safe(command: str, *, require_search_rewrite: bool) -> bool:\n    pid = mitmdump_pid_from_command(command)\n    if not pid:\n        return False\n    try:\n        entries = (Path("/proc") / pid / "environ").read_bytes().split(b"\\0")\n    except OSError:\n        return False\n    proxy_prefixes = tuple(f"{key}=".encode() for key in PROXY_ENV_KEYS)\n    if any(entry.startswith(proxy_prefixes) for entry in entries):\n        return False\n    if require_search_rewrite and b"DP_SEARCH_REWRITE=1" not in entries:\n        return False\n    return True'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED mitmdump_env_is_safe')

# ===== stop_mitmdump_on_port =====
idx = data.find(b'def stop_mitmdump_on_port')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = idx
    end_idx = data.find(b'\n\ndef high_throughput', start + 10)
    if end_idx > 0:
        new_bytes = b'def stop_mitmdump_on_port(proxy_port: int) -> None:\n    for pid, _argv in iter_dianping_mitmdump_processes(proxy_port):\n        subprocess.run(["kill", str(pid)], timeout=5, check=False)\n    deadline = time.time() + 5\n    while time.time() < deadline and port_open("127.0.0.1", proxy_port):\n        time.sleep(0.1)'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED stop_mitmdump_on_port')

# ===== high_throughput_defaults =====
idx = data.find(b'def high_throughput_defaults')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = idx
    end_idx = data.find(b'\n\ndef stop_started', start + 10)
    if end_idx > 0:
        new_bytes = b'def high_throughput_defaults(scroll_count: int, scroll_pause: float) -> Dict[str, Any]:\n    return {\n        "search_rewrite": False,\n        "scroll_count": max(scroll_count, 240),\n        "scroll_pause": min(scroll_pause, 0.15),\n        "scroll_batch": 6,\n    }'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED high_throughput_defaults')

# ===== find_miniapp_window =====
idx = data.find(b'def find_miniapp_wind')
if idx >= 0 and FFFD in data[idx:idx+300]:
    start = idx
    end_idx = data.find(b'\n\ndef choose_miniapp', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\n\x0bdef choose', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def find_miniapp_window() -> Optional[WindowInfo]:\n'
            b'    windows: Dict[str, WindowInfo] = {}\n'
            b'    for query in [\n'
            b'        ["search", "--name", "\xe5\xa4\xa7\xe4\xbc\x97\xe7\x82\xb9\xe8\xaf\x84"],\n'
            b'        ["search", "--name", "WeChatAppEx"],\n'
            b'        ["search", "--name", "\xe5\xbe\xae\xe4\xbf\xa1"],\n'
            b'        ["search", "--class", "wechat"],\n'
            b'    ]:\n'
            b'        result = run_xdotool(query)\n'
            b'        for window_id in [line.strip() for line in result.stdout.splitlines() if line.strip()]:\n'
            b'            info = get_window_info(window_id)\n'
            b'            if info:\n'
            b'                windows[window_id] = info\n'
            b'    return choose_miniapp_window(windows.values())'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED find_miniapp_window')

# ===== choose_miniapp_window =====
idx = data.find(b'def choose_miniapp_wind')
if idx >= 0 and FFFD in data[idx:idx+400]:
    start = idx
    end_idx = data.find(b'\n\ndef is_plaus', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\n\ndef minim', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def choose_miniapp_window(windows: Iterable[WindowInfo]) -> Optional[WindowInfo]:\n'
            b'    candidates = [info for info in windows if is_plausible_miniapp_window(info)]\n'
            b'    if not candidates:\n'
            b'        return None\n'
            b'    def score(info: WindowInfo) -> tuple[int, int]:\n'
            b'        name = info.name\n'
            b'        name_score = 0\n'
            b'        if "WeChatAppEx" in info.cmdline:\n'
            b'            name_score += 300\n'
            b'        if "Google Chrome" in name or "chrome" in info.cmdline.lower():\n'
            b'            name_score -= 300\n'
            b'        if "\xe5\xa4\xa7\xe4\xbc\x97\xe7\x82\xb9\xe8\xaf\x84" in name:\n'
            b'            name_score += 100\n'
            b'        if "WeChatAppEx" in name:\n'
            b'            name_score += 60\n'
            b'        if name == "\xe5\xbe\xae\xe4\xbf\xa1":\n'
            b'            name_score += 10\n'
            b'        if info.width > 1200 or info.height > 1200:\n'
            b'            name_score -= 250\n'
            b'        return name_score, -abs(info.width - 914)\n'
            b'    return max(candidates, key=score)'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED choose_miniapp_window')

# ===== is_plausible_miniapp_window =====
idx = data.find(b'def is_plaus')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = idx
    end_idx = data.find(b'\n\ndef minim', start + 10)
    if end_idx > 0:
        new_bytes = b'def is_plausible_miniapp_window(info: WindowInfo) -> bool:\n    if info.width < 360 or info.height < 620:\n        return False\n    if info.width * info.height < 240_000:\n        return False\n    if info.width > 1400 or info.height > 1280:\n        return False\n    return True'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED is_plausible_miniapp_window')

# ===== minimize_overlapping_windows =====
idx = data.find(b'def minimize_overlapping_windows')
if idx >= 0 and FFFD in data[idx:idx+400]:
    start = idx
    end_idx = data.find(b'\n\ndef prepare_window', start + 10)
    if end_idx > 0:
        new_bytes = b'def minimize_overlapping_windows(target: WindowInfo) -> None:\n    result = run_xdotool(["search", "--all", "--onlyvisible", "--name", ".*"])\n    for window_id in [line.strip() for line in result.stdout.splitlines() if line.strip()]:\n        if window_id == target.window_id:\n            continue\n        info = get_window_info(window_id)\n        if not info or info.width < 200 or info.height < 200:\n            continue\n        if windows_overlap(target, info):\n            run_xdotool(["windowminimize", window_id])'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED minimize_overlapping_windows')

# ===== prepare_window =====
idx = data.find(b'def prepare_window')
if idx >= 0 and FFFD in data[idx:idx+400]:
    start = idx
    end_idx = data.find(b'\n\ndef refresh_window', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def prepare_window(window: WindowInfo, *, width: int = 914, height: int = 882) -> WindowInfo:\n'
            b'    """Make the mini-program a stable independent target for screenshots and window-relative input."""\n'
            b'    run_xdotool(["windowsize", window.window_id, str(width), str(height)])\n'
            b'    time.sleep(0.2)\n'
            b'    refreshed = get_window_info(window.window_id) or window\n'
            b'    screen_width, _screen_height = display_size()\n'
            b'    target_x = max(0, screen_width - width - 24) if screen_width else refreshed.x\n'
            b'    target_y = max(0, refreshed.y)\n'
            b'    run_xdotool(["windowmove", refreshed.window_id, str(target_x), str(target_y)])\n'
            b'    time.sleep(0.2)\n'
            b'    return get_window_info(window.window_id) or refreshed'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED prepare_window')

# ===== refresh_window =====
idx = data.find(b'def refresh_window')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = idx
    # Check if already clean
    if b'def refresh_window(window: Optional[WindowInfo]) -> Optional[WindowInfo]:' in data[start:start+50]:
        pass  # Already clean
    else:
        end_idx = data.find(b'\n\ndef display_size', start + 10)
        if end_idx > 0:
            new_bytes = (
                b'def refresh_window(window: Optional[WindowInfo]) -> Optional[WindowInfo]:\n'
                b'    """Return active mini-program window, refreshing it if WeChat rebuilt the X window."""\n'
                b'    if window is not None:\n'
                b'        current = get_window_info(window.window_id)\n'
                b'        if current and is_plausible_miniapp_window(current):\n'
                b'            return current\n'
                b'    found = find_miniapp_window()\n'
                b'    if found is None:\n'
                b'        return None\n'
                b'    refreshed = prepare_window(found)\n'
                b'    minimize_overlapping_windows(refreshed)\n'
                b'    return refreshed'
            )
            if data[start:end_idx] != new_bytes:
                data[start:end_idx] = new_bytes
                count += 1
                print(f'FIXED refresh_window')

# ===== get_window_info =====
idx = data.find(b'def gdt_window_info')
if idx < 0:
    idx = data.find(b'def get_window_info')
    if idx >= 0 and FFFD not in data[idx:idx+100]:
        idx = -1
if idx >= 0:
    start = idx
    end_idx = data.find(b'\n\ndef process_cmdline', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def get_window_info(window_id: str) -> Optional[WindowInfo]:\n'
            b'    name_result = run_xdotool(["getwindowname", window_id])\n'
            b'    geometry_result = run_xdotool(["getwindowgeometry", window_id])\n'
            b'    if geometry_result.returncode != 0:\n'
            b'        return None\n'
            b'    text = geometry_result.stdout\n'
            b'    position = re.search(r"Position:\s*(-?\d+),(-?\d+)", text)\n'
            b'    geometry = re.search(r"Geometry:\s*(\d+)x(\d+)", text)\n'
            b'    if not position or not geometry:\n'
            b'        return None\n'
            b'    pid_result = run_xdotool(["getwindowpid", window_id])\n'
            b'    pid = pid_result.stdout.strip()\n'
            b'    return WindowInfo(\n'
            b'        window_id=window_id,\n'
            b'        name=name_result.stdout.strip(),\n'
            b'        x=int(position.group(1)),\n'
            b'        y=int(position.group(2)),\n'
            b'        width=int(geometry.group(1)),\n'
            b'        height=int(geometry.group(2)),\n'
            b'        pid=pid,\n'
            b'        cmdline=process_cmdline(pid),\n'
            b'    )'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED get_window_info')

# ===== focus_window =====
idx = data.find(b'def focus_window')
if idx >= 0 and FFFD in data[idx:idx+300]:
    start = idx
    end_idx = data.find(b'\n\ndef is_window_active', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def focus_window(window: WindowInfo) -> None:\n'
            b'    for _ in range(3):\n'
            b'        try:\n'
            b'            run_xdotool(["windowactivate", "--sync", window.window_id])\n'
            b'        except subprocess.TimeoutExpired:\n'
            b'            run_xdotool(["windowactivate", window.window_id])\n'
            b'        run_xdotool(["windowfocus", window.window_id])\n'
            b'        time.sleep(0.25)\n'
            b'        active = run_xdotool(["getactivewindow"])\n'
            b'        if is_window_active(window.window_id, active.stdout):\n'
            b'            return\n'
            b'        time.sleep(0.3)'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED focus_window')

# ===== is_window_active =====
idx = data.find(b'def is_window_active')
if idx >= 0 and FFFD in data[idx:idx+100]:
    start = idx
    end_idx = data.find(b'\n\ndef dismiss', start + 10)
    if end_idx > 0:
        new_bytes = b'def is_window_active(window_id: str, active_stdout: str) -> bool:\n    return str(window_id).strip() == str(active_stdout).strip()'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED is_window_active')

# ===== dismiss_blocking_overlays =====
idx = data.find(b'def dismiss_blocking_overlays')
if idx >= 0 and FFFD in data[idx:idx+300]:
    start = idx
    end_idx = data.find(b'\n\ndef click\n', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\n\ndef click(', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\ndef click(', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def dismiss_blocking_overlays(window: Optional[WindowInfo]) -> None:\n'
            b'    if window is None:\n'
            b'        return\n'
            b'    focus_window(window)\n'
            b'    # Known right-pane blockers observed in PC WeChat: Meituan Taxi privacy\n'
            b'    # modal. Prefer "\xe4\xb8\x8d\xe5\x90\x8c\xe6\x84\x8f" then right-pane back; both are window-relative and\n'
            b'    # clamped by click_relative.\n'
            b'    for x, y in ((585, 828), (790, 820), (520, 48)):\n'
            b'        click_relative(window, x, y)\n'
            b'        time.sleep(0.2)'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED dismiss_blocking_overlays')

# ===== click_relative =====
idx = data.find(b'def click_relative')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = idx
    end_idx = data.find(b'\n\ndef click_xy', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def click_relative(window: WindowInfo, x: int, y: int) -> None:\n'
            b'    x = min(max(2, int(x)), max(2, window.width - 2))\n'
            b'    y = min(max(2, int(y)), max(2, window.height - 2))\n'
            b'    run_xdotool(["mousemove", "--window", window.window_id, str(x), str(y)])\n'
            b'    time.sleep(0.08)\n'
            b'    run_xdotool(["click", "--window", window.window_id, "1"])\n'
            b'    time.sleep(0.25)'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED click_relative')

# ===== click_xy =====
idx = data.find(b'def click_xy')
if idx >= 0 and FFFD in data[idx:idx+100]:
    start = idx
    end_idx = data.find(b'\n\ndef paste', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\nd%f', start + 10)
    if end_idx > 0:
        new_bytes = b'def click_xy(screen_x: int, screen_y: int) -> None:\n    run_xdotool(["mousemove", str(screen_x), str(screen_y)])\n    time.sleep(0.1)\n    run_xdotool(["click", "1"])\n    time.sleep(0.25)'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED click_xy')

# ===== paste_text =====
idx = data.find(b'f \xef\xbf\xbdaste_')
if idx < 0:
    idx = data.find(b'f paste_text')
if idx >= 0 and FFFD in data[idx:idx+500]:
    start = data.rfind(b'\n', 0, idx) + 1
    end_idx = data.find(b'\n\ndef type_text', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def paste_text(text: str, window: Optional[WindowInfo] = None) -> None:\n'
            b'    clip = None\n'
            b'    try:\n'
            b'        clip = subprocess.Popen(\n'
            b'            xclip_set_args(),\n'
            b'            stdin=subprocess.PIPE,\n'
            b'            text=True,\n'
            b'        )\n'
            b'        assert clip.stdin is not None\n'
            b'        clip.stdin.write(text)\n'
            b'        clip.stdin.close()\n'
            b'    except FileNotFoundError:\n'
            b'        clip = None\n'
            b'    if clip is not None:\n'
            b'        time.sleep(0.2)\n'
            b'        if get_clipboard_text() != text:\n'
            b'            type_text(text, window)\n'
            b'        else:\n'
            b'            press("ctrl+v", window)\n'
            b'        time.sleep(0.4)\n'
            b'        try:\n'
            b'            clip.terminate()\n'
            b'            clip.wait(timeout=1)\n'
            b'        except subprocess.TimeoutExpired:\n'
            b'            clip.kill()\n'
            b'    else:\n'
            b'        type_text(text, window)\n'
            b'    time.sleep(0.25)'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED paste_text')

# ===== get_clipboard_text =====
idx = data.find(b'def get_clipboard_text')
if idx < 0:
    idx = data.find(b'def get_cli')
if idx >= 0 and FFFD in data[idx:idx+300]:
    start = idx
    end_idx = data.find(b'\n\ndef clear_input', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def get_clipboard_text(timeout: float = 1.0) -> str:\n'
            b'    try:\n'
            b'        result = subprocess.run(\n'
            b'            ["xclip", "-selection", "clipboard", "-o"],\n'
            b'            capture_output=True,\n'
            b'            text=True,\n'
            b'            timeout=timeout,\n'
            b'            check=False,\n'
            b'        )\n'
            b'    except (FileNotFoundError, subprocess.TimeoutExpired):\n'
            b'        return ""\n'
            b'    return result.stdout if result.returncode == 0 else ""'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED get_clipboard_text')

# ===== press =====
idx = data.find(b'def press(')
if idx >= 0 and FFFD in data[idx:idx+100]:
    start = idx
    end_idx = data.find(b'\n\ndef scroll_pages', start + 10)
    if end_idx > 0:
        new_bytes = b'def press(key: str, window: Optional[WindowInfo] = None) -> None:\n    args = ["key", "--clearmodifiers"]\n    if window is not None:\n        args.extend(["--window", window.window_id])\n    args.append(key)\n    run_xdotool(args)\n    time.sleep(0.2)'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED press')

# ===== event_matches_city =====
idx = data.find(b'def event_matches_city')
if idx >= 0 and FFFD in data[idx:idx+100]:
    start = idx
    end_idx = data.find(b'\n\ndef normalized_keyword', start + 10)
    if end_idx > 0:
        new_bytes = b'def event_matches_city(event: Mapping[str, Any], city_ids: set[str]) -> bool:\n    if not city_ids:\n        return True\n    return str(event.get("cityId", "")) in city_ids'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED event_matches_city')

# ===== keyword_variants_for_store =====
idx = data.find(b'def keyword_variants_for_store')
if idx >= 0 and FFFD in data[idx:idx+300]:
    start = idx
    end_idx = data.find(b'\n\ndef latest_confirmed', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\ndef should_switch', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def keyword_variants_for_store(store: Store) -> List[str]:\n'
            b'    branch = store.name.replace("\xe8\xbe\xbe\xe7\xbe\x8e\xe4\xb9\x90\xe6\xaf\x94\xe8\x90\xa8(", "").replace(")", "").strip()\n'
            b'    variants = [\n'
            b'        f"\xe8\xbe\xbe\xe7\xbe\x8e\xe4\xb9\x90\xe6\xaf\x94\xe8\x90\xa8 {branch}".strip(),\n'
            b'        branch,\n'
            b'        branch[:-1] if branch.endswith("\xe5\xba\x97") else branch,\n'
            b'        store.name,\n'
            b'    ]\n'
            b'    result: List[str] = []\n'
            b'    seen = set()\n'
            b'    for value in variants:\n'
            b'        keyword = normalized_keyword(value)\n'
            b'        if keyword and keyword not in seen:\n'
            b'            seen.add(keyword)\n'
            b'            result.append(keyword)\n'
            b'    return result'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED keyword_variants_for_store')

# ===== latest_confirmed_city_ids =====
idx = data.find(b'def latest_confirmed_city_ids')
if idx >= 0 and FFFD in data[idx:idx+100]:
    start = idx
    end_idx = data.find(b'\n\ndef should_switch', start + 10)
    if end_idx > 0:
        new_bytes = b'def latest_confirmed_city_ids(path: Path, limit: int = 200) -> set[str]:\n    events, _offset = read_events(path, 0)\n    for event in reversed(events[-limit:]):\n        city_id = str(event.get("cityId", ""))\n        if event.get("type") in {"city_context", "search", "takeout_search"} and city_id:\n            return {city_id}\n    return set()'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED latest_confirmed_city_ids')

# ===== event_has_matching_candidate =====
idx = data.find(b'def event_has_matching_candidate')
if idx >= 0 and FFFD in data[idx:idx+80]:
    start = idx
    end_idx = data.find(b'\n\ndef review_event', start + 10)
    if end_idx > 0:
        new_bytes = b'def event_has_matching_candidate(store: Store, event: Mapping[str, Any], min_score: int) -> bool:\n    return choose_candidate_from_event(store, event, min_score) is not None'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED event_has_matching_candidate')

# ===== review_event_matches_candidate =====
idx = data.find(b'def review_event_matches_candidate')
if idx >= 0 and FFFD in data[idx:idx+600]:
    start = idx
    end_idx = data.find(b'\n\ndef candidate_review', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def review_event_matches_candidate(\n'
            b'    event: Mapping[str, Any],\n'
            b'    candidate: Candidate,\n'
            b'    store: Store,\n'
            b'    full_only: bool = False,\n'
            b') -> bool:\n'
            b'    """Match review events by actual mitm evidence, allowing shopId/shopUuid aliases.\n'
            b'    The shop Detail page first emits outsideshopreviewlist.bin with only the\n'
            b'    embedded 3-review module.  The full review page emits\n'
            b'    outsidesiftedreviewlist.bin and paginates in 14-review batches."""\n'
            b'    if event.get("type") != "review":\n'
            b'        return False\n'
            b'    if int(event.get("review_count") or 0) <= 0:\n'
            b'        return False\n'
            b'    if full_only and not is_full_review_event(event):\n'
            b'        return False\n'
            b'    event_uuid = str(event.get("shopuuid", ""))\n'
            b'    candidate_uuid = str(candidate.uuid or "")\n'
            b'    if event_uuid and candidate_uuid:\n'
            b'        return event_uuid == candidate_uuid\n'
            b'    if event_uuid and not candidate_uuid:\n'
            b'        return False\n'
            b'    event_store_name = str(event.get("storeName", ""))\n'
            b'    return normalized_store_identity(event_store_name) == normalized_store_identity(store.name)'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED review_event_matches_candidate')

# ===== candidate_review_event_for_attempt =====
idx = data.find(b'def candidate_review_event_for_attempt')
if idx >= 0 and FFFD in data[idx:idx+200]:
    start = idx
    end_idx = data.find(b'\n\ndef wait_for_candidate', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\nde& waat', start + 10)
    if end_idx > 0:
        new_bytes = b'def candidate_review_event_for_attempt(event: Mapping[str, Any], *, full_only: bool = False) -> bool:\n    if event.get("type") != "review":\n        return False\n    if int(event.get("review_count") or 0) <= 0:\n        return False\n    if full_only and not is_full_review_event(event):\n        return False\n    return True'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED candidate_review_event_for_attempt')

# ===== wait_for_candidate_review_event =====
idx = data.find(b'def wait_for_candidate_review_event')
if idx < 0:
    idx = data.find(b'de& waat_for_ca')
if idx >= 0 and FFFD in data[idx:idx+500]:
    start = idx
    end_idx = data.find(b'\n\ndef open_candidate', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\nclass ReviewCapture', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\n\nclass Review', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def wait_for_candidate_review_event(\n'
            b'    window: WindowInfo,\n'
            b'    points: Points,\n'
            b'    watcher: EventWatcher,\n'
            b'    candidate: Candidate,\n'
            b'    store: Store,\n'
            b'    full_only: bool,\n'
            b'    timeout: float,\n'
            b'    label: str,\n'
            b') -> tuple[Optional[Mapping[str, Any]], bool]:\n'
            b'    event = watcher.wait_for(\n'
            b'        lambda e: candidate_review_event_for_attempt(e, full_only=full_only),\n'
            b'        timeout=timeout,\n'
            b'        label=label,\n'
            b'    )\n'
            b'    if event is None:\n'
            b'        return None, False\n'
            b'    if review_event_matches_candidate(event, candidate, store, full_only=full_only):\n'
            b'        return event, False\n'
            b'    print(\n'
            b'        "\xe6\x94\xb6\xe5\x88\xb0\xe9\x9d\x9e\xe7\x9b\xae\xe6\xa0\x87\xe8\xaf\x84\xe8\xae\xba\xe4\xba\x8b\xe4\xbb\xb6\xef\xbc\x8c\xe5\x9b\x9e\xe9\x80\x80\xe5\xb9\xb6\xe7\xbb\x88\xe6\xad\xa2\xe5\xbd\x93\xe5\x89\x8d\xe5\x80\x99\xe9\x80\x89: "\n'
            b'        f"{event.get(\'storeName\', \'\')} {event.get(\'shopuuid\',\'\')}"\n'
            b'    )\n'
            b'    reset_after_wrong_detail(window, points)\n'
            b'    return None, True'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED wait_for_candidate_review_event')

# ===== ReviewCaptureFailed =====
idx = data.find(b'class ReviewCapture')
if idx >= 0 and FFFD in data[idx:idx+100]:
    start = idx
    end_idx = data.find(b'\n\nclass ReviewCaptureTracker', start + 10)
    if end_idx < 0:
        end_idx = data.find(b'\nclass ReviewCaptureTracker', start + 10)
    if end_idx > 0:
        new_bytes = b'class ReviewCaptureFailed(Exception):\n    def __init__(self, reason: str) -> None:\n        super().__init__(reason)\n        self.reason = reason'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED ReviewCaptureFailed')

# ===== duplicate_store_names =====
idx = data.find(b'def duplicate_store_names')
if idx >= 0 and FFFD in data[idx:idx+100]:
    start = idx
    end_idx = data.find(b'\n\ndef unresolved', start + 10)
    if end_idx > 0:
        new_bytes = b'def duplicate_store_names(stores: Sequence[Store]) -> set[str]:\n    counts: Dict[str, int] = {}\n    for store in stores:\n        counts[store.name] = counts.get(store.name, 0) + 1\n    return {name for name, count in counts.items() if count > 1}'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED duplicate_store_names')

# ===== unresolved_stores =====
idx = data.find(b'def unresolved_stores')
if idx >= 0 and FFFD in data[idx:idx+300]:
    start = idx
    end_idx = data.find(b'\n\ndef pick', start + 10)
    if end_idx > 0:
        new_bytes = b'def unresolved_stores(stores: Sequence[Store], log_dir: Path, progress: Mapping[str, Any]) -> List[Store]:\n    rows, stats = build_export_rows(stores=stores, log_dir=log_dir, explicit_uuid_map=load_uuid_map(log_dir))\n    complete_review_stores = set(stats.get("complete_review_stores", []))\n    duplicate_names = duplicate_store_names(stores)\n    pending: List[Store] = []\n    for index, store in enumerate(stores, start=1):\n        if store_is_audited_complete(index, store, complete_review_stores, duplicate_names, progress):\n            continue\n        if store.name in complete_review_stores and store.name not in duplicate_names:\n            continue\n        pending.append(store)\n    return pending'
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED unresolved_stores')

# ===== pick_pending_stores =====
idx = data.find(b'def pick')
if idx >= 0 and b'pending_st' in data[idx:idx+30] and FFFD in data[idx:idx+500]:
    start = idx
    end_idx = data.find(b'\n\ndef progress_completed', start + 10)
    if end_idx > 0:
        new_bytes = (
            b'def pick_pending_stores(\n'
            b'    stores: Sequence[Store],\n'
            b'    log_dir: Path,\n'
            b'    progress: Mapping[str, Any],\n'
            b'    store_name: str = "",\n'
            b'    include_exported: bool = False,\n'
            b'    original_index: int = 0,\n'
            b'    start_index: int = 0,\n'
            b'    limit: int = 0,\n'
            b') -> List[Store]:\n'
            b'    if original_index:\n'
            b'        if original_index < 1 or original_index > len(stores):\n'
            b'            return []\n'
            b'        pending = [stores[original_index - 1]]\n'
            b'    elif store_name:\n'
            b'        seen_store_names = set()\n'
            b'        pending = []\n'
            b'        for store in stores:\n'
            b'            if store_name not in store.name:\n'
            b'                continue\n'
            b'            if store.name in seen_store_names:\n'
            b'                continue\n'
            b'            seen_store_names.add(store.name)\n'
            b'            pending.append(store)\n'
            b'    elif include_exported:\n'
            b'        pending = list(stores)\n'
            b'    else:\n'
            b'        pending = unresolved_stores(stores, log_dir, progress)\n'
            b'    if start_index:\n'
            b'        pending = pending[start_index:]\n'
            b'    if limit:\n'
            b'        pending = pending[:limit]\n'
            b'    return pending'
        )
        if data[start:end_idx] != new_bytes:
            data[start:end_idx] = new_bytes
            count += 1
            print(f'FIXED pick_pending_stores')

# Write result
with open(TARGET, 'wb') as f:
    f.write(data)

# Verify
try:
    text = data.decode('utf-8')
    compile(text, str(TARGET), 'exec')
    remaining = text.count('�')
    print(f'\nSUCCESS! {count} blocks fixed. File compiles cleanly!')
    if remaining > 0:
        print(f'Note: {remaining} U+FFFD characters remain (may be in comments/strings)')
except SyntaxError as e:
    print(f'\n{count} blocks fixed. SyntaxError at line {e.lineno}: {e.msg}')
    lines = data.decode('utf-8').split('\n')
    for offset in range(-3, 4):
        ln = e.lineno - 1 + offset
        if 0 <= ln < len(lines):
            marker = '>>>' if offset == 0 else '   '
            show = lines[ln].replace(chr(0xfffd), '?')[:160]
            print(f'{marker} L{ln+1}: {show}')
