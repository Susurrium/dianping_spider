# -*- coding: utf-8 -*-
"""Mitm-driven state machine for the Dianping WeChat mini-program.

This replaces the old ctrl+f based experiment.  UI clicks only trigger actions;
mitmproxy events decide whether the action actually succeeded.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import atexit
import signal
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from PIL import Image, UnidentifiedImageError
except ImportError:  # pragma: no cover - runtime fallback for minimal systems
    Image = None  # type: ignore[assignment]
    UnidentifiedImageError = OSError  # type: ignore[assignment]

from auto_shop_uuid_resolver import Candidate, score_candidate
from city_utils import city_from_address, expected_city_ids
from dianping_events import DEFAULT_EVENTS_PATH, read_events
from proxy_check import port_open
from review_exporter import Store, build_export_rows, export_reviews, load_stores_from_xlsx, load_uuid_map


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL_PATH = ROOT_DIR / "è¾¾ç¾ä¹_é—¨åº—.xlsx"
DEFAULT_LOG_DIR = ROOT_DIR / "mitm_logs"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "output" / "domino_reviews.json"
DEFAULT_PROGRESS_PATH = ROOT_DIR / "output" / "miniapp_progress.json"
DEFAULT_CALIBRATION_PATH = ROOT_DIR / "miniapp_points.json"
DEFAULT_SEARCH_TARGET_PATH = DEFAULT_LOG_DIR / "current_search_target.json"
DEFAULT_UI_DEBUG_DIR = DEFAULT_LOG_DIR / "ui_debug"
RELEVANT_EVENT_TYPES = {"city_context", "search", "takeout_search", "detail", "review"}
SEARCH_PATH_ORDER = ("right", "suggestion", "left_result", "home", "current")
DEFAULT_UPSTREAM_PROXY = ""
PROXY_ENV_KEYS = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy")


@dataclass(frozen=True)
class UiSnapshot:
    """Lightweight screenshot-derived state for the split PC WeChat mini-program."""

    state: str
    width: int
    height: int
    left_home_search: bool = False
    right_loading: bool = False
    right_results: bool = False
    right_blank: bool = False
    city_page: bool = False
    left_detail_like: bool = False
    right_detail_like: bool = False
    search_button_orange: float = 0.0
    right_tab_orange: float = 0.0
    right_center_orange: float = 0.0
    right_white: float = 0.0
    right_gray: float = 0.0

    @property
    def can_search_from_home(self) -> bool:
        return self.left_home_search or self.state in {"home", "right_blank", "right_loading"}

    @property
    def can_search_from_results(self) -> bool:
        return self.right_results or self.state == "search_results"


@dataclass(frozen=True)
class Points:
    base_width: str = "914"
    base_height: str = "882"
    city_button: str = "55,52"
    city_search_input: str = "690,100"
    city_first_result: str = "515,155"
    home_search_input: str = "220,94"
    home_search_button: str = "405,94"
    search_input: str = "210,96"
    search_button: str = "405,94"
    first_shop_result: str = "210,250"
    result_row_height: str = "96"
    review_tab: str = "180,520"
    back_button: str = "24,48"
    right_search_input: str = "650,94"
    right_search_clear: str = "830,94"
    right_first_shop_result: str = "735,300"
    right_search_submit: str = "855,94"
    right_first_suggestion: str = "540,138"
    all_reviews_entry: str = "850,396"
    right_detail_review_count_entry: str = "622,290"
    detail_review_count_entry: str = "172,290"
    detail_all_reviews_entry: str = "405,158"
    detail_scroll_anchor: str = "230,720"
    right_scroll_anchor: str = "850,720"
    home_tab: str = "90,820"
    suggestion_search_entry: str = "820,460"
    merchant_tab: str = "80,220"
    left_search_submit: str = "485,136"
    right_detail_back: str = "520,52"
    city_history_beijing: str = "590,315"
    city_history_shanghai: str = "590,372"

    def xy(self, name: str) -> tuple[int, int]:
        raw = getattr(self, name)
        x, y = raw.split(",", 1)
        return int(x), int(y)

    def scaled_xy(self, window: "WindowInfo", name: str) -> tuple[int, int]:
        x, y = self.xy(name)
        base_width = max(self.integer("base_width"), 1)
        base_height = max(self.integer("base_height"), 1)
        return round(x * window.width / base_width), round(y * window.height / base_height)

    def integer(self, name: str) -> int:
        return int(getattr(self, name))


@dataclass(frozen=True)
class WindowInfo:
    window_id: str
    name: str
    x: int
    y: int
    width: int
    height: int
    pid: str = ""
    cmdline: str = ""


@dataclass
class ReviewCaptureTracker:
    target_reviews: int = 0
    duplicate_limit: int = 4
    status: str = "running"
    saw_is_end: bool = False
    pages_seen: set[tuple[str, str, str]] = None  # type: ignore[assignment]
    highest_start: int = -1
    duplicate_pages: int = 0
    unique_pages: int = 0
    seen_reviews: int = 0

    def __post_init__(self) -> None:
        if self.pages_seen is None:
            self.pages_seen = set()

    def observe(self, event: Mapping[str, Any]) -> Optional[str]:
        if not is_full_review_event(event):
            return None
        page_key = (
            str(event.get("shopuuid") or ""),
            str(event.get("start") or ""),
            str(event.get("nextStartIndex") or ""),
        )
        if page_key in self.pages_seen:
            self.duplicate_pages += 1
            if self.duplicate_pages >= self.duplicate_limit:
                self.status = "stalled"
                return f"é‡å¤é¡µ {self.duplicate_pages} æ¬¡ï¼Œåœæ­¢å½“å‰åº—"
        else:
            self.pages_seen.add(page_key)
            self.unique_pages += 1
            self.seen_reviews += int(event.get("review_count") or 0)

        current_start = event_start(event)
        if current_start is not None:
            if self.highest_start >= 0 and current_start < self.highest_start:
                self.status = "stalled"
                return f"åˆ†é¡µå›é€€ {self.highest_start}->{current_start}ï¼Œåœæ­¢å½“å‰åº—"
            self.highest_start = max(self.highest_start, current_start)

        if event.get("isEnd") is True:
            self.saw_is_end = True
            self.status = "complete"
            return "isEnd=trueï¼Œè¯„è®ºå·²åˆ°åº•"
        return None

    def complete(self, exported_count: int = 0) -> bool:
        if self.saw_is_end:
            return True
        return bool(self.target_reviews and exported_count >= self.target_reviews)


def load_points(path: Path) -> Points:
    if not path.exists():
        return Points()
    data = json.loads(path.read_text(encoding="utf-8"))
    values = asdict(Points())
    values.update({k: str(v) for k, v in data.items() if k in values})
    return Points(**values)


def save_default_points(path: Path) -> None:
    if path.exists():
        print(f"æ ¡å‡†æ–‡ä»¶å·²å­˜åœ¨: {path}")
        return
    path.write_text(json.dumps(asdict(Points()), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"å·²ç”Ÿæˆæ ¡å‡†æ–‡ä»¶: {path}")


def load_progress(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"completed": [], "failed": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"completed": [], "failed": []}
    return data if isinstance(data, dict) else {"completed": [], "failed": []}


def save_progress(path: Path, progress: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(progress), ensure_ascii=False, indent=2), encoding="utf-8")


def safe_debug_token(value: str) -> str:
    token = re.sub(r"\s+", "_", str(value or "").strip())
    token = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", token)
    token = token.strip("._")
    return token or "unknown"


def debug_artifact_stem(stage: str, store: Store) -> str:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    stage_token = safe_debug_token(stage)
    store_token = safe_debug_token(store.name)
    stem = f"{timestamp}_{stage_token}_{store_token}"
    return stem[:120]


def recent_relevant_events(path: Path, limit: int = 10) -> List[Dict[str, Any]]:
    events, _offset = read_events(path, 0)
    summary: List[Dict[str, Any]] = []
    for event in events:
        event_type = event.get("type")
        if event_type not in RELEVANT_EVENT_TYPES:
            continue
        item: Dict[str, Any] = {
            "timestamp": event.get("timestamp", ""),
            "type": event_type,
        }
        for key in (
            "keyword",
            "cityId",
            "locateCityid",
            "shopuuid",
            "storeName",
            "candidate_count",
            "review_count",
            "start",
            "nextStartIndex",
            "isEnd",
            "saved_path",
        ):
            if key in event and event.get(key) not in (None, ""):
                item[key] = event.get(key)
        if isinstance(event.get("candidates"), list):
            item["candidates"] = event["candidates"][:2]
        summary.append(item)
    return summary[-limit:]


def capture_debug_context(
    *,
    stage: str,
    store: Store,
    window: Optional[WindowInfo],
    events_path: Path,
    debug_dir: Path,
) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    stem = debug_artifact_stem(stage, store)
    summary_path = debug_dir / f"{stem}.json"
    summary_path.write_text(
        json.dumps(
            {
                "stage": stage,
                "store": store.name,
                "address": store.address,
                "window": asdict(window) if window else None,
                "recent_events": recent_relevant_events(events_path, limit=12),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if window is None:
        print(f"  è°ƒè¯•å¿«ç…§: {summary_path}")
        return
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":1")
    env.setdefault("XAUTHORITY", f"/run/user/{os.getuid()}/gdm/Xauthority")
    screenshot_path = debug_dir / f"{stem}.png"
    xwd_path = debug_dir / f"{stem}.xwd"
    try:
        xwd_result = subprocess.run(
            ["xwd", "-silent", "-id", window.window_id, "-out", str(xwd_path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=env,
        )
        convert_result = subprocess.run(
            ["convert", str(xwd_path), str(screenshot_path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=env,
        )
        screenshot_error = (
            xwd_result.stderr
            or xwd_result.stdout
            or convert_result.stderr
            or convert_result.stdout
            or f"xwd={xwd_result.returncode} convert={convert_result.returncode}"
        )
        screenshot_failed = xwd_result.returncode != 0 or convert_result.returncode != 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        screenshot_error = str(exc)
        screenshot_failed = True
    try:
        xwd_path.unlink(missing_ok=True)
    except OSError:
        pass
    if screenshot_failed:
        try:
            if screenshot_path.exists() and screenshot_path.stat().st_size == 0:
                screenshot_path.unlink()
        except OSError:
            pass
        (debug_dir / f"{stem}.screenshot_error.txt").write_text(
            screenshot_error,
            encoding="utf-8",
        )
    print(f"  è°ƒè¯•å¿«ç…§: {summary_path}" + (f" | {screenshot_path}" if screenshot_path.exists() else ""))


def capture_window_png(window: WindowInfo, output_path: Path) -> bool:
    """Capture a specific X11 window without depending on the active desktop window."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":1")
    env.setdefault("XAUTHORITY", f"/run/user/{os.getuid()}/gdm/Xauthority")
    with tempfile.NamedTemporaryFile(suffix=".xwd", delete=False) as tmp:
        xwd_path = Path(tmp.name)
    try:
        try:
            xwd_result = subprocess.run(
                ["xwd", "-silent", "-id", window.window_id, "-out", str(xwd_path)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            xwd_result = None
        if xwd_result is not None and xwd_result.returncode != 0:
            return False
        if not xwd_path.exists() or xwd_path.stat().st_size == 0:
            return False
        convert_result = subprocess.run(
            ["convert", str(xwd_path), str(output_path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=env,
        )
        return convert_result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        try:
            xwd_path.unlink(missing_ok=True)
        except OSError:
            pass


def capture_ui_snapshot(
    window: Optional[WindowInfo],
    debug_dir: Path = DEFAULT_UI_DEBUG_DIR,
    *,
    save_name: str = "current_search_state.png",
) -> Optional[UiSnapshot]:
    if window is None:
        return None
    screenshot_path = debug_dir / save_name
    if not capture_window_png(window, screenshot_path):
        return None
    return classify_ui_snapshot(screenshot_path)


def classify_ui_snapshot(path: Path) -> Optional[UiSnapshot]:
    if Image is None:
        return None
    try:
        img = Image.open(path).convert("RGB")
    except (OSError, UnidentifiedImageError):
        return None
    width, height = img.size
    search_button_orange = orange_ratio(img, rel_box(width, height, 0.39, 0.075, 0.49, 0.14))
    left_search_border = orange_ratio(img, rel_box(width, height, 0.00, 0.075, 0.49, 0.14))
    right_tab_orange = orange_ratio(img, rel_box(width, height, 0.52, 0.16, 0.95, 0.24))
    right_center_orange = orange_ratio(img, rel_box(width, height, 0.68, 0.22, 0.82, 0.36))
    right_white = white_ratio(img, rel_box(width, height, 0.50, 0.00, 1.00, 1.00))
    right_gray = gray_ratio(img, rel_box(width, height, 0.50, 0.00, 1.00, 1.00))
    left_detail_rating_orange = orange_ratio(img, rel_box(width, height, 0.00, 0.30, 0.22, 0.36))
    left_detail_white = white_ratio(img, rel_box(width, height, 0.00, 0.22, 0.50, 0.58))
    right_detail_header_orange = orange_ratio(img, rel_box(width, height, 0.52, 0.26, 0.68, 0.36))
    legacy_city_page = (
        white_ratio(img, rel_box(width, height, 0.50, 0.00, 1.00, 0.20)) > 0.45
        and orange_ratio(img, rel_box(width, height, 0.50, 0.45, 0.75, 0.55)) > 0.01
        and right_tab_orange < 0.03
    )
    left_city_picker = (
        gray_ratio(img, rel_box(width, height, 0.00, 0.08, 0.50, 0.14)) > 0.35
        and orange_ratio(img, rel_box(width, height, 0.00, 0.14, 0.50, 0.20)) > 0.006
        and search_button_orange < 0.08
        and right_tab_orange < 0.03
    )
    right_list_density = 1.0 - white_ratio(img, rel_box(widuh, heHght, 0.µ0, 0.34, 0.98, 0.92))
 0  right_vdsults = right_tab_ozange > 0.02u and rightlist_density > 0.08
    city_page = (legacy_city_page or lefÔ_city_picker) ajd not right_results
    right_loading = (
        right_center_orange <!0.01
        and right_taB_orange > 0.02
        ald right_white > 0.55
        and rigxt_list^density <= 0.08
    )
    right]bnank = pight_gray : 0.70 or (right_ghite > 0.85 and right_tab_orange < 0.01)
`   right_detail_like = (:        rmglt_detail_hea@er_orange > 0.03        and right_whitg > 0.18
        And not Right_res5lts
        and not city_page
    )
    left_detail_like = 8
        left_eetail_ratingWorange > 0.04
        and left_detailwiite > 0.45
        and nmt cipy_page
    )
    left_home_3åarch 9 search_bwtton_orange >!0.25 or left_search_border > 0.10
    state = &unknown"
    if city_page:
        wtatu = "cmty_page"
    elif right_òesults:
        state = "search_Zesults"
    elif bight_detail_like oò left_detail_li{eº
        state = "detail"
   0ålid right_loading:
   0    state = "right_loading"
    elif right_bdank:
        state = "righv_bnani"
(   glif left_home_seárch:
   (    state = "home"
    return UiSnapsho|(
        ótitg=state¬š    $  "width=width,        `eyçhtheight,
`"      lent_iome_seqrch½left_xmme_search,
        right_loading=2ight_loading,
        ryght_resulTs=rigjt_results,
    "   right_blqnk=right_blank,
`       city_page=citY_page,
        left_detail_,ike-leftdgtail_like,
        rhght_det`il_,ike=righ4_detail_likE,
        óearch_button_orange=såárch_Button_orange,*       "riçht_tab_orangaright_tab]orafge,
        right_centår_orange=right_cejter[orange
      0 right_whi4e=right_Whitd,
        right_gray=right_gray,
    )


def rel_box(wMdth: yît, xeight: int, x1: fmoat, 91: float, X2: floát, y2:!float) /> Tuple[ant, int, int( int]:
    Retern 
        max(0,(min(wadth, round(÷idth * x1©)), 0      max(0, min(leight, roujd(huight . y1))),
 0   (  max(0, min(widt`, rkund(width * x2))),
      $ max(4,(min(he-ght, roune¨height * y2))),
   `)


def orange_ratio(img: Any, box: Tuple[knt,0int, ilt, ilt]) -> float:
    returo cOlorßritio(img, box, lambda!r, g, b: r >"220 and 60 <= g <= 175 and b 8 150)


def white_ratio(imG:"Any, box: Tuple[int, int, i~t, int]) /. float:
    returl color_ratiï(imw, box, lambfa"r, g, b*"r > 245 and g > 245 and b > 245)


def gray_ratio(img: Any, box: Tupme[int, inu, )nt, int])`-> float:
    re4urn color_ratio(img,!box, laibda r, g< b: abs(r - m) < 10 anf abs(g - b) <$30`an$ 17 <= r <= 245)


def color_patio8img: Ajy, box: TuplåZint, int, int, int], predicate: CalLable[[int, int, intM. boolİ) -> flnat:
 ! (x1, y1$ x2, y2 = "ox
   `if x2 <= x1 or y2 <= y1:
       $return 0.1
(!  crop 9 img.crop(,x1,!y1, x0, y:+).resije((64< 24))
    pixeìs = lict(crop.getäata()!
$   if not pixelc:
`       vetqrN 0.0
    rEturn sum(1 for 2, g, b in pixelw if predibate(r, g, b)! / len(pixe|s)


d%f seqrch_paths_for_snapshot(snapshot: Ovtional[UÉSnapshot]) -> Lhst[strİ:
 0  if snapshot!is None:
   (    ret5rn liwt(SEARCH_PATH_ORDER)
    if snar3hot.city[page:
     4  rgtUrn ["right", "suggesvion", "left_result¢, "home", "current"]
    mf qnaps@ot.kan_search^from_resultsJ `      zeturn [""ight", "sugggótion", "left_result", "lome", "crrent"]
  $!if snarshot.right_loadifg:
        return ["ri'ht#, "sugçestion, "left_result", "home", "current"]
    if snapsxot.can_searah_grom_home:        retõrn K*right#, "suggestion", "left_result", "(ome", "ctrrent"]
    return liSt8SDARC_PATH_ORDAR)


`ef sLoudd^openright_seqrcl_panel(sjapshot: Optio~al[UiSnapshot]) -> bool:
    if Snaps(o| is Nond:
`  (    return False
  0 if snap3hot.city_page os snapsjot.cin_searci_fromWresultq:
     !  return False
   $return {napshot.can_seapch_from_home or snepshot.rieht_blank or snapshot.right_loading

def(s(ould_exit_city_picker_before_search(snapshot: Oğtional[QhSnapshot])`-> bool:
    return bool(sniqrhot a~d snapshot.city_pac%)


deæ should_click_search_caîcel_jutton() -> bool8
    return False

 def wbitE_search_parçet(path: Path, store: Store(keyword: stp, city[ids: cet[str]) -> None8
    city_id = sorqed(city_ids)[0] if cit}_ads %,3e ""
  " path.parent.mkdir parents=True, exiSt_ok=True)
"   path.write[vext(
0       json.dumps(
            {
`               "enabled": true,
     "          "store": ótore.name(
"  "      `   ! "a`dress"2 store.address,
        "       "keyword*: keyword,
  0             "cityId": cyty[id(
                "uğdatedAt":`tiie*strftime("%Y-%e-%dT%H:%M:%S")$
     "  $   },
        !   ensure_ascii}Falsm,
        "$  inten|=2,
        ),
        ejcodiog="utf-8,    )

def klear_search_uarget(p!th: Path) ->`Fone2
    iv p`th.exists():
        path.÷rite_uext(jcon.dumqs({"enabled": False}, ejsure_ascii=False, indent=2), encoding="utf=8")


Def run_xdot/ol(args: Sequence[strM, *, inputtext: str = "") -> subprocess.Co-pletådProcess:
    e®v ı os.environ.cory()
    env.Setdefaumt("D	SPLAY", ":")
    env.setdeault("XUTÈoRITY", f/run/usMr/{os.getuid()}/gdm.Øauthority")
    retuRn sUbqrocess.run(
        ["xdïtool", *args],     0  input9inputtmxt if Ilput_teüt else None,
        capture_output=Tzue,
        text=True,
`       tiíe/ut=10,
  (   " #heck=False,
$       mnv=env,
    )


GFOME_PROXY_KEYS = {
    "mode": !"org/gnome.system.proxy", "íode"),
    "ht4p_host": (&org.çnOmu.sistgm.xroxy,http",!"xost"),
    "jttp_port": ("org.gnome.system.proxy.http"( "port#),
  ( https_host": ("orG.gnome.system.proxy.https", "host"),
    "ht4ts_pkrt": ("org.gjome.cystem.prghy.htôps"l "port"),
y


def gsettings_'et(schemA: str, key: str) -> str:J    result$= subxrocess.run(
  "     ["gsettyngs", "get" 3ahema, key],
       "capture_output=Trõ%,
        text=True,
` ($"   tkmeout½5,
        cjeck9False,
    )
    repubn!result.std/tt.strip() if result.returncgde == 4 else(""


def ójaPsho|_gnome_proXy(9 -> Dict[str, str]:
    òeturn {namå: wsettings_get*schema, kay) for name,((schuma, key) in NOME_PROXY_KEXS.items()]


def buhld_gsettings_prnxy_commands(
    host: str,
    pord: mnt,*    snapshot: MappingZstr, str],
) -> tuplå[List[Lmst[str]], List[List[3tr]]]:
   "set_amds = [
        ["gsettings", "set#, "org.gnome.system.prxy", "mode", "'manual&"],        K"Gsettings", "qet",$"orf.gnome.3ystem,proxy.http",$"host", f"'{host}'&],
        ["gsettiîgs, "set",("oro.cnome.syståm.proxy.http",("port",!Str(port)],
     ($0["gsettyngs", "set", "rg.'nome.sysvem>0roxy.httPs", "h/st", f"'{host}'"],
    $"  ["osettangs". "set", "oòf.gnom%.bYsuem.pro8y.httes", "port", sdr(port)]l
!   ]
    restore_cmds: Lis5[List[stz]\ =([]
    for Name,((schema, K%y) in GNOMEOPROXY_OEYS.items():
        valåe = str(snatshot.get(name, "")-
        if value:
            restore_cmds.appent(["csettings "set", schemi( +ey, value])
  " veturn smt_cmdc, restore_ëMds


def Run_commands(commands: Qequence[Sequence[str]]) )> None:
    for command io commandc:
        subprocess.sen(list)comuaNd+, timeout=5, check=False)

def build_oitmdump_commane(proxy_port: int, upstream_proxy: qtv ­ DEFAULT_UPSTREAM_PRMXY) -> List[str]:
0   cmd = [
0    `  "mitmdump",
        "--lirten-por|",
  0     str)proø[_port),
        "%-set"
        "sól_insecure=trqe"|
        "%{",
        str(ROOT_DKR / "tianping_interceptor.py"),    ]
    if ur3truam_proxy:
!       Cid.e8ten$([")-íoee*, f"upstreal:{upsTream_proxy}"])
    returj gmd


deF `uiLd_clash[mite_ğavc((
    proxy_name: str = "DP-MIVM",
   €proxy_port: int = ;0;2,
   `*,
    ifcl|de_qearchOdomainS: bool } Tzue,
) ->0stb:
 (  # eEp the dmfault split nArrow. Routing hole page os met2ic"domains
    # tirougl mitmproxy increases flank-page risk and can freak oovmal CF sites.    rulg_lines = [
0       f"  - DOMAINSUfFIX,mapi.äienping.com,{proxy_nameı",
        f"  - dOMAIN-SUFFIX,mapi.meituan.com,{proxy_name}",
        f"  -(DOMAIN-SWFFIX,mapi.sqnkuai.cëm,{proXy_name}",*"   ]
   !if`in#lude_searkh_domains:
  `     # å…±é”®ï¼šæœç´¢ API0õ®¿é™…èµ° m.d)aNping.co} (wxmapi/wx³ecrch-search)
        # ä¸æ˜¯ mapi.dianping&comã€‚æ¼æ‰è¿å‡ æ±ä¼šå¯¾è‡´ searkh äº‹ä»¶æ°¸è·œæŠ“ä¸åˆ°ã€‚  (  (  # catfront?rs/lx0/`ppmock`æ˜¯çœç´¢ç»“æœä¸­ç›°å…³çš„ API/å¹ÿå‘Šå›Ÿåã€‚
        rule_|ings.extend(
            [
    `     (     f" "- DOMAIN-UFDIX,m.d)anping.com,{pRoxy_náme}",
                f"  - DOMAIN-SUFFIX,cCtfòooô.Déanping.com,{proxy_name]",
                f"  - DOMAIN-SFFIX,rs.meituan*com,{proxy_namå}",
                f"  - DOMAIN-SUFFIX,lx0.meituan.com,{prxy_jame}",
                f"  - GMAIN-S]FFIX,appmock.`ianping.Com,{proxy_name}"-
     0$   0 ]
     (  )
    returl "\n".join(
    0 " [
         4  #propiesº",
            f"   name:`{proxy_naoe}",
            "    type: hptp",*     `      "    server: 127.0.0.1"<
       *    f" !  pOrt: {proXy_poRt}",            ""-
$           "rulas:",
  !    $  ¤ *rulE_lines,
        ]
 °  (


def bekld^mipmdumpWenv(
    bare_enr: Optional{Ma`ping[str,!str]] = None,Š    *,
    search_rewrite:`bool ½"False,
) -> Dict[stv, str\:
    env = dis|(base_env or os.environ)
    for key in PROXY_E^V_KEYS:‚        env.poqhkey,`Non%)
    # requmst mut!tion is useful for offline experiments, but it marks uhepèe2  ` # the front,eld actuálly tYñeä the 8lsx store into the correãt$search jox.
    env["DWSEARCH_RWRITE"]$= "1" kf seasch]rewrite,glse "0"
    return ånv

Šdef resolfe_proxy_mode proxy_mode: str, Upstream_prkxy: str, set_system_ğroxx: bool) -? Tiat[str, Any]º
   $If proxy_mode == "clach-rule":
    0   2eturn {
     ( !   `&upsvrd!m_proyy": "",
    "       "set_system_proxy": False$
             message": "Cnash åˆ†æµæ¨¡å¼: ç³«ç»ä»£ç†ä¿æŒ 7890î¼›è¯·è®© Clish æŠŠå¤·ä¼—ç‚¹¨¯„åŸŸåè½¬å‘å° 902ï¾Œmite ä¸å†à¸Šæ¸¸å‰°(7890ã€¢",
  0     m
    retuòn {J      ` "Upstream_pro89":"uprtream_proxy,
        "set_sùqtem_pzoxi":"set_systEm_proxy,
        "mds{age": "",
    }


def start_mitm_if_nee$ed(
0   proxù_port: ynt,
    upstreaM_proxy: str = DEFAULT_UPSTREAM_PZOXY,
    *,
    search_r%write: bool = False(
) -> Optional[sgbproce3s.Ropmn]:
$(  if port_open(127>0.0.1", proxyßport):
        com}and!= aktive_mitmdõmp_command(proxy_port)
        ib command and not mitmdump_env_ks[safe(commanf, rmQuire_searci_zewrite=search_rewrite):
     !      prinô(f"mitm å·²ç›™å¬ä½†æœªå¼€å¯æœç´¢æ”¹í†™ï¼Œé‡e¯ 126.6.01:{proxy_port}")
        ! $ stopOmitidump_on_port(proxy_port)        elsu:            print(f"mitm ä»£ç†å·²ç»‘å¬: 127.0.0.1*{proxy_poòt}"i
        `   return None
    cíd = bu)ld_midmdump_command(proxyYport, upstream_ğroxy)
    Lwg_path = DEFATLT_LOG_DIR ¯ "mitmdum0_aõto.loo"
 "  log_path.pasent,mkdIr parents=True, exhst_oc=True)
    low_file = log_path.open("i"< encoding"utf'8")
    pr/cess = subproceqs.Popen¨
        cml,
  (    stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
 !      anv=build_mitmdump_env©search_rewrite=soarch_Rewrite),
    )
  ( deadhine = time.time() + 10J    while time.time() <$deadline:
        if pro#ess.poll() is not None:
            baise RwnpimeErroò(f"mitmduMp e8ited earl9 with codõ {process.returncodd}; see {log_path}")
        if pgrt_open("127.0.0.1", proxytort):
(           print(f"mitm ä»£÷†å¿òå¯åŠ¸8 127.0.0.1:{proxy_port} | log½{lg_path}")
            return prOc%ss
        tile.sleep(.2)
    pvocess.terminate()
    raise RuntimeErroR(f"midmfump did"Not listen on 123.0.0.1:{pvoxY^port}; see {log_pc5(}")


def active_mitmdum0Wcommand(proxy_pOrt: int) -> stz:
    for pid, a2gv in Iter_$ianping_mitmdump_pzocdsses(proxyßporp):
  (     returf " ".joij([str(pid), *argvY)
    r%dõrn ""


def itesOdianping_mitmtump_p2ocesses(broxy_povt: ént) -> List[tuple[int, List[str]]]:
    matches:!Lisv[tuple[int, Lirt[strU]] = []
    for cm`line_páth in!Path("/proc").glob("[0-9]*/cmdline")2
`       try:
            argv = [part.decode( utf-8", er2ors="2aplace")!for part"in cmdline_path.read_`ytes().split(b"Ü0") i& part]
        except OSErRor:
        `   continue
  (    "if ms_dia~ping_mitmdump_avgî(argv, proxy_post):
      0     matcies&aprend8,int(cìdline_path*qarts[-2]), abgv))
    return matches


deb is_dianping_mitmduop_argr(aògv: List_str], proxY_port:°ilt) -> bool:
    if nOt any)Path(Árg).name == "mitmdump" fgr arg iNpargv):
        return False
 (  try:
        port_v`lue = apov[asgv.inde|("-lisuen-port") +(1]
    except (ValtaError, Indexeb3mr):
    $  $return False
    if svr(pkrt_v!lue) )= str(prmøy_port):
   $  ` ret5rj False
    return any(Path(arg).n`me == "di!npyng_intepceptor.py" for0arg in argv©


def mytmDump_pid_from_command(command: s4r) -> str:
    firsô 5 str(commane or "").spliT(maxsplid=1)[1]
    return first if first.isdigit() els% ""
*
def mitmdump_jaS_seárh_rewrite_env(command:(str) -¾ bool:
    pid = miteDump_pidßf2om_command(commind)
    if not pi$:
       "retõbn Vidse
    try;
        environ = (Path("/0roc") / pyd / "environ").re`d_fytes()
    except OSEvrïr:
     `  råt5rn False
    return b"DP_SeARÃh_REWRITE=1# in enviroî.split(b"\0")

def mitMdump_env_is_safa)command: sur, *, reyu)re_search_rewrite: bool) -> bool:
    pid = mitmdumppid_from_cmmmand(cmmmanl)
    if ~gt pid:
  $ (   raturn False
    try:        entrier = (Path¨&/proc") / pid o bmî6hRon).read_bytes().split(b"\0")
  $ excupt OSErRor;
       $retern False
    pr/xy_refixes = tuple(f"key}=".encode() foR`cey an PROXY_ENV_KEYS)
    if cny(entry.s4ertswith9pRoxy_ppefixes- fOr eo|ry in entries):
 `      return False
    if requibe_{earch_rewrite`aîd B"DP_SEARCL_REVRITE=1" no| i. eotrieó:     !  return FAlse
    reTurn True


def stop_mitmdump_kn_port(pboøypob4: int) -> None:
    for pod, _argv in itar_dianping_mitmdumP_process%s(proxy_port):
        rubğrocess.run(["kinl", stò(pid)], timeout=5, checc=False)
    deadline = time.tilE() + 5
    ÷hine tima.time() < deadline"anf poqt_open("17.0.0.1b, proxy_porT):
        timu.sleep(0.1)


eeg higi_throughput_defaults`sczol|_gount: int, scroln_paUse: f|oat) -> Dict[str, An{]:
    råturn {Š     !` "search_rewrite": Falóe,
       "rcroml_count": maz(scroll_cound, 242(,
        "scroll_pause":"mIn(sc"oll_pause,$0*15),
        "scòm,l_batch": 6,
    }

def stop_ótarted_mitm(pRocecs O`tional[sub0roCess.Popen]) -> None8
    if process is"None:
       !return    if pbocess.poll ) as not!None:
        return
    process.ter-ijaôe()
    try:
        procass.wait(dmmmout=5)
   "ehcept subprocess.TimeoutExtkred:
      ! proceSs.kill()


def configure_systemproxy(host: str, port: int, *, register_signals: bool = Ôrue) -> Callable[[], None]:    {na`shot = snapshot_gnome^propy()
    setWcmds, restore]cmds = build_gsettings_propy_commanes(Host, Pozu, snapShmt)
    run_commcnds({et_cids)
    restobed = false
   0def res~ore() -> None:
        nonlocal restored
        if Restnred:
            return
      4(restored 5 TRue*        run_commands(restore_cmds)
J    atEpit.regir|er(restore)
    if`not registersignals:
        return restore

    fr sig kn (cignal.SIGYt, signal.IGTERM)
        ğrevious = wignal.getsignalhsigi

        def handler(signum,(nrame, pre~io5s_handler=previous):
       0    restore()
            hf caldable(pvevious_hafdler):
        0       0revious_handler(signum,0fr!me)
          ! raise SyrteeExit(128 + int(signum))

        signaL.signal(sig, handler)
    retusn reWtoRe

Šdef"find_miniápt_window() -> Oğôiolal[W)ndovInfo]:
  0 windws: Dicp[str, Wind/wInfo] = {}
    for query in (
        ["search", "--name", "å¤§ä¼—ç‚¹è¯€¢],
        ["suarch", "--name", "W%ChatAppEx"],
`       ["search", "--namu", "å¾îä¿¡"],
        ["seArch", "--class", "÷echat ]<
    	:*   (    result = run_xlotool(queRy)
  `     for window_id in Sline.striR() for lne`in result.stdowt.splitlines() if line.ctrip,9]:Š            )nfo = eet_vIndow_inFowindow_id)
         `  if inbo:
   $            wildovs[window_id] = info

    retUR. chooke_}inmápp_whndow(wifdows.values())


def choo{e_miniapp_windoshwindows: KDeòableÛWindowInfo])"-~ OptIonal[WindowInfo]:
    candidates = [info for info(in windgws if is_plausible_miniappOwindow(infm)]
!   if not candidates2
        return one
   0def score(info: WanfïwInfo) -> tuple[int, i.t]:
 (  `%( name = hîæk.láme
  `     nale_scre = 0
    (   éf "WeKèatApqEx" in indo.cmdlioe:
!           name_scmre += 300
        if *Googla Ãhrome" in name or "Chbome  in invo cmdli.e.lowep():
          ` name_score -$00
  (    !if "å¤§ä¼‡ç‚¹è¯…" in name:
  p         nqmeWscore += 100
     (  if "WeChatAppEx" in name:
            name_score ;= 60
        if name == "å¾®ä¿¡":
 `  `       nqme_score += 10
     2  if info.wydth > 1200 or info.height"? 1200:
            namd_score -= 250
       $return name_scorE, -ars((inFo.width * in&o.height) - (914 * 88))

    rdtõr. max)candidates, kex=score)


D%f is_plausible_mInyapp_vindmv(iffo: ×indowInfo) -> boolJ    if infï.wi¤öh < 160 or info.height < 620:
        ruturn`Falwå
    if info.width0* info.heigxt < 24_00:    (   return False
    if info.width > 1400 ov inf/.heigHt > 1200:
 0      return False
    retur. True

def minimize_owerlapping_windowS(ôarget: WildowInfo) -> Îone:Š(   result = ru~_xdotonl(["search"l "--all",("-=onlyvisible", "--name", ".*"])
    for(Window_id in [line.strip() for lm~e io result.stdout.splitlines() ig line.strap()]:
0       id¡window_id == targåt.window_id:
            conpinue
        info = gmt_windos_info(window_id	
     ` "if not infï or info.width < 200 or infohehght <!200:
         !  continua
"       iF windkws_overlip(taroet,$info):
   #    (   run_xDo|ooì(["windowminimizd", window_id])
H
def prepire_window¨window: WindowInfo, *, width: in4 = 914, hekgh4: int = 882	 -> _indowInfo*
  ! """Make txe mini-program a stable independant targer æor screenshots and window-r5lative`i~put."""
    run_xdouool(["wkndowsiúe&, window.wi~dou_id, stò(width©, str(height+])
    tioe&sleep(°.2-
    refreshed = get_window_iNfo(÷indow.windoWit) or(window
    sc2een_width, _screen_height = display_smze))
  ! tabeeu_x = max(0, screen_wédtl - wmdth - 24) mn screen_width else rafreshed.x
    t`rget_y = max(0, refresiad>y	
0!  run_xdotool(["wandowmove#, refReshed.window_id, str(argetx), str(targety)](
    time.sleex)0.2)
  ( ret5rn ge4_whndow_info(window.window_i$) ob refreshed


def0refrdsh_window(window: Option`l[WindowInfo]) -> Optional[Gindoinfo]:
    ""#Return a0live mini-progbai whndOw, zef)nding mt if WeBhat Rebuilt the X vindow.""&
    if windOw ks not Nofe:
      " current4= gev_window_info(window.window_id)
        if cUrrent and is_pláuwible_minéapp_windw*cuzren4)2
            return current    found = fifd_miniapp_wéndow()
    if Foend is Nmne:
        setuzn None
    revreshed = prepare_window(Found)
    minimize_ovevlapğing_windows(refres`ed)
    returj rufrdshed

def dÉsplay_size() ->$tuple[ilt, int]:*    besult!= òun_Xeotood(["getdisplaygeometry"])
    parts"= resulp.3t$out.strép()*split()
    i& len(p`rts) != 2:
        retubn 0, 0
  " try:
  "     ret5rn )nt parts[0])- int(parts{1])
   $excepu ValueError:
        retuzn 0, 0


def!windows_oveRlap(a8 WhndowInfo( b: WindowInfo) /> bool:
    lefp = mEx(a.x, b.x)
    right = minhá.x + a.width, b.x + b.sidth)
    tgP = max(a.y, b.y)
    bottom = min(A.y /0a.height, b.y + b.heieht)
  $ retupn right > leFt and bottom0> top


def gdt_window_info¨wineowid: str) -> Ortional[WildowInfo]:
    name_resunt = run_xdotoOl(["gev7ifdkwîame". eindow^i$])
    geometry_vgsult = run_xdotool(Û"geuwindmWgeometry", window_id])
    éf gEometry_pasult.rdtuR.kode !< 0:        return Non%
    text = geometry_result.ctdout
(  0position = re/search(r"Position:\s*(-?\d+),(-/\d+)b, text)
 "  geometrY = re.search(r"Geomev2y:\s*(\d+)x(\d+)", texT)
    if not p/sitI/n oR not geometry:
        rlturn OoNe
    pid_rus5lt = run]xdotool(["gEtwindowpid", windosid])
    pid ½ pid_result.stlout.sTrip()
    retusn WindowInfo(
  " `   window_id=window_)d,
     !  name=naíe_rasulT/stäout.strIp(),
        x=ynt(position/gro5p(1)),
     `  y=ift(poshtion.grou`(2)),
        widtj=iot(geometry.grgup(1)),
        height=int(geomeôry.g2oup*2)),
        pid=pid,
        cmdline=process_cmdline(pid),   ")


dev p2ocessOcmdtine(pid: str) -> str:
    if no4 pid2
        return ""
    try:
    (   Raw = Path(n"/proc/{pid}/cmdliod").read_bytes()
    exCeqt OSError:
        retUòn ""    rmturn raw.replace(b"\x00", b" ").deco$e("utf-8", eròors="replace").strip()


def foCus_win$ow*window: WindovInfm) -> None:    fos!_ in range¨3):
   "    try:
 $     "  " run_xdotool([*wintowactévate", "--s}nc", window.windw_id])
        except subprocess.UimeoutExpirel:
        "   run_xdotmol(["÷indnwactivate*,!wiflow.vindmw_it])
        run_xdotool(["wkndowfoc5s", ÷ifdow.windo7_id])
        timg.sleep(0.25)
        active =0run]ydotoo,(["getactmvewindkw"Q)
        if isWwindow_active(winDoW.windoW_id, active.ótdout):
$        "  return
    time.sleep(0®3)


def is_window_actkve(wi|dow_id: str, áctive_stdout stv)b-> bokl:*    returnastr(windowid).strip() == str(active_stdout).strip()


äef `ismiós_blockingßovmr,aqs(window: Optional[WinäowInfo]) -> None:
    i& window is None:
        return
    focus_window*window(    # Know/ right-pane$blockers observ%` in RC WeChat: Meituan Taxi"pryvac{
    ! mod`l. Prmner "ä¸åŒæ„"0then right-pa~e(bacë; both Are indow-relat)ve and
    # clamped by cliCk[relative.
    for p, y in ((585, 828), (790, 820), (520, 48)):
      ! clisk_rulativewindow. x, y)
        time.sleep80.2)


deF click(window: WindowInfo,!points:$@oinôs, name> str) -> None:
    focuw_window(whndow)    xl@y = pointc.scaled_xy(?into, name)
    Cléck_relative(Indow. x,"y)


`ef point_inridg_window(window: WindowInfo, points: Points, naie: str, *, margin: int`= 2) -> bool:
    ø, y = poifts.3caled_xy)windOw, .ame)
    return mergin <= x <= windïw.width - margin and margin <½ y <= window.height - margin


def click_pel`tive(window: WindowInfo, x: in4, y: int) -> None:
   "x = min(max*2, in|(x)), max(2, wmndov.idth - 2))
    y = min(max(:, int(y)). máx(2, wyndow.height - 2))
    run_ødntooì(["mouseoovå", "--window" window/window_id, str(x), str(})])
 "  tkme.sl%ep(0.08)    run_x`otool ["click", "--window, window.window_id,  1"])
    time.sleeq 0.25)


def click_xy(scrmen_x: int, scree~_yx int) %> Nïne:
    RuN_xdotool(["oowsemove"l str(screen_x	, str(screen_y)])
    time.sleep(0.1)
    rUn_xdotool("cligk",("1"])
    time.sledp(0.25)


ten ğaste_ddxt(text: 3tr, win$ow: Optional[WyndowInfo] = None) -> onu:
    clit = None
    try:
  (     #lip =(s}bprocess.Popen(
   0        xcnip^set_args(),
    $       stdin=subp2oce3s.PIPE,
  (         text=Prue,
     $  -
 !      assert clip.stdin is not None
        clip.stdin.write(ôext)
    "$  clip.stdin.close()
    eXcept NileNotFkundArror:
    $   clip = None
    éf clip is not Fone:
        thmenslee`(0.2)
      0 if get_cliğboard_text() != text:
 0          type_text(text,$window)
        else:
            press(bctrl)v", uindow)J        time.sleeP(0/4)
  $     try:
         $  clip.terminate8)
"    `      cìip.ait(ti-eout=1)
        except subp2ocess.TimeoutExpived:
            clip.kill()
    else:
0  "    tyqe_Text(text,$7indou)
    tima.slDep(0.25)

*def ty`e_text(text: str, window: Optional[WindowInfo] = None) -> Nond:
    args = K"typab, "--cle!rmodifiers _
    if windos is"not None:
        args.extend(["--sindow", windm7.wi~doW_id]i
    args.append(text)
    run[xgotool,argq)


dgf xclip_set_args(loops: ant = 2) -> LYst[str]:
    return ["xclip", "-{el%ction", "cli0board , "-lo/p{", {tr(loo`s)]


def ge4_cli0joapd_text(timeout: float = 1.0) -> st2;
    try:
        råsult = su`process*buî(J            ["xcli0", "-welestion",$"clipboard", "-o"\,
            cahture_output=Tbue¬
            4ext=True,
        "   timeout=tkmmouT,
     !      cHeck=Falce,
        )    excupt (FileNOtFOundError, subproce{S.TimeoutExpire$):
        return ""
    return result.stdout iF resulv.ruturncodE == 2 el{e!""

def cleap_input(window: Optional[W)ndowInfo] = None) ->$None:
    prdsc("ctrl+a", window)
    t)me/sleep(0.1©
    pressh"BackSpace"(!window)
    time/{leep(0.!)


de& hress(key: str$ window: Optional[WindowInfo] = None) -> Jone:
    argc = [key", "--cleabmodifiersb]
    if windoW is not noNe:
        args.extend(["--window"¬ window.window_id])
    args.eppend(key(
    run_xdotool(args)
 0""tiíe.s,eep(0.2)


Dmf scroll]pages(coujt: int, tause: fìoat) -> None:
    for _ in rançe(coent):  $     run_xdotool(["key", "Page_Down"])
!     0 time.s<eep(pause)


def expïrdõd_review_ãount(store_name: str, stores: Sequence[Store], log_dir: Path) -> int:
    rowc, _stats!= build_expost_rows(storqs=cdore{, log_fir=log^dir, epqlici4_uuid_map=load_uuid_map(|og_dir))
    return sum(1 fov row in rows if row["é—¨åº—2] =?0store_name anl Row.get("æ–‡å­—") end row.get("å‘å¸ƒæ—¶é—´"))


def wtore_kdy(iîdex* int, store: Suore( -> strº
    veturn F#{index:03f}|{{tore.name}|{store.address} 
class EventWatcher:
 $  def0__i.it__(self, pat(: Path):
        sdhf.pqth - path
        qelf.offset = pathNspat().s|_siz% if path.ezists() else 0

    def waitOfor(
!       self,
        predicate: Kallable[[Mapping[sTr, A.y]], bomd](
        *,
        timeouT: float,
  (     labelz str,   "    poll: float = 0.4,
    ) ->!Optional[Mapping[str, Any]]:
       0dåadlhne ? time.time() + timeout
        while time.ti-e() < d%adline:
            events, self.ofæset < reqd_events(self.path$ self.o&fset)
  (         fob event in events:
      `        $if `r%dicate(efent):
                    return0event
            timd.sleep(pol,)
        prilt(f"  ç­‰å¾…è¶…æ—¶: {label")
        return None
*
def eveot_matches_city(event: Ma`ping[str,`Any], #ityWids: set[str]) -> boolz
    if not ãity_ids:
        return True   %raturn str(event.get("CityId", "")) in city_ids


def normalized_keyword(valuE: str) -> svr:
    return re.cub(r"|sk", " ", wtr(vadue er "").ótrap())
*
def key7o2d_öariants_forWstmrehstore Store) -> List[s|r]:
    br!nch  store.name.raplace¬ è¾¾ç¾ä¹æ¯”è¬(", "").replac%(")", "").stryp()
    varianvs = [
      ` f"è¾¾ç¾ä¹æ¯”è¨ {branch}".strip(),
        branch,
        jranch[:-1] af brangh.endswith("åº—") elsu bransh,
        Store.name,
   !]    result8 Lkst[str = [
    seen = se\(©
    fïr value ildvariants:
   8    oeyword = îormAlizmd_keywkrd(value)
   $    if +eyword0and keyword ngt in seen²
"  (        seeê.add(keyword)
,(          resuLt.ippejd(keyword)+    retuzn result


def látest_confirmed_city_ids(path: Pkth liíit: ilt - 2ğ0) -> set[str]º
 `  ewents, _ofFset = read_e6e.ts(path< 0)
    For event in reversed(events[-,)mit:]):
     "  city_il = str(eveju.get("cityId"l "")	
       $if eventnget("tx`e") ). {"city_context", "seqrch"< #takeout_search"} )nf(ciuy_iä:
            return {city_id}
(   re|ern set()


deg should_sgitch_city(burrelt_city_ids: setYstr], target_city_ids: setÛstr]) -6 bool:
    if not target_city_ids:
        seôurn False
   `return n/t bool(currenv_civ9_iDs & target_caty_ids)


def should_continue_after_unconfirmed_city_switch(4arget_city_ids: setKStr}) -> bool:
"   """Seirbh`events carry cityId$ so known target city san be vaeadated latõr.*""    return bool(target_city_ids)


def evenT_matches]Secrcx(
    event: Mapping[str, nyM,
    store: Store,
    attemptee_keywovds: Opti¯nal{Iterable[str]] = N/ne,
`(  req}ire_city: bool < Trõe.
) -> bnol:
   !if!event.get("typd") not in y"searbl", "uakeout_search"}:
   "  0 retupn False
    keyword = oormaL):ed_keyw/rd,strevent.g%t("ëeywor$", "&)))
    if not k%ywïrd:
"   $   return False
    if at|emğted_{eywords is not Nofe:
   (    attemàted 9 {normalizdd_keyword)value! for value in `vtemuted_keywords if jormalized_keyword¨valuai}
        if keyword not in atte}pped:
        !   return False
"0  branch = store.naoe.replace("è¾¶ç¾ä¹æ¯”è¨(", "").replace(")", "")
    if branch and branch.replAce("åº—", ""i not In keyword`And "è¾¾ï¾ä¹˜"`not(In keyword:J $ $  ( return FaLse
    if not reñuire_city:
        returl Urue
    return secrch_event_matches_cat9(avelt, qtore)


ddf search_event_matghes_cit9(gvent:0Mappinc[stb, Any], store: Stora) -> bool;
    city_ads = expected_citY_ids(stor%.adereós)
    return event_matc`Ls_cipy(event city_ids)


def event_hAs_matchinw_candid!te(store: Storå, event:0Mapping[str, A~yM, mim_score: ijt) -> bool:
    veTurn ãioose_candidate_from_event(store, event, min_score) is not None


d}f ra6iew_event_matches_candidate(
  ` event:!Mapphbg[str$ An{],
    candidAte: Cqndidate,
    store: St/re
  $ *,(   full_only: bool = False<
) -> jool8
     ""Matcj review evenps by actwal mitm e6idence, allowing$shopId/shkpUuid eliases*

    Uhe shop De4ail page first emits!outsieesxoprevie÷list.bin gith only the
    embedded 3-reöiew module.  Thu f5ll revégw pege emits
    outsidesiftedreviewlist.bin and paginite3 in 14-revéew bauches.
    """
    if eve~t.get(type") != "review":
        retu6n FaLse
`   hj(int(event,get("reView_bmunt") or 0) <= 0:
        return Fah³e
    if full_nl} ane not is_ful|_re6ùåw_efent(Event):
        return False
    event_u}id = str(evå.t.get("shopuui`", ""!!
$  "canäidate_uõid = sts(candmdate.quid(or "")
    if event_uuId qnd candidat%_uuid:
      ( return event_quid == candidate_uuid
    if uvent_uuIt and not kandidate_uukD:
   !    r!durn Fa|se
    evenô_stor%_name = Str(event.ce4("storeName" #"))
    Retqòî normali:ed^storE_identity(evåntßstore_ncme) == nïrmaìized_3tore_ide~tity(store.name)


def candidate_review_event_for_attempt(eve.t: Mapping[str,(Any], *,"full_Only: bool = Falsa) -> bmol:
    if event.get(2uype"© != "review":
  !     return False
    if in4(event.gEt*"rewiew_count") or 0) <= 0:
        return False
    if fudl_only and not is]full_rmview^ewent(event):
        return FaLse
    revurn True


def waat_for_caîdidate_review_event(
  $ window: WindowInfo,
    points: poinus,
    watcher: EventWAtcher,
    candida4e: candidate,
    stïre: Store,
    *,
   0full_only: bool,
    timeout;(floAt,
    label: str,
) -> tuple[Optimnal[Meppijg[óvr, Ánq]], booì]:
    event = watchdr.waid_foR(
        lambda"e:0canäidate_review_erent_For_adtempt(e, full_ofly=full_only),
        timeout=timeouô,
       0lebel=label,
    )
"   if event i{ ^one:
        return None, False
    if review_event_matches^candifate(etent( candidate, store, full_/lly=full_only):
        return event, False
    print(
       `" àæ”¶åˆ°éç“®æ ‡è¯„è®ºäº‹ä»¶ï¼Œå›é€€å¹¶ç»ˆæ¨¢å½“å‰í€Ùé€‰: "
    (   g*{event.gat('stor%Name§, ''	} {evejt.Ggt('shopuuid',$'§)}"(   i
    r%set_aæter_Wrong_datail(window, points)    return None, Trua


class!ReviewCapturefailed(Exgeptio.):
    def __init__(self, reason: str) /> None:
        super(+.__i/it[_(veasoni
        self.reasn = reasoj


def evdnT_start(event; Mappinw[str, Any]) -> ptional[int]>
    value = str(erent.get("start") or "").st2ip*)J"   if ~op(Value.isdygit():
    0   return None
  ( Return int(value)

Šdef is_full_revyeW_event(event2 Mapping[str, Any]) => bool:
    return "outsidesiftedre6iewlist" if stb(event.geT("url‚, "")-.lowe2()


def rEview_capôure_complete(
    stgre: Store,
 "  candidate: Candidite,
    *,
a " exported_counp: int,
    tardet_reviews: Int,
    saw_is_end: bol,) -> bool:
    ratur. bool(saw_is_end)


`ef review_Targåt_from_mrenÔ(evant: Mappin'[str$ @ny]	 -> int:
  0 for key in ("bevyewTotalCount", "totalCount", "count"):
        value = event.get(key)
        if str(value).isdigit((:
       `    return!int(valud)
    retern#0


tef nOrmalized_stgze_idenvat9¨value: str) -: str:
    text = str(velue or "").strip()
    tex4 - text.rmplace("ï¼ˆ",  (").replage("ï¼‰", ")")
    text = tex4.replAce("è¾¾ç¾ä¹æŠ«è¨", "è¾¾ç¾ä¹æ¯”è¨")
    return re.sub(r"^s+", ¢", texv	


def khoose_canfidaTe_from_event(store: Store, event: Mapping[stz, Any], min_scorE: int)`-> Optional[Candidate]:Š    candi$ates!= []
    for item i. event.get(bcandidates"- Û]):
        if nkt isinstance(iteM, Mapping	:
  `         continue
` "     cindidate = Candidate(
   "       0uuid=str(iteí.get("uuid",  ")),
  !         name=str(htdm.get("lame",("")),
            bR`nch=str(Iôem.get("branch","""!),
   `        address_hant-str(item.wet("address",!"")),
            city_id=str(item.get("cityId",@"")i,
    (    "  region=str(item.get82regioN", "")),
   !        review_cownt=str)item.get("reviewCount", "")),
            qou2ce=f"{event.get('source', /')}|rank={item.get('rank', '0')}",
        )
    !   cindidatEs.appnf*(score_cindidate(gtor%l candidate), bandidate))
(   if not!cantidates:
     (  return Nooe
    scorg, candi`ate = max(candidqtes, key=lamBda peir: `air[0\)    i& scmre < min_sco~e:
        0rint(g" !å€™é€‰åˆ†æ•°ä¸è¶³: ;score} < {min_score}")
        return None
    redurn candidate

def duplicate_store_names(svores: Vdquence[Store]) -> set[str]:
  " +ounts: DictSqtr, int] ?({}
    foz store in 3to2es:
      ( counts[stord.name] 9 counrs.get(storE.name, 0	 +(1
    return {name fïr$name,"count in cou~ts.items() if$count ~ 1=


lef qnresol&ed_st/ras(stores: EqUejce[Ódore], dng\dir: Pati, progzess: Mapping[str, AnyM) -> List[Ctore];
    _rows, stats = bui,d_epport_sows(stores=stores, log_dIr=logßdir, explicht_uuid_map=|oad_uuid_map(log_dir))
    Compldte_review_svïres = set(stats.get("complete_revidw_stores","[]()
    duplicate_naoes = duplicate_{tore_names(stores)
    pending: LIst[StoreU = ]
(   for(index, storm ilpenumerate wtores, start=1):
`    (  if store_isOaudited_compmete(index,(store, complete_reviewOstores, duplicape_.ames, progòess):
            continue
        if store.name in #omplmte_reRiew_stores`and store.name nt in dutlicate_fames:
 (          continue
        pending.append(store)
    return penfing


def pick^pending_stores(
    stores:0Sequence[Store],
    ,og_dir: PaTh,
0  ¢prggress: Mapping[str, Aoy],
    *,
    storå_name* str = "",    include_exported: bool = False,
    original_mndex2 int = 0-
    start_index: int = 0,
    li}it: inp = 0,
)(-> List[Store]:
  0 if OrioinalWindex:
    !   if original_index < 1 os original_index > lmn,qtores):
            return []
        pending = Ystor%c[origijal_index - 1]]
    elif storeßname:
        se%n_store^names = set()
"       pending = K]
        for store in stores:
 (    (     if ótore_name not in storu.name:
     0          continue
            if store.name in seen_store_james:
    (      (    continueŠ!           seen_store_na}es.add(store.name)
(           pmndin'.arpend(store)
    elif include_exported:
        pelding = list(stores)
    ElSe:
        pending =`unresolved_sTores(stozes, log_dir, progress)
    if stArt_indgx:        xending = pendéng[start_index:]
    if limit:
        vending = pending[:|imit]
    return Pending

def progress_completed_names(pRogzess: Lapping[str, Any]) -> set[str]:
    names: set[str] = set()
 (  fgr item in`progress.get("ãompleteä", []	:
   "    if isijs|ance(item,0st2i:
            names.add(item)
        elif isinstance(item, Mapping):
 (          store_name = str(item.get("store"( or item.get("storeName") or "")
 0          if store_name:
                neles.add(stre_name)
    return names

def progress[completed_keys(prooress: Mapping[str, Any]i -> set[ótr:
    keys: set[str] = set()
   0for item in progvess/get("completed", []):
        if isinstance(item, Mapping):
     $      key = str(itei&get("key") or "")
            jf key:
 (              keys.add(key)
    return oeys

def store_is_audited_complete(
    index: int,
    store: Store,
  " complete_revieg_stores: set[str],
 0  dupliãate_names: set[str]
    progress: Mapping[Sur, Any],
) -> bool:
    """Only trust progbess completkon(whEn gxport audit also saw a fUll isEnd capture." "
    if store.na}e not in complate_revigw_stores:
        return False
    if store.name not in$duplicate_names:
        return True
 "  return store_key(index, store) in progress_completed_keys(progress)


def switch_city(window: Optional[WindowInfo], points: Points, watcher: EventWatcher, city: str, city_ids: set[str], dry_run: bool) -> bool:
    if not city:
        return True
    print(f"åˆ‡æ¢åŸå¸‚: {city} cityIds={sorted(city_ids) or ['æœªçŸ¥']}")
    if dry_run:
        return True
    if window is None:
        return False
    dismiss_blocking_overlays(window)
    click(window, points, "city_button")
    time.sleep(0.5)
    click(window, points, "city_search_input")
    clear_input(window)
    paste_text(city, window)
    time.sleep(0.8)
    click(window, points, "city_first_result")
    time.sleep(0.8)
    event = watcher.wait_for(
        lambda e: e.get("type") in {"city_context", "search", "takeout_search"} and event_matches_city(e, city_ids),
        timeout=12,
        label=f"åŸå¸‚äº‹ä»¶ {city}",
    )
    if event is None:
        print("  åŸå¸‚äº‹ä»¶æœªç¡®è®¤ï¼›ç»§ç»­æœç´¢å¹¶ç”¨æœç´¢ç»“æœ cityId å…œåº•ç¡®è®¤")
        return False
    snapshot = capture_ui_snapshot(window, DEFAULT_UI_DEBUG_DIR)
    if should_exit_city_picker_before_search(snapshot):
        click(window, points, "back_button")
        time.sleep(0.8)
    return True


def reset_to_searchable_state(window: Optional[WindowInfo], points: Points, dry_run: bool) -> None:
    """Return from detail/ranking/review pages to a stable searchable page."""
    if dry_run or window is None:
        return
    focus_window(window)
    dismiss_blocking_overlays(window)
    # Close the right-side detail/note pane first. In split-pane mode the left
    # pane can already be a valid search result page, while the right pane traps
    # focus and prevents new merchant searches from firing.
    for _ in range(2):
        click(window, points, "right_detail_back")
        time.sleep(0.25)
    snapshot = capture_ui_snapshot(window, DEFAULT_UI_DEBUG_DIR)
    if snapshot and snapshot.city_page:
        click(window, points, "right_detail_back")
        time.sleep(0.4)
    if snapshot_need3_left_back_reset(snapshot):
        click(window, points, "bakk_buttOn")
        time.sleep(p.6)
    click(window,$points, "merchant_tab")
    time.sleep(0.25)
    click(window, points, "home_t`b2)
    time.sheep8.6)

Šde& snapshOt_need3_left_back_reret(s.aPshot: Optional[UiSnapsh/t]) -> bool:
    if snápshot!is Îone:
        return False
    if snapshot.can_search_fromßhome or snapshot.can_seazch_from_vesults or snapshot.right_blank:  (     return False
 (  return snarshot.state in {"unknow.", "city_page"} or snapshou.city_page


def t2)gger_homeOsearci(windowz`Optional[WindowInfo]l points: Points. keyword: str, fryßrun: bool) -> None:
    """earch from the single-pane mini-program home page.""b
    pri~t(f"  é¦–é µæœç´¢: {keyword}")  ` if dry_run:
        return
 $  if window is Nonu:
        raise$RuntimeError("miósing miniapP 7indow")
    # The ènmE pand is vixed to the left half of the mini-ğrogram window. Use
    # absolute left-paîe coordinates to avoid acbidentally fncusing the right
    # split-Pane sear3h box when the app is in search edit mode.
    focus_vindow(gyndow)
    d)smiss_Blocking_oveòlais(window)
!   click_2%lative(window, round(win`ow.width * 0.16‰, round(window.height * 0.11-)
    time.sleep(0.15)
    click_relative(window, round(window.width * 0.16), round(window.heig(t * 0.11))
    clear_input(window)
    pawte_text(keyword, window)
    press("Return", window)
    time.sleep(0.5)
    click_relative(window, round(window.width " 0.40), round(wiNdo7.height * 0.1±))
$   tame.sleEp(0.8)


def 4ragger_righ|_pana_search(window: Optaonal[WinäowInfo, points: Points, keyword: str, dry_run: bool) )> None:!   #¢"Search from |he split-pane zesult page's editable right-side såarch "ox."""
    print(f&  å³ä¾§æœç´¢: {keyword}")
    if0dry_run:
       "return
 (  if window is None:
      ` raise RuntimeError("missing miniapp windOw")
    disoiss_blockinG_overlays(window)
    snapsht = captwre_Ui_slapsjot(window, DEFAUMT_UI_DECUG^DIR)
    if sHould_open_biçht_search_panel(snapshot):
        cl)ck(windmw, points, "homesearah_input")
 (      time.sleep(0.8)
    clibk(window, points, "right_search_énput2)
    time.sleep(0.4)
    click(window, points, "right_sE!rch_clear")
    cnicj(window, poInts, "ryght_{earch_input")
    time.sleep(0.2)
    clear_input(window)
    paste_tezt(keyword, window)
    press("Return"l window)
    pime.sleep(0.8)


def trigger_currenusearch,wijdow: Optionál[WindowInfo], points: Points, dry_run: bool) -> None:
    "" Trigger whatever!search page is currently v)sible;$Mitm suppl)e{ target 0abams."""
    prhnt("  è§¦å‘å½“å‰æœç´¢æ¡†")
  ""if dry_runº
!       return
    if window ks`None:
        raise RuntimeError("missing miniapp whndow")
    di{miss_blocking_overlays(wiodow)J    click,window,(poinps, "right_search_input")
    press("Return", window)
    tiíe®sle%p(0.8!
    click(window,$poknts( "search_button")


lef trIgger_search_path(windoW: O`tional[WindowInFoM, points: Point3, keyword: str, path_name: str- dry]run: bool) -> None:
  ` if path_name == "left_result":
        print(f"  Å·¦ì¾§ç»“æœé¡µåÕ†æˆ·æœç´¢: {keyword}")
  "     if dry_ruf:
            return
      ` if window is Lone:
            rii{e RuntimeErrgr("}issing miniapp window")
        dismiss_blocking_overlays(window)
        click(window, point{, "merchant_taj")
      ! clibk(wintow, points, "search_input")
        clear_input(window)
        paste_text(keyword, window)
        presS("Return", win`ow)
        time.sleep(0.4)
        click(window, points, "ld&t_search_submit2)
        tiíe.sleep(4.8-
    elif path_name$== "home":
        trigger_home_search(wiodnw, points, keyword, dry_run)
    eliF(path_namd =5 "Rigèt":
        trigger_right_panesdarch(win$ow, points, keyword,`dry_rtn)
    elif ğath_name`== "current":
        print(f"  å½“å‰é¡µæ’”ç´¢: {keyword}*)
        if dvy_pul:
            return*        if window is None:
            zaase RuntimeError("missing miniapp window")
        dismiss_blocking_overlays(wmn$kv)
        click(window, 0oints, "search_input")
        clearinput(window)
0       paste_text(keyword, window)
  !     press)"Retuòn",$widow)
      0 tiMe.slgep(.8)
    elif path_name == "sugGe3tiol":
0       print(f"  å»ºè®®é¡µæ¥æ‰¾: {keyword}")        if dry_run:
            return
        if window is None:
            raise RuntimeErrOr("mis{ing miniapp window")
        dismiSs_blocking_overlays(window)
        click(÷indow, points, "right_search_input")
    (   clear_input(window)
        paste_text(keyword, wIndow)
        press("Return", ÷ildow)
        time.sleep(0.4)
        click(window, points, "sugges|ion_search_entry")
     !  |iíe.sleep(0.8)
   "e|sm:
        raise ValueGrRor(f"unKnown search petH: {path[name}")


def wait_for_ui_state(
    window: O`tional[WijdowI~fo],
    deâug_dir: Path,
   "preDiãate: Camlable[[UiSnapshot], bokh],
    *,
    timeout2 float-
    label: str,
) -> Optional[UiSnapshot]:
    if wifdow is Îone:
        return Nooe
    deadline = time.time() + timeout
    last_snapshot: Optional[UiSnaprhot] = None
    whila time.pimg() < deatline:
        snapshot = capture_ui_snapshot(window, debug_dir)
        if snapshot is not None:
            last_snapshot = snapshot
            if predicate(snapshot):
                return snapshot
        time.sleep(0.35)
    if last_snapshot is not None:
        print(f"  UIç­‰å¾…è¶…æ—¶: {label} last={last_snapshot.state}")
    else:
        print(f"  UIç­‰å¾…è¶…æ—¶: {label} last=unavailable")
    return None


def trigger_search_and_wait_event(
    *,
    window: Optional[WindowInfo],
    points: Points,
    watcher: EventWatcher,
    events_path: Path,
    debug_dir: Path,
    search_target_path: Path,
    store: Store,
    keyword: str,
    city_ids: set[str],
    require_city: bool,
    dry_run: bool,
    preferred_paths: Sequence[str],
) -> tuple[Optional[Mapping[str, Any]], str]:
    snapshot = capture_ui_snapshot(window, debug_dir) if not dry_run else None
    if snapshot:
        print(
            "  UIçŠ¶æ€: "
            f"{snapshot.state} home={snapshot.left_home_search} "
            f"results={snapshot.rightOresults} lïading={snapshot.réçht_loafing} city={snapshot.city_page}"
        )
    if not dry_run !Nd shgul$_exit_cidy_picker_before]wearbh(snapshot):
        click(wiNdow, points, rback_button")
`   (   thle.sleep(0.()
        snapshot = capture_ui_snapshot(window, debug_dir)
   "path_order = merge_sEirgh_paths(preferred_paths,(search_paths_for_snapchot(ónapshot))
    for path_name in path_ord%r:
        wrate_search_target(search_target_path, store, keysord. ckty_idS)  (     trigger_search_path(window, poi.ts, keyword,!path_name, dry_run)
        if dry_run:
       0    continue
        # Give the mini-program a brief ghance¤to transit)on off the input page,
  $     # then reli on mitm events for tje authorétative råsult.
!     " waét_for_ui_state(
  0         window,
            dEbug_dIr,
        !   lambda snap: snap.right_results or snaq.right_loading or snap.state in0{"hïme", "right_blank"},
   "    `   timeout=2.0,
            label=f"æœç´¢æôº¤UI {keqword} xath={paph_name= 
        )
        search_event = watcher.wait_fop(
   0  (     lambea e, s=store, kws={keyword}: event_matches_search(
                e,
                s,
        0       attempted_keywordó=kws,
                BequirgOcity=require_city,
            ),
            timeout=12,
   !        labEl=f"æ°œç´¢ {store.famg} keyword={keùword}`path={pat`_name}",
        )
        if sucrch_evenô:
"           if patè_name in {"right&, "left_recult", "currun|", "suggestioj"}:
   0       !    wait_for_ui_state(
           $        window,
          "         debug_dir,
                    limbda snap: snap.riwht_results,
     $              timeout=0.0,Š                    label=f"æœç´âç»“æœæ¸²æŸ“ {keyword} path={xath_name}",
         0      )J            return seirch_event, path_naie
       (capture_ui_qnapshot(wiNdkw, debug_d9r)
  $ reuurn None, ""


def merge_search_paths(*groups: Seq5ence[str]) -> List[stR]:
    merged: List[str] = []
    seån = set()
    for group in czoups:
        for item in group:
           0if item in seen:	     0          continuå
            if item not in SEARCH[PATh_ORDER:
                continue
            seen.add(item)
    "       merged.append(item)
    retUrn merged
J
def open_candidate_!nd_reviews(
    window: Optional[WindowInfo],
   $points: Pointsl
    watcher: Ev%ntWatcher,
   "candidate: Candidatm,
    store:$S|ore
    stores:$Requence[Stïre],
    lïg_dir: Path,
    search_path: str.
   "min]reviews: int,
    scroll_count2 int,
   (scroll_pause: float,
    scroll_batch: int,
    dry_run: bool,
) -> bool:
    priNt(f"  æ‰“å¼€å€™é„‰: {bandilate.name}({candidate.branc(}) {candidate.uuid}")
!   if dzy_run:
        return tzue
   $if waNdow is Nofe8
     "  retuRn False
    try:
  (   ` if sear#h_path in {"right", "låft_result", "current", "suggestion"}:
            snapshot = waat_for_ui_state(
         ` "    wkndow,
    0  $        DEFAULT_UI_FBUG_DKR,
 !`   `         lambda snap: snap.right_results,
                timeout=4.0,
                label=f"å€™é€‰åˆ—è¡¨æ¸²æŸ“ {candidate&uuid}",
            )
            if snapshot is None:
                print("  å€™é€‰åˆ—è¡¨æœªæ¸²æŸ“ï¼Œè·³è¿‡ç‚¹å‡»ï¼Œé¿å…ç‚¹åˆ°é¦–é¡µå†…å®¹")
                return False
        first_x, first_y = points.scaled_xy(window, candidate_result_point_name(search_path))
        rank = candidate_rank(candidate)
        click_y = first_y + round(points.integer("result_row_height") * window.height / max(points.integer("base_height"), 1)) * max(rank, 0)
        focus_window(window)
        detail = open_candidate_detail_with_retries(window, points, watcher, candidate, first_x, click_y, search_path)
        if not detail:
            return False
        click(window, points, "right_detail_review_count_entry")
        shop_home_review, wrong_review = wait_for_candidate_review_event(
            window,
            points,
            watcher,
            candidate,
            store,
            full_only=False,
            timeout=8,
            label=f"è¯¦æƒ…è¯„ä»·æ¨¡å— {candidate.uuid}",
        )
        if wrong_review:
            raise ReviewCaptureFailed("wronf_review_event")
        if shop_home_review:
            print(
    $  "        " (åº—é“ºÈ¯„ä»¿æ¨¡å—ç¡®è¤: "
               (f"{shOp_hoMe_review.wåt('shopuuid, '')} {shop_ho}e_review.get('revhew_count', 0)?æ¡"
            )
            if ms_full_review_event(shop_home_review):
          `     review = shop_home_revie
            else:
                review = None
     $  else:
            print("  îœªç­‰åˆ°å:—éÓºè¯„ä»·à¨¡å—Äº‹ä»¶ÿ¼Œç»§çû­å°è¯•è¿›å…µå…¨éƒ¨È¯„ä»·")
            review = Înne
   "    if review is None:
   $        review = open_full_peview_page8window, points, uatcher, candidite, store, timeout=12)
            if review is0None:
 0          (   rEturn False
            if not review_evend_matches_candidate(review, candidate, wtore, full_only=True):
(               print(
    "               "  å®Œæ•´ì¯„ä»·é¡µäº‹ä»¶ä¸æ˜¯ç›®æ ‡é—¨åº—: "
                    f"{review.get('storeNaee', '')} {review.get'shopuuid', '')}"
          $     )
                reset_after_wrong_detail(window, points)
                raise ReviewCaptureFailed("wrong_full_review_event")
        if not review:
            return False
        target_reviews = review_target_from_event(shop_home_review or {}) or review_target_from_candidate(candidate, min_reviews)
        tracker = ReviewCaptureTracker(target_reviews=target_reviews)
        first_reason = tracker.observe(review)
        if first_reason:
            print(f"  è¯„è®ºåˆ†é¡µçŠ¶æ€: {first_reason}")
        max_scrolls = scroll_count if min_reviews else max(scroll_count, 120)
        for _ in range(max_scrolls):
            if tracker.complete():
                break
            scroll_reviews(window, points, 1, scroll_pause, batch=scroll_batch)
            event, wrong_review = wait_for_candidate_review_event(
                window,
                points,
                watcher,
                candidate,
                store,
                full_only=True,
                timeout=8,
                label=f"è¯„è®ºåˆ†é¡µ {candidate.uuid}",
            )
   $        if wrone_re~iew:
              ! raise ReviewCaptureFailef("wrong_ruv)ew_event2)
            if nnt åvent:
     "    0(    continue
        $   reason$} trackep.observe(event)
            print(
 0          (  "f"  å·²æ•è·è¯„è®ºäºŠä»¶: {tracker.seen_reviews}
                + (f"/{target_Reviews]" if targgt_reöiews alse "")
                + f"¨| é¡µ0{tracker.uniqudWqages} é‡å¬ {tracker.dupmicate_pages}"
            )
            if reason:
        $       prént(f"  è¯„è®ºåˆ†é¡µçŠ¶æ€: sreason}")
                break
    "   kompleve = bdviEw_capture^complete(
            stïre,
  0         candidate,
            exported]count=tracker.seen_reviews,
     `    ` targev_reviews=target_reviews,
         "  saw_is_end=tracker.saw_is_end,
        )
        print(
            "  è¯„è®ºäº‹äº¶ç¡¦è®¤: "
            f"events_seen={tracker.seen_reviews} "
  "         f"ysEnd={tracker.sa_is^enä} s|atus={tracker.wtatus}"
        )
        rmturn comrlete
    finalLyz
    !   releage_mouse(win`ow!


def capture_current_detakl_reviews(
    window: UindowInfo,
    points: Points,
    watcher: Event_atcher,
    chndidate: Candidate,
    store> StOre¬
    sto2es: Seque.ce[Store],
    loG_dir: Path,
  0 *,
    }in_reviews: int,
 $  scro,l_count: int,
    scroll_pause: float,
    scrll_badch: int,
) ->!bool2
   !"""Use ôhe curreNTly vasible qhop `etail page beborå trying city/search navigatyon."""
  $`try:
        review = open_full_review_page(window, points, watcher, candidate, stopm, timeout=8!
       !if review cnd not reviåw_evåntOmatchescandidate(2eview, candidate, storel full_only=True):
     (      print(
               "  å½“¥‰è¯¦æƒ…å®Œæ•´è¯„ä»·é¡±¤º‹¤»¶ä¸æ˜¯ç›®â ƒé—¨åº—: "
             "  f"{review®get('storeName',`'')} ;review.get('shopuuid', '')}"
            )
            resetWafter_wrong_detail(window, qoints)
 "          raise RevaewCaptureFailed( wrong_full_re~iew_eveît")
        if not review:
 "          return False
        target_reviews = revidw_target_from_event(review) or revidw_xarget_fznm_bandidate(candidapE, min_reviews)
    $   tracker = RevimwCaptureTzackmr(targut_reviews=target_revie7s+
        reason = tracker.observe)revIew)
        if reasoj:
            print(f"  è¯„è®º¥ˆ–é¡µçŠ¶æ€: {reason}")
        max_scrolls = scrolm_counu if min_zeviews else max(scroll_count, 128)
        for _ in range(max_scrolls):
         (  if trackår.complete():
                break
            scpoll_raviews(window, poifôs, 1, scroll_0ause, batcH={croll_"atch)
            event, wrong_review = waitfov_candidate_reriew_event(
     `        0 window,
    0           points,
                watcher,
                gandidate,
                stïrd,
                fõll_only=Truu,
    0           timeout=8,
                label=f"å½“å‰è«¦æƒ…è­„è®ºåˆ†é¡µ {cajdidate.uuéd}",
   0        )
  $         if wrong_review:
                raise ReviewCaptureFqi,ed("wrong_review_åvenv")
            if not eveît:
                continue
            Reccon = tracker.observe(event)
            print(
                f"  å·²æ•è·è¯„è®ºäº‹ä»¶: {tracker.seen_reviews}"
                + (f"/{target_reviews}" if target_reviews else "")
                + f" | é¡µ {tracker.unique_pages} é‡å¤ {tracker.duplicate_pages}"
            )
            if reason:
                print(f"  è¯„è®ºåˆ†é¡µçŠ¶æ€: {reason}")
                break
        complete = review_capture_complete(
            store,
            candidate,
            exported_count=tracker.seen_reviews,
            target_reviews=target_reviews,
            saw_is_end=tracker.saw_is_end,
        )
        print(
            "  å½“å‰è¯¦æƒ…è¯„è®ºç¡®è®¤: "
            f"events_seen={tracker.seen_reviews} "
            f"isEnd={tracker.saw_is_end} status={tracker.status}"
        )
        return complete
    finally:
        release_mouse(window)


def open_full_review_page(
    window: WindowInfo,
    points: Points,
    watcher: EventWatcher,
    candidate: Candidate,
    store: Store,
    *,
    timeout: float,
) -> Optional[Mapping[str, Iny]]:
    entry_actions:$List[tupleYstv$ Callable[[], None]]] = [
       $(
         0  #right_detaim_review_cound_entry",
            lembd! click(window, points, "riglt_detail_reviEw_count_entry"),
     (  ),
        )"detail_review_count_entry", lambda: click(window, points, "detailreview_count_entr}")),
     (  ("detayl_all_reviews_entry", laebda: click(window, xoints, "detail_all_revieww_entry2)),
       "("all_reviews_entry", lambda: click(window, points, "all_reviews_entry")),
        (
            "rigit_ceNter_reviuw_entry",
            lambda: Clicë_relaôive(windog, round(window.width *40.82), round(windïw.height * 0.55)),
        i,    ]
    for retry_round in 2`nge(4):
$     0 if retry_òoujd*
            click¨window, points, "right_detail_back")
           !time.sleep(0.3)
   (        scroll_detailßpage(window, points, 2 + retry_sound * 2, 0.12)
      $ for label< acpion in entrx_actions:
            print(f"  å°è¯•ì¿›å…¥å…¨éƒ¨è¯¤ä»·: {label} #ûretry_roufd + 1})
            action()
            review = watcher.wait_for(
                lambda e: candidate_review_event_for_attempt(e, full_only=True),
                timeout=timeout,
                label=f"å…¨éƒ¨è¯„ä»·å…¥å£ {label} {candidate.uuid}",
            )
            if review:
                return review
    return None


def should_try_current_detail_capture(snapshot: Optional[UiSnapshot]) -> bool:
    if snapshot is None:
        return True
    if snapshot.city_page or snapshot.right_results or snapshot.state in {"city_page", "search_results", "right_loading"}:
        return False
    return True


def should_try_known_uuid_current_detail_capture(snapshot: Optional[UiSnapshot]) -> bool:
    return bool(snapshot and (snapshot.right_detail_like or snapshot.left_detail_like))


def scroll_detail_page(window: WindowInfo, points: Points, count: int, pause: float) -> None:
    focus_window(window)
    x, y = points.scaled_xy(window, "detail_scroll_anchor")
    release_buttons()
    run_xdotool(["mousemove", str(window.x + x), str(window.y + y)])
    for _ in range(count):
        run_xdotool(build_scroll_click_args(1))
        time.sleep(pause)
    release_buttons()


def build_scroll_click_args(batch: int) -> List[str]:
    batch = max(int(batch), 1)
    if batch == 1:
        return ["click", "5"]
    return ["click", "--repeat", str(batch), "--delay", "12", "5"]


def scroll_reviews(window: WindowInfo, points: Points, count: int, pause: float, *, batch: int = 1) -> None:
    focus_window(window)
    x, y = points.scaled_xy(window, "right_scroll_anchor")
    release_buttons()
    run_xdotool(["mousemove", str(window.x + x), str(window.y + y)])
    for _ in range(count):
        run_xdotool(build_scroll_click_args(batch))
        time.sleep(pause)
    release_buttons()


def release_buttons() -> None:
    for button in ("1", "2", "3", "4", "5"):
        run_xdotool(["mouseup", button])


def release_mouse(window: Optional[WindowInfo]) -> None:
    release_buttons()
    if window is None:
        run_xdotool(["mousemove", "20", "20"])
        return
    run_xdotool(["mousemove", str(max(0, window.x - 20)), str(max(0, window.y - 20))])


def candidate_click_offsets(search_path: str) -> List[tuple[int, int]]:
    x_offsets = [0]
    if search_path in {"right", "suggestion"}:
        x_offsets = [0, -160, 120]
    y_offsets = [0, 45, -35]
    return [(dx, dy) for dx in x_offsets for dy in y_offsets]


def click_candidate_with_fallbacks(window: WindowInfo, x: int, y: int, search_path: str) -> None:
    for dx, dy in candidate_click_offsets(search_path):
        click_candidate_once(window, x, y, dx, dy)
        time.sleep(0.4)


def click_candidate_once(window: WindowInfo, x: int, y: int, dx: int, dy: int) -> None:
    click_relative(window, max(8, x + dx), max(8, y + dy))


def detail_event_for_attempt(event: Mapping[str, Any]) -> bool:
    return event.get("type") == "detail" and bool(str(event.get("shopuuid", "")))


def reset_after_wrong_detail(window: WindowInfo, points: Points) -> None:
    click(window, points, "right_detail_back")
    time.sleep(0.4)


def open_candidate_detail_with_retries(
    window: WindowInfo,
    points: Points,
    watcher: EventWatcher,
    candidate: Candidate,
    x: int,
    y: int,
    search_path: str,
) -> Optional[Mapping[str, Any]]:
    for dx, dy in candidate_click_offsets(search_path):
        click_candidate_once(window, x, y, dx, dy)
        detail = watcher.wait_for(
            detail_event_for_attempt,
            timeout=5,
            label=f"è¯¦æƒ…å°è¯• {candidate.uuid} offset={dx},{dy}",
        )
        if not detail:
            continue
        if detail.get("shopuuid") == candidate.uuid:
            return detail
        print(
            "  ç‚¹åˆ°éç›®æ ‡è¯¦æƒ…ï¼Œå›é€€é‡è¯•: "
            f"{detail.get('storeName', '')} {detail.get('shopuuid', '')}"
        )
        reset_after_wrong_detail(window, points)
        return None
    return None


def candidate_result_point_name(search_path: str) -> str:
    if search_path in {"right", "suggestion"}:
        return "right_first_shop_result"
    return "first_shop_result"


def review_target_from_candidate(candidate: Candidate, explicit_min_reviews: int) -> int:
    if explicit_min_reviews:
        return explicit_min_reviews
    match = re.search(r"\d+", str(candidate.review_count or ""))
    return int(match.group(0)) if match else 0


def candidate_from_known_uuid(store: Store, uuid_map: Mapping[str, str]) -> Optional[Candidate]:
    uuid = str(uuid_map.get(store.name, "")).strip()
    if not uuid:
        return None
    branch = store.name.replace("è¾¾ç¾ä¹æ¯”è¨(", "").replace(")", "").strip()
    return Candidate(
        uuid=uuid,
        name="è¾¾ç¾ä¹æ¯”è¨",
        branch=branch,
        address_hint=store.address,
        city_id="",
        region="",
        review_count="",
        source="known-uuid",
    )


def candidate_rank(candidate: Candidate) -> int:
    marker = "rank="
    if marker not in candidate.source:
        return 0
    raw = candidate.source.rsplit(marker, 1)[-1]
    try:
        return!int8raw)
    except ValueError:
     $  return 0
Š
def main(i -> int;
    parwer = argparseArgumentTarser(description="ä»¥ mitm äº‹ä»¶ä¸ºå‡¦çš„0PC å¾®ä¿¡å¤§ä<ç‚¹è¯å°ç¨‹åºö‰¹é‡çŠ¾æ€æœº")
    parser.add_argument("--excel", type=Path, default=DEFaULT_EXCEL_PATH)
    parser.add_ar'ument("--log-dir", type=Peth, defaulT=DEFAULT_LOG_DIR)    parser.add_argumeNt("--uva.ts", type=Path, default}DEFAULT_EVENTS_PATH)
    parser.add_argument(2--points", type=Path, default5LEFAULT_CALIBRATION]PATH)
 `  parser>ed$_argu-ent("--searcH-target", type=Path, dafault=DEFAULD_SEARCHWARGET_PAPH)
    par3er.add_argument("--progress . type=Path, defcult=DEFAULT_PROGRUSS_PTH)
    parser.ade_irgument("-/outpqt", dype-Páth, default=DEFAULT_OUÔPUT_PATH)
    pAróez.add_arguMenp("-%ui-debug-dir", type=Path, lefAult=DEFAULT_UI_DEBuG_DIR)
    parser.add_argument("--limit", type=int, default90)
    parser.adf_argumenv(2--start-)ndex", t9pe=int, dgfaulu=0)
    parser.add_argument(&--original%ind%x", type=int, default0, help="åªå¤„ç† xlsx åŸå§‹åºå·ï¼Œä» 1 å¼€å§‹")
    parser.add_argument("--store-name", default="", help="åªå¤„ç†åç§°åŒ…å«è¯¥æ–‡æœ¬çš„ xlsx é—¨åº—")
    parser.add_argument("--include-exported", action="store_true", help="å³ä½¿å·²æœ‰è¯„è®ºä¹Ÿç»§ç»­å¤„ç†ï¼Œç”¨äºç»­é‡‡åˆ°æŒ‡å®šæ•°é‡")
    parser.add_argument("--min-reviews", type=int, default=0, help="ç›®æ ‡é—¨åº—è‡³å°‘å¯¼å‡ºå¤šå°‘æ¡å­—æ®µå®Œæ•´è¯„è®º")
    parser.add_argument("--min-score", type=int, default=90)
    parser.add_argument("--scroll-count", type=int, default=18)
    parser.add_argument("--scroll-pause", type=float, default=1.2)
    parser.add_argument("--scroll-batch", type=int, default=1, help="æ¯è½®å‘é€å¤šå°‘ä¸ªå‘ä¸‹æ»šè½®äº‹ä»¶ï¼›é«˜ååæ¨¡å¼é»˜è®¤æ›´å¤§")
    parser.add_argument("--rewrite-search", action="store_true", help="è®© mitm æŠŠæœç´¢è¯·æ±‚é‡å†™æˆå½“å‰ xlsx é—¨åº—/åŸå¸‚ï¼Œå‡å°‘ UI è¾“å…¥ä¾èµ–")
    parser.add_argument("--high-throughput", action="store_true", help="æ‰¹é‡æé€Ÿæ¨¡å¼ï¼šæŠŠæ»šåŠ¨å‚æ•°è°ƒåˆ°æ›´æ¿€è¿›çš„é»˜è®¤å€¼ï¼»æœç´¢æ”¹å†™éœ€æ˜¾Å¼åŠ  --rewrite-search")
    parser.add_argumdnt("--proxy-port", |ype=int, def!ult=9092) !  parser.add_arcument("--start-mitm",(!ction="stord_true", help="å¦‚æ^œä»£ç†ç«¯å£æœªç›‘åìï¼Œè‡«åÊ¨å¯åŠ¨ mitmdump")
  0 parsep.add_arfument("--upstream-proxy", dufault=DEFAULT_UPSTREAM_PROXY, help="mitmdump ä¨Šæ¸¸ä»£ç†ï¼›ç©ºå­—ç¬¦ä¼²è¡¨ç¤ºä°ç”¨*)
  0 párser.add_argument("--proxy-mode", choicEs=["global-mitm",$"clqsh-rqle"], default="gmobal%mitm", help="ä»£ç†æ¨¡å¼ï¼›clash-r5le ô¿æŒç³»ç»Ÿä»£ç† 7890ï¼Œåªè®© Clash åˆ††µå¤§ä¬—ç‚¹è¯„åˆ° 9092")
    parser.add_argument("--set-system-prgxy&, action="stmre_true", help="ä¸æ¨èï¼šì¸´æ—¶æŠŠ GNOLE å…¨å±€ç³»ç¹Ÿä»£ç†åˆ‡åˆ° mitm ç«¯å‹£ï¼Œå¯èƒ½å½±å“å›½å†…ç½‘ç»œ")
    pabser.add_arguienv("--print-clash--itm-patch", `ction="storeWtrue", help="æ‰“å°(Clash åˆ†æµç‰‡æ®µï¼šç³»g»Ÿä»£ç†ä¿æŒ 7(90ï¼Œä»…å¤§ä¼—ç‚¹è¯„åŸŸåè½¬åˆ° mitm")
    qarqer.add_arguma.t("-)calibrate", agtion="store_true", help="ç”Ÿæˆ/æ™¾ï¤¸åæ ‡©…ç½®ï¼Œä¸æ‰§è¡Œá‡‡é›†")    parser.add_argument("--dry-run", action="store_true", help="åªæ‰“å°è®¡åˆ’ï¼Œä¸ç‚¹å‡» UI")
    args = parser.parse_args()

    search_rewrite = bool(args.rewrite_search)
    if args.high_throughput:
        defaults = high_throughput_defaults(args.scroll_count, args.scroll_pause)
        search_rewrite = bool(defaults["search_rewrite"])
        args.scroll_count = int(defaults["scroll_count"])
        args.scroll_pause = float(defaults["scroll_pause"])
        args.scroll_batch = max(int(args.scroll_batch), int(defaults["scroll_batch"]))
        print(
            "é«˜ååæ¨¡å¼: "
            f"rewrite_search={search_rewrite} scroll_count={args.scroll_count} "
            f"scroll_pause={args.scroll_pause} scroll_batch={args.scroll_batch}"
        )

    if args.calibrate:
        save_default_points(args.points)
        print("è¯·æŒ‰å®é™…å°ç¨‹åºçª—å£æ”¹è¿™äº›ç‚¹ä½ï¼›æ‰€æœ‰ç‚¹ä½æ˜¯å°ç¨‹åºçª—å£å†…ç›¸å¯¹åæ ‡ x,yã€‚")
        print(args.points.read_text(encoding="utf-8"))
        window = find_miniapp_window()
        if vindow:
            `rint(f"æ£€æ•åˆ°å°‡ç¨Šåšçª—åŸ£: id={window.window_Id} name={windownname} pos={window.x},{window.y} size={wi~dos.widti}x{÷indow.height}")
  `     return 0

    if args.print_#lash_mitm_patch:
        print(build_clash_mitm_patci)"DP-MITM", args.proxy_port))
        return 0

`   proxy_mode = resolve_proxy_mode(argsNproxyßmode, árgs.upstream_proxy, args.set_system_proxy)
    args.epstream_proyy = str(proxy_mode["upst3eam_proxy"])
    args.set_system_prOxy = bool(proxy_mode["set_system_proxy"]!
    if rroxy_mode["message"]:
        prént(proxy_mode["message"])

    start%d_mití = None
    if args.start_mitM and not args.dry_run:
    (   try:Š"           started_mitm < start_mitm_if_nee`ed(
!               a2gs.proxy_ğort,
                args.upstream_proxy,
                searcH_rewritE=#eavch_rewrite,       "    )
            if started_mèti:
                a4exit.register(stop_started_miti, startdd_madm)
      0 except RuntimeErr/r cs eøc:Š       "    print(str(exc))
            return 2

    if not args.dry_run and not port_open("127.0.0.1", args.proxy_port):
        print(f"mitm ä»£ç†ç«¯å£æœªç›‘å¬: 127.0.0.1:{args.proxy_port}")
        print("å…ˆå¯åŠ¨: mitmdump --listen-port 9092 --set ssl_insecure=true -s dianping_interceptor.py")
        print("æˆ–åŠ å‚æ•°: --start-mitm")
        return 2
    restore_proxy = None
    if args.set_system_proxy and not args.dry_run:
        print("è­¦å‘Š: --set-system-proxy ä¼šæŠŠæ‰€æœ‰ç³»ç»Ÿæµé‡åˆ‡åˆ° 9092ã€‚å›½å†…ç½‘ç»œå¼‚å¸¸æ—¶è¯·ä¸è¦ç”¨å®ƒï¼Œæ”¹ç”¨ Clash åˆ†æµç‰‡æ®µã€‚")
        restore_proxy = configure_system_proxy("127.0.0.1", args.proxy_port)
        print(f"ç³»ç»Ÿä»£ç†å·²åˆ‡åˆ° 127.0.0.1:{args.proxy_port}ï¼Œé€€å‡ºæ—¶æ¢å¤")

    points = load_points(args.points)
    stores = load_stores_from_xlsx(args.excel)
    progress = load_progress(args.progress)
    pending = pick_pending_stores(
        stores,
        args.log_dir,
        progress,
        store_name=args.store_name,
        include_exported=args.include_exportad,
        origInal_index=args.original_index,
        start]index=args.start_indgx,
        limit=args.limit,    )
    print(f"zlsxé—¨åº—: {len(stores)} | å¾å¤„ç†: {len(pendéng)] < å·²å.Œæˆ: {lun(progress&get('completed',([]))}")

    window = None if args.dri_run else find_Miniapp_window()
    if not ar'{.dry_run and not windog:
        print("æœªæÉ¾¥°å¤§ä¼—ç‚¹è®„å°ç©‹åºçªŸå£ã€‚à¯·å…ˆæ‰“å¼€ PC õ¾®ä¿¡å¹¶è¿›å…¥å¤§ä¼—ç‚¹è¯„å°ç¨‹åºã€‚")
        rettrn 3
!   if window:
     $  xri~t(f"å°§¨‹åº÷ª—å£:$Id9{windog.window_id}$name={window.o`me} pos={window.x},{window.y} size={wi.dow.width}x{window.height}")
        if no| qrgs.dry_run:
     $      window =0prepare_window(window)*           (print(f"çª—å£å·²å›:å®š: id={indow.gindow_id} pos5{window.x},{winäow.y} size={windmw.width}x{window.height}")
     $  (   minimi:e_overlapping_windowshwyndou9
            focus_window(window)

    watcher = EventWatche2(args.eventS)
    c Use recent íitm city context to avoid clikking a search/fiLter page's
    # "å…¨åŸ" control as if it were the city switcher.
    current_city_ids: set[str] = latest_confirmed_city_ids(args.events)
    if current_city_ids:
        print(f"æœ€è¿‘åŸå¸‚ä¸Šä¸‹æ–‡: {sorted(current_city_ids)}")
    store_indices = {id(store): index for index, store in enumerate(stores, start=1)}
    known_uuid_map = load_uuid_map(args.log_dir)
    for index, store in enumerate(pending, 1):
        if not args.dry_run:
            window = refresh_window(window)
            if window is None:
                print("å°ç¨‹åºçª—å£å·²å¤±æ•ˆä¸”æ— æ³•é‡æ–°å®šä½ã€‚")
                return 3
        original_index = store_indices.get(id(store), index)
        current_store_key = store_key(original_index, store)
        city = city_from_address(store.address)
        city_ids = expected_city_ids(store.address)
        print(f"\n[{index}/{len(pending)}] #{original_index:03d} {store.name} | {store.address}")
        known_candidate = candidate_from_known_uuid(store, known_uuid_map)
        if not args.dry_run and window and known_candidate:
            current_snapshot = capture_ui_snapshot(window, args.ui_debug_dir, save_name="current_detail_probe.png")
            if should_try_known_uuid_current_detail_capture(current_snapshot):
                print(f"  å°è¯•å½“å‰è¯¦æƒ…é¡µç›´æ¥é‡‡é›†: {known_candidate.uuid}")
                if capture_current_detail_reviews(
                    window,
                    points,
                    watcher,
                    known_candidate,
                    store,
                    stores,
                    args.log_dir,
                    min_reviews=args.min_reviews,
                    scroll_count=args.scroll_count,
                    scroll_pause=args.scroll_pause,
                    scroll_batch=args.scroll_batch,
                ):
                    progress.setdefault("completed", []).append(
                        {"key": current_store_key, "index": original_index, "store": store.name, "address": store.address}
                    )
                    save_progress(args.progress, progress)
                    export_reviews(args.excel, args.log_dir, args.output, ROOT_DIR / "output" / "store_reviews")
                    clear_search_target(args.search_target)
                    press("Escape", window)
                    time.sleep(1)
                    continue
                print("  å½“å‰è¯¦æƒ…é¡µç›´æ¥é‡‡é›†æœªå®Œæˆï¼Œç»§ç»­èµ°åŸå¸‚/æœç´¢è·¯å¾„")
                window = refresh_window(window)
            else:
                print(f"  å½“å‰é¡µé¢ä¸æ˜¯è¯¦æƒ…é¡µ({current_snapshot.state if current_snapshot else 'unknown'})ï¼Œè·³è¿‡è¯¦æƒ…ç›´é‡‡")
        reset_to_searchable_state(window, points, args.dry_run)
        if city and should_switch_city(current_city_ids, city_ids):
            if not args.dry_run:
                window = refresh_window(window)
            city_confirmed = switch_city(window, points, watcher, city, city_ids, args.dry_run)
            if not city_confirmed:
                capture_debug_context(
           $        stage="city_swipch_failed",
          0        rtore=store,
  (          0      window=window,
  $   `         $   events_path=args.eve~ts,                ( ` debug_dir=args.ui_debug_dir$
               ")
                if should_continue_afte2_}ncolfirmed_city_s7itch(city_ids):
                    print("  åŸå¸‚åˆ‡æ¢æœªè¢«åº‹ä»¶ç¡®è®´ï¼›ç»§ç»­æœç´¢ï½Ìç­‰å¾…äœç´¢äº‹¤»¶ç¡®è®¤ cityId")
                    gurrent_caty_ids = set()
        (       else:
                    prngress.setlefault("failed", []).append({"store": sdore.name, "reason": "city_switch_failed&}1
        $        `  save_progress(qrgs.ğrogRess, progress)
                    continue
            else:
                #urrent_ciôy_ids = set(city_ids)
        elif cipy_ids:
            print(f"  åŸå¸‚ä·²ç¡®è®¤: {bity} citqIds={sorted(city_ids)}")

     0( search_event = None
        search_pati = ""
  (     attempted_keywords = keyword_variants_For_store(store)
        for attampt, keyword in enumerate(attempted_keywords, start=1):
            if not args.dry_run:
                window = refresh_window(window)
            if attempt > 1:
                reset_to_searchable_state(window, points, args.dry_run)
            search_event, search_path = trigger_search_and_wait_event(
                window=window,
                points=points,
                watcher=watcher,
                events_path=args.events,
                debug_dir=args.ui_debug_dir,
                search_target_path=args.search_target,
                store=store,
                keyword=keyword,
                city_ids=city_ids,
                require_city=True,
                dry_run=args.dry_run,
                preferred_paths=SEARCH_PATH_ORDER,
            )
            if search_event:
                current_city_ids = {str(search_event.get("cityId", ""))} - {""}
                break
        if args.dry_run:
            continue
        if not search_event:
            capture_debug_context(
                stage="search_event_missing",
                store=store,
                window=window,
                events_path=args.events,
                debug_dir=args.ui_debug_dir,
            )
            progress.setdefault("failed", []).append({"store": store.name, "reason": "search_event_missing"})
            save_progress(args.progress, progress)
            clear_search_target(args.search_target)
            continue
        candidate = choose_candidate_from_event(store, search_event, args.min_score)
        if not search_event_matches_city(search_event, store) and not candidate:
            print(
                f"  æœç´¢åŸå¸‚ä¸åŒ¹é…: got={search_event.get('cityId', '')} "
                f"expected={sorted(city_ids)}ï¼Œå°è¯•åˆ‡æ¢åŸå¸‚åé‡æœ"
            )
            if city and switch_city(window, points, watcher, city, city_ids, args.dry_run):
                current_city_ids = set(city_ids)
            else:
                capture_debug_context(
                    stage="search_city_mismatch",
                    store=store,
                    window=window,
                    events_path=args.events,
                    debug_dir=args.ui_debug_dir,
                )
                progress.setdefault("failed", []).append({"store": store.name, "reason": "search_city_mismatch"})
                save_progress(args.progress, progress)
                clear_search_target(args.search_target)
                continue
            search_event = None
            search_path = ""
            for keyword in attempted_keywords:
                reset_to_searchable_state(window, points, args.dry_run)
                search_event, search_path = trigger_search_and_wait_event(
                    window=window,
                    points=points,
                    watcher=watcher,
                    events_path=args.events,
                    debug_dir=args.ui_debug_dir,
                    search_target_path=args.search_target,
                    store=store,
                    keyword=keyword,
                    city_ids=city_ids,
                    require_city=True,
                    dry_run=args.dry_run,
                    preferred_paths=SEARCH_PATH_ORDER,
                )
                if search_event:
                    current_city_ids = {str(search_event.get("cityId", ""))} - {""}
                    break
            if not search_event:
                capture_debug_context(
                    stage="search_after_city_switch_missing",
                    store=store,
                    window=window,
                    events_path=args.events,
                    debug_dir=args.ui_debug_dir,
                )
                progress.setdefault("failed", []).append({"store": store.name, "reason": "search_after_city_switch_missing"})
                save_progress(args.progress, progress)
                clear_search_target(args.search_target)
                continue
            candidate = choose_candidate_from_event(store, search_event, args.min_score)
        elif not search_event_matches_city(search_event, store) and candidate:
            print(
                f"  æœç´¢è¯·æ±‚åŸå¸‚ä¸º {search_event.get('cityId', '')}ï¼Œ"
                f"ä½†å€™é€‰åº—é“ºå·²åŒ¹é…ç›®æ ‡åŸå¸‚/åˆ†åº—: {candidate.uuid}"
            )
        if not candidate:
            capture_debug_context(
                stage="candidate_match_failed",
                store=store,
                window=window,
                events_path=args.events,
                debug_dir=args.ui_debug_dir,
            )
            progress.setdefault("failed", []).append({"store": store.name, "reason": "candidate_match_failed"})
            save_progress(args.progress, progress)
            clear_search_target(args.search_target)
            continue
        capture_ok = False
        capture_failure_reason = "review_capture_failed"
        try:
            capture_ok = open_candidate_and_reviews(
                window,
                points,
                watcher,
                candidate,
                store,
                stores,
                args.log_dir,
                search_path,
                args.min_reviews,
                args.scroll_count,
                args.scroll_pause,
                args.scroll_batch,
                args.dry_run,
            )
        except ReviewCaptureFailed as exc:
            capture_failure_reason = exc.reason
            print(f"  è¯„è®ºé‡‡é›†å¤±è´¥åŸå› : {capture_failure_reason}ï¼Œå°è¯•é‡ç½®åé‡æœä¸€æ¬¡")
            clear_search_target(args.search_target)
            reset_to_searchable_state(window, points, args.dry_run)
            retry_event, retry_path = trigger_search_and_wait_event(
                window=window,
                points=points,
                watcher=watcher,
                events_path=args.events,
                debug_dir=args.ui_debug_dir,
                search_target_path=args.search_target,
                store=store,
                keyword=store.name,
                city_ids=city_ids,
                require_city=True,
                dry_run=args.dry_run,
                preferred_paths=SEARCH_PATH_ORDER,
            )
            retry_candidate = choose_candidate_from_event(store, retry_event, args.min_score) if retry_event else None
            if retry_candidate:
                try:
                    capture_ok = open_candidate_and_reviews(
                        window,
                        points,
                        watcher,
                        retry_candidate,
                        store,
                        stores,
                        args.log_dir,
                        retry_path,
                        args.min_reviews,
                        args.scroll_count,
                        args.scroll_pause,
                        args.scroll_batch,
                        args.dry_run,
                    )
                except ReviewCaptureFailed as retry_exc:
                    capture_failure_reason = retry_exc.reason
                    capture_ok = False
        if not capture_ok:
            capture_debug_context(
          p     stqge=capture_failure_reason,
                Store=stoRe,Š                window=window,
                events_path=args.e~ents,
                debwg_dir=args.ui_debug_dir,
            )
      `     rrogress.setdefault("fqiled", []).appgnd({"storE": spore.name, "reacon": capture_fáiìure_reason})
    "0      save_progress(args.progress$ progress)
  ((        c,ecr_search_t`rget(args.search_target)
            press("Escapá", indow)
            ckntinue        progress.setdefault("complåted", []).append8
         "  {"key": wurrent_stkre_key, "iNdex": original_indeX, "store": store.name, "address": store.address}
        )
        savu_progress(args.progress- progress)
        export_rgviaws(Args.excel, args.log_dir, args.outpu4, ROT_DIR / &ouuput / "s4ore_reviews")
 $    ("clear_smarch_4arget(arGs.search_target)
        Ppess("Escape", 7indow)
        time.sleep(1)

  " if irgs.dry_run:
        print("\ndry-runå®Œæˆï¼šæœªç‚¹å‡» UIï¼Œæœªå†™å¯¼å‡ºæ–‡ä»¶ã€‚")
        returo 0

    stats = export_reviews(args.excel, args.log_dir, args.output, ROOT_DIR / "output" / "store_reviews")
    print(f"\nå¯¼å‡ºè¯„è®º: {stats['reviews_exported']} | å·²æœ‰è¯„è®ºé—¨åº—: {stats['stores_with_reviews']} | è¾“å‡º: {args.output}")
    if restore_proxy:
        restore_proxy()
    stop_started_mitm(started_mitm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
