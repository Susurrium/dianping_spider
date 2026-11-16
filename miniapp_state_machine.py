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
DEFAULT_EXCEL_PATH = ROOT_DIR / "达美乐_门店.xlsx"
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
    duplicate_limit: int = 6
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
                return f"重复页 {self.duplicate_pages} 次，停止当前店"
        else:
            self.pages_seen.add(page_key)
            self.unique_pages += 1
            self.seen_reviews += int(event.get("review_count") or 0)

        current_start = event_start(event)
        if current_start is not None:
            if self.highest_start >= 0 and current_start < self.highest_start:
                self.status = "stalled"
                return f"分页回退 {self.highest_start}->{current_start}，停止当前店"
            self.highest_start = max(self.highest_start, current_start)

        if event.get("isEnd") is True:
            self.saw_is_end = True
            self.status = "complete"
            return "isEnd=true，评论已到底"
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
        print(f"校准文件已存在: {path}")
        return
    path.write_text(json.dumps(asdict(Points()), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成校准文件: {path}")


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
        print(f"  调试快照: {summary_path}")
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
    print(f"  调试快照: {summary_path}" + (f" | {screenshot_path}" if screenshot_path.exists() else ""))


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


def classify_ui_snapshot(screenshot_path: Path) -> Optional[UiSnapshot]:
    """Analyze a screenshot and classify the current UI state."""
    try:
        from PIL import Image
        img = Image.open(screenshot_path)
    except Exception:
        return None
    w, h = img.size
    # Define analysis regions (proportional to window size)
    left_search_box = (int(w * 0.05), int(h * 0.10), int(w * 0.42), int(h * 0.30))
    right_loading_box = (int(w * 0.55), int(h * 0.10), int(w * 0.95), int(h * 0.30))
    right_results_box = (int(w * 0.55), int(h * 0.35), int(w * 0.95), int(h * 0.90))
    right_center_box = (int(w * 0.60), int(h * 0.40), int(w * 0.90), int(h * 0.60))
    right_tab_box = (int(w * 0.55), int(h * 0.05), int(w * 0.95), int(h * 0.15))
    city_header_box = (int(w * 0.30), int(h * 0.05), int(w * 0.70), int(h * 0.20))
    left_detail_box = (int(w * 0.05), int(h * 0.15), int(w * 0.45), int(h * 0.90))
    right_detail_box = (int(w * 0.55), int(h * 0.15), int(w * 0.95), int(h * 0.90))
    search_btn_box = (int(w * 0.10), int(h * 0.15), int(w * 0.40), int(h * 0.25))

    left_search_orange = orange_ratio(img, left_search_box)
    right_loading_orange = orange_ratio(img, right_loading_box)
    right_results_orange = orange_ratio(img, right_results_box)
    right_center_orange = orange_ratio(img, right_center_box)
    right_tab_orange = orange_ratio(img, right_tab_box)
    city_orange = orange_ratio(img, city_header_box)
    right_white = white_ratio(img, right_results_box)
    right_gray = gray_ratio(img, right_results_box)

    left_home_search = left_search_orange > 0.12
    right_loading = right_loading_orange > 0.15
    right_results = right_results_orange > 0.08
    right_blank = right_white > 0.80 and right_results_orange < 0.02
    city_page = city_orange > 0.15
    left_detail = orange_ratio(img, left_detail_box) > 0.01
    right_detail = orange_ratio(img, right_detail_box) > 0.08
    # Taxi modal overlay: right side gray/white but left still shows detail
    left_has_content = left_detail or left_search_orange > 0.03
    taxi_modal = right_gray > 0.40 and right_white > 0.30 and left_has_content and not right_results

    # Determine primary state
    if taxi_modal:
        state = "detail"
    elif city_page and not left_detail:
        state = "city_page"
    elif right_detail or left_detail:
        state = "detail"
    elif right_results:
        state = "search_results"
    elif left_home_search:
        state = "home"
    elif right_loading:
        state = "right_loading"
    elif right_blank and not left_detail:
        state = "right_blank"
    else:
        state = "home"

    return UiSnapshot(
        state=state,
        width=w,
        height=h,
        left_home_search=left_home_search,
        right_loading=right_loading,
        right_results=right_results,
        right_blank=right_blank,
        city_page=city_page,
        left_detail_like=left_detail,
        right_detail_like=right_detail,
        search_button_orange=round(left_search_orange, 4),
        right_tab_orange=round(right_tab_orange, 4),
        right_center_orange=round(right_center_orange, 4),
        right_white=round(right_white, 4),
        right_gray=round(right_gray, 4),
    )

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


def gray_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:
    return color_ratio(img, box, lambda r, g, b: abs(r - g) < 10 and abs(g - b) < 10 and 17 <= r <= 245)
def rel_box(width: int, height: int, x1: float, y1: float, x2: float, y2: float) -> Tuple[int, int, int, int]:
    return (
        max(0, min(width, round(width * x1))),
        max(0, min(height, round(height * y1))),
        max(0, min(width, round(width * x2))),
        max(0, min(height, round(height * y2))),
    )


def orange_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:
    return color_ratio(img, box, lambda r, g, b: r > 220 and 60 <= g <= 175 and b < 150)

def white_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:
    return color_ratio(img, box, lambda r, g, b: r > 245 and g > 245 and b > 245)


def gray_ratio(img: Any, box: Tuple[int, int, int, int]) -> float:
    return color_ratio(img, box, lambda r, g, b: abs(r - g) < 10 and abs(g - b) < 10 and 17 <= r <= 245)
def color_ratio(img: Any, box: Tuple[int, int, int, int], predicate: Callable[[int, int, int], bool]) -> float:
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return 0.0
    crop = img.crop((x1, y1, x2, y2)).resize((64, 64))
    pixels = list(crop.getdata())
    if not pixels:
        return 0.0
    return sum(1 for r, g, b in pixels if predicate(r, g, b)) / len(pixels)
def search_paths_for_snapshot(snapshot: Optional[UiSnapshot]) -> List[str]:
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
    return list(SEARCH_PATH_ORDER)
def should_open_right_search_panel(snapshot: Optional[UiSnapshot]) -> bool:
    if snapshot is None:
        return False
    if snapshot.city_page or snapshot.can_search_from_results:
        return False
    return snapshot.can_search_from_home or snapshot.right_blank or snapshot.right_loading
def should_exit_city_picker_before_search(snapshot: Optional[UiSnapshot]) -> bool:
    return bool(snapshot and snapshot.city_page)


def should_click_search_cancel_button() -> bool:
    return False

def write_search_target(path: Path, store: Store, keyword: str, city_ids: set[str]) -> None:
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
    )


def clear_search_target(path: Path) -> None:
    if path.exists():
        path.write_text(json.dumps({"enabled": False}, ensure_ascii=False, indent=2), encoding="utf-8")
def run_xdotool(args: Sequence[str], *, input_text: str = "") -> subprocess.CompletedProcess:
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
    )
GNOME_PROXY_KEYS = {
    "mode": ("org.gnome.system.proxy", "mode"),
    "http_host": ("org.gnome.system.proxy.http", "host"),
    "http_port": ("org.gnome.system.proxy.http", "port"),
    "https_host": ("org.gnome.system.proxy.https", "host"),
    "https_port": ("org.gnome.system.proxy.https", "port"),
}

