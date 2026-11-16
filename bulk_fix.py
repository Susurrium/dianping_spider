#!/usr/bin/env python3
"""Bulk fix all corrupted functions in miniapp_state_machine.py."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path

TARGET = Path(__file__).resolve().parent / 'miniapp_state_machine.py'

with open(TARGET, 'rb') as f:
    data = bytearray(f.read())

FFFD = b'\xef\xbf\xbd'
count = 0

def find_func(name_bytes, min_len=3):
    """Find a function definition by name prefix in the bytearray."""
    idx = data.find(name_bytes)
    if idx < 0:
        return None, None
    # Go back to start of line
    start = data.rfind(b'\n', 0, idx) + 1
    # Find end: next top-level def or class
    end = data.find(b'\ndef ', start + len(name_bytes))
    if end < 0:
        end = data.find(b'\nclass ', start + len(name_bytes))
    if end < 0:
        end = data.find(b'\n@', start + len(name_bytes))
    if end < 0:
        end = len(data)
    # Ensure end is at a clean boundary (before the next \ndef)
    return start, end

def replace_func(search_bytes, new_bytes, label):
    global data, count
    start, end = find_func(search_bytes)
    if start is None:
        print(f'  NOT FOUND: {label}')
        return False
    old = bytes(data[start:end])
    if old.strip() == new_bytes.strip():
        return False
    data[start:end] = new_bytes
    count += 1
    print(f'  FIXED {label}')
    return True

print('Fixing corrupted functions...')

# gsettings_get
replace_func(
    b'def gsettings_get',
    b'def gsettings_get(schema: str, key: str) -> str:\n    result = subprocess.run(\n        ["gsettings", "get", schema, key],\n        capture_output=True,\n        text=True,\n        timeout=5,\n        check=False,\n    )\n    return result.stdout.strip() if result.returncode == 0 else ""',
    'gsettings_get')

# build_gsettings_proxy_commands
start, end = find_func(b'def build_gsettings_proxy_commands')
if start is not None:
    data[start:end] = b'def build_gsettings_proxy_commands(\n    host: str,\n    port: int,\n    snapshot: Mapping[str, str],\n) -> tuple[List[List[str]], List[List[str]]]:\n    set_cmds = [\n        ["gsettings", "set", "org.gnome.system.proxy", "mode", "\'manual\'"],\n        ["gsettings", "set", "org.gnome.system.proxy.http", "host", f"\'{host}\'"],\n        ["gsettings", "set", "org.gnome.system.proxy.http", "port", str(port)],\n        ["gsettings", "set", "org.gnome.system.proxy.https", "host", f"\'{host}\'"],\n        ["gsettings", "set", "org.gnome.system.proxy.https", "port", str(port)],\n    ]\n    restore_cmds: List[List[str]] = []\n    for name, (schema, key) in GNOME_PROXY_KEYS.items():\n        value = str(snapshot.get(name, ""))\n        if value:\n            restore_cmds.append(["gsettings", "set", schema, key, value])\n    return set_cmds, restore_cmds'
    count += 1
    print('  FIXED build_gsettings_proxy_commands')

# build_mitmdump_command
start, end = find_func(b'def build_mitmdump_command')
if start is not None:
    data[start:end] = b'def build_mitmdump_command(proxy_port: int, upstream_proxy: str = DEFAULT_UPSTREAM_PROXY) -> List[str]:\n    cmd = [\n        "mitmdump",\n        "--listen-port",\n        str(proxy_port),\n        "--set",\n        "ssl_insecure=true",\n        "-s",\n        str(ROOT_DIR / "dianping_interceptor.py"),\n    ]\n    if upstream_proxy:\n        cmd.extend(["--mode", f"upstream:{upstream_proxy}"])\n    return cmd'
    count += 1
    print('  FIXED build_mitmdump_command')

# build_clash_mitm_patch
for marker in [b'def build_clash_mitm_patch', b'deF `uild_claqh[mitm_patc']:
    start, end = find_func(marker)
    if start is not None:
        break
if start is not None:
    data[start:end] = b'def build_clash_mitm_patch(\n    proxy_name: str = "DP-MITM",\n    proxy_port: int = 9092,\n    *,\n    include_search_domains: bool = True,\n) -> str:\n    # Keep the default split narrow.\n    rule_lines = [\n        f"  - DOMAIN-SUFFIX,mapi.dianping.com,{proxy_name}",\n        f"  - DOMAIN-SUFFIX,mapi.meituan.com,{proxy_name}",\n        f"  - DOMAIN-SUFFIX,mapi.sankuai.com,{proxy_name}",\n    ]\n    if include_search_domains:\n        rule_lines += [\n            f"  - DOMAIN-SUFFIX,m.dianping.com,{proxy_name}",\n            f"  - DOMAIN-SUFFIX,catfront.dianping.com,{proxy_name}",\n            f"  - DOMAIN-SUFFIX,rs.meituan.com,{proxy_name}",\n            f"  - DOMAIN-SUFFIX,lx0.meituan.com,{proxy_name}",\n            f"  - DOMAIN-SUFFIX,appmock.meituan.com,{proxy_name}",\n        ]\n    return "\\n".join(\n        [\n            "rules:",\n            "  - type: http",\n            *rule_lines,\n        ]\n    )'
    count += 1
    print('  FIXED build_clash_mitm_patch')

# build_mitmdump_env
start, end = find_func(b'def build_mitmdump_env')
if start is not None:
    data[start:end] = b'def build_mitmdump_env(\n    base_env: Optional[Mapping[str, str]] = None,\n    *,\n    search_rewrite: bool = False,\n) -> Dict[str, str]:\n    env = dict(base_env or os.environ)\n    for key in PROXY_ENV_KEYS:\n        env.pop(key, None)\n    env["DP_SEARCH_REWRITE"] = "1" if search_rewrite else "0"\n    return env'
    count += 1
    print('  FIXED build_mitmdump_env')

# resolve_proxy_mode
start, end = find_func(b'def resolve_proxy_mode')
if start is not None:
    data[start:end] = b'def resolve_proxy_mode(proxy_mode: str, upstream_proxy: str, set_system_proxy: bool) -> Dict[str, Any]:\n    if proxy_mode == "split":\n        return {\n            "upstream_proxy": "",\n            "set_system_proxy": False,\n            "message": "Clash \xe5\x88\x86\xe6\xb5\x81\xe6\xa8\xa1\xe5\xbc\x8f: \xe7\xb3\xbb\xe7\xbb\x9f\xe4\xbb\xa3\xe7\x90\x86\xe4\xbf\x9d\xe6\x8c\x81 7890\xef\xbc\x8c\xe8\xaf\xb7\xe8\xae\xa9 Clash \xe6\x8a\x8a\xe5\xa4\xa7\xe4\xbc\x97\xe7\x82\xb9\xe8\xaf\x84\xe5\x9f\x9f\xe5\x90\x8d\xe8\xbd\xac\xe5\x8f\x91\xe5\x88\xb0 9092\xef\xbc\x8cmitm \xe4\xb8\x8d\xe5\x86\x8d\xe4\xb8\x8a\xe6\xb8\xb8\xe5\x88\xb0 7890\xe3\x80\x82",\n        }\n    return {\n        "upstream_proxy": upstream_proxy,\n        "set_system_proxy": set_system_proxy,\n        "message": "",\n    }'
    count += 1
    print('  FIXED resolve_proxy_mode')

# start_mitm_if_needed
for marker in [b'def start_mitm_if_needed', b'def start_mitm_if_nee$ed']:
    start, end = find_func(marker)
    if start is not None:
        break
if start is not None:
    data[start:end] = b'def start_mitm_if_needed(\n    proxy_port: int,\n    upstream_proxy: str = DEFAULT_UPSTREAM_PROXY,\n    search_rewrite: bool = False,\n) -> Optional[subprocess.Popen]:\n    if port_open("127.0.0.1", proxy_port):\n        command = active_mitmdump_command(proxy_port)\n        if command and not mitmdump_env_is_safe(command, require_search_rewrite=search_rewrite):\n            print(f"mitm \xe5\xb7\xb2\xe7\x9b\x91\xe5\x90\xac\xe4\xbd\x86\xe6\x9c\xaa\xe5\xbc\x80\xe5\x90\xaf\xe6\x90\x9c\xe7\xb4\xa2\xe6\x94\xb9\xe5\x86\x99\xef\xbc\x8c\xe9\x87\x8d\xe5\x90\xaf 127.0.0.1:{proxy_port}")\n            stop_mitmdump_on_port(proxy_port)\n        else:\n            print(f"mitm \xe5\xb7\xb2\xe7\x9b\x91\xe5\x90\xac: 127.0.0.1:{proxy_port}")\n            return None\n    cmd = build_mitmdump_command(proxy_port, upstream_proxy)\n    log_path = DEFAULT_LOG_DIR / "mitmdump_auto.log"\n    log_path.parent.mkdir(parents=True, exist_ok=True)\n    log_file = log_path.open("a", encoding="utf-8")\n    process = subprocess.Popen(\n        cmd,\n        stdout=log_file,\n        stderr=subprocess.STDOUT,\n        text=True,\n        env=build_mitmdump_env(search_rewrite=search_rewrite),\n    )\n    deadline = time.time() + 10\n    while time.time() < deadline:\n        if process.poll() is not None:\n            raise RuntimeError(f"mitmdump exited early with code {process.returncode}; see {log_path}")\n        if port_open("127.0.0.1", proxy_port):\n            print(f"mitm \xe4\xbb\xa3\xe7\x90\x86\xe5\xb7\xb2\xe5\x90\xaf\xe5\x8a\xa8: 127.0.0.1:{proxy_port} | log={log_path}")\n            return process\n        time.sleep(0.2)\n    process.terminate()\n    raise RuntimeError(f"mitmdump did not listen on 127.0.0.1:{proxy_port}; see {log_path}")'
    count += 1
    print('  FIXED start_mitm_if_needed')

# mitmdump_pid_from_command
replace_func(
    b'def mitmdump_pid_from_command',
    b'def mitmdump_pid_from_command(command: str) -> str:\n    first = str(command or "").split(maxsplit=1)[0]\n    return first if first.isdigit() else ""',
    'mitmdump_pid_from_command')

# mitmdump_has_search_rewrite_env
replace_func(
    b'def mitmdump_has_search_rewrite_env',
    b'def mitmdump_has_search_rewrite_env(command: str) -> bool:\n    pid = mitmdump_pid_from_command(command)\n    if not pid:\n        return False\n    try:\n        environ = (Path("/proc") / pid / "environ").read_bytes()\n    except OSError:\n        return False\n    return b"DP_SEARCH_REWRITE=1" in environ.split(b"\\0")',
    'mitmdump_has_search_rewrite_env')

# mitmdump_env_is_safe
replace_func(
    b'def mitmdump_env_is_saf',
    b'def mitmdump_env_is_safe(command: str, *, require_search_rewrite: bool) -> bool:\n    pid = mitmdump_pid_from_command(command)\n    if not pid:\n        return False\n    try:\n        entries = (Path("/proc") / pid / "environ").read_bytes().split(b"\\0")\n    except OSError:\n        return False\n    proxy_prefixes = tuple(f"{key}=".encode() for key in PROXY_ENV_KEYS)\n    if any(entry.startswith(proxy_prefixes) for entry in entries):\n        return False\n    if require_search_rewrite and b"DP_SEARCH_REWRITE=1" not in entries:\n        return False\n    return True',
    'mitmdump_env_is_safe')

# stop_mitmdump_on_port
replace_func(
    b'def stop_mitmdump_on_port',
    b'def stop_mitmdump_on_port(proxy_port: int) -> None:\n    for pid, _argv in iter_dianping_mitmdump_processes(proxy_port):\n        subprocess.run(["kill", str(pid)], timeout=5, check=False)\n    deadline = time.time() + 5\n    while time.time() < deadline and port_open("127.0.0.1", proxy_port):\n        time.sleep(0.1)',
    'stop_mitmdump_on_port')

# high_throughput_defaults
replace_func(
    b'def high_throughput_defaults',
    b'def high_throughput_defaults(scroll_count: int, scroll_pause: float) -> Dict[str, Any]:\n    return {\n        "search_rewrite": False,\n        "scroll_count": max(scroll_count, 240),\n        "scroll_pause": min(scroll_pause, 0.15),\n        "scroll_batch": 6,\n    }',
    'high_throughput_defaults')

# stop_started_mitm
replace_func(
    b'def stop_started_mitm',
    b'def stop_started_mitm(process: Optional[subprocess.Popen]) -> None:\n    if process is None:\n        return\n    if process.poll() is not None:\n        return\n    try:\n        process.terminate()\n        process.wait(timeout=5)\n    except subprocess.TimeoutExpired:\n        process.kill()',
    'stop_started_mitm')

# is_dianping_mitmdump_argv
replace_func(
    b'def is_dianping_mitmdump_argv',
    b'def is_dianping_mitmdump_argv(argv: Sequence[str], proxy_port: int) -> bool:\n    try:\n        port_value = argv[argv.index("--listen-port") + 1]\n    except (ValueError, IndexError):\n        return False\n    if str(port_value) != str(proxy_port):\n        return False\n    return any(Path(arg).name == "dianping_interceptor.py" for arg in argv)',
    'is_dianping_mitmdump_argv')

# choose_miniapp_window
for marker in [b'def choose_miniapp_window', b'def choose_miniapp_windos']:
    start, end = find_func(marker)
    if start is not None:
        break
if start is not None:
    data[start:end] = b'def choose_miniapp_window(windows: Iterable[WindowInfo]) -> Optional[WindowInfo]:\n    candidates = [info for info in windows if is_plausible_miniapp_window(info)]\n    if not candidates:\n        return None\n    def score(info: WindowInfo) -> tuple[int, int]:\n        name = info.name\n        name_score = 0\n        if "WeChatAppEx" in info.cmdline:\n            name_score += 300\n        if "Google Chrome" in name or "chrome" in info.cmdline.lower():\n            name_score -= 300\n        if "\xe5\xa4\xa7\xe4\xbc\x97\xe7\x82\xb9\xe8\xaf\x84" in name:\n            name_score += 100\n        if "WeChatAppEx" in name:\n            name_score += 60\n        if name == "\xe5\xbe\xae\xe4\xbf\xa1":\n            name_score += 10\n        if info.width > 1200 or info.height > 1200:\n            name_score -= 250\n        return name_score, -abs(info.width - 914)\n    return max(candidates, key=score)'
    count += 1
    print('  FIXED choose_miniapp_window')

# is_plausible_miniapp_window
replace_func(
    b'def is_plaus',
    b'def is_plausible_miniapp_window(info: WindowInfo) -> bool:\n    if info.width < 360 or info.height < 620:\n        return False\n    if info.width * info.height < 240_000:\n        return False\n    if info.width > 1400 or info.height > 1280:\n        return False\n    return True',
    'is_plausible_miniapp_window')

# minimize_overlapping_windows
replace_func(
    b'def minimize_overlapping_windows',
    b'def minimize_overlapping_windows(target: WindowInfo) -> None:\n    result = run_xdotool(["search", "--all", "--onlyvisible", "--name", ".*"])\n    for window_id in [line.strip() for line in result.stdout.splitlines() if line.strip()]:\n        if window_id == target.window_id:\n            continue\n        info = get_window_info(window_id)\n        if not info or info.width < 200 or info.height < 200:\n            continue\n        if windows_overlap(target, info):\n            run_xdotool(["windowminimize", window_id])',
    'minimize_overlapping_windows')

# prepare_window
for marker in [b'def prepare_window', b'def prepare_window\xef\xbf\xbd']:
    start, end = find_func(marker)
    if start is not None:
        break
if start is not None:
    data[start:end] = b'def prepare_window(window: WindowInfo, *, width: int = 914, height: int = 882) -> WindowInfo:\n    """Make the mini-program a stable independent target."""\n    run_xdotool(["windowsize", window.window_id, str(width), str(height)])\n    time.sleep(0.2)\n    refreshed = get_window_info(window.window_id) or window\n    screen_width, _screen_height = display_size()\n    target_x = max(0, screen_width - width - 24) if screen_width else refreshed.x\n    target_y = max(0, refreshed.y)\n    run_xdotool(["windowmove", refreshed.window_id, str(target_x), str(target_y)])\n    time.sleep(0.2)\n    return get_window_info(window.window_id) or refreshed'
    count += 1
    print('  FIXED prepare_window')

# refresh_window
replace_func(
    b'def refresh_window',
    b'def refresh_window(window: Optional[WindowInfo]) -> Optional[WindowInfo]:\n    """Return active mini-program window, refreshing it if WeChat rebuilt the X window."""\n    if window is not None:\n        current = get_window_info(window.window_id)\n        if current and is_plausible_miniapp_window(current):\n            return current\n    found = find_miniapp_window()\n    if found is None:\n        return None\n    refreshed = prepare_window(found)\n    minimize_overlapping_windows(refreshed)\n    return refreshed',
    'refresh_window')

# get_window_info
for marker in [b'def get_window_info', b'def gdt_window_info']:
    start, end = find_func(marker)
    if start is not None:
        break
if start is not None:
    data[start:end] = b'def get_window_info(window_id: str) -> Optional[WindowInfo]:\n    name_result = run_xdotool(["getwindowname", window_id])\n    geometry_result = run_xdotool(["getwindowgeometry", window_id])\n    if geometry_result.returncode != 0:\n        return None\n    text = geometry_result.stdout\n    position = re.search(r"Position:\s*(-?\d+),(-?\d+)", text)\n    geometry = re.search(r"Geometry:\s*(\d+)x(\d+)", text)\n    if not position or not geometry:\n        return None\n    pid_result = run_xdotool(["getwindowpid", window_id])\n    pid = pid_result.stdout.strip()\n    return WindowInfo(\n        window_id=window_id,\n        name=name_result.stdout.strip(),\n        x=int(position.group(1)),\n        y=int(position.group(2)),\n        width=int(geometry.group(1)),\n        height=int(geometry.group(2)),\n        pid=pid,\n        cmdline=process_cmdline(pid),\n    )'
    count += 1
    print('  FIXED get_window_info')

# focus_window
replace_func(
    b'def focus_window',
    b'def focus_window(window: WindowInfo) -> None:\n    for _ in range(3):\n        try:\n            run_xdotool(["windowactivate", "--sync", window.window_id])\n        except subprocess.TimeoutExpired:\n            run_xdotool(["windowactivate", window.window_id])\n        run_xdotool(["windowfocus", window.window_id])\n        time.sleep(0.25)\n        active = run_xdotool(["getactivewindow"])\n        if is_window_active(window.window_id, active.stdout):\n            return\n        time.sleep(0.3)',
    'focus_window')

# is_window_active
replace_func(
    b'def is_window_active',
    b'def is_window_active(window_id: str, active_stdout: str) -> bool:\n    return str(window_id).strip() == str(active_stdout).strip()',
    'is_window_active')

# click_relative
replace_func(
    b'def click_relative',
    b'def click_relative(window: WindowInfo, x: int, y: int) -> None:\n    x = min(max(2, int(x)), max(2, window.width - 2))\n    y = min(max(2, int(y)), max(2, window.height - 2))\n    run_xdotool(["mousemove", "--window", window.window_id, str(x), str(y)])\n    time.sleep(0.08)\n    run_xdotool(["click", "--window", window.window_id, "1"])\n    time.sleep(0.25)',
    'click_relative')

# click_xy
replace_func(
    b'def click_xy',
    b'def click_xy(screen_x: int, screen_y: int) -> None:\n    run_xdotool(["mousemove", str(screen_x), str(screen_y)])\n    time.sleep(0.1)\n    run_xdotool(["click", "1"])\n    time.sleep(0.25)',
    'click_xy')

# get_clipboard_text
replace_func(
    b'def get_clipboard_text',
    b'def get_clipboard_text(timeout: float = 1.0) -> str:\n    try:\n        result = subprocess.run(\n            ["xclip", "-selection", "clipboard", "-o"],\n            capture_output=True,\n            text=True,\n            timeout=timeout,\n            check=False,\n        )\n    except (FileNotFoundError, subprocess.TimeoutExpired):\n        return ""\n    return result.stdout if result.returncode == 0 else ""',
    'get_clipboard_text')

# press
replace_func(
    b'def press(',
    b'def press(key: str, window: Optional[WindowInfo] = None) -> None:\n    args = ["key", "--clearmodifiers"]\n    if window is not None:\n        args.extend(["--window", window.window_id])\n    args.append(key)\n    run_xdotool(args)\n    time.sleep(0.2)',
    'press')

# scroll_pages
replace_func(
    b'def scroll_pages',
    b'def scroll_pages(count: int, pause: float) -> None:\n    for _ in range(count):\n        run_xdotool(["key", "Page_Down"])\n        time.sleep(pause)',
    'scroll_pages')

# event_matches_city
replace_func(
    b'def event_matches_city',
    b'def event_matches_city(event: Mapping[str, Any], city_ids: set[str]) -> bool:\n    if not city_ids:\n        return True\n    return str(event.get("cityId", "")) in city_ids',
    'event_matches_city')

# event_matches_search
replace_func(
    b'def event_matches_search',
    b'def event_matches_search(event: Mapping[str, Any], store: Store, keyword: str, attempted_keywords: set[str] | None = None, require_city: bool = False) -> bool:\n    if attempted_keywords is not None:\n        attempted = {normalized_keyword(value) for value in attempted_keywords if normalized_keyword(value)}\n        if keyword not in attempted:\n            return False\n    branch = store.name.replace("\xe8\xbe\xbe\xe7\xbe\x8e\xe4\xb9\x90\xe6\xaf\x94\xe8\x90\xa8(", "").replace(")", "")\n    if branch and branch.replace("\xe5\xba\x97", "") not in keyword and "\xe8\xbe\xbe\xe7\xbe\x8e\xe4\xb9\x90" not in keyword:\n        return False\n    if not require_city:\n        return True\n    return search_event_matches_city(event, store)',
    'event_matches_search')

# event_has_matching_candidate
replace_func(
    b'def event_has_matching_candidate',
    b'def event_has_matching_candidate(store: Store, event: Mapping[str, Any], min_score: int) -> bool:\n    return choose_candidate_from_event(store, event, min_score) is not None',
    'event_has_matching_candidate')

# review_event_matches_candidate
replace_func(
    b'def review_event_matches_candidate',
    b'def review_event_matches_candidate(\n    event: Mapping[str, Any],\n    candidate: Candidate,\n    store: Store,\n    full_only: bool = False,\n) -> bool:\n    """Match review events by actual mitm evidence, allowing shopId/shopUuid aliases."""\n    if event.get("type") != "review":\n        return False\n    if int(event.get("review_count") or 0) <= 0:\n        return False\n    if full_only and not is_full_review_event(event):\n        return False\n    event_uuid = str(event.get("shopuuid", ""))\n    candidate_uuid = str(candidate.uuid or "")\n    if event_uuid and candidate_uuid:\n        return event_uuid == candidate_uuid\n    if event_uuid and not candidate_uuid:\n        return False\n    event_store_name = str(event.get("storeName", ""))\n    return normalized_store_identity(event_store_name) == normalized_store_identity(store.name)',
    'review_event_matches_candidate')

# candidate_review_event_for_attempt
replace_func(
    b'def candidate_review_event_for_attempt',
    b'def candidate_review_event_for_attempt(event: Mapping[str, Any], *, full_only: bool = False) -> bool:\n    if event.get("type") != "review":\n        return False\n    if int(event.get("review_count") or 0) <= 0:\n        return False\n    if full_only and not is_full_review_event(event):\n        return False\n    return True',
    'candidate_review_event_for_attempt')

# duplicate_store_names
replace_func(
    b'def duplicate_store_names',
    b'def duplicate_store_names(stores: Sequence[Store]) -> set[str]:\n    counts: Dict[str, int] = {}\n    for store in stores:\n        counts[store.name] = counts.get(store.name, 0) + 1\n    return {name for name, count in counts.items() if count > 1}',
    'duplicate_store_names')

# unresolved_stores
replace_func(
    b'def unresolved_stores',
    b'def unresolved_stores(stores: Sequence[Store], log_dir: Path, progress: Mapping[str, Any]) -> List[Store]:\n    rows, stats = build_export_rows(stores=stores, log_dir=log_dir, explicit_uuid_map=load_uuid_map(log_dir))\n    complete_review_stores = set(stats.get("complete_review_stores", []))\n    duplicate_names = duplicate_store_names(stores)\n    pending: List[Store] = []\n    for index, store in enumerate(stores, start=1):\n        if store_is_audited_complete(index, store, complete_review_stores, duplicate_names, progress):\n            continue\n        if store.name in complete_review_stores and store.name not in duplicate_names:\n            continue\n        pending.append(store)\n    return pending',
    'unresolved_stores')

# Save
with open(TARGET, 'wb') as f:
    f.write(data)

# Verify
text = data.decode('utf-8')
try:
    compile(text, str(TARGET), 'exec')
    remaining = text.count('�')
    print(f'\nSUCCESS! {count} blocks fixed. File compiles!')
    if remaining:
        print(f'Note: {remaining} U+FFFD chars remain (likely in strings/comments)')
except SyntaxError as e:
    print(f'\nL{e.lineno}: {e.msg}')
    lines = text.split('\n')
    for o in range(-3, 4):
        ln = e.lineno - 1 + o
        if 0 <= ln < len(lines):
            m = '>>>' if o == 0 else '   '
            show = lines[ln].replace(chr(0xfffd), '?')[:180]
            print(f'{m} L{ln+1}: {show}')
