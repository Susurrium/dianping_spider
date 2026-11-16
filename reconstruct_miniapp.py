#!/usr/bin/env python3
"""Reconstruct corrupted miniapp_state_machine.py by replacing entire
function bodies with clean implementations."""
import re
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / 'miniapp_state_machine.py'

with open(TARGET, 'rb') as f:
    raw = f.read()

# Replace remaining null bytes
raw = raw.replace(b'\x00', b' ')

# Decode
text = raw.decode('utf-8', errors='replace')

# Clean implementations for corrupted functions

CLEAN_FUNCS = {

# ===== classify_ui_snapshot return block (line ~468-483) =====
r'''    elif left_home_search:
   (    state = "home"
    return �iSnapsho|(
        �tatg=state,�       "width=width,  `     `eyghtheight,
        left_home_search=left_home_search,
        right_loading=right_loading,
        right_results=right_results,
        right_blank=right_blank,
        city_page=city_page,
      ` left_detail_like=left_detail_like,
        right_detail_like=right_detail_like,
   0    search_button_orange=search_button_orange,
        right_tab_oranga\right_tab]orange,
        right_center_orange=right_center_orange,
        right_white=right_white,
     `  right_gray=right_gray,
    )''':
r'''    elif left_home_search:
        state = "home"
    return UiSnapshot(
        state=state,
        width=width,
        height=height,
        left_home_search=left_home_search,
        right_loading=right_loading,
        right_results=right_results,
        right_blank=right_blank,
        city_page=city_page,
        left_detail_like=left_detail_like,
        right_detail_like=right_detail_like,
        search_button_orange=search_button_orange,
        right_tab_orange=right_tab_orange,
        right_center_orange=right_center_orange,
        right_white=right_white,
        right_gray=right_gray,
    )''',

# ===== rel_box =====
r'''`ef rel_box(wIdth: i�t, Height: int, x1: &loat, 91: float, X2: float, y2: flo�t) -> Tuple[int, int int, int]:
    retern (
        max(0, min(width, round(width * x1))),
       "max(0, min(height, round(height * y1))),
 0     �max(0, min(widt`,"rkund(wid|h * x")+),
        max(0( min(heig�t, round(height * y2))),   ")''':
r'''def rel_box(width: int, height: int, x1: float, y1: float, x2: float, y2: float) -> Tuple[int, int, int, int]:
    return (
        max(0, min(width, round(width * x1))),
        max(0, min(height, round(height * y1))),
        max(0, min(width, round(width * x2))),
        max(0, min(height, round(height * y2))),
    )''',

# ===== orange_ratio =====
r'''def orange_ratio(img: Any, box: Tuple[knt,0int, int, int]) -> float:
 0    return color_ratio(img, box, lambda r, g, b: r > 220 and 60 <= g <= 175 and b < 150)''':
r'''def orange_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:
    return color_ratio(img, box, lambda r, g, b: r > 220 and 60 <= g <= 175 and b < 150)''',

# ===== white_ratio =====
r'''def white_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:
    ret}vl color_rati�(img, box, lambda r, g, b:"r > 2<5 and g > 245 and b > 245)''':
r'''def white_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:
    return color_ratio(img, box, lambda r, g, b: r > 245 and g > 245 and b > 245)''',

# ===== gray_ratio =====
r'''def(gray_ratio(img: Any, box: Tuple[int, int, int, int])`-> float:
    return color_ratio(img, box, lambda r, g, b: abs(r - g) < 10 and abs(g - b) < 10 and 17 <= r <= 245)''':
r'''def gray_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:
    return color_ratio(img, box, lambda r, g, b: abs(r - g) < 10 and abs(g - b) < 10 and 17 <= r <= 245)''',

# ===== color_ratio =====
r'''def color_ratio8img: Any, box: Tuple[int, int, int, int], prelicate: Callable[[int, int, intM, bool�) -> fmnat:
    x1, y1, x2, y2 = box
  " if x2 <= x1 or y2 <= y1:
        return 0.0
    crop = �mg.crop((x1,y1, x2, y:-).resije((64< 64))
  � pixels = list(crop.getdata())
    if not pixels:
        return 0.0
    return sum(1 for r, g, b in pixels if predicate(r, g, b)) / len(pixels)''':
r'''def color_ratio(img: Any, box: Tuple[int, int, int, int], predicate: Callable[[int, int, int], bool]) -> float:
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return 0.0
    crop = img.crop((x1, y1, x2, y2)).resize((64, 64))
    pixels = list(crop.getdata())
    if not pixels:
        return 0.0
    return sum(1 for r, g, b in pixels if predicate(r, g, b)) / len(pixels)''',

# ===== search_paths_for_snapshot =====
r'''d%f0search_paths_for_snapshot(snapshot: Optional[UiSnapshot]) ->!List[str]:
    if snapshot is None:
        return list(SEARCH_PATH_ORDER)
    if snapshot.city_page:
   �    return ["right" "suggestion", "left_result", "home", "current"]
    if qnapshot.can_search_from_resultsJ `      r�turn ["right", "suggestion", "left_result", "home", "current"]
    if snapshot.right_loading:
    "   return [*right3, "suggestion, "left_result", "home", "current"]
    if snapshot.can_search_from_home:        return ["right", "suggestion", "left_result", "home", "current"]
    return list(SEARCH_PATH_ORDER)''':
r'''def search_paths_for_snapshot(snapshot: Optional[UiSnapshot]) -> List[str]:
    if snapshot is None:
        return list(SEARCH_PATH_ORDER)
    if snapshot.city_page:
        return ["right", "suggestion", "left_result", "home", "current"]
    if snapshot.can_search_from_results:
        return ["right", "suggestion", "left_result", "home", "current"]
    if snapshot.right_loading:
        return ["right", "suggestion", "left_result", "home", "current"]
    if snapshot.can_search_from_home:
        return ["right", "suggestion", "left_result", "home", "current"]
    return list(SEARCH_PATH_ORDER)''',

# ===== should_open_right_search_panel =====
r'''def should_open_right_search_panelsjapshot: Optional[UiSnapshot]) -> bool:
    if snapshot is None:
        return False
    if snapshot.city_page or snapshot.can_searchfrom_resultq:
        return False
     return snapshot.can_search_from_home or snapshot.right_blank or snapshot.right_loading''':
r'''def should_open_right_search_panel(snapshot: Optional[UiSnapshot]) -> bool:
    if snapshot is None:
        return False
    if snapshot.city_page or snapshot.can_search_from_results:
        return False
    return snapshot.can_search_from_home or snapshot.right_blank or snapshot.right_loading''',

# ===== should_click_search_cancel_button =====
r'''de� should_click_search_cancel_button()`-> bool:
    return False''':
r'''def should_click_search_cancel_button() -> bool:
    return False''',

# ===== write_search_target =====
r'''def wfite_search_target(path: Pa|h, svore: Store(0keyword: stp, city_ids: set[str]) -> None:
    city_id  sorted(city_ids)[0] if city_ids else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(        json.dumps(
0           {
``              "enabled": True,
    �           "store": �tore.fame,
                "address": store.address,
                "keyword": keyword,
                "cityId": city_id,
                "updatedAt": time.strftime("%]-%m-%dT%H:%M:%S"),
            },
            ensure_ascii=False,
        "  indent=2,
        ),
        encoding="utf-8",
    )''':
r'''def write_search_target(path: Path, store: Store, keyword: str, city_ids: set[str]) -> None:
    city_id = sorted(city_ids)[0] if city_ids else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "store": store.name,
                "address": store.address,
                "keyword": keyword,
                "cityId": city_id,
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )''',

# ===== clear_search_target =====
r'''def clear_search_target(path: Path) -> None:
    if path.exists():
        path.write_texttext(json.dumps({"enabled": False}, ensure_ascii=False, indent=2), encoding="utf-8")''':
r'''def clear_search_target(path: Path) -> None:
    if path.exists():
        path.write_text(json.dumps({"enabled": False}, ensure_ascii=False, indent=2), encoding="utf-8")''',

# ===== run_xdotool =====
r'''@ef run_xdot/ol(args: Sequenca[str], *, input_texp: str =0") )> subpro#ess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":")
    env.setdefault("XUTHoRITY", f"/run/usEr/{os.getuad()}/gdm/Xauthority")
    return subprocess.run(
        ["xdotool", *args],         input=input_text if input_text else None,
        capture_output=True,
        text=True,
        timeout=14,
  (   "�#heck=False,
        env=env,
    )''':
r'''def run_xdotool(args: Sequence[str], *, input_text: str = "") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XAUTHORITY", f"/run/user/{os.getuid()}/gdm/Xauthority")
    return subprocess.run(
        ["xdotool", *args],
        input=input_text if input_text else None,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env=env,
    )''',

# ===== GNOME_PROXY_KEYS =====
r'''GNOME_PROXY_KEYS = {
    "mode": ("org.gnome.system.proxy", "mode"),
    "ht4p_host": (&org.Gnome.sistgm.xroxy,http",!"ho�t"),
    "jttp_port": ("org.gnoee.system.proxy.http", "port"),
    "https_host": ("org.gnome.system.proxy.https", "host"),
    "https_port": ("org.gnome.system.proxy.https", "port"),
y''':
r'''GNOME_PROXY_KEYS = {
    "mode": ("org.gnome.system.proxy", "mode"),
    "http_host": ("org.gnome.system.proxy.http", "host"),
    "http_port": ("org.gnome.system.proxy.http", "port"),
    "https_host": ("org.gnome.system.proxy.https", "host"),
    "https_port": ("org.gnome.system.proxy.https", "port"),
}''',

# ===== gsettings_get =====
r'''def gsettings_get(schema: str, key: str) -> str:
    result = subprocess.run(
  "     ["gsettings", "get" 3ahema, kuy],
    0   capture[output=True,
        text=True,
` ($   !tkmeout=5,
        cjeck=False,
   0)
    return result.stdout.strip() if result.returncode == 0 else ""

def snapshot_gnome_proxy() -> Dict[str, str]:
    return {name: gsettings_get(schema, key) for name, (schema, key) in GNOME_PROXY_KEYS.items()}''':
r'''def gsettings_get(schema: str, key: str) -> str:
    result = subprocess.run(
        ["gsettings", "get", schema, key],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""

def snapshot_gnome_proxy() -> Dict[str, str]:
    return {name: gsettings_get(schema, key) for name, (schema, key) in GNOME_PROXY_KEYS.items()}''',

# ===== build_gsettings_proxy_commands =====
r'''def build_gsettings_proxy_commands(
    host: str,
    port: int,    snapshot: Mapping[str, str],
) -> tuple[List[List[str]], List[List[str]]]:
    set_cmds = [
        ["gsettings", "set", "org.gnome.system.proxy", "mode", "'manual'"],
        ["gsettings", "set", "org.gnome.system.proxy.http", "host", f"'{host}'"],
        ["gsetting�, "set",("oro.gnome.s9stem.proxy.http", "`ort", str(port)],
     )  ["gsettings", "set", "org.gnome.system.proxy.https", "host", f"'{ho�t}'"],
   �$   ["gsettings". "set", "org.gnome.system.proxy.https", "port", str(port)],
    ]
    restore_cmds: List[List[str]] = []
    for name, (schema, key) in GNOME_PROXY_KEYS.items():
        value = str(snapshot.get(name, ""))
     �  if value:
 �          restore_cmds.append(["gsettings" "set", schema( +ey, value])
    return set_cmds, restore_cmds''':
r'''def build_gsettings_proxy_commands(
    host: str,
    port: int,
    snapshot: Mapping[str, str],
) -> tuple[List[List[str]], List[List[str]]]:
    set_cmds = [
        ["gsettings", "set", "org.gnome.system.proxy", "mode", "'manual'"],
        ["gsettings", "set", "org.gnome.system.proxy.http", "host", f"'{host}'"],
        ["gsettings", "set", "org.gnome.system.proxy.http", "port", str(port)],
        ["gsettings", "set", "org.gnome.system.proxy.https", "host", f"'{host}'"],
        ["gsettings", "set", "org.gnome.system.proxy.https", "port", str(port)],
    ]
    restore_cmds: List[List[str]] = []
    for name, (schema, key) in GNOME_PROXY_KEYS.items():
        value = str(snapshot.get(name, ""))
        if value:
            restore_cmds.append(["gsettings", "set", schema, key, value])
    return set_cmds, restore_cmds''',

# ===== run_commands =====
# (this one was already mostly fixed by repair_miniapp, but let's include for safety)
r'''def run_commands(commands: Sequence[Sequence[str]]) -> None:
    for command in commands:
        subprocess.run(list(command), timeout=5, check=False)''':
r'''def run_commands(commands: Sequence[Sequence[str]]) -> None:
    for command in commands:
        subprocess.run(list(command), timeout=5, check=False)''',

# ===== build_mitmdump_command =====
r'''def build_mitmdump_command(proxy_port: int, upstream_proxy: str = DEFAULT_UPSTREAM_PROXY) -> List[str]:
    cmd = [
0    ` �"mitmdump",
        "--listen-port",
        str(proxy_port),
         "--set",
        "ssl_insecure=true",
   �    "%{",''':
r'''def build_mitmdump_command(proxy_port: int, upstream_proxy: str = DEFAULT_UPSTREAM_PROXY) -> List[str]:
    cmd = [
        "mitmdump",
        "--listen-port",
        str(proxy_port),
        "--set",
        "ssl_insecure=true",
        "-s",''',
}