def gsettings_get(schema: str, key: str) -> str:
    result = subprocess.run(
        ["gsettings", "get", schema, key],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""
def snapshot_gnome_proxy() -> Dict[str, str]:
    return {name: gsettings_get(schema, key) for name, (schema, key) in GNOME_PROXY_KEYS.items()}


def build_gsettings_proxy_commands(
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
    return set_cmds, restore_cmds
def run_commands(commands: Sequence[Sequence[str]]) -> None:
    for command in commands:
        subprocess.run(list(command), timeout=5, check=False)


def build_mitmdump_command(proxy_port: int, upstream_proxy: str = DEFAULT_UPSTREAM_PROXY) -> List[str]:
    cmd = [
        "mitmdump",
        "--listen-port",
        str(proxy_port),
        "--set",
        "ssl_insecure=true",
        "-s",
        str(ROOT_DIR / "dianping_interceptor.py"),
    ]
    if upstream_proxy:
        cmd.extend(["--mode", f"upstream:{upstream_proxy}"])
    return cmd
def build_clash_mitm_patch(
    proxy_name: str = "DP-MITM",
    proxy_port: int = 9092,
    *,
    include_search_domains: bool = True,
) -> str:
    # Keep the default split narrow.
    rule_lines = [
        f"  - DOMAIN-SUFFIX,mapi.dianping.com,{proxy_name}",
        f"  - DOMAIN-SUFFIX,mapi.meituan.com,{proxy_name}",
        f"  - DOMAIN-SUFFIX,mapi.sankuai.com,{proxy_name}",
    ]
    if include_search_domains:
        rule_lines += [
            f"  - DOMAIN-SUFFIX,m.dianping.com,{proxy_name}",
            f"  - DOMAIN-SUFFIX,catfront.dianping.com,{proxy_name}",
            f"  - DOMAIN-SUFFIX,rs.meituan.com,{proxy_name}",
            f"  - DOMAIN-SUFFIX,lx0.meituan.com,{proxy_name}",
            f"  - DOMAIN-SUFFIX,appmock.meituan.com,{proxy_name}",
        ]
    return "\n".join(
        [
            "rules:",
            "  - type: http",
            *rule_lines,
        ]
    )

def build_mitmdump_env(
    base_env: Optional[Mapping[str, str]] = None,
    *,
    search_rewrite: bool = False,
) -> Dict[str, str]:
    env = dict(base_env or os.environ)
    for key in PROXY_ENV_KEYS:
        env.pop(key, None)
    env["DP_SEARCH_REWRITE"] = "1" if search_rewrite else "0"
    return env
def resolve_proxy_mode(proxy_mode: str, upstream_proxy: str, set_system_proxy: bool) -> Dict[str, Any]:
    if proxy_mode == "split":
        return {
            "upstream_proxy": "",
            "set_system_proxy": False,
            "message": "Clash 分流模式: 系统代理保持 7890，请让 Clash 把大众点评域名转发到 9092，mitm 不再上游到 7890。",
        }
    return {
        "upstream_proxy": upstream_proxy,
        "set_system_proxy": set_system_proxy,
        "message": "",
    }
def start_mitm_if_needed(
    proxy_port: int,
    upstream_proxy: str = DEFAULT_UPSTREAM_PROXY,
    search_rewrite: bool = False,
) -> Optional[subprocess.Popen]:
    if port_open("127.0.0.1", proxy_port):
        command = active_mitmdump_command(proxy_port)
        if command and not mitmdump_env_is_safe(command, require_search_rewrite=search_rewrite):
            print(f"mitm 已监听但未开启搜索改写，重启 127.0.0.1:{proxy_port}")
            stop_mitmdump_on_port(proxy_port)
        else:
            print(f"mitm 已监听: 127.0.0.1:{proxy_port}")
            return None
    cmd = build_mitmdump_command(proxy_port, upstream_proxy)
    log_path = DEFAULT_LOG_DIR / "mitmdump_auto.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        env=build_mitmdump_env(search_rewrite=search_rewrite),
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"mitmdump exited early with code {process.returncode}; see {log_path}")
        if port_open("127.0.0.1", proxy_port):
            print(f"mitm 代理已启动: 127.0.0.1:{proxy_port} | log={log_path}")
            return process
        time.sleep(0.2)
    process.terminate()
    raise RuntimeError(f"mitmdump did not listen on 127.0.0.1:{proxy_port}; see {log_path}")
def active_mitmdump_command(proxy_port: int) -> str:
    for pid, argv in iter_dianping_mitmdump_processes(proxy_port):
        return " ".join([str(pid), *argv])
    return ""


def iter_dianping_mitmdump_processes(proxy_port: int) -> List[tuple[int, List[str]]]:
    matches: List[tuple[int, List[str]]] = []
    for cmdline_path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            argv = [part.decode("utf-8", errors="replace") for part in cmdline_path.read_bytes().split(b"\0") if part]
        except OSError:
            continue
        if is_dianping_mitmdump_argv(argv, proxy_port):
            matches.append((int(cmdline_path.parts[-2]), argv))
    return matches


def is_dianping_mitmdump_argv(argv: Sequence[str], proxy_port: int) -> bool:
    try:
        port_value = argv[argv.index("--listen-port") + 1]
    except (ValueError, IndexError):
        return False
    if str(port_value) != str(proxy_port):
        return False
    return any(Path(arg).name == "dianping_interceptor.py" for arg in argv)
def mitmdump_pid_from_command(command: str) -> str:
    first = str(command or "").split(maxsplit=1)[0]
    return first if first.isdigit() else ""
def mitmdump_has_search_rewrite_env(command: str) -> bool:
    pid = mitmdump_pid_from_command(command)
    if not pid:
        return False
    try:
        environ = (Path("/proc") / pid / "environ").read_bytes()
    except OSError:
        return False
    return b"DP_SEARCH_REWRITE=1" in environ.split(b"\0")
def mitmdump_env_is_safe(command: str, *, require_search_rewrite: bool) -> bool:
    pid = mitmdump_pid_from_command(command)
    if not pid:
        return False
    try:
        entries = (Path("/proc") / pid / "environ").read_bytes().split(b"\x00")
    except OSError:
        return False
    proxy_prefixes = tuple(f"{key}=".encode() for key in PROXY_ENV_KEYS)
    if any(entry.startswith(proxy_prefixes) for entry in entries):
        return False
    if require_search_rewrite and b"DP_SEARCH_REWRITE=1" not in entries:
        return False
    return True

def stop_mitmdump_on_port(proxy_port: int) -> None:
    for pid, _argv in iter_dianping_mitmdump_processes(proxy_port):
        subprocess.run(["kill", str(pid)], timeout=5, check=False)
    deadline = time.time() + 5
    while time.time() < deadline and port_open("127.0.0.1", proxy_port):
        time.sleep(0.1)
def high_throughput_defaults(scroll_count: int, scroll_pause: float) -> Dict[str, Any]:
    return {
        "search_rewrite": False,
        "scroll_count": max(scroll_count, 320),
        "scroll_pause": min(scroll_pause, 0.10),
        "scroll_batch": 8,
    }
def stop_started_mitm(process: Optional[subprocess.Popen]) -> None:
    if process is None:
        return
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
def configure_system_proxy(host: str, port: int, *, register_signals: bool = True) -> Callable[[], None]:
    snapshot = snapshot_gnome_proxy()
    set_cmds, restore_cmds = build_gsettings_proxy_commands(host, port, snapshot)
    run_commands(set_cmds)
    restored = False

    def restore() -> None:
        nonlocal restored
        if restored:
            return
        restored = True
        run_commands(restore_cmds)

    atexit.register(restore)
    if not register_signals:
        return restore

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous = signal.getsignal(sig)

        def handler(signum, frame, previous_handler=previous):
            restore()
            if callable(previous_handler):
                previous_handler(signum, frame)
            raise SystemExit(128 + int(signum))

        signal.signal(sig, handler)
    return restore


def find_miniapp_window() -> Optional[WindowInfo]:
    windows: Dict[str, WindowInfo] = {}
    for query in [
        ["search", "--name", "大众点评"],
        ["search", "--name", "WeChatAppEx"],
        ["search", "--name", "微信"],
        ["search", "--class", "wechat"],
    ]:
        result = run_xdotool(query)
        for window_id in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
            info = get_window_info(window_id)
            if info:
                windows[window_id] = info
    return choose_miniapp_window(windows.values())
def choose_miniapp_window(windows: Iterable[WindowInfo]) -> Optional[WindowInfo]:
    candidates = [info for info in windows if is_plausible_miniapp_window(info)]
    if not candidates:
        return None
    def score(info: WindowInfo) -> tuple[int, int]:
        name = info.name
        name_score = 0
        if "WeChatAppEx" in info.cmdline:
            name_score += 300
        if "Google Chrome" in name or "chrome" in info.cmdline.lower():
            name_score -= 300
        if "大众点评" in name:
            name_score += 100
        if "WeChatAppEx" in name:
            name_score += 60
        if name == "微信":
            name_score += 10
        if info.width > 1200 or info.height > 1200:
            name_score -= 250
        return name_score, -abs(info.width - 914)
    return max(candidates, key=score)
def is_plausible_miniapp_window(info: WindowInfo) -> bool:
    if info.width < 360 or info.height < 620:
        return False
    if info.width * info.height < 240_000:
        return False
    if info.width > 1400 or info.height > 1280:
        return False
    return True
def minimize_overlapping_windows(target: WindowInfo) -> None:
    result = run_xdotool(["search", "--all", "--onlyvisible", "--name", ".*"])
    for window_id in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
        if window_id == target.window_id:
            continue
        info = get_window_info(window_id)
        if not info or info.width < 200 or info.height < 200:
            continue
        if windows_overlap(target, info):
            run_xdotool(["windowminimize", window_id])
def prepare_window(window: WindowInfo, *, width: int = 914, height: int = 882) -> WindowInfo:
    """Make the mini-program a stable independent target."""
    run_xdotool(["windowsize", window.window_id, str(width), str(height)])
    time.sleep(0.2)
    refreshed = get_window_info(window.window_id) or window
    screen_width, _screen_height = display_size()
    target_x = max(0, screen_width - width - 24) if screen_width else refreshed.x
    target_y = max(0, refreshed.y)
    run_xdotool(["windowmove", refreshed.window_id, str(target_x), str(target_y)])
    time.sleep(0.2)
    return get_window_info(window.window_id) or refreshed
def refresh_window(window: Optional[WindowInfo]) -> Optional[WindowInfo]:
    """Return active mini-program window, refreshing it if WeChat rebuilt the X window."""
    if window is not None:
        current = get_window_info(window.window_id)
        if current and is_plausible_miniapp_window(current):
            return current
    found = find_miniapp_window()
    if found is None:
        return None
    refreshed = prepare_window(found)
    minimize_overlapping_windows(refreshed)
    return refreshed
def display_size() -> tuple[int, int]:
    result = run_xdotool(["getdisplaygeometry"])
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0


def windows_overlap(a: WindowInfo, b: WindowInfo) -> bool:
    left = max(a.x, b.x)
    right = min(a.x + a.width, b.x + b.width)
    top = max(a.y, b.y)
    bottom = min(a.y + a.height, b.y + b.height)
    return right > left and bottom > top


def get_window_info(window_id: str) -> Optional[WindowInfo]:
    name_result = run_xdotool(["getwindowname", window_id])
    geometry_result = run_xdotool(["getwindowgeometry", window_id])
    if geometry_result.returncode != 0:
        return None
    text = geometry_result.stdout
    position = re.search(r"Position:\s*(-?\d+),(-?\d+)", text)
    geometry = re.search(r"Geometry:\s*(\d+)x(\d+)", text)
    if not position or not geometry:
        return None
    pid_result = run_xdotool(["getwindowpid", window_id])
    pid = pid_result.stdout.strip()
    return WindowInfo(
        window_id=window_id,
        name=name_result.stdout.strip(),
        x=int(position.group(1)),
        y=int(position.group(2)),
        width=int(geometry.group(1)),
        height=int(geometry.group(2)),
        pid=pid,
        cmdline=process_cmdline(pid),
    )
def process_cmdline(pid: str) -> str:
    if not pid or not pid.isdigit():
        return ""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"", b" ").decode("utf-8", errors="replace").strip()
