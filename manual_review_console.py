# -*- coding:utf-8 -*-
"""Manual-first review capture console for the Dianping mini-program.

The user manually opens the correct store's full review page in PC WeChat.
This console manages mitmproxy, system proxy, window scrolling, status, and
exports without trying to automate city/search navigation.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import shlex
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import parse_qs, urlparse

from capture_audit import audit
from dianping_events import DEFAULT_EVENTS_PATH, read_events
from miniapp_state_machine import (
    DEFAULT_LOG_DIR,
    DEFAULT_OUTPUT_PATH,
    Points,
    WindowInfo,
    build_clash_mitm_patch,
    build_mitmdump_command,
    build_mitmdump_env,
    configure_system_proxy,
    exported_review_count,
    find_miniapp_window,
    focus_window,
    get_window_info,
    load_points,
    port_open,
    run_xdotool,
    scroll_reviews,
    stop_started_mitm,
)
from review_exporter import DEFAULT_EXCEL_PATH, DEFAULT_STORE_OUTPUT_DIR, export_reviews, load_stores_from_xlsx
from city_utils import city_from_address
from miniapp_state_machine import keyword_variants_for_store


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_PROXY_PORT = 9092
DEFAULT_CONSOLE_PORT = 8765
DEFAULT_CLASH_PORT = 7890
DEFAULT_DIAGNOSTIC_UPSTREAM_PROXY = f"http://127.0.0.1:{DEFAULT_CLASH_PORT}/"
DEFAULT_POINTS_PATH = ROOT_DIR / "miniapp_points.json"
DEFAULT_AUDIT_PATH = ROOT_DIR / "output" / "capture_audit.json"
CLASH_CONFIG_PATH = Path("/home/hetaisheng/clash/config.yaml")
CLASH_MITM_BACKUP_PATH = Path("/home/hetaisheng/clash/config.yaml.bak-dianping-mitm-active")


@dataclass
class ManualCaptureState:
    mitm_running: bool
    proxy_port: int
    system_proxy_port: int
    scroll_running: bool
    window_name: str
    scroll_all_windows: bool = False
    window_count: int = 0
    audit: Mapping[str, Any] = field(default_factory=dict)
    recent_reviews: list[Mapping[str, Any]] = field(default_factory=list)
    review_progress: Mapping[str, Any] = field(default_factory=dict)
    next_store: Mapping[str, Any] = field(default_factory=dict)
    message: str = ""


class ManualCaptureController:
    default_scroll_pause = 0.05
    default_scroll_batch = 8
    default_scroll_idle_timeout = 8.0
    default_scroll_max_duration = 90.0
    reliable_fast_scroll_pause = 0.02
    reliable_fast_scroll_batch = 16
    reliable_fast_page_wait_timeout = 2.5
    reliable_fast_idle_timeout = 6.0
    reliable_fast_max_duration = 150.0

    def __init__(
        self,
        *,
        proxy_port: int = DEFAULT_PROXY_PORT,
        clash_port: int = DEFAULT_CLASH_PORT,
        upstream_proxy: Optional[str] = None,
        excel_path: Path = DEFAULT_EXCEL_PATH,
        log_dir: Path = DEFAULT_LOG_DIR,
        output_path: Path = DEFAULT_OUTPUT_PATH,
        points_path: Path = DEFAULT_POINTS_PATH,
    ):
        self.proxy_port = proxy_port
        self.clash_port = clash_port
        self.upstream_proxy = upstream_proxy or f"http://127.0.0.1:{clash_port}/"
        self.excel_path = excel_path
        self.log_dir = log_dir
        self.output_path = output_path
        self.points_path = points_path
        self.mitm_process: Optional[subprocess.Popen] = None
        self.restore_proxy = None
        self.scroll_thread: Optional[threading.Thread] = None
        self.scroll_stop = threading.Event()
        self.scroll_all_windows = False
        self.message = ""
        self._status_cache: Optional[tuple[float, Mapping[str, Any], list[Any]]] = None
        self.status_cache_ttl = 15.0

    def start_proxy(self) -> str:
        if current_system_proxy_port() != self.clash_port:
            restore_clash_proxy(self.clash_port)
        process = self._ensure_mitm("")
        if process is None and not port_open("127.0.0.1", self.proxy_port):
            self.message = f"mitm 未运行: 127.0.0.1:{self.proxy_port}"
            return self.message
        upstream_text = f"；无上游，避免 {self.clash_port}/{self.proxy_port} 回环"
        self.message = (
            f"mitm 已开启: 127.0.0.1:{self.proxy_port}{upstream_text}；"
            f"未修改 Clash，系统代理保持 {self.clash_port}"
        )
        return self.message

    def enable_dianping_split_proxy(self) -> str:
        process = self._ensure_mitm("")
        if process is None and not port_open("127.0.0.1", self.proxy_port):
            self.message = "先点开始代理，确认 mitm 监听后再开启点评 API 分流"
            return self.message
        enable_clash_mitm_rule(self.proxy_port, include_search_domains=False)
        self.message = (
            f"已开启点评 API 分流: 仅 mapi.* -> 127.0.0.1:{self.proxy_port}；"
            f"系统代理保持 {self.clash_port}"
        )
        return self.message

    def enable_full_tunnel_proxy(self) -> str:
        process = self._ensure_mitm(self.upstream_proxy)
        if process is None and not port_open("127.0.0.1", self.proxy_port):
            self.message = "先点开始代理，确认 mitm 监听后再开启全链路诊断代理"
            return self.message
        disable_clash_mitm_rule()
        if self.restore_proxy is None:
            self.restore_proxy = configure_system_proxy("127.0.0.1", self.proxy_port, register_signals=False)
        else:
            configure_system_proxy("127.0.0.1", self.proxy_port, register_signals=False)
        self.message = (
            f"已开启全链路诊断代理: 系统代理 -> 127.0.0.1:{self.proxy_port} -> "
            f"{self.clash_port} 上游；用于验证小程序上下文，停止代理会恢复 {self.clash_port}"
        )
        return self.message

    def disable_dianping_split_proxy(self) -> str:
        disable_clash_mitm_rule()
        self.message = f"点评 API 分流已关闭；系统代理保持 {self.clash_port}"
        return self.message

    def stop_proxy(self) -> str:
        self.stop_scroll()
        if self.restore_proxy is not None:
            self.restore_proxy()
            self.restore_proxy = None
        stop_started_mitm(self.mitm_process)
        self.mitm_process = None
        restore_clash_proxy(self.clash_port)
        self.message = f"mitm 已停止；点评 API 分流规则保留；系统代理保持 {self.clash_port}"
        return self.message

    def _ensure_mitm(self, upstream_proxy: str) -> Optional[subprocess.Popen]:
        if port_open("127.0.0.1", self.proxy_port):
            command = active_mitmdump_command(self.proxy_port)
            if command and not mitmdump_command_matches_upstream(command, self.proxy_port, upstream_proxy):
                stop_mitmdump_on_port(self.proxy_port)
            else:
                return self.mitm_process
        if port_open("127.0.0.1", self.proxy_port):
            return self.mitm_process
        log_path = self.log_dir / "manual_mitmdump.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            build_mitmdump_command(self.proxy_port, upstream_proxy),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            env=build_mitmdump_env(),
        )
        deadline = time.time() + 10
        while time.time() < deadline:
            if process.poll() is not None:
                self.message = f"mitmdump 启动失败，见 {log_path}"
                return None
            if port_open("127.0.0.1", self.proxy_port):
                self.mitm_process = process
                return process
            time.sleep(0.2)
        process.terminate()
        self.message = f"mitmdump 未监听 127.0.0.1:{self.proxy_port}"
        return None

    def start_scroll(
        self,
        *,
        pause: float = None,
        batch: int = None,
        all_windows: bool = False,
        idle_timeout: float = None,
        max_duration: float = None,
        page_wait_timeout: float = None,
        mode_name: str = "普通",
    ) -> str:
        if self.scroll_thread and self.scroll_thread.is_alive():
            self.message = "滚动已在运行"
            return self.message
        if pause is None:
            pause = self.default_scroll_pause
        if batch is None:
            batch = self.default_scroll_batch
        if idle_timeout is None:
            idle_timeout = self.default_scroll_idle_timeout
        if max_duration is None:
            max_duration = self.default_scroll_max_duration
        if page_wait_timeout is None:
            page_wait_timeout = min(max(idle_timeout / 2, 1.0), 3.0)
        windows = find_miniapp_windows() if all_windows else [find_miniapp_window()]
        windows = [window for window in windows if window is not None]
        if not windows:
            self.message = "未找到大众点评小程序窗口"
            return self.message
        points = load_points(self.points_path)
        events_offset = current_events_offset(DEFAULT_EVENTS_PATH)
        self.scroll_stop.clear()
        self.scroll_all_windows = all_windows
        self.scroll_thread = threading.Thread(
            target=self._scroll_loop,
            args=(windows, points, pause, batch, events_offset, idle_timeout, max_duration, page_wait_timeout),
            daemon=True,
        )
        self.scroll_thread.start()
        self.message = (
            f"开始{mode_name}滚动: {len(windows)} 个窗口；"
            f"isEnd 才算完整，{idle_timeout:g}s 无新页释放鼠标，最长 {max_duration:g}s"
        )
        return self.message

    def start_reliable_fast_scroll(self, *, all_windows: bool = False) -> str:
        return self.start_scroll(
            pause=self.reliable_fast_scroll_pause,
            batch=self.reliable_fast_scroll_batch,
            all_windows=all_windows,
            idle_timeout=self.reliable_fast_idle_timeout,
            max_duration=self.reliable_fast_max_duration,
            page_wait_timeout=self.reliable_fast_page_wait_timeout,
            mode_name="可靠极速",
        )

    def _scroll_loop(
        self,
        windows: list[WindowInfo],
        points: Points,
        pause: float,
        batch: int,
        events_offset: int,
        idle_timeout: float,
        max_duration: float,
        page_wait_timeout: float,
    ) -> None:
        tracker = ScrollCompletionTracker(
            started_at=time.time(),
            idle_timeout=idle_timeout,
            max_duration=max_duration,
        )
        offset = events_offset
        stop_reason = ""
        try:
            while not self.scroll_stop.is_set():
                for window in windows:
                    if self.scroll_stop.is_set():
                        break
                    scroll_reviews(window, points, 1, pause, batch=max(batch, 1))
                    events, offset = read_new_events_until(DEFAULT_EVENTS_PATH, offset, timeout=page_wait_timeout)
                    now = time.time()
                    stop_reason = tracker.observe(events, now=now) or tracker.timeout_reason(now=now)
                    if stop_reason:
                        self.scroll_stop.set()
                        break
                if not stop_reason:
                    stop_reason = tracker.timeout_reason(now=time.time())
                    if stop_reason:
                        self.scroll_stop.set()
        finally:
            self.scroll_all_windows = False
            release_mouse_from_windows(windows)
            self.rescue_dead_proxy_if_needed()
        if stop_reason:
            self.message = f"滚动自动停止: {stop_reason}"
            # 自动导出：滚动结束后立刻把当前店写入 output/store_reviews/<NNN>_<name>.json
            try:
                stats = export_reviews(self.excel_path, self.log_dir, self.output_path, DEFAULT_STORE_OUTPUT_DIR)
                self.message += (
                    f" | 已自动导出: 完整门店 {stats['stores_with_reviews']}/{stats['stores_in_excel']}, "
                    f"评论 {stats['reviews_exported']} 条"
                )
            except Exception as exc:
                self.message += f" | 自动导出失败: {exc}"

    def stop_scroll(self) -> str:
        self.scroll_stop.set()
        if self.scroll_thread and self.scroll_thread.is_alive():
            self.scroll_thread.join(timeout=3)
        self.scroll_all_windows = False
        self.message = "滚动已停止"
        return self.message

    def export(self) -> str:
        stats = export_reviews(self.excel_path, self.log_dir, self.output_path, DEFAULT_STORE_OUTPUT_DIR)
        report = audit(self.excel_path, self.log_dir, output_path=self.output_path, report_path=DEFAULT_AUDIT_PATH)
        self.message = (
            f"导出完成: 门店 {stats['stores_with_reviews']}/{stats['stores_in_excel']}，"
            f"评论 {stats['reviews_exported']}，缺失 {report['stats']['stores_missing_reviews']}"
        )
        return self.message

    def status(self) -> ManualCaptureState:
        self.rescue_dead_proxy_if_needed()
        window = find_miniapp_window()
        windows = find_miniapp_windows()
        report, stores = self._cached_report_and_stores()
        mitm_running = port_open("127.0.0.1", self.proxy_port)
        return ManualCaptureState(
            mitm_running=mitm_running,
            proxy_port=self.proxy_port,
            system_proxy_port=current_system_proxy_port(),
            scroll_running=bool(self.scroll_thread and self.scroll_thread.is_alive()),
            scroll_all_windows=self.scroll_all_windows,
            window_name=window.name if window else "",
            window_count=len(windows),
            audit=report,
            recent_reviews=recent_review_events(DEFAULT_EVENTS_PATH, limit=12),
            review_progress=review_progress_summary(recent_review_events(DEFAULT_EVENTS_PATH, limit=80)),
            next_store=next_missing_store_info(stores, report),
            message=self.message,
        )

    def _cached_report_and_stores(self) -> tuple[Mapping[str, Any], list[Any]]:
        now = time.time()
        if self._status_cache and now - self._status_cache[0] < self.status_cache_ttl:
            return self._status_cache[1], self._status_cache[2]
        report = load_cached_audit_report(DEFAULT_AUDIT_PATH)
        if not report:
            try:
                report = audit(self.excel_path, self.log_dir, output_path=self.output_path, report_path=DEFAULT_AUDIT_PATH)
            except Exception as exc:
                report = {"error": str(exc), "stats": {}}
        stores = load_stores_from_xlsx(self.excel_path)
        self._status_cache = (now, report, stores)
        return report, stores

    def cleanup(self) -> None:
        self.stop_proxy()

    def rescue_dead_proxy_if_needed(self) -> None:
        mitm_running = port_open("127.0.0.1", self.proxy_port)
        mitm_https_ok: Optional[bool] = None
        if current_system_proxy_port() == self.proxy_port and mitm_running:
            mitm_https_ok = mitm_https_probe(self.proxy_port)
        if proxy_needs_rescue(
            system_proxy_port=current_system_proxy_port(),
            mitm_running=mitm_running,
            proxy_port=self.proxy_port,
            mitm_https_ok=mitm_https_ok,
        ):
            if self.restore_proxy is not None:
                self.restore_proxy()
                self.restore_proxy = None
            restore_clash_proxy(self.clash_port)
            self.message = (
                f"检测到系统代理指向 {self.proxy_port} 但 mitm 未运行，"
                f"已自动恢复到 {self.clash_port}"
            )


def recent_review_events(path: Path, limit: int = 12) -> list[Dict[str, Any]]:
    events, _offset = read_events(path, 0)
    reviews = [event for event in events if event.get("type") == "review"]
    return reviews[-limit:]


def load_cached_audit_report(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def current_events_offset(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        return f.tell()


def read_new_events_until(path: Path, offset: int, *, timeout: float) -> tuple[list[Dict[str, Any]], int]:
    deadline = time.time() + max(timeout, 0)
    while True:
        events, new_offset = read_events(path, offset)
        if events or time.time() >= deadline:
            return events, new_offset
        time.sleep(0.05)


def is_terminal_review_event(event: Mapping[str, Any]) -> bool:
    return is_full_page_review_event(event) and event.get("isEnd") is True


def is_full_page_review_event(event: Mapping[str, Any]) -> bool:
    if event.get("type") != "review":
        return False
    url = str(event.get("url") or "").lower()
    return "outsidesiftedreviewlist" in url or "outsideshopreviewlist" in url


def numeric_event_start(event: Mapping[str, Any]) -> Optional[int]:
    value = str(event.get("start") or "").strip()
    return int(value) if value.isdigit() else None


def review_progress_summary(events: list[Mapping[str, Any]]) -> Dict[str, Any]:
    full_events = [event for event in events if is_full_page_review_event(event)]
    if not full_events:
        return {}
    active_shopuuid = str(full_events[-1].get("shopuuid") or "")
    shop_events = [
        event for event in full_events if not active_shopuuid or str(event.get("shopuuid") or "") == active_shopuuid
    ]
    seen_pages: set[tuple[str, str, str]] = set()
    unique_starts: list[str] = []
    duplicate_pages = 0
    resets = 0
    previous_start: Optional[int] = None
    total_reviews = 0
    is_end = False
    latest = shop_events[-1]
    for event in shop_events:
        start_text = str(event.get("start") or "")
        page_key = (
            str(event.get("shopuuid") or ""),
            start_text,
            str(event.get("nextStartIndex") or ""),
        )
        if page_key in seen_pages:
            duplicate_pages += 1
        else:
            seen_pages.add(page_key)
            unique_starts.append(start_text)
            total_reviews += int(event.get("review_count") or 0)
        current_start = numeric_event_start(event)
        if current_start is not None and previous_start is not None and current_start < previous_start:
            resets += 1
        if current_start is not None:
            previous_start = current_start
        if event.get("isEnd") is True:
            is_end = True
    status = "complete" if is_end else "stalled" if resets or duplicate_pages >= 3 else "running"
    return {
        "shopuuid": active_shopuuid,
        "storeName": str(latest.get("storeName") or ""),
        "status": status,
        "unique_pages": len(seen_pages),
        "unique_starts": unique_starts,
        "duplicate_pages": duplicate_pages,
        "resets": resets,
        "total_reviews": total_reviews,
        "nextStartIndex": str(latest.get("nextStartIndex") or ""),
        "isEnd": is_end,
    }


@dataclass
class ScrollCompletionTracker:
    started_at: float
    idle_timeout: float
    max_duration: float
    active_shopuuid: str = ""
    last_progress_at: float = 0.0
    total_pages: int = 0
    total_reviews: int = 0
    duplicate_pages: int = 0
    resets: int = 0
    completion_status: str = "running"
    seen_pages: set[tuple[str, str, str, str]] = field(default_factory=set)
    last_any_event_at: float = 0.0
    highest_start: int = -1

    def observe(self, events: list[Mapping[str, Any]], *, now: float) -> Optional[str]:
        for event in events:
            if not is_full_page_review_event(event):
                continue
            shopuuid = str(event.get("shopuuid") or "")
            if self.active_shopuuid and shopuuid and shopuuid != self.active_shopuuid:
                continue
            if not self.active_shopuuid and shopuuid:
                self.active_shopuuid = shopuuid
            self.last_any_event_at = now

            page_key = (
                shopuuid,
                str(event.get("start") or ""),
                str(event.get("nextStartIndex") or ""),
            )
            if page_key not in self.seen_pages:
                self.seen_pages.add(page_key)
                self.total_pages += 1
                self.total_reviews += int(event.get("review_count") or 0)
                self.last_progress_at = now
            else:
                self.duplicate_pages += 1

            current_start = numeric_event_start(event)
            if current_start is not None:
                if self.highest_start >= 0 and current_start < self.highest_start:
                    self.resets += 1
                    self.completion_status = "stalled"
                    return (
                        f"{self.active_shopuuid or shopuuid or 'unknown'} 分页回退 "
                        f"{self.highest_start}->{current_start}，已释放鼠标；"
                        f"新增 {self.total_pages} 页 / {self.total_reviews} 条，重复页 {self.duplicate_pages} 次"
                    )
                self.highest_start = max(self.highest_start, current_start)

            if is_terminal_review_event(event):
                self.completion_status = "complete"
                shop = self.active_shopuuid or shopuuid or "unknown"
                return f"{shop} isEnd=true，新增 {self.total_pages} 页 / {self.total_reviews} 条"
        return None

    def timeout_reason(self, *, now: float) -> Optional[str]:
        if now - self.started_at >= self.max_duration:
            self.completion_status = "suspect"
            return (
                f"达到最长滚动时间 {self.max_duration:g}s，新增 {self.total_pages} 页 / "
                f"{self.total_reviews} 条，重复页 {self.duplicate_pages} 次"
            )
        reference_time = self.last_any_event_at or self.last_progress_at
        if self.total_pages > 0 and reference_time and now - reference_time >= self.idle_timeout:
            self.completion_status = "suspect"
            return (
                f"{self.idle_timeout:g}s 没有新评论页，新增 {self.total_pages} 页 / "
                f"{self.total_reviews} 条，重复页 {self.duplicate_pages} 次"
            )
        return None


def current_system_proxy_port() -> int:
    result = subprocess.run(
        ["gsettings", "get", "org.gnome.system.proxy.http", "port"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def proxy_needs_rescue(
    *,
    system_proxy_port: int,
    mitm_running: bool,
    proxy_port: int,
    mitm_https_ok: Optional[bool] = None,
) -> bool:
    if system_proxy_port != proxy_port:
        return False
    if not mitm_running:
        return True
    return mitm_https_ok is False


def proxy_mode_needs_mitm(*, system_proxy_port: int, mitm_running: bool, proxy_port: int) -> bool:
    return system_proxy_port == proxy_port and mitm_running


def active_mitmdump_command(proxy_port: int) -> str:
    result = subprocess.run(
        ["pgrep", "-af", "mitmdump"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    needle = f"--listen-port {proxy_port}"
    for line in result.stdout.splitlines():
        if needle in line:
            return line
    return ""


def mitmdump_command_matches_upstream(command: str, proxy_port: int, upstream_proxy: str) -> bool:
    if f"--listen-port {proxy_port}" not in command:
        return False
    tokens = shlex.split(command)
    upstream_mode = f"upstream:{upstream_proxy}" if upstream_proxy else ""
    if "--mode" not in tokens:
        return upstream_proxy == ""
    try:
        mode_value = tokens[tokens.index("--mode") + 1]
    except IndexError:
        return upstream_proxy == ""
    return mode_value == upstream_mode


def stop_mitmdump_on_port(proxy_port: int) -> None:
    result = subprocess.run(
        ["pgrep", "-af", "mitmdump"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    needle = f"--listen-port {proxy_port}"
    for line in result.stdout.splitlines():
        if needle not in line:
            continue
        pid = line.split(maxsplit=1)[0]
        if pid.isdigit():
            subprocess.run(["kill", pid], timeout=5, check=False)
    deadline = time.time() + 5
    while time.time() < deadline and port_open("127.0.0.1", proxy_port):
        time.sleep(0.1)


def mitm_https_probe(proxy_port: int) -> bool:
    result = subprocess.run(
        [
            "curl",
            "-x",
            f"http://127.0.0.1:{proxy_port}",
            "-k",
            "-sS",
            "--max-time",
            "5",
            "https://www.baidu.com/",
            "-o",
            os.devnull,
        ],
        capture_output=True,
        text=True,
        timeout=7,
        check=False,
    )
    return result.returncode == 0


def release_mouse_from_windows(windows: list[WindowInfo]) -> None:
    for button in ("1", "2", "3", "4", "5"):
        run_xdotool(["mouseup", button])
    if not windows:
        run_xdotool(["mousemove", "20", "20"])
        return
    left = min(window.x for window in windows)
    top = min(window.y for window in windows)
    run_xdotool(["mousemove", str(max(0, left - 20)), str(max(0, top - 20))])


def clash_config_has_mitm_rule(text: str) -> bool:
    return "name: DP-MITM" in text and "DOMAIN-SUFFIX,mapi.dianping.com,DP-MITM" in text


def remove_clash_mitm_rule_text(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == "- name: DP-MITM":
            index += 1
            while index < len(lines):
                current = lines[index]
                stripped = current.strip()
                if stripped.startswith("- ") or current in {"rules:", "proxy-groups:"} or (
                    current and not current.startswith((" ", "\t", "-"))
                ):
                    break
                index += 1
            continue
        stripped = line.strip()
        if stripped.startswith("- DOMAIN") and stripped.endswith(",DP-MITM"):
            index += 1
            continue
        output.append(line)
        index += 1
    return "\n".join(output) + ("\n" if text.endswith("\n") else "")


def inject_clash_mitm_rule_text(text: str, *, proxy_port: int, include_search_domains: bool = True) -> str:
    text = remove_clash_mitm_rule_text(text)
    if clash_config_has_mitm_rule(text):
        return text
    if "proxies:\n" not in text or "rules:\n" not in text:
        raise ValueError("Clash config missing proxies:/rules: sections")
    patch = build_clash_mitm_patch("DP-MITM", proxy_port, include_search_domains=include_search_domains)
    proxy_block, rule_block = patch.split("\n\nrules:\n", 1)
    proxy_lines = "\n".join(proxy_block.splitlines()[1:]) + "\n"
    rule_lines = "\n".join(f" {line.strip()}" for line in rule_block.splitlines() if line.strip()) + "\n"
    text = text.replace("proxies:\n", f"proxies:\n{proxy_lines}", 1)
    text = text.replace("rules:\n", f"rules:\n{rule_lines}", 1)
    return text


def reload_clash_config(config_path: Path = CLASH_CONFIG_PATH) -> None:
    # 必须带 ?force=true，否则 Clash 看 path 没变会跳过 reload，
    # 导致 config.yaml 里加了 DP-MITM 规则但内存里仍是旧规则。
    subprocess.run(
        [
            "curl",
            "-sS",
            "-X",
            "PUT",
            "http://127.0.0.1:9090/configs?force=true",
            "-H",
            "Content-Type: application/json",
            "--data",
            json.dumps({"path": str(config_path)}),
        ],
        timeout=10,
        check=False,
    )


def enable_clash_mitm_rule(
    proxy_port: int,
    config_path: Path = CLASH_CONFIG_PATH,
    *,
    include_search_domains: bool = True,
) -> None:
    original = config_path.read_text(encoding="utf-8")
    if not CLASH_MITM_BACKUP_PATH.exists():
        CLASH_MITM_BACKUP_PATH.write_text(original, encoding="utf-8")
    patched = inject_clash_mitm_rule_text(
        original,
        proxy_port=proxy_port,
        include_search_domains=include_search_domains,
    )
    if patched != original:
        config_path.write_text(patched, encoding="utf-8")
    reload_clash_config(config_path)


def disable_clash_mitm_rule(config_path: Path = CLASH_CONFIG_PATH) -> None:
    if CLASH_MITM_BACKUP_PATH.exists():
        config_path.write_text(CLASH_MITM_BACKUP_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        CLASH_MITM_BACKUP_PATH.unlink(missing_ok=True)
        reload_clash_config(config_path)


def restore_clash_proxy(clash_port: int = DEFAULT_CLASH_PORT) -> None:
    commands = [
        ["gsettings", "set", "org.gnome.system.proxy.http", "host", "127.0.0.1"],
        ["gsettings", "set", "org.gnome.system.proxy.http", "port", str(clash_port)],
        ["gsettings", "set", "org.gnome.system.proxy.https", "host", "127.0.0.1"],
        ["gsettings", "set", "org.gnome.system.proxy.https", "port", str(clash_port)],
    ]
    for command in commands:
        subprocess.run(command, timeout=5, check=False)


def next_missing_store_info(stores: list[Any], audit_report: Mapping[str, Any]) -> Dict[str, Any]:
    missing = audit_report.get("missing_stores")
    if not isinstance(missing, list) or not missing:
        return {}
    missing_name = str(missing[0])
    for index, store in enumerate(stores, start=1):
        if store.name != missing_name:
            continue
        keywords = keyword_variants_for_store(store)
        return {
            "index": index,
            "store": store.name,
            "address": store.address,
            "city": city_from_address(store.address),
            "keyword": keywords[0] if keywords else store.name,
        }
    return {"store": missing_name, "keyword": missing_name}


def find_miniapp_windows() -> list[WindowInfo]:
    result = run_xdotool(["search", "--name", "大众点评"])
    windows: Dict[str, WindowInfo] = {}
    for window_id in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
        info = get_window_info(window_id)
        if info:
            windows[window_id] = info
    if not windows:
        single = find_miniapp_window()
        return [single] if single else []
    return sorted(windows.values(), key=lambda item: (item.x, item.y, item.window_id))


def render_html(state: ManualCaptureState) -> str:
    stats = dict((state.audit or {}).get("stats") or {})
    captured = (state.audit or {}).get("captured_stores") or []
    missing = (state.audit or {}).get("missing_stores") or []
    progress = dict(state.review_progress or {})
    rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(item.get('timestamp', '')))}</td>"
        f"<td>{escape(str(item.get('storeName', '')))}</td>"
        f"<td>{escape(str(item.get('shopuuid', '')))}</td>"
        f"<td>{escape(str(item.get('review_count', '')))}</td>"
        f"<td>{escape(str(item.get('start', '')))}</td>"
        f"<td>{escape(str(item.get('url', '')))}</td>"
        "</tr>"
        for item in state.recent_reviews
    )
    captured_rows = "\n".join(
        f"<li>{escape(str(item.get('门店', '')))}: {escape(str(item.get('评论数', '')))} 条</li>"
        for item in captured[:20]
    )
    missing_rows = "\n".join(f"<li>{escape(str(name))}</li>" for name in missing[:20])
    next_store = dict(state.next_store or {})
    next_store_html = ""
    if next_store:
        next_store_html = f"""
  <div class="card">
    <h2>下一家待采</h2>
    <p>#{escape(str(next_store.get('index', '')))} {escape(str(next_store.get('store', '')))}</p>
    <p>城市：<code>{escape(str(next_store.get('city', '')))}</code></p>
    <p>搜索词：<code>{escape(str(next_store.get('keyword', '')))}</code></p>
    <p>地址：{escape(str(next_store.get('address', '')))}</p>
  </div>"""
    progress_html = ""
    if progress:
        starts = ", ".join(str(item) for item in progress.get("unique_starts", [])[-12:])
        progress_html = f"""
  <div class="card">
    <h2>当前评论进度</h2>
    <p>门店：{escape(str(progress.get('storeName', '')))} <code>{escape(str(progress.get('shopuuid', '')))}</code></p>
    <p>状态：<code>{escape(str(progress.get('status', '')))}</code>；唯一页 {escape(str(progress.get('unique_pages', 0)))}；
    估算新增 {escape(str(progress.get('total_reviews', 0)))} 条；重复页 {escape(str(progress.get('duplicate_pages', 0)))}；
    回退 {escape(str(progress.get('resets', 0)))}</p>
    <p>start：<code>{escape(starts)}</code>；nextStartIndex：<code>{escape(str(progress.get('nextStartIndex', '')))}</code>；
    isEnd：<code>{escape(str(progress.get('isEnd', '')))}</code></p>
  </div>"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="5">
  <title>大众点评评论半自动采集</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; color: #202124; }}
    .bar {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 16px 0; }}
    button {{ padding: 9px 14px; border: 1px solid #ddd; background: #fff; border-radius: 6px; cursor: pointer; }}
    button.primary {{ background: #ff6d38; color: #fff; border-color: #ff6d38; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .card {{ border: 1px solid #e0e0e0; border-radius: 6px; padding: 14px; }}
    .ok {{ color: #137333; }} .bad {{ color: #b3261e; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 6px; text-align: left; vertical-align: top; }}
    code {{ background: #f5f5f5; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>大众点评评论半自动采集</h1>
  <div class="card">
    <strong>用法：</strong>先点“开始代理”。控制台只启动 mitm，不修改 Clash；国内网络继续走你的 Clash 端口。
    需要抓包时再点“开启点评 API 分流”，它只分流 <code>mapi.*</code> 到 9092，不代理整站页面。
  </div>
  <div class="bar">
    <form method="post" action="/action"><input type="hidden" name="name" value="start_proxy"><button class="primary">开始代理</button></form>
    <form method="post" action="/action"><input type="hidden" name="name" value="enable_split"><button>开启点评 API 分流</button></form>
    <form method="post" action="/action"><input type="hidden" name="name" value="enable_full_tunnel"><button>全链路诊断代理</button></form>
    <form method="post" action="/action"><input type="hidden" name="name" value="disable_split"><button>关闭点评 API 分流</button></form>
    <form method="post" action="/action"><input type="hidden" name="name" value="stop_proxy"><button>停止代理/恢复网络</button></form>
    <form method="post" action="/action"><input type="hidden" name="name" value="start_reliable_fast"><button class="primary">可靠极速采当前店</button></form>
    <form method="post" action="/action"><input type="hidden" name="name" value="start_reliable_fast_all"><button class="primary">可靠极速采所有窗口</button></form>
    <form method="post" action="/action"><input type="hidden" name="name" value="start_scroll"><button>普通滚动当前窗口</button></form>
    <form method="post" action="/action"><input type="hidden" name="name" value="stop_scroll"><button>停止滚动</button></form>
    <form method="post" action="/action"><input type="hidden" name="name" value="export"><button>导出 JSON</button></form>
    <form method="get" action="/"><button>刷新</button></form>
  </div>
  <div class="grid">
    <div class="card">代理: <span class="{'ok' if state.mitm_running else 'bad'}">{'运行中' if state.mitm_running else '未运行'}</span> <code>127.0.0.1:{state.proxy_port}</code></div>
    <div class="card">系统代理端口: <code>{escape(str(state.system_proxy_port))}</code></div>
    <div class="card">滚动: <span class="{'ok' if state.scroll_running else 'bad'}">{'运行中' if state.scroll_running else '未运行'}</span>{'（所有窗口）' if state.scroll_all_windows else ''} <small>可靠极速 {ManualCaptureController.reliable_fast_scroll_batch} 次/轮，间隔 {ManualCaptureController.reliable_fast_scroll_pause}s；只有 isEnd 算完整，{ManualCaptureController.reliable_fast_idle_timeout:g}s 无新页释放鼠标</small></div>
    <div class="card">小程序窗口数: {escape(str(state.window_count))}</div>
    <div class="card">窗口: {escape(state.window_name or '未找到')}</div>
    <div class="card">已导出门店: {escape(str(stats.get('stores_with_reviews', 0)))} / {escape(str(stats.get('stores_in_excel', 0)))}</div>
    <div class="card">导出评论: {escape(str(stats.get('reviews_exported', 0)))}</div>
    <div class="card">缺失门店: {escape(str(stats.get('stores_missing_reviews', 0)))}</div>
  </div>
  <p>{escape(state.message)}</p>
  {progress_html}
  {next_store_html}
  <h2>最近评论事件</h2>
  <table><thead><tr><th>时间</th><th>门店</th><th>shopuuid</th><th>条数</th><th>start</th><th>接口</th></tr></thead><tbody>{rows}</tbody></table>
  <div class="grid">
    <div class="card"><h2>已采集前 20</h2><ul>{captured_rows}</ul></div>
    <div class="card"><h2>缺失前 20</h2><ul>{missing_rows}</ul></div>
  </div>
</body>
</html>"""


class ConsoleHandler(BaseHTTPRequestHandler):
    controller: ManualCaptureController

    def do_GET(self) -> None:
        self._send_html(render_html(self.controller.status()))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/action":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        action = parse_qs(body).get("name", [""])[0]
        try:
            if action == "start_proxy":
                self.controller.start_proxy()
            elif action == "enable_split":
                self.controller.enable_dianping_split_proxy()
            elif action == "enable_full_tunnel":
                self.controller.enable_full_tunnel_proxy()
            elif action == "disable_split":
                self.controller.disable_dianping_split_proxy()
            elif action == "stop_proxy":
                self.controller.stop_proxy()
            elif action == "start_reliable_fast":
                self.controller.start_reliable_fast_scroll()
            elif action == "start_reliable_fast_all":
                self.controller.start_reliable_fast_scroll(all_windows=True)
            elif action == "start_scroll":
                self.controller.start_scroll()
            elif action == "start_scroll_all":
                self.controller.start_scroll(all_windows=True)
            elif action == "stop_scroll":
                self.controller.stop_scroll()
            elif action == "export":
                self.controller.export()
            else:
                self.controller.message = f"未知操作: {action}"
        except Exception as exc:
            self.controller.message = f"操作失败: {exc}"
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[console] {self.address_string()} {fmt % args}")

    def _send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_server(host: str, port: int, controller: ManualCaptureController, open_browser: bool) -> None:
    ConsoleHandler.controller = controller
    server = ThreadingHTTPServer((host, port), ConsoleHandler)

    def shutdown(signum: int, _frame: object) -> None:
        controller.cleanup()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    url = f"http://{host}:{port}/"
    print(f"半自动采集控制台: {url}")
    if open_browser:
        webbrowser.open(url)
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="大众点评评论半自动采集网页控制台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_CONSOLE_PORT)
    parser.add_argument("--proxy-port", type=int, default=DEFAULT_PROXY_PORT)
    parser.add_argument("--clash-port", type=int, default=DEFAULT_CLASH_PORT)
    parser.add_argument("--upstream-proxy", default=None)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()

    controller = ManualCaptureController(
        proxy_port=args.proxy_port,
        clash_port=args.clash_port,
        upstream_proxy=args.upstream_proxy,
    )
    run_server(args.host, args.port, controller, args.open_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