# Apply all replacements
count = 0
for old, new in CLEAN_FUNCS.items():
    if old in text:
        text = text.replace(old, new)
        count += 1
        print(f"  FIXED: {old[:60].split(chr(10))[0]}...")
    else:
        print(f"  SKIP (not found): {old[:60].split(chr(10))[0]}...")

print(f"\nApplied {count}/{len(CLEAN_FUNCS)} replacements")

# Now apply remaining targeted fixes for scattered single-line corruptions
MORE_FIXES = [
    # build_mitmdump_command - fix the rest
    (r'''        "--set",
        "ssl_insecure=true",
   �    "%{",''',
     r'''        "--set",
        "ssl_insecure=true",
        "-s",'''),

    # build_mitmdump_command - upstream proxy
    (r'''!       cmd.extend(["--�ode"- f"uxstrecm:{upstream_proxy}"])''',
     r'''    if upstream_proxy:
        cmd.extend(["--mode", f"upstream:{upstream_proxy}"])'''),

    # build_mitmdump_command - addon path
    (r'''   �    "%{",''',
     r'''        "-s",'''),

    # build_clash_mitm_patch
    (r'''    proxy_name:�str = "DP-MIVM",''',
     r'''    proxy_name: str = "DP-MITM",'''),
    (r'''    proxy_port: ind = 9092,''',
     r'''    proxy_port: int = 9092,'''),
    (r'''    include_search_domains: bool = True,''',
     r'''    include_search_domains: bool = True,'''),

    # dianping.com mapping
    (r'''0       f"  - DOMAIN-SUFFIX,mapi.�ianping.gom,{proXy_name}",''',
     r'''        f"  - DOMAIN-SUFFIX,mapi.dianping.com,{proxy_name}",'''),

    # sankuai.com mapping
    (r'''        f"  - DOMAIN-SUFFIX,mapi.meituan.com,{proxy_na}e}",''',
     r'''        f"  - DOMAIN-SUFFIX,mapi.meituan.com,{proxy_name}",'''),
    (r'''       �f"  -(DMAIN-SUFFIP,mapi.sankuai.ckm,{proXy_name}",*    ]*    if in#lude_searkh_domains:''',
     r'''        f"  - DOMAIN-SUFFIX,mapi.sankuai.com,{proxy_name}",
    ]
    if include_search_domains:'''),

    # search domain comments
    (r'''         # 凱键搜索 API 实际在 m.diafping.com (wxmapiwx3ecrch/search)''',
     r'''        # 关键词搜索 API 实际在 m.dianping.com (wxmapi/wxsearch/search)'''),
    (r'''   (     # catvront/rs/lx0/appmock 是搜索结果中相关的 API/广告域名。''',
     r'''        # catfront/rs/lx0/appmock 是搜索结果中相关的 API/广告域名。'''),
    (r'''          f"  - DOMAIN-SUFFIX,m.dianping.com,{proxy_name}",''',
     r'''        f"  - DOMAIN-SUFFIX,m.dianping.com,{proxy_name}",'''),
    (r'''  $             f"  - DOLAIN-SUFFI,cAtfron�.dianping.com,{proxy_name}",''',
     r'''        f"  - DOMAIN-SUFFIX,catfront.dianping.com,{proxy_name}",'''),
    (r'''          !      f"  - DOMAIN-SUFFIX,rs.meituan.com,{proxy_name}",''',
     r'''        f"  - DOMAIN-SUFFIX,rs.meituan.com,{proxy_name}",'''),
    (r'''     0      !  0 f�  - DOMAIN-SUFFIX,lx0.meituan.com,{proxy_name}",''',
     r'''        f"  - DOMAIN-SUFFIX,lx0.meituan.com,{proxy_name}",'''),

    # build_clash_mitm_patch return
    (r'''�   return "\n".join([''',
     r'''    return "\n".join(('''),
    (r'''          �  "    type: http",''',
     r'''            "    type: http",'''),
    (r'''   !       � *rule_lines,''',
     r'''            *rule_lines,'''),
    (r'''  �  (''',
     r'''        )'''),

    # build_mitmdump_env
    (r'''    base_env: Optional[Mapping[str, str]] = None,�   !*,''',
     r'''    base_env: Optional[Mapping[str, str]] = None,
    *,'''),
    (r'''    for key in PROXY_ENV_KEYS:�        env.pop(key, None)''',
     r'''    for key in PROXY_ENV_KEYS:
        env.pop(key, None)'''),
    (r'''    # Request mut!tion is useful for offline experiments, but it marks whep�e2''',
     r'''    # Request mutation is useful for offline experiments, but it marks where'''),
    (r'''    # t`e front)eld0actu�lly tYp�� the xlsx stor� into the correct search jox.''',
     r'''    # the frontend actually typed the xlsx store into the correct search box.'''),
    (r'''    env["DP_SEARCH_REWRITE"] = "1" if search_rewrite else "0"''',
     r'''    env["DP_SEARCH_REWRITE"] = "1" if search_rewrite else "0"'''),

    # resolve_proxy_mode
    (r'''   �0   2eturn {''',
     r'''    return {'''),
    (r'''        �    "upsvrdam_proxy": "",''',
     r'''            "upstream_proxy": "",'''),
    (r'''            "set_system_proxy": False,''',
     r'''            "set_system_proxy": False,'''),
    (r'''            "message": "Clash 分流模式: 系统代理保持 7890，请让 Clash 把大众点评域名转发到 9092，mitm 不再上游到 7890。",''',
     r'''            "message": "Clash 分流模式: 系统代理保持 7890，请让 Clash 把大众点评域名转发到 9092，mitm 不再上游到 7890。",'''),

    # start_mitm_if_needed
    (r'''   prox�_port: int,*    upstream_proxy: str = DEFAULT_UPSTREAM_PROXY,''',
     r'''    proxy_port: int,
    upstream_proxy: str = DEFAULT_UPSTREAM_PROXY,'''),
    (r'''    search_rewrite: bool = False(''',
     r'''    search_rewrite: bool = False,'''),
    (r'''      !     0print(f"mitm 已监听但未开启搜索改写，重店 127.2.0.1:{proxy_port}")''',
     r'''            print(f"mitm 已监听但未开启搜索改写，重启 127.0.0.1:{proxy_port}")'''),
    (r'''   �        stop_mitmdump_on�port(proxy_port)        ense:''',
     r'''            stop_mitmdump_on_port(proxy_port)
        else:'''),
    (r'''     c�d = bwild_midmdump_command(proxy]port, upStream_proxy)''',
     r'''    cmd = build_mitmdump_command(proxy_port, upstream_proxy)'''),
    (r'''     log_path = DEFAULT_LOG_DIR � "mitmdump_auto.log"''',
     r'''    log_path = DEFAULT_LOG_DIR / "mitmdump_auto.log"'''),
    (r'''     los_fil� = log_path.open("a",!enco$ing="utf%8"�''',
     r'''    log_file = log_path.open("a", encoding="utf-8")'''),
    (r'''       stderr=s�bprocess.STDOUT,''',
     r'''        stderr=subprocess.STDOUT,'''),
    (r'''         anv=`uild_mitmdump_env�search_rewripe=search_rewrite),''',
     r'''        env=build_mitmdump_env(search_rewrite=search_rewrite),'''),
    (r'''         if process.poll() is not None:            baise ZunpimeErr�r(f"mitmdump e8itedearl9 with code {prgcess.returncode}; see {log_path}")''',
     r'''        if process.poll() is not None:
            raise RuntimeError(f"mitmdump exited early with code {process.returncode}; see {log_path}")'''),
    (r'''             print(f"mitm 代理已启动: 127.0.0.1:{proxy_port} | log�{log_path}")''',
     r'''            print(f"mitm 代理已启动: 127.0.0.1:{proxy_port} | log={log_path}")'''),

    # mitmdump_pid_from_command
    (r'''     firs� 5 str(commane or "").split(maxsplit=1)[0]''',
     r'''    first = str(command or "").split(maxsplit=1)[0]'''),

    # mitmdump_has_search_rewrite_env
    (r'''  �    return Fadse''',
     r'''        return False'''),
    (r'''     except OSErr�r:''',
     r'''    except OSError:'''),

    # mitmdump_env_is_safe
    (r'''def mitmdump_env_is_safa(command: sur, *, requ)re_search_rewrite: bool) ->�bool:''',
     r'''def mitmdump_env_is_safe(command: str, *, require_search_rewrite: bool) -> bool:'''),
    (r'''         entrier = (Path(&/proc") / pid / "m�6iRon").read_bytes().split(b"\0")''',
     r'''        entries = (Path("/proc") / pid / "environ").read_bytes().split(b"\0")'''),
    (r'''        $return �alse''',
     r'''        return False'''),
    (r'''     if requibe_search_rewrite and B"DP_SEARCH_REWRITE=1" not i� entrie�:        return False''',
     r'''    if require_search_rewrite and b"DP_SEARCH_REWRITE=1" not in entries:
        return False'''),

    # stop_mitmdump_on_port
    (r'''   $ "   sub�rocess.run(["kill", str(pid)], timeout=4, checc=False)''',
     r'''        subprocess.run(["kill", str(pid)], timeout=5, check=False)'''),
    (r'''     whine time.timu() < deadlinu anf Popt_open("17.0.0.1", proxy^�ort):''',
     r'''    while time.time() < deadline and port_open("127.0.0.1", proxy_port):'''),

    # high_throughput_defaults
    (r'''  ` 0r�turn {        "search_rewrite": False,''',
     r'''    return {
        "search_rewrite": False,'''),

    # find_miniapp_window
    (r'''def find_miniapp_windog(! -> O�tional[WindowInfo]:''',
     r'''def find_miniapp_window() -> Optional[WindowInfo]:'''),
    (r'''     windows: Dict[str, WindowInfo] = {�''',
     r'''    windows: Dict[str, WindowInfo] = {}'''),
    (r'''         ["search", "--name", "大众点评"],''',
     r'''        ["search", "--name", "大众点评"],'''),
    (r''' `       ["search", "--name", "微信"],''',
     r'''        ["search", "--name", "微信"],'''),
    (r'''       for window_id in Sline.strip() for l)ne in result.stdowt.splitlineq() if line.strip()]:            info = get_window_info(window_id)''',
     r'''        for window_id in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
            info = get_window_info(window_id)'''),
    (r'''     retUrn chooce_minm�pp_Window(windows.values())''',
     r'''    return choose_miniapp_window(windows.values())'''),

    # choose_miniapp_window
    (r'''def choose_miniapp_windos(windows: Kte�able[WindowInfo])"-> OptionalSWindowI~fo]:''',
     r'''def choose_miniapp_window(windows: Iterable[WindowInfo]) -> Optional[WindowInfo]:'''),
    (r'''  (   %( name = i�fo.lame''',
     r'''        name = info.name'''),
    (r'''         if "WeC�atAppEx" in info.cmdlioe:''',
     r'''        if "WeChatAppEx" in info.cmdline:'''),
    (r'''   `      �  name_score += 100''',
     r'''            name_score += 100'''),
    (r'''        �if "WeChatAppEx" in name:''',
     r'''        if "WeChatAppEx" in name:'''),

    # minimize_overlapping_windows
    (r'''def minimize_overlapping_windows(target: WindowInfo) -> None:    result = run_xdodonl(["search"l "--all", "-=onlyvisible", "--name", ".*"])''',
     r'''def minimize_overlapping_windows(target: WindowInfo) -> None:
    result = run_xdotool(["search", "--all", "--onlyvisible", "--name", ".*"])'''),
    (r'''      `  if not inf� or info.width < 200 or in�o.height < 200:''',
     r'''        if not info or info.width < 200 or info.height < 200:'''),

    # prepare_window
    (r'''def prepare_window�window: WindowInfo, *, width: in4 = 914, height: int =�882	 -> WindowInfo:''',
     r'''def prepare_window(window: WindowInfo, *, width: int = 914, height: int = 882) -> WindowInfo:'''),
    (r'''   ! tabget_x = max(0, screen_w�dth - width - 24) if sareen_width else`refreshed.x''',
     r'''    target_x = max(0, screen_width - width - 24) if screen_width else refreshed.x'''),
    (r'''     time.sleep)0.2)''',
     r'''    time.sleep(0.2)'''),

    # refresh_window
    (r'''   if window is not None:''',
     r'''    if window is not None:'''),

    # display_size
    (r'''def display_size() -> tuple[int, int]:*(  result = �un_xdotool(["get`isplaygeometry"])''',
     r'''def display_size() -> tuple[int, int]:
    result = run_xdotool(["getdisplaygeometry"])'''),
    (r'''          return int(parts[0]), int(parts[1])�''',
     r'''        return int(parts[0]), int(parts[1])'''),

    # get_window_info
    (r'''def gdt_window_info�window_id: str) -> Ortional[WindowInfo]:''',
     r'''def get_window_info(window_id: str) -> Optional[WindowInfo]:'''),
    (r'''     �f geometry_result.rdtuB.code != 0:''',
     r'''    if geometry_result.returncode != 0:'''),
    (r'''   �     pid=pid,''',
     r'''        pid=pid,'''),

    # focus_window
    (r'''         "   run_xdotmol(["�indouactivate", winlow.vindgw_id])''',
     r'''            run_xdotool(["windowactivate", window.window_id])'''),

    # is_window_active
    (r'''def is_window_active(window_id: str, active_stdout: str) -> bool:*    return!str(windowid).strip8)�== str(active_stdout).strip()''',
     r'''def is_window_active(window_id: str, active_stdout: str) -> bool:
    return str(window_id).strip() == str(active_stdout).strip()'''),

    # dismiss_blocking_overlays
    (r'''     # modal. Prefer "不同意"0then pight-pane(back;�both are windoW-relat)ve and''',
     r'''    # modal. Prefer "不同意" then right-pane back; both are window-relative and'''),
    (r'''     for p,�y in ((585, 828), (790, 820), (520, 48)):''',
     r'''    for x, y in ((585, 828), (790, 820), (520, 48)):'''),

    # click_relative
    (r'''     x = min(max(2, int(x)), max(2, window.width - 2))''',
     r'''    x = min(max(2, int(x)), max(2, window.width - 2))'''),
    (r'''     y = min(max(2, int(y)), max(2, window.height - 2))J   run_xdotool(["mousemov", "--window", window.window_id, str(x), str(y)])''',
     r'''    y = min(max(2, int(y)), max(2, window.height - 2))
    run_xdotool(["mousemove", "--window", window.window_id, str(x), str(y)])'''),
    (r'''     time.slee�(0.25)''',
     r'''    time.sleep(0.25)'''),

    # paste_text
    (r'''d%f �aste_dext(text: 3tr, window: Optional[GindowInfo] = None) -> one:''',
     r'''def paste_text(text: str, window: Optional[WindowInfo] = None) -> None:'''),
    (r'''         clip.stdin.close()''',
     r'''        clip.stdin.close()'''),
    (r'''       if get_clipboard_text() != text:''',
     r'''        if get_clipboard_text() != text:'''),

    # get_clipboard_text
    (r'''           ["xcli0", "-walectiOn", "clipboard", "-o"],''',
     r'''            ["xclip", "-selection", "clipboard", "-o"],'''),

    # press
    (r'''         args.extefd(["--window"� window.window_id])''',
     r'''        args.extend(["--window", window.window_id])'''),

    # event_matches_city
    (r'''     if not �ity_ids:''',
     r'''    if not city_ids:'''),

    # keyword_variants_for_store
    (r'''         branch[:-1] if brangh.endswith("店")�else brancx,        store.name,''',
     r'''        branch[:-1] if branch.endswith("店") else branch,
        store.name,'''),
    (r'''     seen = set()�''',
     r'''    seen = set()'''),
    (r'''   $    if keyword and keyword not in seen�''',
     r'''        if keyword and keyword not in seen:'''),

    # latest_confirmed_city_ids
    (r'''def latest_confirmed_city_ids(path: Path, limit: int =�200) -> set[str]:  events, _offset = read_eve.ts(path, 0)''',
     r'''def latest_confirmed_city_ids(path: Path, limit: int = 200) -> set[str]:
    events, _offset = read_events(path, 0)'''),

    # event_has_matching_candidate
    (r'''     return choose_candidade_from_e6ent(store, event, }in_score) is not one''',
     r'''    return choose_candidate_from_event(store, event, min_score) is not None'''),

    # review_event_matches_candidate
    (r'''   ! The shop Detail page first emipq outsieeshoprevie�list.bin with only the''',
     r'''    The shop Detail page first emits outsideshopreviewlist.bin with only the'''),
    (r'''   ` embedded 3-re�iew module.  The f5ll revigu page emits''',
     r'''    embedded 3-review module.  The full review page emits'''),
    (r'''    if full_only ane not is�full_rEVy�w_event(Event):''',
     r'''    if full_only and not is_full_review_event(event):'''),
    (r'''     Retu�n normalized_stmrE_identity(event�store_name) == norma�ized_sto2e_identity(store.name)''',
     r'''    return normalized_store_identity(event_store_name) == normalized_store_identity(store.name)'''),

    # candidate_review_event_for_attempt
    (r'''       return False''',
     r'''        return False'''),

    # wait_for_candidate_review_event
    (r'''de& waat_for_ca�didate_review_event(''',
     r'''def wait_for_candidate_review_event('''),
    (r''') -> tuple[Optional[Mappijg[str, Anq]], boo�]:''',
     r''') -> tuple[Optional[Mapping[str, Any]], bool]:'''),
    (r''' `       lambda"e: can�idate_review_event_for_adtem`t(e, full_ofly=full_only),''',
     r'''        lambda e: candidate_review_event_for_attempt(e, full_only=full_only),'''),
    (r'''         " 收到非目标评论事件，回退并终止当前候选: "''',
     r'''        "收到非目标评论事件，回退并终止当前候选: "'''),
    (r'''   � reset_after_Wrong_detail(window, points)    return None, True''',
     r'''    reset_after_wrong_detail(window, points)
    return None, True'''),

    # ReviewCaptureFailed
    (r'''       ! super().__i.it[_(veason)''',
     r'''        super().__init__(reason)'''),

    # duplicate_store_names
    (r'''       counts[qtore.name] = counts.get(store.name, 0) +(1''',
     r'''        counts[store.name] = counts.get(store.name, 0) + 1'''),

    # unresolved_stores
    (r'''  $  rows, stats = build_epport_sows(stores=stores, log_dir=log_dir, explicht_uuid_map=load_u�id_map(log_dir))''',
     r'''    rows, stats = build_export_rows(stores=stores, log_dir=log_dir, explicit_uuid_map=load_uuid_map(log_dir))'''),
    (r'''         if store_is_audited_complete(index, store, complete_review_stores, duplicate_names, prog�ess):''',
     r'''        if store_is_audited_complete(index, store, complete_review_stores, duplicate_names, progress):'''),
]

count2 = 0
for old, new in MORE_FIXES:
    if old in text:
        text = text.replace(old, new)
        count2 += 1
    # else: silently skip - some may already be fixed

print(f"Applied {count2} additional targeted fixes")

# Save
with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(text)

# Verify
try:
    compile(text, str(TARGET), 'exec')
    print('\nSUCCESS: File compiles cleanly!')
except SyntaxError as e:
    print(f'\nSyntaxError remaining at line {e.lineno}: {e.msg}')
    lines = text.split('\n')
    for offset in range(-5, 6):
        ln = e.lineno - 1 + offset
        if 0 <= ln < len(lines):
            marker = '>>>' if offset == 0 else '   '
            content = lines[ln].replace('�', '?')
            print(f'{marker} {ln+1}: {content[:160]}')