def focus_window(window: WindowInfo) -> None:
    for _ in range(3):
        try:
            run_xdotool(["windowactivate", "--sync", window.window_id])
        except subprocess.TimeoutExpired:
            run_xdotool(["windowactivate", window.window_id])
        run_xdotool(["windowfocus", window.window_id])
        time.sleep(0.25)
        active = run_xdotool(["getactivewindow"])
        if is_window_active(window.window_id, active.stdout):
            return
        time.sleep(0.3)
def is_window_active(window_id: str, active_stdout: str) -> bool:
    return str(window_id).strip() == str(active_stdout).strip()
def dismiss_blocking_overlays(window: Optional[WindowInfo]) -> None:
    if window is None:
        return
    focus_window(window)
    # Known right-pane blockers observed in PC WeChat: Meituan Taxi privacy
    # modal. Prefer "不同意" then right-pane back; both are window-relative and
    # clamped by click_relative.
    for x, y in ((585, 828), (790, 820), (520, 48)):
        click_relative(window, x, y)
        time.sleep(0.2)
def click(window: WindowInfo, points: Points, name: str) -> None:
    focus_window(window)
    x, y = points.scaled_xy(window, name)
    click_relative(window, x, y)


def point_inside_window(window: WindowInfo, points: Points, name: str, *, margin: int = 2) -> bool:
    x, y = points.scaled_xy(window, name)
    return margin <= x <= window.width - margin and margin <= y <= window.height - margin


def click_relative(window: WindowInfo, x: int, y: int) -> None:
    x = min(max(2, int(x)), max(2, window.width - 2))
    y = min(max(2, int(y)), max(2, window.height - 2))
    run_xdotool(["mousemove", "--window", window.window_id, str(x), str(y)])
    time.sleep(0.08)
    run_xdotool(["click", "--window", window.window_id, "1"])
    time.sleep(0.25)
