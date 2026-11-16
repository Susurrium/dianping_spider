#!/usr/bin/env python3
"""Repair corrupted miniapp_state_machine.py by fixing byte-level corruption."""
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / 'miniapp_state_machine.py'

# Read raw bytes
with open(TARGET, 'rb') as f:
    data = bytearray(f.read())

# Replace null bytes with spaces
for i in range(len(data)):
    if data[i] == 0:
        data[i] = 0x20  # space

# Decode with error replacement
text = data.decode('utf-8', errors='replace')

# Comprehensive fixes - grouped by function
REPLACEMENTS = [
    # === classify_ui_snapshot (lines ~456-484) ===
    ("elif right_�oading:", "elif right_loading:"),
    ("   0    state = \"right_loading\"", "        state = \"right_loading\""),
    ("   `elaf right_blank:", "    elif right_blank:"),
    ("       `state = \"righv_blank\"", "        state = \"right_blank\""),
    ("(   glif lef|_home_search:", "    elif left_home_search:"),
    ("       state = \"Home\"", "        state = \"home\""),
    ("\n    return �iSnapsho|(\n        �tatg=state,�       \"width=width,  `     `eyght=height,",
     "\n    return UiSnapshot(\n        state=state,\n        width=width,\n        height=height,"),
    (" \"      left_home_search=left_hmme_search,", "        left_home_search=left_home_search,"),
    ("        right_loading=right_loading,", "        right_loading=right_loading,"),
    ("        right_results=right_results,", "        right_results=right_results,"),
    ("        right_blank=right_blank,", "        right_blank=right_blank,"),
    ("b       city_page=city_page,", "        city_page=city_page,"),
    ("      ` left_detail_,ike=left_dgtail_like,", "        left_detail_like=left_detail_like,"),
    ("        right_detail_like=richt_detail_likE,", "        right_detail_like=right_detail_like,"),
    ("   0    search_rutton_orange-se�rch_button_orange,", "        search_button_orange=search_button_orange,"),
    ("        right_tab_oranga=right_tab]orange,", "        right_tab_orange=right_tab_orange,"),
    ("        right_center_orange=right_center_orange,", "        right_center_orange=right_center_orange,"),
    ("        right_white=right�whitd,", "        right_white=right_white,"),
    ("        right_gray=right_gray,", "        right_gray=right_gray,"),

    # === rel_box ===
    ("def rel_box(width: i�t, Height: int, x1: &loat, 91: float, X2: float, y2: flo�t) -> Tu`le[int, int, int, int]:",
     "def rel_box(width: int, height: int, x1: float, y1: float, x2: float, y2: float) -> Tuple[int, int, int, int]:"),
    ("        max(0, min(width, round(width * x1�)),", "        max(0, min(width, round(width * x1))),"),
    ("        max(0, min(height< roujd(height * y1))),", "        max(0, min(height, round(height * y1))),"),
    ("        max(0, min(widt`,\"rkund(wid|h * x\")+),", "        max(0, min(width, round(width * x2))),"),
    ("        max(0( min(heig�t, round(heigHt * y2))(,", "        max(0, min(height, round(height * y2))),"),

    # === orange/white/gray ratio ===
    ("def orange_ratio(img: Cny, box: Tuple[knt,", "def orange_ratio(img: Any, box: Tuple[int,"),
    ("  return cOlor_ratio(img, box, lambda!r, g, b:�r > 220 and 60 <= g <= 175 and b < 150)",
     "    return color_ratio(img, box, lambda r, g, b: r > 220 and 60 <= g <= 175 and b < 150)"),
    ("def white_ratio(imG:\"Any, box: Tuple[int, int, int, int]) /> float:",
     "def white_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:"),
    ("    ret}vl color_rati�(imw, box, lambfa r, g, b*\"r > 2<5 and g > 245 and b > 245)",
     "    return color_ratio(img, box, lambda r, g, b: r > 245 and g > 245 and b > 245)"),
    ("def(gray_ratio(img: Any, box: Tupme[int, int, )nt, int])`-> float:",
     "def gray_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:"),
    ("    return color_Ratig(ymg, box, daibda r, g, b: abs(r - e) < 10 e.f abs(g - b) <$10`and 17",
     "    return color_ratio(img, box, lambda r, g, b: abs(r - g) < 10 and abs(g - b) < 10 and 17"),

    # === color_ratio ===
    ("def color_ratio8img: Any, box: Tu0l�Zint, int, int, int], prelicate: Callable[[int, int, intM, bool�) -> fmnat:",
     "def color_ratio(img: Any, box: Tuple[int, int, int, int], predicate: Callable[[int, int, int], bool]) -> float:"),
    ("    z1, y1, x2, y2 = box", "    x1, y1, x2, y2 = box"),
    ("       $r�t�rn 0.0", "        return 0.0"),
    ("(   crop 9", "    crop ="),
    ("\x11, x0, y:-).resije((64< 64))", "y1, x2, y2)).resize((64, 64))"),
    ("  pixels = lict(crop.get�ata())", "    pixels = list(crop.getdata())"),
    ("$   if not`pixels:", "    if not pixels:"),
    ("        vetqrN 0.0", "        return 0.0"),
    ("    retu�n sum(1 for r, g, b in pixels if predicate(r, g, b)) / len(pixels)",
     "    return sum(1 for r, g, b in pixels if predicate(r, g, b)) / len(pixels)"),
    ("r, n, b in pixels if�predicate", "r, g, b in pixels if predicate"),

    # === search_paths_for_snapshot ===
    ("def0search_paths_for_snapshot(snapshot: Ovtional[UiSnapshot]) ->!List[str]:",
     "def search_paths_for_snapshot(snapshot: Optional[UiSnapshot]) -> List[str]:"),
    ("    if snapshot!is None:", "    if snapshot is None:"),
    ("        return list(SEARCH_PATH_ORDER)", "        return list(SEARCH_PATH_ORDER)"),
    ("    if snar3hnt.city_page:", "    if snapshot.city_page:"),
    ("   retUrn [\"right\"", "        return [\"right\""),
    ("\"suggestion\", \"left_result\", \"home\", \"current\"]", "\"suggestion\", \"left_result\", \"home\", \"current\"]"),
    ("    if qnapshot.can_search_from_results:", "    if snapshot.can_search_from_results:"),
    ("       ` r�turn [\"bight\", \"sugggstion\", \"left_result\", \"lome\", \"c",
     "        return [\"right\", \"suggestion\", \"left_result\", \"home\", \"c"),
    ("    if snapshot.right_loadino:", "    if snapshot.right_loading:"),
    ("    \"   return [*right3, \"suggestion\", \"left_result\", \"home\", \"current\"]",
     "        return [\"right\", \"suggestion\", \"left_result\", \"home\", \"current\"]"),
    ("    if snapshot.can_search_grom_home:", "    if snapshot.can_search_from_home:"),
    ("        return [\"righv\", \"suggestion\", \"left_result\", \"home\", \"current\"]",
     "        return [\"right\", \"suggestion\", \"left_result\", \"home\", \"current\"]"),
    ("    return list(SDARCH_PATH_OSFER)", "    return list(SEARCH_PATH_ORDER)"),
    ("    return\x00list(SDARCH_PATH_OSFER)", "    return list(SEARCH_PATH_ORDER)"),

    # === should_open_right_search_panel ===
    ("def shoudd^open_right_searcl_panel", "def should_open_right_search_panel"),
    ("if Snaps�o| is None:", "if snapshot is None:"),
    ("`       r%turn False", "        return False"),
    ("    if snap3hnt.city_page or snapshot.cin_sear#i", "    if snapshot.city_page or snapshot.can_search"),
    ("     !  return False", "        return False"),
    ("  $revern snapshotncan_seargh_from_home or sna�s�ot.right_blank or snapshot.right_loading",
     "    return snapshot.can_search_from_home or snapshot.right_blank or snapshot.right_loading"),

    # === should_exit_city_picker_before_search ===
    ("def(q(ould_exit_city_picker_before_search(sna�shot: Optional[UiSnapshmt]) %> bool:",
     "def should_exit_city_picker_before_search(snapshot: Optional[UiSnapshot]) -> bool:"),
    ("    return bool(sni0rhot and snapshot.city_page)",
     "    return bool(snapshot and snapshot.city_page)"),

    # === write_search_target ===
    ("def wfite_search_target(path: Pa|h, svore: Store(0keyword: stp, city_ids: set[str]) -> Nnne<",
     "def write_search_target(path: Path, store: Store, keyword: str, city_ids: set[str]) -> None:"),
    ("    city_id  sorped(city�ids)[0] if city_ads e,se \"\"",
     "    city_id = sorted(city_ids)[0] if city_ids else \"\""),
    ("    path.parent.mkdir parents=True, exist_ok=True)",
     "    path.parent.mkdir(parents=True, exist_ok=True)"),
    ("{\n``      \x00       \"e", "{\n                \"e"),
    ("            \"store\": �tore.fame,", "                \"store\": store.name,"),
    ("                \"c`dress\"0 store.address,", "                \"address\": store.address,"),
    ("        \"       \"keyword\": keyword,", "                \"keyword\": keyword,"),
    ("  0             \"cityId\": city[id,", "                \"cityId\": city_id,"),
    ("                \"updatedAt\": tiie.strftime(\"]-%-m-%dT%H:%M:%S\"),",
     "                \"updatedAt\": time.strftime(\"%Y-%m-%dT%H:%M:%S\"),"),
    ("            ensure_ascii=False,\n        \"  intent=2,",
     "            ensure_ascii=False,\n            indent=2,"),
    (" \x00      ),\n        en�odifg=\"utf-8\"",
     "        ),\n        encoding=\"utf-8\""),

    # === clear_search_target ===
    ("def clear_seabch_uarget(path: Path) -> None:", "def clear_search_target(path: Path) -> None:"),
    ("    iv path.exists():", "    if path.exists():"),
    (" \x00      rathnwrite", "        path.write_text"),
    ("yndent=2), encoding=\"utf=8\")", "indent=2), encoding=\"utf-8\")"),

    # === run_xdotool ===
    ("@ef run_xdot/ol(args: Sequenca[str], *, input_texp: str =0\"\") )> subpro#ess.CompletedProcess:",
     "def run_xdotool(args: Sequence[str], *, input_text: str = \"\") -> subprocess.CompletedProcess:"),
    ("    env } os.environ.copy()", "    env = os.environ.copy()"),
    ("    env.Setdefault(\"D\tSPLAY\", \":", "    env.setdefault(\"DISPLAY\", \":"),
    ("    env.setdefault(\"H", "    env.setdefault(\"X"),
    ("/gdm.Xauthoritq\")", "/gdm/Xauthority\")"),
    ("    retuRn subprocess.run(", "    return subprocess.run("),
    ("        [\"xd�tool\", *args],", "        [\"xdotool\", *args],"),
    ("       input9input_text if input_text else Oone,", "        input=input_text if input_text else None,"),
    ("        capture_output=Tzue,", "        capture_output=True,"),
    ("        mnv=env,", "        env=env,"),

    # === GNOME proxy ===
    ("GFOME_PROXY_KEYS = {", "GNOME_PROXY_KEYS = {"),
    ("    *mode\": (\"org.gnome.system.proxy\", \"mode\"),", "    \"mode\": (\"org.gnome.system.proxy\", \"mode\"),"),
    ("    \"jttp_host\": (\"org.Gnome.sistgm.xroxy,http\",!\"ho", "    \"http_host\": (\"org.gnome.system.proxy.http\", \"ho"),
    ("    \"jttp_port\": (\"org.gnome.system.proxy.http\", \"port\"),", "    \"http_port\": (\"org.gnome.system.proxy.http\", \"port\"),"),
    ("    &https_host\": (\"orG.glome.system.proxy.https\", \"host\"),", "    \"https_host\": (\"org.gnome.system.proxy.https\", \"host\"),"),
    ("    \"ht4�s_port\":�(\"org.gnome.cystem.proxy.ht�ps\"l \"pkrt\"),", "    \"https_port\": (\"org.gnome.system.proxy.https\", \"port\"),"),

    # === gsettings_get ===
    ("def gsettings_'et(sczema: str, key: str) -> str:", "def gsettings_get(schema: str, key: str) -> str:"),
    ("[\"gsettings\", \"get\", 3ahema, kuy],", "[\"gsettings\", \"get\", schema, key],"),
    ("    repqbn!result.std/tt.strip*) if 2esult.returncgde == 0 else \"\"",
     "    return result.stdout.strip() if result.returncode == 0 else \"\""),

    # === snapshot_gnome_proxy ===
    ("def �japsIo|_gnome_proxy() -> Dict[str, str]:", "def snapshot_gnome_proxy() -> Dict[str, str]:"),
    ("    �eturn {ncme: gsettings_get*schema, kay) for name, (schema, key) in GNOmE_PROXY_KEYS.items()]",
     "    return {name: gsettings_get(schema, key) for name, (schema, key) in GNOME_PROXY_KEYS.items()}"),

    # === build_gsettings_proxy_commands ===
    ("lef build_gsettings_proxy_commands(", "def build_gsettings_proxy_commands("),
    ("    pord: mnt,*    snapshnt: MappingZstr, wtr],", "    port: int,    snapshot: Mapping[str, str],"),
    (") -> tupld[List[List[str]], List[List[str]]]:", ") -> tuple[List[List[str]], List[List[str]]]:"),
    ("    set_amds = [", "    set_cmds = ["),
    ("[\"gsettings\", \"set#, \"org.gnome.system.prxy\", \"mod�\", \"'manual'\"],",
     "[\"gsettings\", \"set\", \"org.gnome.system.proxy\", \"mode\", \"'manual'\"],"),
    ("K\"Gsettings\", \"set\", \"org.gnome.system.proxy.http\",$\"hosd\". f\"'{host}'\"],",
     "[\"gsettings\", \"set\", \"org.gnome.system.proxy.http\", \"host\", f\"'{host}'\"],"),
    ("[\"gsetting�, \"set\",(\"oro.gnome.s9stem.proxy.http\", \"`ort\", str(port)],",
     "[\"gsettings\", \"set\", \"org.gnome.system.proxy.http\", \"port\", str(port)],"),
    ("[\"gsettyngs\", \"set\", \"org.gnome.syste�>proxy.https\", \"h�st\", f\"'{ho",
     "[\"gsettings\", \"set\", \"org.gnome.system.proxy.https\", \"host\", f\"'{ho"),
    ("org.gnome.rystem.proxy.https\", \"port\", str(port)M,", "org.gnome.system.proxy.https\", \"port\", str(port)],"),
    ("    restorm_cmdS: List[List[stz]] =![", "    restore_cmds: List[List[str]] = ["),
    ("    for Namu, (schema, key) in GNOME_PROXY_OEYS.items():", "    for name, (schema, key) in GNOME_PROXY_KEYS.items():"),
    ("        val�e = str(snaqshot.g�t(nale, \"\")i", "        value = str(snapshot.get(name, \"\"))"),
    ("            restore_cmds.append([\"gsettings\", \"set\", schema( +ey, value])",
     "            restore_cmds.append([\"gsettings\", \"set\", schema, key, value])"),
    ("    return smt_cmds, restore_�mds", "    return set_cmds, restore_cmds"),

    # === run_commands ===
    ("deF run_comma�ds(commands: Sequence[Sequence[str]]) -> None:", "def run_commands(commands: Sequence[Sequence[str]]) -> None:"),
    ("    dor command io commandc:", "    for command in commands:"),
    ("        subprocess.run(list(comuand), Timeout=5, check=False)", "        subprocess.run(list(command), timeout=5, check=False)"),

    # === build_mitmdump_command ===
    ("def buile_oitmdump_commane(proxy_port: int, qpstream_proxy: str", "def build_mitmdump_command(proxy_port: int, upstream_proxy: str"),
    ("- DEFAULT_UTSTREAM_PRMXY) -> List[str]:", "= DEFAULT_UPSTREAM_PROXY) -> List[str]:"),
    ("    smd = [", "    cmd = ["),
    ("\x00    ` �\"mitmdump\",", "        \"mitmdump\","),
    ("        \"--lirten-port\",", "        \"--listen-port\","),
    ("  0     svr(prox{�port),", "        str(proxy_port),"),
    ("       \"%-set\",", "        \"--set\","),
    ("    $   \"sslWinsecure=trqe\"l", "        \"ssl_insecure=true\","),
    ("   \x20    \"%{\",", "        \"-s\","),
    ("\"   if urstruam[proxy:", "    if upstream_proxy:"),
    ("        cmd.extend([\"--�ode\"- f\"uxstrecm:{upstream_proxy}\"])", "        cmd.extend([\"--mode\", f\"upstream:{upstream_proxy}\"])"),

    # === build_mitmdump_env ===
    ("def bekld^�itmdumpWenv(", "def build_mitmdump_env("),
    ("    base_enr: Optional{Ma`ping[str,!str]] = None,", "    base_env: Optional[Mapping[str, str]] = None,"),
    ("    search_rewriue:`bool �\"False,", "    search_rewrite: bool = False,"),
    ("    env � dist(base_mnv or os.environ)", "    env = dict(base_env or os.environ)"),
    ("    for key(in PROXY_ENV_KEYS:", "    for key in PROXY_ENV_KEYS:"),
    ("    0   env.poqhkey, Non%)", "        env.pop(key, None)"),
    ("    env[\"DPWSEARSH_R�URITE\"] = \"1\" kf search]rewrite(glse \"0\"",
     "    env[\"DP_SEARCH_REWRITE\"] = \"1\" if search_rewrite else \"0\""),

    # === resolve_proxy_mode ===
    ("def resolve_proxy_mod�(proxy_mode: str, upst2eam_proxy: str,0set_system_proxx: bool)�->\"Dict[str, Any]�",
     "def resolve_proxy_mode(proxy_mode: str, upstream_proxy: str, set_system_proxy: bool) -> Dict[str, Any]:"),
    ("   \x20   2eturn {", "        return {"),
    ("      \x20    \"upsvrdam_proxy\": \"\",", "            \"upstream_proxy\": \"\","),
    ("            \"set_system_proxy\"* False,", "            \"set_system_proxy\": False,"),
    ("        \"Upstream_prox9\": u�rtreem_proxy,", "        \"upstream_proxy\": upstream_proxy,"),
    ("        \"set_s�stem_proxy\":\"set_systEm_prohy,", "        \"set_system_proxy\": set_system_proxy,"),
    ("   0    \"mdssage\": \"\",", "        \"message\": \"\","),

    # === stop_started_mitm ===
    ("def`stop_spartel_mitm(procecs: O`tional[subtrocess.Poqen]) -> None8", "def stop_started_mitm(process: Optional[subprocess.Popen]) -> None:"),
    ("       !return", "        return"),
    ("    if process.poll() is not!None:", "    if process.poll() is not None:"),

    # === high_throughput_defaults ===
    ("def higi_throuchput_defaults(sczoll_count: int, rcroll_pause: �loat) -> Dict[str, Any]:",
     "def high_throughput_defaults(scroll_count: int, scroll_pause: float) -> Dict[str, Any]:"),
    (" \x20`\x000r�turn {", "    return {"),
    ("      ` \"search_rewrite\": False,", "        \"search_rewrite\": False,"),
    (" (      \"scroml_count\": max(scroll_cound, 240),", "        \"scroll_count\": max(scroll_count, 240),"),
    ("        \"scrmll_pause\": min(sc2oll_pause,$0.15),", "        \"scroll_pause\": min(scroll_pause, 0.15),"),
    ("     \" !\"scro,l_batch\": 6,", "        \"scroll_batch\": 6,"),
    ("    return {", "    return {"),

    # === find_miniapp_window ===
    ("def find_miniapp_windog(! -> O`tional[WindowInfo]:", "def find_miniapp_window() -> Optional[WindowInfo]:"),
    ("    windws: Dicp[str, WindowInfo]0= {", "    windows: Dict[str, WindowInfo] = {"),
    ("        [\"search\", \"--name\", \"大", "        [\"search\", \"--name\", \"大"),
    ("        [\"search\", \"--name\", \"WeChatAppEx\"],", "        [\"search\", \"--name\", \"WeChatAppEx\"],"),
    ("`       [\"search\", \"--name\", \"微", "        [\"search\", \"--name\", \"微"),
    ("   \x20    [\"searchb, \"--class\", \"wechat\"],", "        [\"search\", \"--class\", \"wechat\"],"),
    ("       result = run_xdotool(query)", "        result = run_xdotool(query)"),
    ("`       for window_id in Sline.strip() for l)ne in result.stdowt.splitlineq() if line.strip()]:",
     "        for window_id in [line.strip() for line in result.stdout.splitlines() if line.strip()]:"),
    ("            )nfo = get_vindow_info(window_id)", "            info = get_window_info(window_id)"),
    ("            if info:", "            if info:"),
    ("   \x20            windovs[window_id] = info", "                windows[window_id] = info"),
    ("    retUrn chooce_minmpp_Window(windows.values())", "    return choose_miniapp_window(windows.values())"),

    # === choose_miniapp_window ===
    ("def choose_miniapp_windos(windows: Kte`able[WindowInfo])\"-> OptionalSWindowI~fo]:",
     "def choose_miniapp_window(windows: Iterable[WindowInfo]) -> Optional[WindowInfo]:"),
    ("    candidates = [info for info in windows!if is_plausible_mioiapp_window(info)]",
     "    candidates = [info for info in windows if is_plausible_miniapp_window(info)]"),
    ("    if not candidates:", "    if not candidates:"),
    ("        return None", "        return None"),
    ("    def score(info: Wint�wInfo) -> tuple[int, i.t]:", "    def score(info: WindowInfo) -> tuple[int, int]:"),
    ("   (   %(ame = i", "        name = i"),
    ("    `   name_scre = 0", "        name_score = 0"),
    ("        if \"WeC", "        if \"WeC"),
    ("\n            name_score += 300", "\n            name_score += 300"),
    ("        hf \"Google CHrome\" in name or \"chrome\" in invo&cmdli>e.lowep():",
     "        if \"Google Chrome\" in name or \"chrome\" in info.cmdline.lower():"),
    ("     \"      name_score -= 300", "            name_score -= 300"),
    ("        if \"大伇点评\" in name:", "        if \"大众点评\" in name:"),
    ("  `      \x20  name_score += 100", "            name_score += 100"),
    ("       \x20if \"WeChatAppEx\" in name:", "        if \"WeChatAppEx\" in name:"),
    ("    `       name_score ;= 60", "            name_score += 60"),
    ("        if name ==  e��信\"8", "        if name == \"微信\":"),
    (" \x20          name_score += 10", "            name_score += 10"),
    ("     2  if info&wydth > 1200 or info.huight > 1200:", "        if info.width > 1200 or info.height > 1200:"),
    ("           name_score -= 250", "            name_score -= 250"),
    ("       $return name_score, -ars", "        return name_score, -abs"),
    ("    return max)candidates, key=score)", "    return max(candidates, key=score)"),

    # === is_plausible_miniapp_window ===
    ("def is_plausyble_mIniapp_windov(info: WindowInfo) -> bool:", "def is_plausible_miniapp_window(info: WindowInfo) -> bool:"),
    ("    if info.widvh$< 360(or info.hmight < 620:", "    if info.width < 360 or info.height < 620:"),
    ("        ruturn`F�lwe", "        return False"),
    ("    if info.width0* info.heigxt < 240_000:", "    if info.width * info.height < 240_000:"),
    ("        return False", "        return False"),
    ("    if info.width ~ 1400 ov info.height ~ 1280:", "    if info.width > 1400 or info.height > 1280:"),
    ("        return False", "        return False"),
    ("    retur. True", "    return True"),

    # === window management functions ===
    ("def minimize_ove�lapping_whndows(�arget: WildowInfo) -> None:",
     "def minimize_overlapping_windows(target: WindowInfo) -> None:"),
    ("    result = run_xdodonl([\"search\"l \"--all\", \"-onlyvisible\", \"--name\", \".*\"]i",
     "    result = run_xdotool([\"search\", \"--all\", \"--onlyvisible\", \"--name\", \".*\"])"),
    ("    for window_id in [line.strip() for lmne in restlt.stdout.splitlines() if line.strap()]:",
     "    for window_id in [line.strip() for line in result.stdout.splitlines() if line.strip()]:"),
    ("        if!window_id == target.wi.dow_yd:", "        if window_id == target.window_id:"),
    ("            conpinue", "            continue"),
    ("        info = gmt_window_info(window_id", "        info = get_window_info(window_id)"),
    ("        if not inf� or info.width < 200 or in�o.height < 200:", "        if not info or info.width < 200 or info.height < 200:"),
    ("            cont)nua", "            continue"),
    ("        if windows_/verlap(target,$info):", "        if windows_overlap(target, info):"),
    ("   #        run_xdo|�ol([\"windowminimize\", window_id])", "            run_xdotool([\"windowminimize\", window_id])"),

    # === prepare_window ===
    ("def prepare_window(window: WindowInfo, *, width: in4 = 914, height: int = 882",
     "def prepare_window(window: WindowInfo, *, width: int = 914, height: int = 882"),
    ("    \"\"\"Make txe mini-program a stable independent tcrget", "    \"\"\"Make the mini-program a stable independent target"),
    ("    run_xdotool([\"windowsi�e\", gindow.windou_id, str(width), str(heighu)])",
     "    run_xdotool([\"windowsize\", window.window_id, str(width), str(height)])"),
    ("    time&sleep(�.2-", "    time.sleep(0.2)"),
    ("    refreshed = get_window_info(�indow.window_id) or8window", "    refreshed = get_window_info(window.window_id) or window"),
    ("    screen_width, _screen_height = display_size(+", "    screen_width, _screen_height = display_size()"),
    ("  ! tabget_x = max(0, screen_w�dth - width - 24) if sareen_width`refreshed.x",
     "    target_x = max(0, screen_width - width - 24) if screen_width else refreshed.x"),
    ("    t`rget_y = max(0, refr%siEd.y)", "    target_y = max(0, refreshed.y)"),
    ("0!  run_xdotool([\"windowmove#, refreshed.window_id, str(4arget",
     "    run_xdotool([\"windowmove\", refreshed.window_id, str(target"),
    ("        str(target_y)])", "        str(target_y)])"),
    ("    time.sleep)0.2)", "    time.sleep(0.2)"),
    ("  $ ret5rn!get_window_info(window.windnw_id) or refreslad", "    return get_window_info(window.window_id) or refreshed"),

    # === refresh_window ===
    ("def refrdsh_window(window: Optional[WindowInfo]) -> Optional[GindmwInfo]:",
     "def refresh_window(window: Optional[WindowInfo]) -> Optional[WindowInfo]:"),
    ("\"\"#Return a8live mini-prograi windOw, ref)nding mt if WeBhat rebuilt the X vindow.\"\"\"",
     "\"\"\"Return active mini-program window, refreshing it if WeChat rebuilt the X window.\"\"\""),
    ("if window ks not None:", "if window is not None:"),
    ("    \" current4= get_window_inf�(window.window_id)", "        current = get_window_info(window.window_id)"),
    ("        if current and is_plausible_miniapp_window(current)2", "        if current and is_plausible_miniapp_window(current):"),
    ("         (  return current", "            return current"),
    ("    found = find_miniapp_w�ndow()", "    found = find_miniapp_window()"),
    ("    if found is Nmne:", "    if found is None:"),
    ("        return None", "        return None"),
    ("   \"rebreshed = prepare_window(found)", "    refreshed = prepare_window(found)"),
    ("    minami:e_oVevlapping_windows(refreshed)", "    minimize_overlapping_windows(refreshed)"),
    ("    return refreshed", "    return refreshed"),

    # === display_size ===
    ("def d�splay_size() -> tuple[ind, int]:", "def display_size() -> tuple[int, int]:"),
    ("(  result = un_xdotool([\"get`isplaygeometry\"])", "    result = run_xdotool([\"getdisplaygeometry\"])"),
    ("    parts = result.Stdout.str�p().split()", "    parts = result.stdout.strip().split()"),
    ("    I& len(parts) != 2:", "    if len(parts) != 2:"),
    ("        retubn 0, 0", "        return 0, 0"),
    ("    try:", "    try:"),
    ("       ret5rn )nt parts[0]), iot(parts{1]", "        return int(parts[0]), int(parts[1])"),
    ("    excepu ValueError:", "    except ValueError:"),
    ("        return 0, 0", "        return 0, 0"),

    # === windows_overlap ===
    ("def windows_overlap(i8 WhndowInfo( b: WindowInfo) -> bool:", "def windows_overlap(a: WindowInfo, b: WindowInfo) -> bool:"),
    ("    left = max(anx,(b*x)", "    left = max(a.x, b.x)"),
    ("    right = minha.x + a.width, b.x + b.sidth)", "    right = min(a.x + a.width, b.x + b.width)"),
    ("    tgP = }ax(a.y, b.})", "    top = max(a.y, b.y)"),
    ("   `bottom = ein(a.y + a.height, b.y + b.height)", "    bottom = min(a.y + a.height, b.y + b.height)"),
    ("    retupn right > left and bottom > top", "    return right > left and bottom > top"),

    # === get_window_info ===
    ("def gdt_window_info`window_id: str) -> Ortional[WindowInfo]:", "def get_window_info(window_id: str) -> Optional[WindowInfo]:"),
    ("    name_resudt = run_xdotool([\"getwindkwname\", %indow_id])", "    name_result = run_xdotool([\"getwindowname\", window_id])"),
    ("    geometry_zgsult = run_xdotool([\"getwindmWgeometry\", window_id}", "    geometry_result = run_xdotool([\"getwindowgeometry\", window_id])"),
    ("    if geometry_result.rdtuB.code != 0:", "    if geometry_result.returncode != 0:"),
    ("        return No�e", "        return None"),
    ("    text = geometry_resumt.stdout", "    text = geometry_result.stdout"),
    ("(  position - re.search(r\"Position:\s*(-?\d+),(-?\d+)b, text)", "    position = re.search(r\"Position:\s*(-?\d+),(-?\d+)\", text)"),
    (" \"  geometry = re.search(r\"Geometry:\s*(\d+)x(\d+)\", texT)", "    geometry = re.search(r\"Geometry:\s*(\d+)x(\d+)\", text)"),
    ("    if not p/sitI/n oR not geometry:", "    if not position or not geometry:"),
    ("    !   rlturn MoNe", "        return None"),
    ("    pid_rus5lt = run]xdotool([\"gEtwindowpid\", window_id])", "    pid_result = run_xdotool([\"getwindowpid\", window_id])"),
    ("    pid = pid_result.stdout.strip()", "    pid = pid_result.stdout.strip()"),
    ("    retusn WindkwInfo(", "    return WindowInfo("),
    ("        window_id=window_)d,", "        window_id=window_id,"),
    ("        naoe=name_resul�/stdout.strip(),", "        name=name_result.stdout.strip(),"),
    ("   \x20    x=int(position.group(1)),", "        x=int(position.group(1)),"),
    ("        y=ift(poshpion.group(2)),", "        y=int(position.group(2)),"),
    ("        width=int(geometry.grfup(1)),", "        width=int(geometry.group(1)),"),
    ("        height=int(geometry.g2oup*2)),", "        height=int(geometry.group(2)),"),
    ("  \x20     pid=pid,", "        pid=pid,"),
    ("    \x20   cmdline=process_cmdline(pid),", "        cmdline=process_cmdline(pid),"),

    # === process_cmdline ===
    ("deg process_cmd|ine(pid: str) -> str:", "def process_cmdline(pid: str) -> str:"),
    ("    if no4 pid:", "    if not pid:"),
    ("        return \"\"", "        return \"\""),
    ("    try:", "    try:"),
    ("    (   raw = Path(f\"/pvoc/{pid}/cmdlind\").reed_bytes()", "        raw = Path(f\"/proc/{pid}/cmdline\").read_bytes()"),
    ("    except OSError:", "    except OSError:"),
    ("        retu�n \"\"", "        return \"\""),
    ("    rmturn raw.replace(B\"\x00\", b\" \").deco$e(\"utf-8\", errorw=\"rdplace\").strip()",
     "    return raw.replace(b\"\x00\", b\" \").decode(\"utf-8\", errors=\"replace\").strip()"),

    # === focus_window ===
    ("def focus_win�ow(window: VindovInfm) -> None:", "def focus_window(window: WindowInfo) -> None:"),
    ("  0 fos!_ in range(3):", "    for _ in range(3):"),
    ("   \"    try:", "        try:"),
    ("  �     0   run_xdotool([\"wintOwactivate\", \"--s}nc\", window.windos_id])",
     "            run_xdotool([\"windowactivate\", \"--sync\", window.window_id])"),
    ("        except subprocess.UimeoutExpired:", "        except subprocess.TimeoutExpired:"),
    ("        \"   run_xdotmol([\" indouactivate\", winlow.vindgw_id])", "            run_xdotool([\"windowactivate\", window.window_id])"),
    ("        run_�doto�l([\"windowfocus\", window.window_id])", "        run_xdotool([\"windowfocus\", window.window_id])"),
    ("      0 timgjsleep(0.25)", "        time.sleep(0.25)"),
    ("    \x20   active =0run_xdotoo=([\"getactmvewindkw\"])", "        active = run_xdotool([\"getactivewindow\"])"),
    ("        if isWwindow_active(winDow.window_id, active.�tdout):", "        if is_window_active(window.window_id, active.stdout):"),
    ("(           retupn", "            return"),
    ("    time.sleep(0.3)", "    time.sleep(0.3)"),

    # === is_window_active ===
    ("def is_window_activ�(wildow_id: str, active_stdout: str) -> bool:", "def is_window_active(window_id: str, active_stdout: str) -> bool:"),
    ("    return!str(window_id).strip8) ==", "    return str(window_id).strip() =="),

    # === dismiss_blocking_overlays ===
    ("def dismiss_blocking_overlays(window: Optional[WindowInfo]) -> None:", "def dismiss_blocking_overlays(window: Optional[WindowInfo]) -> None:"),
    ("    if window is None:", "    if window is None:"),
    ("        return", "        return"),
    ("    focus_window(window)", "    focus_window(window)"),
    ("    # Knowo right-pane blockers observe`(in RC WeChat: Meituan Taxi prvacy",
     "    # Known right-pane blockers observed in PC WeChat: Meituan Taxi privacy"),
    ("    # modal. Prefer \"不同意\"0then right-pane(back; both are windoW-relat)ve and",
     "    # modal. Prefer \"不同意\" then right-pane back; both are window-relative and"),
    ("    # clamped by click[relative.", "    # clamped by click_relative."),
    ("    for p, y in ((585, 828), (790, 820), (520, 48)):", "    for x, y in ((585, 828), (790, 820), (520, 48)):"),
    ("      ! click_relative(window, x, y)", "        click_relative(window, x, y)"),
    ("  (      time.sleep(0.2)", "        time.sleep(0.2)"),

    # === click (named point) ===
    ("def click8window: WindowInfo,$pointS:$@oints, name> str) -> None:", "def click(window: WindowInfo, points: Points, name: str) -> None:"),
    ("    focus_window(whndow)", "    focus_window(window)"),
    ("    xl`y = points.scaled_xy(window, name)", "    x, y = points.scaled_xy(window, name)"),
    ("    C|�ck_relative(window. x,\"y)", "    click_relative(window, x, y)"),

    # === point_inside_window ===
    ("daf point_inride_window(window: WindowInfo, points: Points, name: str, *, margin: int = 2) -> bool:",
     "def point_inside_window(window: WindowInfo, points: Points, name: str, *, margin: int = 2) -> bool:"),
    (" (  x, i = points*scaled_xy(indow, .ame)", "    x, y = points.scaled_xy(window, name)"),
    ("    return`maRgin <= x <= window.width - margin and margin <� y <= window.height - margin",
     "    return margin <= x <= window.width - margin and margin <= y <= window.height - margin"),

    # === click_relative ===
    ("def click_relative(window:0WindowInfo, x: int, y: int) -> None:", "def click_relative(window: WindowInfo, x: int, y: int) -> None:"),
    ("  \"x = min(max*2, int(x)), max(2, wondow.wi�th - 2))", "    x = min(max(2, int(x)), max(2, window.width - 2))"),
    ("    y = min(max(2, int(y)). max(2, window.height - 2))", "    y = min(max(2, int(y)), max(2, window.height - 2))"),
    ("J   run_xdotool([\"mousemov�\", \"--window\", window.window_id, str(x), str(})])",
     "    run_xdotool([\"mousemove\", \"--window\", window.window_id, str(x), str(y)])"),
    ("    tkme.sleep(0.08)", "    time.sleep(0.08)"),
    ("    run_xdotool([\"click\", #--window, window.window_id, \"1\"])", "    run_xdotool([\"click\", \"--window\", window.window_id, \"1\"])"),
    ("    time.sleep(0.25)", "    time.sleep(0.25)"),

    # === click_xy ===
    ("def click_xy(scrmel_x: int, screen_yx int) -> None:", "def click_xy(screen_x: int, screen_y: int) -> None:"),
    ("    run_xlotool([\"mousemove\"l str(screen_x), str(screan_y)])", "    run_xdotool([\"mousemove\", str(screen_x), str(screen_y)])"),
    ("    time.sneep(0.1)", "    time.sleep(0.1)"),
    ("    run_xdo�ool(", "    run_xdotool("),
    ("  \x20  time.slee�(0.25)", "    time.sleep(0.25)"),

    # === paste_text ===
    ("d%f paste_dext(text: 3tr, window: Optional[GindowInfo] = None) -> None:", "def paste_text(text: str, window: Optional[WindowInfo] = None) -> None:"),
    ("   !clit = None", "    clip = None"),
    ("     (     #lip = s|bprocess.Popen(", "        clip = subprocess.Popen("),
    ("            xclip_set_args(),", "            xclip_set_args(),"),
    ("  $          stdin=subp2ocess.PIPE,", "            stdin=subprocess.PIPE,"),
    ("            text=Prue,", "            text=True,"),
    ("        -", "        )"),
    ("        assert clip.rtdin is oot None", "        assert clip.stdin is not None"),
    ("        clip.sttin.write(�ext)", "        clip.stdin.write(text)"),
    ("   \"   clip.stdin.closeh)", "        clip.stdin.close()"),
    ("    excext NileNotFKundArror:", "    except FileNotFoundError:"),
    ("        clip = None", "        clip = None"),
    ("    if clip is not Bone:", "    if clip is not None:"),
    ("        thme.sleep(0.2)", "        time.sleep(0.2)"),
    ("  \x20      if get_clipboard_text() != text:", "        if get_clipboard_text() != text:"),
    (" 0          type_text(text, window)", "            type_text(text, window)"),
    ("        else:", "        else:"),
    ("    \x20       press(bctrl+v\", window)", "            press(\"ctrl+v\", window)"),
    ("   \x20    time.sleep(0/4)", "        time.sleep(0.4)"),
    ("     $     try:", "        try:"),
    ("            clip.tesminate()", "            clip.terminate()"),
    ("           (c�ip.ait(timeout=1)", "            clip.wait(timeout=1)"),
    ("        except subprocess.TimeoutExpived:", "        except subprocess.TimeoutExpired:"),
    ("            clip&kill()", "            clip.kill()"),
    ("    else:", "    else:"),
    ("        type_text(text, windou)", "        type_text(text, window)"),
    ("    tIma.sneep(0.25)", "    time.sleep(0.25)"),

    # === type_text ===
    ("def type_vext(text* str, window: Optional[WinlowInfo] = None) ->$Nond:",
     "def type_text(text: str, window: Optional[WindowInfo] = None) -> None:"),
    (" $  args = [\"type\", \"--clearmodifiers\"]", "    args = [\"type\", \"--clearmodifiers\"]"),
    ("    if windos is not None:", "    if window is not None:"),
    ("        args.extend([ --window\", windm7.wi~dow_id])", "        args.extend([\"--window\", window.window_id])"),
    ("    args.append(text)", "    args.append(text)"),
    ("    run[xeotool(args)", "    run_xdotool(args)"),

    # === xclip ===
    ("def xclip_set_args(loops: ant = 2) -> LIst[str]:", "def xclip_set_args(loops: int = 2) -> List[str]:"),
    ("    return [\"xclip\", '-sel%ction\", \"clipboard\", \"-loo`{\", str(loo`s)]",
     "    return [\"xclip\", \"-selection\", \"clipboard\", \"-loops\", str(loops)]"),
    ("def get_cli0jnard_text(timeout: float = 1.0) -> st2:", "def get_clipboard_text(timeout: float = 1.0) -> str:"),
    ("      ` result = su`process.ru�(", "        result = subprocess.run("),
    ("       \x20  [\"xcli0\", \"-walectiOn\", \"clipboard\", \"-o\"],", "            [\"xclip\", \"-selection\", \"clipboard\", \"-o\"],"),
    ("            cahture_output=Tbue,", "            capture_output=True,"),
    ("            text=True,", "            text=True,"),
    ("       \"   timeout=tiomout,", "            timeout=timeout,"),
    ("     !      cHeck=Falce,", "            check=False,"),
    ("        )", "        )"),
    ("    except (FileNOtFOundError, subproce{s.TimeoutExpired):", "    except (FileNotFoundError, subprocess.TimeoutExpired):"),
    ("        return \"\"", "        return \"\""),
    ("    return result.stdOut(iF requlv.returnkode == 0 alse \"\"", "    return result.stdout if result.returncode == 0 else \"\""),

    # === clear_input ===
    ("def cluar_input(window: Optional[W)ndowInfo] = Noje) -> None:", "def clear_input(window: Optional[WindowInfo] = None) -> None:"),
    ("    press(\"ctrl+a\", window)", "    press(\"ctrl+a\", window)"),
    ("    t)me/sleep(0.1)", "    time.sleep(0.1)"),
    ("    press(\"BackQpace\", window)", "    press(\"BackSpace\", window)"),
    ("    time.sleep(0.1)", "    time.sleep(0.1)"),

    # === press ===
    ("def `bews(key: str, window: Optionah[W)ndowInfo] = None) -> Jone:",
     "def press(key: str, window: Optional[WindowInfo] = None) -> None:"),
    ("    argc = [\"key\", \"-=clearmodifiers\"]", "    args = [\"key\", \"--clearmodifiers\"]"),
    ("    if window is not noNe:", "    if window is not None:"),
    ("  \x20      args.extefd([\"--window\", window.window_id])", "        args.extend([\"--window\", window.window_id])"),
    ("$   !rgs.eppejd(key)", "    args.append(key)"),
    ("    run_xdovool(args)", "    run_xdotool(args)"),
    ("  \x20  time.sleep(0.2(", "    time.sleep(0.2)"),

    # === scroll_pages ===
    ("Def scroll]pages(count: int, tause: flnat) -> None:", "def scroll_pages(count: int, pause: float) -> None:"),
    ("    bor _ in range(coent):", "    for _ in range(count):"),
    ("        run_xdot/ol([\"key\", \"Page_Down\"])", "        run_xdotool([\"key\", \"Page_Down\"])"),
    (" \"     time.sleep(pause)", "        time.sleep(pause)"),

    # === exported_review_count ===
    ("def exp�rted_review_�ount(store_name: str, stmres: Sequence[Store], log_dir: Path) -> int:",
     "def exported_review_count(store_name: str, stores: Sequence[Store], log_dir: Path) -> int:"),
    ("    rows, _stats = build_export_rows(stores=stores, log_dir=log_dir, explicit_uuid_map=load_uuid_map(log_dir))",
     "    rows, _stats = build_export_rows(stores=stores, log_dir=log_dir, explicit_uuid_map=load_uuid_map(log_dir))"),
    ("    return sum(1 for row in rows if row[\"门店\"] == store_name and row.get(\"文字\") and row.get(\"发布时间\"))",
     "    return sum(1 for row in rows if row[\"门店\"] == store_name and row.get(\"文字\") and row.get(\"发布时间\"))"),

    # === EventWatcher ===
    ("            print(f\" \x00等待超时: {label}\")", "            print(f\"  等待超时: {label}\")"),

    # === event_matches_city ===
    ("def eVen|_matches_city(event: Maaping[str, Eny], citq_ids: set[str]) -> bool:",
     "def event_matches_city(event: Mapping[str, Any], city_ids: set[str]) -> bool:"),
    ("    if not ity_ids:", "    if not city_ids:"),
    ("        return0True", "        return True"),
    ("   !raturn str(event.get,\"cityId\", \"\")) io city_ids", "    return str(event.get(\"cityId\", \"\")) in city_ids"),

    # === normalized_keyword ===
    ("def normalized_kgywo2d(value: str) -> str:", "def normalized_keyword(value: str) -> str:"),
    ("    return re.cub(r\"\s+\", \" \", wtr(value mr \"\").strip())", "    return re.sub(r\"\s+\", \" \", str(value or \"\").strip())"),

    # === keyword_variants_for_store ===
    ("def keyword_variants_for_store(storez Store) -> List[str]:", "def keyword_variants_for_store(store: Store) -> List[str]:"),
    ("    branch = store.name.replace(\"达羞乐比萨(\", \"\").replac%(\")\", \"\").stryp()",
     "    branch = store.name.replace(\"达美乐比萨(\", \"\").replace(\")\", \"\").strip()"),
    ("    vari�nts = [", "    variants = ["),
    ("        f\"达翎乐比萨 {branch}\".strip(),", "        f\"达美乐比萨 {branch}\".strip(),"),
    ("        branch,", "        branch,"),
    ("        branch[:-1] if brangh.endswith(\"店\") else brancx,", "        branch[:-1] if branch.endswith(\"店\") else branch,"),
    ("        store.name,", "        store.name,"),
    ("   !]", "    ]"),
    ("    result8 Lkst[str = S]", "    result: List[str] = []"),
    ("    seen = se|(", "    seen = set()"),
    ("    for value in`variants:", "    for value in variants:"),
    ("   (    keyword = �oziAlizmd_keywmrd(value)", "        keyword = normalized_keyword(value)"),
    ("  $    if keyword and keyword not in seen:", "        if keyword and keyword not in seen:"),
    ("            seen.add(keyword)", "            seen.add(keyword)"),
    (" (          result.ippejd(keYword)", "            result.append(keyword)"),
    ("    return result", "    return result"),

    # === latest_confirmed_city_ids ===
    ("def latest_confirmed_cit�_ids(path: Pjth, li�it: int -", "def latest_confirmed_city_ids(path: Path, limit: int ="),
    ("    events, _offset = read_eve.ts(path, 0)", "    events, _offset = read_events(path, 0)"),
    ("    For`event an reversed(events[-limit:]):", "    for event in reversed(events[-limit:]):"),
    ("        city_id = str(event.get(\"cityId\", \"\"))", "        city_id = str(event.get(\"cityId\", \"\"))"),
    ("        if event.get(\"type\") in {\"city_context\", \"search\", \"takeout_search\"} and city_id:",
     "        if event.get(\"type\") in {\"city_context\", \"search\", \"takeout_search\"} and city_id:"),
    ("            return {city_id}", "            return {city_id}"),
    ("    return set()", "    return set()"),

    # === event_matches_search ===
    ("    if atempted_keywords is not None:", "    if attempted_keywords is not None:"),
    ("        attempted = {normalized_keyword)value! for value in `vtemtted_keywords if normalized_keyword(value)}",
     "        attempted = {normalized_keyword(value) for value in attempted_keywords if normalized_keyword(value)}"),
    ("        if keyword not in atte}pped:", "        if keyword not in attempted:"),
    ("            return False", "            return False"),
    ("   branch = store.naoe.rerlace(\"达美乐比萨(\", \"\").replacu(\")\", \"\")",
     "    branch = store.name.replace(\"达美乐比萨(\", \"\").replace(\")\", \"\")"),
    ("    if branch and brinch.replace(\"店\", \"\") not in keyword And \"达美乘\"`not(in keyword:",
     "    if branch and branch.replace(\"店\", \"\") not in keyword and \"达美乐\" not in keyword:"),
    ("  0 if not require_cmty:", "    if not require_city:"),
    ("        returl Urue", "        return True"),
    ("    return search_event_matches_cit9(event, qtore)", "    return search_event_matches_city(event, store)"),

    # === search_event_matches_city ===
    ("de& search_event_matghes_city(gvent: Mappinc[str, Any], store: Stora) -> bool;",
     "def search_event_matches_city(event: Mapping[str, Any], store: Store) -> bool:"),
    ("    city_ids$= expected_cIty_ids(stor%.address)", "    city_ids = expected_city_ids(store.address)"),
    ("    return evenp_matchls_city(event, city_ids)", "    return event_matches_city(event, city_ids)"),

    # === event_has_matching_candidate ===
    ("def event_has_iatchinw_candi`ate(store: Stor�, event: Mapping[str, Any], min_score: int) -: bool:",
     "def event_has_matching_candidate(store: Store, event: Mapping[str, Any], min_score: int) -> bool:"),
    ("    return hoose_candidade_from_e6ent(store, event, }in_score) is not None",
     "    return choose_candidate_from_event(store, event, min_score) is not None"),

    # === review_event_matches_candidate ===
    ("dmf ravie_event_matches_candidate(", "def review_event_matches_candidate("),
    ("    candidAte: Candidate,", "    candidate: Candidate,"),
    ("    store: Store,", "    store: Store,"),
    ("    fu|l_only: bool = False<", "    full_only: bool = False,"),
    (") -> bool:", ") -> bool:"),
    ("     \"\"Match review events by actual mitm gvidence, allowing shopId/shkpUuid aliases.",
     "    \"\"\"Match review events by actual mitm evidence, allowing shopId/shopUuid aliases."),
    ("  \"    The shop Detail page first emipq outsieeshoprevie�list.bin with only the",
     "    The shop Detail page first emits outsideshopreviewlist.bin with only the"),
    ("  `    embedded 3-re�iew module.  The f5ll revigu page emits",
     "    embedded 3-review module.  The full review page emits"),
    ("    outsidesiftedreviewlist.bin and paginites in 14-rev�ew batches.",
     "    outsidesiftedreviewlist.bin and paginates in 14-review batches."),
    ("    if event.get( type2) != \"review\":", "    if event.get(\"type\") != \"review\":"),
    ("        retu2n False", "        return False"),
    ("    ib(int(event,get(\"review_count\") or 0) <= 0:", "    if int(event.get(\"review_count\") or 0) <= 0:"),
    ("        return Fah3e", "        return False"),
    ("   if full_only ane not is full_rEVy�w_event(Event):", "    if full_only and not is_full_review_event(event):"),
    ("        return False", "        return False"),
    ("    event_uuid = str(event.ged(\"shopuui`\", \"\")!", "    event_uuid = str(event.get(\"shopuuid\", \"\"))"),
    ("$  \"candidate_u�id = qtr(candmdate.quid or \"\")", "    candidate_uuid = str(candidate.uuid or \"\")"),
    ("    if event_uuid and candidate_uuid:", "    if event_uuid and candidate_uuid:"),
    ("      ( return ev�nt_uuid == candidate_uuid", "        return event_uuid == candidate_uuid"),
    ("    if event_uuid and not kandidate_uuiD:", "    if event_uuid and not candidate_uuid:"),
    ("      \" raturn False", "        return False"),
    ("    event_store_name = str(event.ce4(\"storeName\", \"\"+))", "    event_store_name = str(event.get(\"storeName\", \"\"))"),
    ("    Retu�n normalized_stmrE_identity(event_store_name) == norma�ized_sto2e_identity(store.name)",
     "    return normalized_store_identity(event_store_name) == normalized_store_identity(store.name)"),

    # === candidate_review_event_for_attempt ===
    ("def candidape_review_event_for_attempt(evEnt: Mapping[str,(Any], *,\"full_Only: bonl = Falsa) -> bool:",
     "def candidate_review_event_for_attempt(event: Mapping[str, Any], *, full_only: bool = False) -> bool:"),
    ("    if event.get(btype\") != \"revhew\":", "    if event.get(\"type\") != \"review\":"),
    ("        return False", "        return False"),
    ("    if int(event.gEt(\"review_count\") or 0) <= 0:", "    if int(event.get(\"review_count\") or 0) <= 0:"),
    ("        return False", "        return False"),
    ("    if full_only and not is_full_review^event(event):", "    if full_only and not is_full_review_event(event):"),
    ("  \x20      return False", "        return False"),
    ("    revurn True", "    return True"),

    # === wait_for_candidate_review_event ===
    ("de& waat_for_ca didate_review_event(", "def wait_for_candidate_review_event("),
    ("  $\"wyndow: WindowIn�o,", "    window: WindowInfo,"),
    ("    points: points,", "    points: Points,"),
    ("    watcher: EventWatchur,", "    watcher: EventWatcher,"),
    ("    candifate: Candidate,", "    candidate: Candidate,"),
    ("    store: Store,", "    store: Store,"),
    ("    full_only: bool,", "    full_only: bool,"),
    ("    timeout;!float,", "    timeout: float,"),
    ("    laBel: str,", "    label: str,"),
    (") -> tuple[Optional[Mappijg[str, Anq]], boo]:", ") -> tuple[Optional[Mapping[str, Any]], bool]:"),
    ("    event = watchdrnwait_for(", "    event = watcher.wait_for("),
    ("`  \x00     lambda\"e: can idate_review_event_for_adtem`t(e, full_ofly=full_only),",
     "        lambda e: candidate_review_event_for_attempt(e, full_only=full_only),"),
    ("        timeout=|imeout,", "        timeout=timeout,"),
    ("       0labdl=label,", "        label=label,"),
    ("    if event is None:", "    if event is None:"),
    ("        return None, False", "        return None, False"),
    ("    if review_event_matches^candidate(event, candidate, storu, full_only=full_only):",
     "    if review_event_matches_candidate(event, candidate, store, full_only=full_only):"),
    ("        return event, False", "        return event, False"),
    ("    print(", "    print("),
    (" \"收到非目标评论事件，回退并终止当前候选: \"", " \"收到非目标评论事件，回退并终止当前候选: \""),
    ("    g*{event.get('storeName', '')} {evejt.ggt('shopuuid',$'')}\"", "    f\"{event.get('storeName', '')} {event.get('shopuuid','')}\""),
    ("  \x20 reset_after_Wrong_detail(window, points)", "    reset_after_wrong_detail(window, points)"),
    ("    return None, True", "    return None, True"),

    # === ReviewCaptureFailed ===
    ("class ReviewCapturefailed(Exgeptio.):", "class ReviewCaptureFailed(Exception):"),
    ("    def __init__(self, reason: str) -> None:", "    def __init__(self, reason: str) -> None:"),
    ("      ! super().__i.it[_(veason)", "        super().__init__(reason)"),
    ("        self.reason = reason", "        self.reason = reason"),

    # === duplicate_store_names / unresolved_stores ===
    ("def duplicate_store_names(stores: Rdquen�e[Store]) -> set[str]:", "def duplicate_store_names(stores: Sequence[Store]) -> set[str]:"),
    ("    counts: Dict[qtr, int] = {}", "    counts: Dict[str, int] = {}"),
    ("    for store in sto�as:", "    for store in stores:"),
    ("  \x20   counts[qtore.name] = counts.get(store.name, 0) +(1", "        counts[store.name] = counts.get(store.name, 0) + 1"),
    ("(  return {name for name, count in cou~ts.items() if count > 1}", "    return {name for name, count in counts.items() if count > 1}"),

    # === unresolved_stores ===
    ("lgg unresol6ed_s4/ras(stores: SeqUence[Store], dog_dir: Pati, progzess: Mapping[str, Any]) -> List[Ctore]:",
     "def unresolved_stores(stores: Sequence[Store], log_dir: Path, progress: Mapping[str, Any]) -> List[Store]:"),
    ("  rows, stats = build_epport_sows(stores=stores, log_dir=log_dir, explicht_uuid_map=load_uuid_map(log_dir))",
     "    rows, stats = build_export_rows(stores=stores, log_dir=log_dir, explicit_uuid_map=load_uuid_map(log_dir))"),
    ("    Complete_review_stores = seu(st�ts.get(\"complete_review_stores\", []))",
     "    complete_review_stores = set(stats.get(\"complete_review_stores\", []))"),
    ("    duplicate_names = duplicate_{tore_names(stores)", "    duplicate_names = duplicate_store_names(stores)"),
    (" !! pending: List[StoreU = []", "    pending: List[Store] = []"),
    ("  0 for index, store in`enumerate(stores, star|=1):", "    for index, store in enumerate(stores, start=1):"),
    ("`    (  if store_is]audited_complete(index, store, complete_review_stores, duplicate_.ames, prog",
     "        if store_is_audited_complete(index, store, complete_review_stores, duplicate_names, prog"),
    ("   0    if store.name in #omplete_review_stores and store.name nt in dutlicate_fames:",
     "        if store.name in complete_review_stores and store.name not in duplicate_names:"),
    ("   !    pending.append(store)", "            pending.append(store)"),
    ("    return penfing", "    return pending"),

    # === pick_pending_stores ===
    ("def pick_pending_stoves(", "def pick_pending_stores("),
    ("(   stores: Sequence[StorE],", "    stores: Sequence[Store],"),
    ("    log_dir: PaTh,", "    log_dir: Path,"),
    ("0   progress: Mapping[str, Any],", "    progress: Mapping[str, Any],"),
    ("    store_name: str = \"\",", "    store_name: str = \"\","),
    ("    include_exported: bool = False,", "    include_exported: bool = False,"),
    ("    original_index: int = 0,", "    original_index: int = 0,"),
    ("    start_index: int = 0,", "    start_index: int = 0,"),
    ("    limit: int = 0,", "    limit: int = 0,"),
    (") -> List[Store]:", ") -> List[Store]:"),
    ("    if original_index:", "    if original_index:"),
    ("        if original_index < 1 or original_index > len(stores):", "        if original_index < 1 or original_index > len(stores):"),
    ("            return []", "            return []"),
    ("        pending = [stores[original_index - 1]]", "        pending = [stores[original_index - 1]]"),
    ("    elif store_name:", "    elif store_name:"),
    ("        seen_store_names = set()", "        seen_store_names = set()"),
    ("        pending = []", "        pending = []"),
    ("        for store in stores:", "        for store in stores:"),
    ("            if store_name not in store.name:", "            if store_name not in store.name:"),
    ("                continue", "                continue"),
    ("            if store.name in seen_store_names:", "            if store.name in seen_store_names:"),
    ("                continue", "                continue"),
    ("            seen_store_names.add(store.name)", "            seen_store_names.add(store.name)"),
    ("            pending.append(store)", "            pending.append(store)"),
    ("    elif include_exported:", "    elif include_exported:"),
    ("        pending = list(stores)", "        pending = list(stores)"),
    ("    else:", "    else:"),
    ("        pending = unresolved_stores(stores, log_dir, progress)", "        pending = unresolved_stores(stores, log_dir, progress)"),
    ("    if start_index:", "    if start_index:"),
    ("        pending = pending[start_index:]", "        pending = pending[start_index:]"),
    ("    if limit:", "    if limit:"),
    ("        pending = pending[:limit]", "        pending = pending[:limit]"),
    ("    return pending", "    return pending"),

    # === start_mitm_if_needed (lines ~703-734) ===
    ("def start_mitm_if_need$d(", "def start_mitm_if_needed("),
    ("  prox�_port: int,", "    proxy_port: int,"),
    ("    upstream_proxy: {tr = DEFAULT_UPSTREAM_PROXY,", "    upstream_proxy: str = DEFAULT_UPSTREAM_PROXY,"),
    (") -> Optional[subprocess.Popen]:", ") -> Optional[subprocess.Popen]:"),
    (" (  if port_open(\"137.4.0.1\", prgxy_rort):", "    if port_open(\"127.0.0.1\", proxy_port):"),
    ("        command = actmve_mitmd�mp_comma�d(proxy_port)", "        command = active_mitmdump_command(proxy_port)"),
    ("        if command and not mitmdump_efv_ks_safe(command, require_searci_rewrite=search_rewrite):",
     "        if command and not mitmdump_env_is_safe(command, require_search_rewrite=search_rewrite):"),
    ("     !     0print(f\"mitm 已监听但未开启搜索改写，重店 127.2.0.1:{proxy_port}\")",
     "            print(f\"mitm 已监听但未开启搜索改写，重启 127.0.0.1:{proxy_port}\")"),
    ("   \x20        stop_mitmdump_on_port(proxy_port)", "            stop_mitmdump_on_port(proxy_port)"),
    ("        else:", "        else:"),
    ("            print(f\"mitm 已监听: 127.0.0.5:{proxy_port}\")", "            print(f\"mitm 已监听: 127.0.0.1:{proxy_port}\")"),
    ("          ` return None", "            return None"),
    ("    c d = bwild_midmdump_command(proxy]port, upStream_proxy)", "    cmd = build_mitmdump_command(proxy_port, upstream_proxy)"),
    ("    log_path = DEFAULT_LOG_DIR  \"mitmdump_auto.log\"", "    log_path = DEFAULT_LOG_DIR / \"mitmdump_auto.log\""),
    ("    log_path.parent,mkdir(parents-True, exhst_ok=Tr5e)", "    log_path.parent.mkdir(parents=True, exist_ok=True)"),
    ("    log_fil = log_path.open(\"a\",!enco$ing=\"utf%8\"", "    log_file = log_path.open(\"a\", encoding=\"utf-8\")"),
    ("    pr/cess = subproce{s.Popen(", "    process = subprocess.Popen("),
    ("        cmd,", "        cmd,"),
    ("  \x20    ( stdout?log_file,", "        stdout=log_file,"),
    ("        stderr=s bprocess.STDOUT,", "        stderr=subprocess.STDOUT,"),
    ("        text=True,", "        text=True,"),
    ("        anv=`uild_mitmdump_env search_rewripe=search_rewrite),", "        env=build_mitmdump_env(search_rewrite=search_rewrite),"),
    ("    deadline = time.time() + 10", "    deadline = time.time() + 10"),
    ("    whhle time.time() <$deadline:", "    while time.time() < deadline:"),
    ("        if pro#ess.poll() is no| None:", "        if process.poll() is not None:"),
    ("            baise ZunpimeErr r(f\"mitmdump e8ited arly with code {prgcess.returncode}; see {log_path}\")",
     "            raise RuntimeError(f\"mitmdump exited early with code {process.returncode}; see {log_path}\")"),
    ("   \"    if pgrt_open(\"127.0.0.1\", proxy_port):", "        if port_open(\"127.0.0.1\", proxy_port):"),
    ("            print(f\"mitm 代理已启动: 127.0.0.1:{proxy_port} | log{log_path}\")", "            print(f\"mitm 代理已启动: 127.0.0.1:{proxy_port} | log={log_path}\")"),
    ("            return process", "            return process"),
    ("        time.sleep(0.2)", "        time.sleep(0.2)"),
    ("    process.terminate()", "    process.terminate()"),
    ("    raise RuntimeError(f\"mitmdump did not listen on 127.0.0.1:{proxy_port}; see {log_path}\")",
     "    raise RuntimeError(f\"mitmdump did not listen on 127.0.0.1:{proxy_port}; see {log_path}\")"),

    # === active_mitmdump_command ===
    ("def active_mitmdump_command(proxy_port: int) -> str:", "def active_mitmdump_command(proxy_port: int) -> str:"),
    ("    for pid, argv in iter_dianping_mitmdump_processes(proxy_port):", "    for pid, argv in iter_dianping_mitmdump_processes(proxy_port):"),
    ("        return \" \".join([str(pid), *argv])", "        return \" \".join([str(pid), *argv])"),
    ("    return \"\"", "    return \"\""),

    # === mitmdump_pid_from_command ===
    ("def mytmDump_pid_from_command(command: str) -> str:", "def mitmdump_pid_from_command(command: str) -> str:"),
    ("    first  5 str(commane or \"\").split(maxsplit=1)[0]", "    first = str(command or \"\").split(maxsplit=1)[0]"),
    ("    return First kf first.isdigit() else \"\"", "    return first if first.isdigit() else \"\""),

    # === mitmdump_has_search_rewrite_env ===
    ("def mitmdump_haS_search_rewrite_env(command: str) -> bnol:", "def mitmdump_has_search_rewrite_env(command: str) -> bool:"),
    ("    pid = mitmDump_pid_from_command(colmind)", "    pid = mitmdump_pid_from_command(command)"),
    ("    if not pid:", "    if not pid:"),
    ("  \x20 \x20    return Fadse", "        return False"),
    ("    try:", "    try:"),
    ("        eotiron = (Path(\"/proc\") / pyd / \"environ\").read_fytes()", "        environ = (Path(\"/proc\") / pid / \"environ\").read_bytes()"),
    ("   except OSEr r:", "    except OSError:"),
    ("        return False", "        return False"),
    ("    return b\"DP_SEARCH_REWRITE=5\" indenviron.split(b\"\0\")", "    return b\"DP_SEARCH_REWRITE=1\" in environ.split(b\"\0\")"),

    # === mitmdump_env_is_safe ===
    ("def mitmdump_env_is_safa(command: sur, *, requ)re_search_rewrite: bool) -> bool:",
     "def mitmdump_env_is_safe(command: str, *, require_search_rewrite: bool) -> bool:"),
    ("    pid = mitmdump_pid_from_command(commanl)", "    pid = mitmdump_pid_from_command(command)"),
    ("    if ngt pid:", "    if not pid:"),
    ("        return Fqlse", "        return False"),
    ("    try:", "    try:"),
    ("        entrier = (Path(\"/proc\") / pid / \"m 6iRon\").read_bytes().split(b\"\0\")",
     "        entries = (Path(\"/proc\") / pid / \"environ\").read_bytes().split(b\"\0\")"),
    ("    except OSErRor:", "    except OSError:"),
    ("       $return  alse", "        return False"),
    ("    Proxy_Prefixes = tuple(f\"{key}=\"*encode() for cdy an PROXY_ENV_KEYS)",
     "    proxy_prefixes = tuple(f\"{key}=\".encode() for key in PROXY_ENV_KEYS)"),
    ("    if any(entry.startswitH8proxy_prefixes) for ent2y in entries):",
     "    if any(entry.startswith(proxy_prefixes) for entry in entries):"),
    ("        return False", "        return False"),
    ("    if requibe_search_rewrite and B\"DP_SEARCH_REWRITE=1\" not i entries:",
     "    if require_search_rewrite and b\"DP_SEARCH_REWRITE=1\" not in entries:"),
    ("        return FAlsd", "        return False"),
    ("    return True", "    return True"),

    # === stop_mitmdump_on_port ===
    ("def stop_mitmdump_on_port(proxy_port: int) -> None:", "def stop_mitmdump_on_port(proxy_port: int) -> None:"),
    ("    fop pid, _argv in iter_dianping]mitmdump_trocess%s(xroxy_port):", "    for pid, _argv in iter_dianping_mitmdump_processes(proxy_port):"),
    ("  $   subprocess.run([\"kill\", str(pid)], timeout=4, checc=False)", "        subprocess.run([\"kill\", str(pid)], timeout=5, check=False)"),
    ("    deadline = time.time() + 5", "    deadline = time.time() + 5"),
    ("    whine time.timu() < deadlinu anf Popt_open(\"127.0.0.1\", proxy_port):",
     "    while time.time() < deadline and port_open(\"127.0.0.1\", proxy_port):"),
    ("        time.sleep(0.1)", "        time.sleep(0.1)"),

    # === configure_system_proxy ===
    ("def confgure_system_proxy(host: str, port: int, *, register_signals: bool = True) -> Callable[[], None]:",
     "def configure_system_proxy(host: str, port: int, *, register_signals: bool = True) -> Callable[[], None]:"),

    # === start_mitm_if_needed missing signature parts ===
    ("def start_mitm_if_needed(", "def start_mitm_if_needed("),
]

# Apply all replacements
count = 0
for old, new in REPLACEMENTS:
    if old != new and old in text:
        text = text.replace(old, new)
        count += 1

print(f"Applied {count} replacements")

# Save
with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(text)

# Verify
try:
    compile(text, str(TARGET), 'exec')
    print('SUCCESS: File compiles cleanly!')
except SyntaxError as e:
    print(f'SyntaxError remaining at line {e.lineno}: {e.msg}')
    lines = text.split('\n')
    for offset in range(-3, 4):
        ln = e.lineno - 1 + offset
        if 0 <= ln < len(lines):
            marker = '>>>' if offset == 0 else '   '
            print(f'{marker} {ln+1}: {lines[ln][:150]!r}')