def click_xy(screen_x: int, screen_y: int) -> None:
    run_xdotool(["mousemove", str(screen_x), str(screen_y)])
    time.sleep(0.1)
    run_xdotool(["click", "1"])
    time.sleep(0.25)
def type_text(text: str, window: Optional[WindowInfo] = None) -> None:
    args = ["type", "--clearmodifiers"]
    if window is not None:
        args.extend(["--window", window.window_id])
    args.append(text)
    run_xdotool(args)


def xclip_set_args(loops: int = 2) -> List[str]:
    return ["xclip", "-selection", "clipboard", "-loop", str(loops)]

def get_clipboard_text(timeout: float = 1.0) -> str:
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""
def clear_input(window: Optional[WindowInfo] = None) -> None:
    press("ctrl+a", window)
    time.sleep(0.1)
    press("BackSpace", window)
    time.sleep(0.1)


def press(key: str, window: Optional[WindowInfo] = None) -> None:
    args = ["key", "--clearmodifiers"]
    if window is not None:
        args.extend(["--window", window.window_id])
    args.append(key)
    run_xdotool(args)
    time.sleep(0.2)
def scroll_pages(count: int, pause: float) -> None:
    for _ in range(count):
        run_xdotool(["key", "Page_Down"])
        time.sleep(pause)
def exported_review_count(store_name: str, stores: Sequence[Store], log_dir: Path) -> int:
    rows, _stats = build_export_rows(stores=stores, log_dir=log_dir, explicit_uuid_map=load_uuid_map(log_dir))
    return sum(1 for row in rows if row["门店"] == store_name and row.get("文字") and row.get("发布时间"))


def store_key(index: int, store: Store) -> str:
    return f"{index:03d}|{store.name}|{store.address}"


class EventWatcher:
    def __init__(self, path: Path):
        self.path = path
        self.offset = path.stat().st_size if path.exists() else 0

    def wait_for(
        self,
        predicate: Callable[[Mapping[str, Any]], bool],
        *,
        timeout: float,
        label: str,
        poll: float = 0.15,
    ) -> Optional[Mapping[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            events, self.offset = read_events(self.path, self.offset)
            for event in events:
                if predicate(event):
                    return event
            time.sleep(poll)
        print(f"  等待超时: {label}")
        return None
def latest_confirmed_city_ids(events_path: Path) -> set[str]:
    """Return the set of city IDs from the most recent city_context events in the events file."""
    city_ids: set[str] = set()
    if not events_path.exists():
        return city_ids
    for line in reversed(events_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "city_context":
            city_id = str(event.get("cityId", ""))
            if city_id:
                city_ids.add(city_id)
            if len(city_ids) >= 1:
                break
    return city_ids

def event_matches_city(event: Mapping[str, Any], city_ids: set[str]) -> bool:
    if not city_ids:
        return True
    return str(event.get("cityId", "")) in city_ids
def normalized_keyword(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def keyword_variants_for_store(store: Store) -> List[str]:
    branch = store.name.replace("达美乐比萨(", "").replace(")", "").strip()
    variants = [
        f"达美乐比萨 {branch}".strip(),
        branch,
        branch[:-1] if branch.endswith("店") else branch,
        store.name,
    ]
    result: List[str] = []
    seen = set()
    for value in variants:
        keyword = normalized_keyword(value)
        if keyword and keyword not in seen:
            seen.add(keyword)
            result.append(keyword)
    return result
def should_switch_city(current_city_ids: set[str], target_city_ids: set[str]) -> bool:
    if not target_city_ids:
        return False
    return not bool(current_city_ids & target_city_ids)


def should_continue_after_unconfirmed_city_switch(target_city_ids: set[str]) -> bool:
    """Search events carry cityId, so known target city can be validated later."""
    return bool(target_city_ids)


def event_matches_search(event: Mapping[str, Any], store: Store, keyword: str, attempted_keywords: set[str] | None = None, require_city: bool = False) -> bool:
    if attempted_keywords is not None:
        attempted = {normalized_keyword(value) for value in attempted_keywords if normalized_keyword(value)}
        if keyword not in attempted:
            return False
    branch = store.name.replace("达美乐比萨(", "").replace(")", "")
    if branch and branch.replace("店", "") not in keyword and "达美乐" not in keyword:
        return False
    if not require_city:
        return True
    return search_event_matches_city(event, store)
def search_event_matches_city(event: Mapping[str, Any], store: Store) -> bool:
    city_ids = expected_city_ids(store.address)
    return event_matches_city(event, city_ids)


def event_has_matching_candidate(store: Store, event: Mapping[str, Any], min_score: int) -> bool:
    return choose_candidate_from_event(store, event, min_score) is not None
def review_event_matches_candidate(
    event: Mapping[str, Any],
    candidate: Candidate,
    store: Store,
    full_only: bool = False,
) -> bool:
    """Match review events by actual mitm evidence, allowing shopId/shopUuid aliases."""
    if event.get("type") != "review":
        return False
    if int(event.get("review_count") or 0) <= 0:
        return False
    if full_only and not is_full_review_event(event):
        return False
    event_uuid = str(event.get("shopuuid", ""))
    candidate_uuid = str(candidate.uuid or "")
    if event_uuid and candidate_uuid:
        return event_uuid == candidate_uuid
    if event_uuid and not candidate_uuid:
        return False
    event_store_name = str(event.get("storeName", ""))
    return normalized_store_identity(event_store_name) == normalized_store_identity(store.name)
def candidate_review_event_for_attempt(event: Mapping[str, Any], *, full_only: bool = False) -> bool:
    if event.get("type") != "review":
        return False
    if int(event.get("review_count") or 0) <= 0:
        return False
    if full_only and not is_full_review_event(event):
        return False
    return True
def wait_for_candidate_review_event(
    window: WindowInfo,
    points: Points,
    watcher: EventWatcher,
    candidate: Candidate,
    store: Store,
    full_only: bool,
    timeout: float,
    label: str,
) -> tuple[Optional[Mapping[str, Any]], bool]:
    event = watcher.wait_for(
        lambda e: candidate_review_event_for_attempt(e, full_only=full_only),
        timeout=timeout,
        label=label,
    )
    if event is None:
        return None, False
    if review_event_matches_candidate(event, candidate, store, full_only=full_only):
        return event, False
    print(
        "收到非目标评论事件，回退并终止当前候选: "
        f"{event.get('storeName', '')} {event.get('shopuuid','')}"
    )
    reset_after_wrong_detail(window, points)
    return None, True
class ReviewCaptureFailed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)  
        self.reason = reason


def event_start(event: Mapping[str, Any]) -> Optional[int]:
    value = str(event.get("start") or "").strip()
    if not value.isdigit():
        return None
    return int(value)


def is_full_review_event(event: Mapping[str, Any]) -> bool:
    return "outsidesiftedreviewlist" in str(event.get("url", "")).lower()


def review_capture_complete(
    store: Store,
    candidate: Candidate,
    *,
    exported_count: int,
    target_reviews: int,
    saw_is_end: bool,
) -> bool:
    return bool(saw_is_end)


def review_target_from_event(event: Mapping[str, Any]) -> int:
    for key in ("reviewTotalCount", "totalCount", "count"):
        value = event.get(key)
        if str(value).isdigit():
            return int(value)
    return 0


def normalized_store_identity(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("达美乐披萨", "达美乐比萨")
    return re.sub(r"\s+", "", text)


def choose_candidate_from_event(store: Store, event: Mapping[str, Any], min_score: int) -> Optional[Candidate]:
    candidates = []
    for item in event.get("candidates", []):
        if not isinstance(item, Mapping):
            continue
        candidate = Candidate(
            uuid=str(item.get("uuid", "")),
            name=str(item.get("name", "")),
            branch=str(item.get("branch", "")),
            address_hint=str(item.get("address", "")),
            city_id=str(item.get("cityId", "")),
            region=str(item.get("region", "")),
            review_count=str(item.get("reviewCount", "")),
            source=f"{event.get('source', '')}|rank={item.get('rank', '0')}",
        )
        candidates.append((score_candidate(store, candidate), candidate))
    if not candidates:
        return None
    score, candidate = max(candidates, key=lambda pair: pair[0])
    if score < min_score:
        print(f"  候选分数不足: {score} < {min_score}")
        return None
    return candidate


def duplicate_store_names(stores: Sequence[Store]) -> set[str]:
    counts: Dict[str, int] = {}
    for store in stores:
        counts[store.name] = counts.get(store.name, 0) + 1
    return {name for name, count in counts.items() if count > 1}
def unresolved_stores(stores: Sequence[Store], log_dir: Path, progress: Mapping[str, Any]) -> List[Store]:
    rows, stats = build_export_rows(stores=stores, log_dir=log_dir, explicit_uuid_map=load_uuid_map(log_dir))
    complete_review_stores = set(stats.get("complete_review_stores", []))
    duplicate_names = duplicate_store_names(stores)
    pending: List[Store] = []
    for index, store in enumerate(stores, start=1):
        if store_is_audited_complete(index, store, complete_review_stores, duplicate_names, progress):
            continue
        if store.name in complete_review_stores and store.name not in duplicate_names:
            continue
        pending.append(store)
    return pending
def pick_pending_stores(
    stores: Sequence[Store],
    log_dir: Path,
    progress: Mapping[str, Any],
    *,
    store_name: str = "",
    include_exported: bool = False,
    original_index: int = 0,
) -> List[Store]:
    pending = unresolved_stores(stores, log_dir, progress)
    if store_name:
        pending = [s for s in pending if s.name == store_name]
    if include_exported:
        return pending
    return [s for s in pending if not store_exported(s, log_dir)]
def progress_completed_names(progress: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in progress.get("completed", []):
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, Mapping):
            store_name = str(item.get("store") or item.get("storeName") or "")
            if store_name:
                names.add(store_name)
    return names


def progress_completed_keys(progress: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for item in progress.get("completed", []):
        if isinstance(item, Mapping):
            key = str(item.get("key") or "")
            if key:
                keys.add(key)
    return keys


def store_is_audited_complete(
    index: int,
    store: Store,
    complete_review_stores: set[str],
    duplicate_names: set[str],
    progress: Mapping[str, Any],
) -> bool:
    """Only trust progress completion when export audit also saw a full isEnd capture."""
    if store.name not in complete_review_stores:
        return False
    if store.name not in duplicate_names:
        return True
    return store_key(index, store) in progress_completed_keys(progress)


def switch_city(window: Optional[WindowInfo], points: Points, watcher: EventWatcher, city: str, city_ids: set[str], dry_run: bool) -> bool:
    if not city:
        return True
    print(f"切换城市: {city} cityIds={sorted(city_ids) or ['未知']}")
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
        timeout=6,
        label=f"城市事件 {city}",
    )
    if event is None:
        print("  城市事件未确认；继续搜索并用搜索结果 cityId 兜底确认")
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
    if snapshot_needs_left_back_reset(snapshot):
        click(window, points, "back_button")
        time.sleep(0.6)
    click(window, points, "merchant_tab")
    time.sleep(0.25)
    click(window, points, "home_tab")
    time.sleep(0.6)


def snapshot_needs_left_back_reset(snapshot: Optional[UiSnapshot]) -> bool:
    if snapshot is None:
        return False
    if snapshot.can_search_from_home or snapshot.can_search_from_results or snapshot.right_blank:
        return False
    return snapshot.state in {"unknown", "city_page"} or snapshot.city_page


def trigger_home_search(window: Optional[WindowInfo], points: Points, keyword: str, dry_run: bool) -> None:
    """Search from the single-pane mini-program home page."""
    print(f"  首页搜索: {keyword}")
    if dry_run:
        return
    if window is None:
        raise RuntimeError("missing miniapp window")
    # The home pane is fixed to the left half of the mini-program window. Use
    # absolute left-pane coordinates to avoid accidentally focusing the right
    # split-pane search box when the app is in search edit mode.
    focus_window(window)
    dismiss_blocking_overlays(window)
    click_relative(window, round(window.width * 0.16), round(window.height * 0.11))
    time.sleep(0.15)
    click_relative(window, round(window.width * 0.16), round(window.height * 0.11))
    clear_input(window)
    paste_text(keyword, window)
    press("Return", window)
    time.sleep(0.5)
    click_relative(window, round(window.width * 0.44), round(window.height * 0.11))
    time.sleep(0.8)


def trigger_right_pane_search(window: Optional[WindowInfo], points: Points, keyword: str, dry_run: bool) -> None:
    """Search from the split-pane result page's editable right-side search box."""
    print(f"  右侧搜索: {keyword}")
    if dry_run:
        return
    if window is None:
        raise RuntimeError("missing miniapp window")
    dismiss_blocking_overlays(window)
    snapshot = capture_ui_snapshot(window, DEFAULT_UI_DEBUG_DIR)
    if should_open_right_search_panel(snapshot):
        click(window, points, "home_search_input")
        time.sleep(0.8)
    click(window, points, "right_search_input")
    time.sleep(0.4)
    click(window, points, "right_search_clear")
    click(window, points, "right_search_input")
    time.sleep(0.2)
    clear_input(window)
    paste_text(keyword, window)
    press("Return", window)
    time.sleep(0.8)


def trigger_current_search(window: Optional[WindowInfo], points: Points, dry_run: bool) -> None:
    """Trigger whatever search page is currently visible; mitm supplies target params."""
    print("  触发当前搜索框")
    if dry_run:
        return
    if window is None:
        raise RuntimeError("missing miniapp window")
    dismiss_blocking_overlays(window)
    click(window, points, "right_search_input")
    press("Return", window)
    time.sleep(0.8)
    click(window, points, "search_button")


def trigger_search_path(window: Optional[WindowInfo], points: Points, keyword: str, path_name: str, dry_run: bool) -> None:
    if path_name == "left_result":
        print(f"  左侧结果页商户搜索: {keyword}")
        if dry_run:
            return
        if window is None:
            raise RuntimeError("missing miniapp window")
        dismiss_blocking_overlays(window)
        click(window, points, "merchant_tab")
        click(window, points, "search_input")
        clear_input(window)
        paste_text(keyword, window)
        press("Return", window)
        time.sleep(0.4)
        click(window, points, "left_search_submit")
        time.sleep(0.8)
    elif path_name == "home":
        trigger_home_search(window, points, keyword, dry_run)
    elif path_name == "right":
        trigger_right_pane_search(window, points, keyword, dry_run)
    elif path_name == "current":
        print(f"  当前页搜索: {keyword}")
        if dry_run:
            return
        if window is None:
            raise RuntimeError("missing miniapp window")
        dismiss_blocking_overlays(window)
        click(window, points, "search_input")
        clear_input(window)
        paste_text(keyword, window)
        press("Return", window)
        time.sleep(0.8)
    elif path_name == "suggestion":
        print(f"  建议页查找: {keyword}")
        if dry_run:
            return
        if window is None:
            raise RuntimeError("missing miniapp window")
        dismiss_blocking_overlays(window)
        click(window, points, "right_search_input")
        clear_input(window)
        paste_text(keyword, window)
        press("Return", window)
        time.sleep(0.4)
        click(window, points, "suggestion_search_entry")
        time.sleep(0.8)
    else:
        raise ValueError(f"unknown search path: {path_name}")


def wait_for_ui_state(
    window: Optional[WindowInfo],
    debug_dir: Path,
    predicate: Callable[[UiSnapshot], bool],
    *,
    timeout: float,
    label: str,
) -> Optional[UiSnapshot]:
    if window is None:
        return None
    deadline = time.time() + timeout
    last_snapshot: Optional[UiSnapshot] = None
    while time.time() < deadline:
        snapshot = capture_ui_snapshot(window, debug_dir)
        if snapshot is not None:
            last_snapshot = snapshot
            if predicate(snapshot):
                return snapshot
        time.sleep(0.35)
    if last_snapshot is not None:
        print(f"  UI等待超时: {label} last={last_snapshot.state}")
    else:
        print(f"  UI等待超时: {label} last=unavailable")
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
            "  UI状态: "
            f"{snapshot.state} home={snapshot.left_home_search} "
            f"results={snapshot.right_results} loading={snapshot.right_loading} city={snapshot.city_page}"
        )
    if not dry_run and should_exit_city_picker_before_search(snapshot):
        click(window, points, "back_button")
        time.sleep(0.8)
        snapshot = capture_ui_snapshot(window, debug_dir)
    path_order = merge_search_paths(preferred_paths, search_paths_for_snapshot(snapshot))
    for path_name in path_order:
        write_search_target(search_target_path, store, keyword, city_ids)
        trigger_search_path(window, points, keyword, path_name, dry_run)
        if dry_run:
            continue
        # Give the mini-program a brief chance to transition off the input page,
        # then rely on mitm events for the authoritative result.
        wait_for_ui_state(
            window,
            debug_dir,
            lambda snap: snap.right_results or snap.right_loading or snap.state in {"home", "right_blank"},
            timeout=2.0,
            label=f"搜索提交UI {keyword} path={path_name}",
        )
        search_event = watcher.wait_for(
            lambda e, s=store, kws={keyword}: event_matches_search(
                e,
                s,
                attempted_keywords=kws,
                require_city=require_city,
            ),
            timeout=6,
            label=f"搜索 {store.name} keyword={keyword} path={path_name}",
        )
        if search_event:
            if path_name in {"right", "left_result", "current", "suggestion"}:
                wait_for_ui_state(
                    window,
                    debug_dir,
                    lambda snap: snap.right_results,
                    timeout=2.0,
                    label=f"搜索结果渲染 {keyword} path={path_name}",
                )
            return search_event, path_name
        capture_ui_snapshot(window, debug_dir)
    return None, ""


def merge_search_paths(*groups: Sequence[str]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for group in groups:
        for item in group:
            if item in seen:
                continue
            if item not in SEARCH_PATH_ORDER:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def open_candidate_and_reviews(
    window: Optional[WindowInfo],
    points: Points,
    watcher: EventWatcher,
    candidate: Candidate,
    store: Store,
    stores: Sequence[Store],
    log_dir: Path,
    search_path: str,
    min_reviews: int,
    scroll_count: int,
    scroll_pause: float,
    scroll_batch: int,
    dry_run: bool,
) -> bool:
    print(f"  打开候选: {candidate.name}({candidate.branch}) {candidate.uuid}")
    if dry_run:
        return True
    if window is None:
        return False
    try:
        if search_path in {"right", "left_result", "current", "suggestion"}:
            snapshot = wait_for_ui_state(
                window,
                DEFAULT_UI_DEBUG_DIR,
                lambda snap: snap.right_results,
                timeout=2.0,
                label=f"候选列表渲染 {candidate.uuid}",
            )
            if snapshot is None:
                print("  候选列表未渲染，跳过点击，避免点到首页内容")
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
            timeout=3,
            label=f"详情评价模块 {candidate.uuid}",
        )
        if wrong_review:
            raise ReviewCaptureFailed("wrong_review_event")
        if shop_home_review:
            print(
                "  店铺评价模块确认: "
                f"{shop_home_review.get('shopuuid', '')} {shop_home_review.get('review_count', 0)}条"
            )
            if is_full_review_event(shop_home_review):
                review = shop_home_review
            else:
                review = None
        else:
            print("  未等到店铺评价模块事件，继续尝试进入全部评价")
            review = None
        if review is None:
            review = open_full_review_page(window, points, watcher, candidate, store, timeout=6)
            if review is None:
               return False
            if not review_event_matches_candidate(review, candidate, store, full_only=True):
                print(
                    "  完整评价页事件不是目标门店: "
                    f"{review.get('storeName', '')} {review.get('shopuuid', '')}"
                )
                reset_after_wrong_detail(window, points)
                raise ReviewCaptureFailed("wrong_full_review_event")
        if not review:
           return False
        target_reviews = review_target_from_event(shop_home_review or {}) or review_target_from_candidate(candidate, min_reviews)
        tracker = ReviewCaptureTracker(target_reviews=target_reviews)
        first_reason = tracker.observe(review)
        if first_reason:
            print(f"  评论分页状态: {first_reason}")
        max_scrolls = scroll_count
        empty_scrolls = 0
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
                timeout=3,
                label=f"评论分页 {candidate.uuid}",
            )
            if wrong_review:
                raise ReviewCaptureFailed("wrong_review_event")
            if not event:
                empty_scrolls += 1
                if empty_scrolls >= 8:
                    print(f"  连续 {empty_scrolls} 次未收到评论事件，停止滚动")
                    break
                continue
            empty_scrolls = 0
            reason = tracker.observe(event)
            print(
                f"  已捕获评论事件: {tracker.seen_reviews}"
                + (f"/{target_reviews}" if target_reviews else "")
                + f" | 页 {tracker.unique_pages} 重复 {tracker.duplicate_pages}"
            )
            if reason:
                print(f"  评论分页状态: {reason}")
                break
        complete = review_capture_complete(
            store,
            candidate,
            exported_count=tracker.seen_reviews,
            target_reviews=target_reviews,
            saw_is_end=tracker.saw_is_end,
        )
        print(
            "  评论事件确认: "
            f"events_seen={tracker.seen_reviews} "
            f"isEnd={tracker.saw_is_end} status={tracker.status}"
        )
        return complete
    finally:
        release_mouse(window)


def capture_current_detail_reviews(
    window: WindowInfo,
    points: Points,
    watcher: EventWatcher,
    candidate: Candidate,
    store: Store,
    stores: Sequence[Store],
    log_dir: Path,
    *,
    min_reviews: int,
    scroll_count: int,
    scroll_pause: float,
    scroll_batch: int,
) -> bool:
    """Use the currently visible shop detail page before trying city/search navigation."""
    try:
        review = open_full_review_page(window, points, watcher, candidate, store, timeout=4)
        if review and not review_event_matches_candidate(review, candidate, store, full_only=True):
            print(
                "  当前详情完整评价页事件不是目标门店: "
                f"{review.get('storeName', '')} {review.get('shopuuid', '')}"
            )
            reset_after_wrong_detail(window, points)
            raise ReviewCaptureFailed("wrong_full_review_event")
        if not review:
           return False
        target_reviews = review_target_from_event(review) or review_target_from_candidate(candidate, min_reviews)
        tracker = ReviewCaptureTracker(target_reviews=target_reviews)
        reason = tracker.observe(review)
        if reason:
            print(f"  评论分页状态: {reason}")
        max_scrolls = scroll_count
        empty_scrolls = 0
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
                timeout=3,
                label=f"当前详情评论分页 {candidate.uuid}",
            )
            if wrong_review:
                raise ReviewCaptureFailed("wrong_review_event")
            if not event:
                empty_scrolls += 1
                if empty_scrolls >= 8:
                    print(f"  连续 {empty_scrolls} 次未收到评论事件，停止滚动")
                    break
                continue
            empty_scrolls = 0
            reason = tracker.observe(event)
            print(
                f"  已捕获评论事件: {tracker.seen_reviews}"
                + (f"/{target_reviews}" if target_reviews else "")
                + f" | 页 {tracker.unique_pages} 重复 {tracker.duplicate_pages}"
            )
            if reason:
                print(f"  评论分页状态: {reason}")
                break
        complete = review_capture_complete(
            store,
            candidate,
            exported_count=tracker.seen_reviews,
            target_reviews=target_reviews,
            saw_is_end=tracker.saw_is_end,
        )
        print(
            "  当前详情评论确认: "
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
) -> Optional[Mapping[str, Any]]:
    entry_actions: List[tuple[str, Callable[[], None]]] = [
        (
            "right_detail_review_count_entry",
            lambda: click(window, points, "right_detail_review_count_entry"),
        ),
        ("detail_review_count_entry", lambda: click(window, points, "detail_review_count_entry")),
        ("detail_all_reviews_entry", lambda: click(window, points, "detail_all_reviews_entry")),
        ("all_reviews_entry", lambda: click(window, points, "all_reviews_entry")),
        (
            "right_center_review_entry",
            lambda: click_relative(window, round(window.width * 0.82), round(window.height * 0.45)),
        ),
    ]
    for retry_round in range(4):
        if retry_round:
            click(window, points, "right_detail_back")
            time.sleep(0.3)
            scroll_detail_page(window, points, 2 + retry_round * 2, 0.12)
        for label, action in entry_actions:
            print(f"  尝试进入全部评价: {label} #{retry_round + 1}")
            action()
            review = watcher.wait_for(
                lambda e: candidate_review_event_for_attempt(e, full_only=True),
                timeout=timeout,
                label=f"全部评价入口 {label} {candidate.uuid}",
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


def scroll_reviews(window: WindowInfo, points: Points, count: int, pause: float, *, batch: int = 4) -> None:
    focus_window(window)
    x, y = points.scaled_xy(window, "right_scroll_anchor")
    release_buttons()
    run_xdotool(["mousemove", str(window.x + x), str(window.y + y)])
    time.sleep(0.05)
    args = build_scroll_click_args(batch)
    for _ in range(count):
        run_xdotool(args)
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
            timeout=3,
            label=f"详情尝试 {candidate.uuid} offset={dx},{dy}",
        )
        if not detail:
            continue
        if detail.get("shopuuid") == candidate.uuid:
            return detail
        print(
            "  点到非目标详情，回退重试: "
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
    branch = store.name.replace("达美乐比萨(", "").replace(")", "").strip()
    return Candidate(
        uuid=uuid,
        name="达美乐比萨",
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
        return int(raw)
    except ValueError:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="以 mitm 事件为准的 PC 微信大众点评小程序批量状态机")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS_PATH)
    parser.add_argument("--points", type=Path, default=DEFAULT_CALIBRATION_PATH)
    parser.add_argument("--search-target", type=Path, default=DEFAULT_SEARCH_TARGET_PATH)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--ui-debug-dir", type=Path, default=DEFAULT_UI_DEBUG_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--original-index", type=int, default=0, help="只处理 xlsx 原始序号，从 1 开始")
    parser.add_argument("--store-name", default="", help="只处理名称包含该文本的 xlsx 门店")
    parser.add_argument("--include-exported", action="store_true", help="即使已有评论也继续处理，用于续采到指定数量")
    parser.add_argument("--min-reviews", type=int, default=0, help="目标门店至少导出多少条字段完整评论")
    parser.add_argument("--min-score", type=int, default=90)
    parser.add_argument("--scroll-count", type=int, default=240)
    parser.add_argument("--scroll-pause", type=float, default=0.25)
    parser.add_argument("--scroll-batch", type=int, default=4, help="每轮发送多少个向下滚轮事件；高吞吐模式默认更大")
    parser.add_argument("--rewrite-search", action="store_true", help="让 mitm 把搜索请求重写成当前 xlsx 门店/城市，减少 UI 输入依赖")
    parser.add_argument("--high-throughput", action="store_true", help="批量极速模式：把滚动参数调到更激进的默认值；搜索改写需显式加 --rewrite-search")
    parser.add_argument("--proxy-port", type=int, default=9092)
    parser.add_argument("--start-mitm", action="store_true", help="如果代理端口未监听，自动启动 mitmdump")
    parser.add_argument("--upstream-proxy", default=DEFAULT_UPSTREAM_PROXY, help="mitmdump 上游代理；空字符串表示不用")
    parser.add_argument("--proxy-mode", choices=["global-mitm", "clash-rule"], default="global-mitm", help="代理模式；clash-rule 保持系统代理 7890，只让 Clash 分流大众点评到 9092")
    parser.add_argument("--set-system-proxy", action="store_true", help="不推荐：临时把 GNOME 全局系统代理切到 mitm 端口，可能影响国内网络")
    parser.add_argument("--print-clash-mitm-patch", action="store_true", help="打印 Clash 分流片段：系统代理保持 7890，仅大众点评域名转到 mitm")
    parser.add_argument("--calibrate", action="store_true", help="生成/显示坐标配置，不执行采集")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不点击 UI")
    args = parser.parse_args()

    search_rewrite = bool(args.rewrite_search)
    if args.high_throughput:
        defaults = high_throughput_defaults(args.scroll_count, args.scroll_pause)
        search_rewrite = bool(defaults["search_rewrite"])
        args.scroll_count = int(defaults["scroll_count"])
        args.scroll_pause = float(defaults["scroll_pause"])
        args.scroll_batch = max(int(args.scroll_batch), int(defaults["scroll_batch"]))
        print(
            "高吞吐模式: "
            f"rewrite_search={search_rewrite} scroll_count={args.scroll_count} "
            f"scroll_pause={args.scroll_pause} scroll_batch={args.scroll_batch}"
        )

    if args.calibrate:
        save_default_points(args.points)
        print("请按实际小程序窗口改这些点位；所有点位是小程序窗口内相对坐标 x,y。")
        print(args.points.read_text(encoding="utf-8"))
        window = find_miniapp_window()
        if window:
            print(f"检测到小程序窗口: id={window.window_id} name={window.name} pos={window.x},{window.y} size={window.width}x{window.height}")
        return 0

    if args.print_clash_mitm_patch:
        print(build_clash_mitm_patch("DP-MITM", args.proxy_port))
        return 0

    proxy_mode = resolve_proxy_mode(args.proxy_mode, args.upstream_proxy, args.set_system_proxy)
    args.upstream_proxy = str(proxy_mode["upstream_proxy"])
    args.set_system_proxy = bool(proxy_mode["set_system_proxy"])
    if proxy_mode["message"]:
        print(proxy_mode["message"])

    started_mitm = None
    if args.start_mitm and not args.dry_run:
        try:
            started_mitm = start_mitm_if_needed(
                args.proxy_port,
                args.upstream_proxy,
                search_rewrite=search_rewrite,
            )
            if started_mitm:
                atexit.register(stop_started_mitm, started_mitm)
        except RuntimeError as exc:
            print(str(exc))
            return 2

    if not args.dry_run and not port_open("127.0.0.1", args.proxy_port):
        print(f"mitm 代理端口未监听: 127.0.0.1:{args.proxy_port}")
        print("先启动: mitmdump --listen-port 9092 --set ssl_insecure=true -s dianping_interceptor.py")
        print("或加参数: --start-mitm")
        return 2
    restore_proxy = None
    if args.set_system_proxy and not args.dry_run:
        print("警告: --set-system-proxy 会把所有系统流量切到 9092。国内网络异常时请不要用它，改用 Clash 分流片段。")
        restore_proxy = configure_system_proxy("127.0.0.1", args.proxy_port)
        print(f"系统代理已切到 127.0.0.1:{args.proxy_port}，退出时恢复")

    points = load_points(args.points)
    stores = load_stores_from_xlsx(args.excel)
    progress = load_progress(args.progress)
    pending = pick_pending_stores(
        stores,
        args.log_dir,
        progress,
        store_name=args.store_name,
        include_exported=args.include_exported,
        original_index=args.original_index,
        start_index=args.start_index,
        limit=args.limit,
    )
    print(f"xlsx门店: {len(stores)} | 待处理: {len(pending)} | 已完成: {len(progress.get('completed', []))}")

    window = None if args.dry_run else find_miniapp_window()
    if not args.dry_run and not window:
        print("未找到大众点评小程序窗口。请先打开 PC 微信并进入大众点评小程序。")
        return 3
    if window:
        print(f"小程序窗口: id={window.window_id} name={window.name} pos={window.x},{window.y} size={window.width}x{window.height}")
        if not args.dry_run:
            window = prepare_window(window)
            print(f"窗口已固定: id={window.window_id} pos={window.x},{window.y} size={window.width}x{window.height}")
            minimize_overlapping_windows(window)
            focus_window(window)

    watcher = EventWatcher(args.events)
    # Use recent mitm city context to avoid clicking a search/filter page's
    # "全城" control as if it were the city switcher.
    current_city_ids: set[str] = latest_confirmed_city_ids(args.events)
    if current_city_ids:
        print(f"最近城市上下文: {sorted(current_city_ids)}")
    store_indices = {id(store): index for index, store in enumerate(stores, start=1)}
    known_uuid_map = load_uuid_map(args.log_dir)
    for index, store in enumerate(pending, 1):
        if not args.dry_run:
            window = refresh_window(window)
            if window is None:
                print("小程序窗口已失效且无法重新定位。")
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
                print(f"  尝试当前详情页直接采集: {known_candidate.uuid}")
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
                print("  当前详情页直接采集未完成，继续走城市/搜索路径")
                window = refresh_window(window)
            else:
                print(f"  当前页面不是详情页({current_snapshot.state if current_snapshot else 'unknown'})，跳过详情直采")
        reset_to_searchable_state(window, points, args.dry_run)
        if city and should_switch_city(current_city_ids, city_ids):
            if not args.dry_run:
                window = refresh_window(window)
            city_confirmed = switch_city(window, points, watcher, city, city_ids, args.dry_run)
            if not city_confirmed:
                capture_debug_context(
                    stage="city_switch_failed",
                    store=store,
                    window=window,
                    events_path=args.events,
                    debug_dir=args.ui_debug_dir,
                )
                if should_continue_after_unconfirmed_city_switch(city_ids):
                    print("  城市切换未被事件确认；继续搜索，等待搜索事件确认 cityId")
                    current_city_ids = set()
                else:
                    progress.setdefault("failed", []).append({"store": store.name, "reason": "city_switch_failed"})
                    save_progress(args.progress, progress)
                    continue
            else:
                current_city_ids = set(city_ids)
        elif city_ids:
            print(f"  城市已确认: {city} cityIds={sorted(city_ids)}")

        search_event = None
        search_path = ""
        attempted_keywords = keyword_variants_for_store(store)
        for attempt, keyword in enumerate(attempted_keywords, start=1):
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
                f"  搜索城市不匹配: got={search_event.get('cityId', '')} "
                f"expected={sorted(city_ids)}，尝试切换城市后重搜"
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
                f"  搜索请求城市为 {search_event.get('cityId', '')}，"
                f"但候选店铺已匹配目标城市/分店: {candidate.uuid}"
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
            print(f"  评论采集失败原因: {capture_failure_reason}，尝试重置后重搜一次")
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
                stage=capture_failure_reason,
                store=store,
                window=window,
                events_path=args.events,
                debug_dir=args.ui_debug_dir,
            )
            progress.setdefault("failed", []).append({"store": store.name, "reason": capture_failure_reason})
            save_progress(args.progress, progress)
            clear_search_target(args.search_target)
            press("Escape", window)
            continue
        progress.setdefault("completed", []).append(
            {"key": current_store_key, "index": original_index, "store": store.name, "address": store.address}
        )
        save_progress(args.progress, progress)
        export_reviews(args.excel, args.log_dir, args.output, ROOT_DIR / "output" / "store_reviews")
        clear_search_target(args.search_target)
        press("Escape", window)
        time.sleep(1)

    if args.dry_run:
        print("\ndry-run完成：未点击 UI，未写导出文件。")
        return 0

    stats = export_reviews(args.excel, args.log_dir, args.output, ROOT_DIR / "output" / "store_reviews")
    print(f"\n导出评论: {stats['reviews_exported']} | 已有评论门店: {stats['stores_with_reviews']} | 输出: {args.output}")
    if restore_proxy:
        restore_proxy()
    stop_started_mitm(started_mitm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
