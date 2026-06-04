import unittest

from auto_shop_uuid_resolver import Candidate
from dianping_events import build_event
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from miniapp_state_machine import (
    EventWatcher,
    Points,
    ReviewCaptureFailed,
    ReviewCaptureTracker,
    UiSnapshot,
    WindowInfo,
    choose_miniapp_window,
    build_clash_mitm_patch,
    build_mitmdump_env,
    build_mitmdump_command,
    classify_ui_snapshot,
    capture_current_detail_reviews,
    release_mouse,
    focus_window,
    refresh_window,
    is_plausible_miniapp_window,
    should_try_current_detail_capture,
    latest_confirmed_city_ids,
    high_throughput_defaults,
    mitmdump_has_search_rewrite_env,
    open_candidate_and_reviews,
    open_full_review_page,
    point_inside_window,
    dismiss_blocking_overlays,
    should_try_known_uuid_current_detail_capture,
    reset_to_searchable_state,
    review_event_matches_candidate,
    start_mitm_if_needed,
    snapshot_needs_left_back_reset,
    unresolved_stores,
    review_capture_complete,
    review_target_from_event,
)
from review_exporter import Store

ROOT = Path(__file__).resolve().parent.parent


def review_event(start: str, next_start: str, *, is_end: bool = False, count: int = 14):
    return {
        "type": "review",
        "shopuuid": "shop-1",
        "storeName": "达美乐比萨(测试店)",
        "review_count": count,
        "start": start,
        "nextStartIndex": next_start,
        "isEnd": is_end,
        "url": "https://mapi.dianping.com/mapi/review/outsidesiftedreviewlist.bin",
    }


class ReviewCaptureTrackerTests(unittest.TestCase):
    def test_window_selection_prefers_miniapp_title_over_large_wechat_host(self):
        large_host = WindowInfo(
            "host",
            "微信",
            76,
            32,
            2484,
            1568,
            pid="1",
            cmdline="/opt/wechat/RadiumWMPF/runtime/WeChatAppEx",
        )
        miniapp = WindowInfo(
            "mini",
            "大众点评美食电影运动旅游门票",
            1111,
            416,
            412,
            798,
            pid="1",
            cmdline="/opt/wechat/RadiumWMPF/runtime/WeChatAppEx",
        )

        self.assertEqual(choose_miniapp_window([large_host, miniapp]), miniapp)

    def test_large_wechat_host_is_not_a_plausible_miniapp_window(self):
        large_host = WindowInfo(
            "host",
            "微信",
            76,
            32,
            2484,
            1568,
            pid="1",
            cmdline="/opt/wechat/RadiumWMPF/runtime/WeChatAppEx",
        )

        self.assertFalse(is_plausible_miniapp_window(large_host))

    def test_refresh_window_refinds_miniapp_when_old_id_is_gone(self):
        old = WindowInfo("old", "大众点评美食电影运动旅游门票", 0, 0, 914, 882)
        new = WindowInfo("new", "大众点评美食电影运动旅游门票", 1111, 416, 412, 798)

        with (
            patch("miniapp_state_machine.get_window_info", return_value=None),
            patch("miniapp_state_machine.find_miniapp_window", return_value=new),
            patch("miniapp_state_machine.prepare_window", return_value=new) as prepare,
            patch("miniapp_state_machine.minimize_overlapping_windows"),
        ):
            refreshed = refresh_window(old)

        self.assertEqual(refreshed, new)
        prepare.assert_called_once_with(new)

    def test_focus_window_falls_back_when_sync_activation_times_out(self):
        import subprocess

        window = WindowInfo("1", "微信", 100, 50, 914, 882)
        calls = []

        def fake_run_xdotool(args):
            calls.append(args)
            if args == ["windowactivate", "--sync", "1"]:
                raise subprocess.TimeoutExpired(["xdotool", *args], timeout=10)
            if args == ["getactivewindow"]:
                return Mock(stdout="1\n", returncode=0)
            return Mock(stdout="", returncode=0)

        with (
            patch("miniapp_state_machine.run_xdotool", side_effect=fake_run_xdotool),
            patch("miniapp_state_machine.time.sleep"),
        ):
            focus_window(window)

        self.assertIn(["windowactivate", "1"], calls)
        self.assertIn(["windowfocus", "1"], calls)

    def test_release_mouse_sends_mouseup_before_moving_pointer(self):
        window = WindowInfo("1", "微信", 100, 50, 914, 882)

        with patch("miniapp_state_machine.run_xdotool") as run_xdotool:
            release_mouse(window)

        self.assertEqual(run_xdotool.call_args_list[0].args[0], ["mouseup", "1"])
        self.assertEqual(run_xdotool.call_args_list[1].args[0], ["mouseup", "2"])
        self.assertEqual(run_xdotool.call_args_list[2].args[0], ["mouseup", "3"])
        self.assertEqual(run_xdotool.call_args_list[3].args[0], ["mouseup", "4"])
        self.assertEqual(run_xdotool.call_args_list[4].args[0], ["mouseup", "5"])
        self.assertEqual(run_xdotool.call_args_list[-1].args[0], ["mousemove", "80", "30"])

    def test_scroll_reviews_releases_mouse_before_and_after_wheel_events(self):
        from miniapp_state_machine import scroll_reviews

        window = WindowInfo("1", "微信", 100, 50, 914, 882)
        points = Points()

        with (
            patch("miniapp_state_machine.focus_window"),
            patch("miniapp_state_machine.run_xdotool") as run_xdotool,
            patch("miniapp_state_machine.time.sleep"),
        ):
            scroll_reviews(window, points, count=1, pause=0, batch=6)

        calls = [call.args[0] for call in run_xdotool.call_args_list]
        self.assertEqual(calls[0:5], [["mouseup", "1"], ["mouseup", "2"], ["mouseup", "3"], ["mouseup", "4"], ["mouseup", "5"]])
        self.assertIn(["mousemove", "950", "770"], calls)
        self.assertIn(["click", "--repeat", "6", "--delay", "12", "5"], calls)
        self.assertEqual(calls[-5:], [["mouseup", "1"], ["mouseup", "2"], ["mouseup", "3"], ["mouseup", "4"], ["mouseup", "5"]])

    def test_review_event_with_wrong_uuid_is_not_accepted_by_store_name_fallback(self):
        store = Store("达美乐比萨(测试店)", "上海测试路1号")
        candidate = Candidate("shop-1", "达美乐比萨", "测试店", "", "1", "", "40条", "unit")
        wrong = review_event("0", "14")
        wrong["shopuuid"] = "wrong-shop"

        self.assertFalse(review_event_matches_candidate(wrong, candidate, store, full_only=True))

    def test_complete_only_on_is_end_or_target_count(self):
        tracker = ReviewCaptureTracker(target_reviews=40)

        self.assertIsNone(tracker.observe(review_event("0", "14")))
        self.assertIsNone(tracker.observe(review_event("14", "28")))
        self.assertFalse(tracker.complete(exported_count=28))
        self.assertTrue(tracker.complete(exported_count=40))

        tracker = ReviewCaptureTracker(target_reviews=0)
        self.assertIsNone(tracker.observe(review_event("0", "14")))
        self.assertFalse(tracker.complete(exported_count=14))
        self.assertIn("isEnd=true", tracker.observe(review_event("14", "28", is_end=True)) or "")
        self.assertTrue(tracker.complete(exported_count=28))

    def test_pagination_reset_marks_stalled_not_complete(self):
        tracker = ReviewCaptureTracker(target_reviews=0)

        self.assertIsNone(tracker.observe(review_event("0", "14")))
        self.assertIsNone(tracker.observe(review_event("14", "28")))
        reason = tracker.observe(review_event("0", "14"))

        self.assertIn("分页回退", reason or "")
        self.assertEqual(tracker.status, "stalled")
        self.assertFalse(tracker.complete(exported_count=28))

    def test_duplicate_pages_mark_suspect_after_threshold(self):
        tracker = ReviewCaptureTracker(target_reviews=0, duplicate_limit=2)
        page = review_event("0", "14")

        self.assertIsNone(tracker.observe(page))
        self.assertIsNone(tracker.observe(page))
        reason = tracker.observe(page)

        self.assertIn("重复页", reason or "")
        self.assertEqual(tracker.status, "stalled")

    def test_review_capture_complete_checks_target_or_is_end(self):
        store = Store("达美乐比萨(测试店)", "上海测试路1号")
        candidate = Candidate("shop-1", "达美乐比萨", "测试店", "", "1", "", "40条", "unit")

        self.assertFalse(review_capture_complete(store, candidate, exported_count=28, target_reviews=40, saw_is_end=False))
        self.assertFalse(review_capture_complete(store, candidate, exported_count=40, target_reviews=40, saw_is_end=False))
        self.assertTrue(review_capture_complete(store, candidate, exported_count=28, target_reviews=40, saw_is_end=True))

    def test_review_target_from_event_uses_total_count(self):
        self.assertEqual(review_target_from_event({"reviewTotalCount": "745"}), 745)
        self.assertEqual(review_target_from_event({"count": 423}), 423)
        self.assertEqual(review_target_from_event({}), 0)

    def test_review_event_includes_total_count_from_shop_review_module(self):
        event = build_event(
            url="https://mapi.dianping.com/mapi/review/outsideshopreviewlist.bin",
            params={"shopuuid": "shop-1"},
            data={
                "shopReviewInfo": {
                    "reviewTotalCount": 745,
                    "reviewList": [{"reviewId": "r1", "content": "很好"}],
                    "isEnd": False,
                },
                "topTitle": "评价(745)",
            },
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["reviewTotalCount"], "745")


class CityContextTests(unittest.TestCase):
    def test_latest_confirmed_city_ids_reads_recent_city_context(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"type":"city_context","cityId":"2"}',
                        '{"type":"detail","shopuuid":"old"}',
                        '{"type":"city_context","cityId":"1"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(latest_confirmed_city_ids(path), {"1"})


class MitmStartupTests(unittest.TestCase):
    def test_high_throughput_does_not_force_search_rewrite(self):
        defaults = high_throughput_defaults(18, 1.2)

        self.assertFalse(defaults["search_rewrite"])
        self.assertGreaterEqual(defaults["scroll_count"], 240)

    def test_default_mitmdump_command_has_no_upstream(self):
        command = build_mitmdump_command(9092)

        self.assertIn("--listen-port", command)
        self.assertNotIn("--mode", command)
        self.assertNotIn("upstream:", " ".join(command))

    def test_default_clash_patch_only_routes_comment_api_domains(self):
        patch_text = build_clash_mitm_patch("DP-MITM", 9092, include_search_domains=False)

        self.assertIn("DOMAIN-SUFFIX,mapi.dianping.com,DP-MITM", patch_text)
        self.assertIn("DOMAIN-SUFFIX,mapi.meituan.com,DP-MITM", patch_text)
        self.assertIn("DOMAIN-SUFFIX,mapi.sankuai.com,DP-MITM", patch_text)
        self.assertNotIn("DOMAIN-SUFFIX,m.dianping.com,DP-MITM", patch_text)
        self.assertNotIn("DOMAIN-SUFFIX,catfront.dianping.com,DP-MITM", patch_text)
        self.assertNotIn("DOMAIN-SUFFIX,lx0.meituan.com,DP-MITM", patch_text)

    def test_clash_patch_can_include_search_domains_for_autonomous_mode(self):
        patch_text = build_clash_mitm_patch("DP-MITM", 9092, include_search_domains=True)

        self.assertIn("DOMAIN-SUFFIX,m.dianping.com,DP-MITM", patch_text)
        self.assertIn("DOMAIN-SUFFIX,catfront.dianping.com,DP-MITM", patch_text)

    def test_build_mitmdump_env_strips_inherited_proxy_variables(self):
        env = build_mitmdump_env(
            {
                "PATH": "/bin",
                "http_proxy": "http://127.0.0.1:7890/",
                "HTTPS_PROXY": "http://127.0.0.1:7890/",
                "ALL_PROXY": "socks5://127.0.0.1:7891/",
            },
            search_rewrite=True,
        )

        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["DP_SEARCH_REWRITE"], "1")
        self.assertNotIn("http_proxy", env)
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertNotIn("ALL_PROXY", env)

    def test_restarts_existing_mitmdump_without_search_rewrite_when_required(self):
        fake_process = Mock()
        fake_process.poll.return_value = None
        fake_process.pid = 456

        with (
            patch("miniapp_state_machine.port_open", side_effect=[True, False, True]),
            patch("miniapp_state_machine.active_mitmdump_command", return_value="123 mitmdump --listen-port 9092"),
            patch("miniapp_state_machine.mitmdump_has_search_rewrite_env", return_value=False),
            patch("miniapp_state_machine.stop_mitmdump_on_port") as stop_port,
            patch("miniapp_state_machine.subprocess.Popen", return_value=fake_process) as popen,
        ):
            process = start_mitm_if_needed(9092, "", search_rewrite=True)

        self.assertIs(process, fake_process)
        stop_port.assert_called_once_with(9092)
        self.assertEqual(popen.call_args.kwargs["env"]["DP_SEARCH_REWRITE"], "1")

    def test_mitmdump_search_rewrite_env_reads_pid_environ(self):
        with (
            patch("miniapp_state_machine.mitmdump_pid_from_command", return_value="123"),
            patch("miniapp_state_machine.Path.read_bytes", return_value=b"DP_SEARCH_REWRITE=0\x00"),
        ):
            self.assertFalse(mitmdump_has_search_rewrite_env("123 mitmdump --listen-port 9092"))

        with (
            patch("miniapp_state_machine.mitmdump_pid_from_command", return_value="123"),
            patch("miniapp_state_machine.Path.read_bytes", return_value=b"DP_SEARCH_REWRITE=1\x00"),
        ):
            self.assertTrue(mitmdump_has_search_rewrite_env("123 mitmdump --listen-port 9092"))

    def test_restarts_existing_mitmdump_with_inherited_proxy_env(self):
        fake_process = Mock()
        fake_process.poll.return_value = None
        fake_process.pid = 456

        with (
            patch("miniapp_state_machine.port_open", side_effect=[True, False, True]),
            patch("miniapp_state_machine.active_mitmdump_command", return_value="123 mitmdump --listen-port 9092"),
            patch("miniapp_state_machine.mitmdump_env_is_safe", return_value=False),
            patch("miniapp_state_machine.stop_mitmdump_on_port") as stop_port,
            patch("miniapp_state_machine.subprocess.Popen", return_value=fake_process),
        ):
            start_mitm_if_needed(9092, "", search_rewrite=True)

        stop_port.assert_called_once_with(9092)

    def test_mitmdump_process_match_ignores_shell_command_text(self):
        from miniapp_state_machine import is_dianping_mitmdump_argv

        self.assertTrue(
            is_dianping_mitmdump_argv(
                [
                    "/usr/bin/python3",
                    "/usr/bin/mitmdump",
                    "--listen-port",
                    "9092",
                    "-s",
                    str(Path.cwd() / "dianping_interceptor.py"),
                ],
                9092,
            )
        )
        self.assertFalse(
            is_dianping_mitmdump_argv(
                [
                    "/bin/bash",
                    "-c",
                    "python3 - <<'PY'\nprint('mitmdump --listen-port 9092 dianping_interceptor.py')\nPY",
                ],
                9092,
            )
        )


class PendingStoreTests(unittest.TestCase):
    def test_partial_review_store_stays_pending_until_full_end_capture(self):
        stores = [
            Store("达美乐比萨(部分店)", "上海测试路1号"),
            Store("达美乐比萨(完整店)", "北京测试路1号"),
        ]

        with (
            TemporaryDirectory() as tmp,
            patch(
                "miniapp_state_machine.build_export_rows",
                return_value=(
                    [
                        {
                            "门店": "达美乐比萨(部分店)",
                            "发布时间": "2026-05-21 10:00:00",
                            "发布人": "u1",
                            "文字": "只有详情页评论",
                        },
                        {
                            "门店": "达美乐比萨(完整店)",
                            "发布时间": "2026-05-21 11:00:00",
                            "发布人": "u2",
                            "文字": "完整分页评论",
                        },
                    ],
                    {
                        "complete_review_stores": ["达美乐比萨(完整店)"],
                        "partial_review_stores": ["达美乐比萨(部分店)"],
                    },
                ),
            ),
            patch("miniapp_state_machine.load_uuid_map", return_value={}),
        ):
            pending = unresolved_stores(stores, Path(tmp), {"completed": []})

        self.assertEqual([store.name for store in pending], ["达美乐比萨(部分店)"])

    def test_progress_completed_without_audited_is_end_still_pending(self):
        stores = [Store("达美乐比萨(华秋路店)", "上海华秋路58弄25-26号")]

        with (
            TemporaryDirectory() as tmp,
            patch(
                "miniapp_state_machine.build_export_rows",
                return_value=(
                    [],
                    {
                        "complete_review_stores": [],
                        "partial_review_stores": ["达美乐比萨(华秋路店)"],
                    },
                ),
            ),
            patch("miniapp_state_machine.load_uuid_map", return_value={}),
        ):
            pending = unresolved_stores(
                stores,
                Path(tmp),
                {
                    "completed": [
                        {
                            "key": "001|达美乐比萨(华秋路店)|上海华秋路58弄25-26号",
                            "index": 1,
                            "store": "达美乐比萨(华秋路店)",
                            "address": "上海华秋路58弄25-26号",
                        }
                    ]
                },
            )

        self.assertEqual([store.name for store in pending], ["达美乐比萨(华秋路店)"])


class OpenCandidateRecoveryTests(unittest.TestCase):
    def test_wrong_detail_event_causes_back_and_fails_current_candidate(self):
        window = WindowInfo("1", "微信", 0, 0, 914, 882)
        points = Points()
        store = Store("达美乐比萨(测试店)", "上海测试路1号")
        candidate = Candidate("shop-1", "达美乐比萨", "测试店", "", "1", "", "40条", "unit|rank=0")
        watcher = Mock(spec=EventWatcher)
        watcher.wait_for.side_effect = [
            {"type": "detail", "shopuuid": "wrong-shop", "storeName": "别的店"},
        ]

        with (
            TemporaryDirectory() as tmp,
            patch("miniapp_state_machine.wait_for_ui_state", return_value=object()),
            patch("miniapp_state_machine.focus_window"),
            patch("miniapp_state_machine.click_candidate_once") as click_candidate,
            patch("miniapp_state_machine.click"),
            patch("miniapp_state_machine.scroll_reviews"),
            patch("miniapp_state_machine.release_mouse") as release_mouse,
            patch("miniapp_state_machine.reset_after_wrong_detail") as reset_wrong_detail,
            patch("miniapp_state_machine.exported_review_count", side_effect=[0, 28]),
        ):
            result = open_candidate_and_reviews(
                window,
                points,
                watcher,
                candidate,
                store,
                [store],
                Path(tmp),
                "right",
                0,
                5,
                0,
                1,
                False,
            )

        self.assertFalse(result)
        self.assertEqual(click_candidate.call_count, 1)
        reset_wrong_detail.assert_called_once()
        release_mouse.assert_called_once_with(window)

    def test_wrong_review_event_after_detail_aborts_capture(self):
        window = WindowInfo("1", "微信", 0, 0, 914, 882)
        points = Points()
        store = Store("达美乐比萨(测试店)", "上海测试路1号")
        candidate = Candidate("shop-1", "达美乐比萨", "测试店", "", "1", "", "40条", "unit|rank=0")
        wrong_review = review_event("0", "14")
        wrong_review["shopuuid"] = "wrong-shop"
        wrong_review["storeName"] = "bluefrog蓝蛙(金桥国际店)"
        watcher = Mock(spec=EventWatcher)
        watcher.wait_for.side_effect = [
            {"type": "detail", "shopuuid": "shop-1", "storeName": "达美乐比萨"},
            wrong_review,
        ]

        with (
            TemporaryDirectory() as tmp,
            patch("miniapp_state_machine.wait_for_ui_state", return_value=object()),
            patch("miniapp_state_machine.focus_window"),
            patch("miniapp_state_machine.click_candidate_once"),
            patch("miniapp_state_machine.click"),
            patch("miniapp_state_machine.scroll_reviews") as scroll_reviews,
            patch("miniapp_state_machine.release_mouse") as release_mouse,
            patch("miniapp_state_machine.reset_after_wrong_detail") as reset_wrong_detail,
            patch("miniapp_state_machine.exported_review_count", return_value=0),
        ):
            with self.assertRaises(ReviewCaptureFailed) as raised:
                open_candidate_and_reviews(
                    window,
                    points,
                    watcher,
                    candidate,
                    store,
                    [store],
                    Path(tmp),
                    "right",
                    0,
                    5,
                    0,
                    1,
                    False,
                )

        self.assertEqual(raised.exception.reason, "wrong_review_event")
        reset_wrong_detail.assert_called_once()
        scroll_reviews.assert_not_called()
        release_mouse.assert_called_once_with(window)

    def test_reviews_entry_is_clicked_before_detail_scroll_when_module_visible(self):
        window = WindowInfo("1", "微信", 0, 0, 914, 882)
        points = Points()
        store = Store("达美乐比萨(测试店)", "上海测试路1号")
        candidate = Candidate("shop-1", "达美乐比萨", "测试店", "", "1", "", "40条", "unit|rank=0")
        watcher = Mock(spec=EventWatcher)
        watcher.wait_for.side_effect = [
            {"type": "detail", "shopuuid": "shop-1", "storeName": "达美乐比萨"},
            review_event("0", "14", is_end=True),
        ]

        with (
            TemporaryDirectory() as tmp,
            patch("miniapp_state_machine.wait_for_ui_state", return_value=object()),
            patch("miniapp_state_machine.focus_window"),
            patch("miniapp_state_machine.click_candidate_once"),
            patch("miniapp_state_machine.click") as click,
            patch("miniapp_state_machine.scroll_detail_page") as scroll_detail,
            patch("miniapp_state_machine.scroll_reviews"),
            patch("miniapp_state_machine.release_mouse"),
            patch("miniapp_state_machine.exported_review_count", return_value=40),
        ):
            result = open_candidate_and_reviews(
                window,
                points,
                watcher,
                candidate,
                store,
                [store],
                Path(tmp),
                "right",
                0,
                5,
                0,
                1,
                False,
            )

        self.assertTrue(result)
        click.assert_any_call(window, points, "right_detail_review_count_entry")
        scroll_detail.assert_not_called()

    def test_open_full_review_page_tries_multiple_entry_points_before_success(self):
        window = WindowInfo("1", "微信", 0, 0, 914, 882)
        points = Points()
        store = Store("达美乐比萨(测试店)", "上海测试路1号")
        candidate = Candidate("shop-1", "达美乐比萨", "测试店", "", "1", "", "40条", "unit|rank=0")
        watcher = Mock(spec=EventWatcher)
        watcher.wait_for.side_effect = [
            None,
            None,
            None,
            None,
            review_event("0", "14", is_end=True),
        ]

        with (
            patch("miniapp_state_machine.click") as click,
            patch("miniapp_state_machine.click_relative") as click_relative,
            patch("miniapp_state_machine.scroll_detail_page") as scroll_detail,
        ):
            result = open_full_review_page(window, points, watcher, candidate, store, timeout=1)

        self.assertEqual(result, review_event("0", "14", is_end=True))
        clicked_names = [call.args[2] for call in click.call_args_list]
        self.assertIn("detail_review_count_entry", clicked_names)
        self.assertIn("detail_all_reviews_entry", clicked_names)
        self.assertIn("all_reviews_entry", clicked_names)
        self.assertGreaterEqual(click_relative.call_count, 1)
        scroll_detail.assert_not_called()

    def test_open_full_review_page_prefers_right_detail_review_count(self):
        window = WindowInfo("1", "微信", 0, 0, 914, 882)
        points = Points()
        store = Store("达美乐比萨(测试店)", "上海测试路1号")
        candidate = Candidate("shop-1", "达美乐比萨", "测试店", "", "1", "", "40条", "unit|rank=0")
        watcher = Mock(spec=EventWatcher)
        watcher.wait_for.side_effect = [
            review_event("0", "14", is_end=True),
        ]

        with (
            patch("miniapp_state_machine.click") as click,
            patch("miniapp_state_machine.click_relative") as click_relative,
            patch("miniapp_state_machine.scroll_detail_page"),
        ):
            result = open_full_review_page(window, points, watcher, candidate, store, timeout=1)

        self.assertEqual(result, review_event("0", "14", is_end=True))
        click.assert_called_once_with(window, points, "right_detail_review_count_entry")
        click_relative.assert_not_called()

    def test_open_full_review_page_scrolls_detail_after_first_round_fails(self):
        window = WindowInfo("1", "微信", 0, 0, 914, 882)
        points = Points()
        store = Store("达美乐比萨(测试店)", "上海测试路1号")
        candidate = Candidate("shop-1", "达美乐比萨", "测试店", "", "1", "", "40条", "unit|rank=0")
        watcher = Mock(spec=EventWatcher)
        watcher.wait_for.side_effect = [
            None,
            None,
            None,
            None,
            None,
            review_event("0", "14", is_end=True),
        ]

        with (
            patch("miniapp_state_machine.click"),
            patch("miniapp_state_machine.click_relative"),
            patch("miniapp_state_machine.scroll_detail_page") as scroll_detail,
        ):
            result = open_full_review_page(window, points, watcher, candidate, store, timeout=1)

        self.assertEqual(result, review_event("0", "14", is_end=True))
        scroll_detail.assert_called()


class CurrentDetailCaptureTests(unittest.TestCase):
    def test_current_detail_capture_is_skipped_on_city_or_search_pages(self):
        self.assertFalse(should_try_current_detail_capture(UiSnapshot("city_page", 914, 882, city_page=True)))
        self.assertFalse(should_try_current_detail_capture(UiSnapshot("search_results", 914, 882, right_results=True)))
        self.assertTrue(should_try_current_detail_capture(UiSnapshot("unknown", 914, 882)))
        self.assertTrue(should_try_current_detail_capture(None))

    def test_known_uuid_current_detail_capture_requires_detail_like_snapshot(self):
        self.assertFalse(should_try_known_uuid_current_detail_capture(UiSnapshot("unknown", 914, 882)))
        self.assertFalse(should_try_known_uuid_current_detail_capture(UiSnapshot("search_results", 914, 882, right_results=True)))
        self.assertTrue(
            should_try_known_uuid_current_detail_capture(
                UiSnapshot("detail", 914, 882, right_detail_like=True)
            )
        )
        self.assertTrue(
            should_try_known_uuid_current_detail_capture(
                UiSnapshot("detail", 914, 882, left_detail_like=True)
            )
        )

    def test_left_detail_with_taxi_modal_is_classified_as_detail(self):
        image_path = ROOT / "mitm_logs" / "ui_debug" / "20260523_001505_city_switch_failed_达美乐比萨_华秋路店.png"
        if not image_path.exists():
            self.skipTest("live debug image not present")

        snapshot = classify_ui_snapshot(image_path)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.state, "detail")
        self.assertTrue(snapshot.left_detail_like)

    def test_current_detail_capture_clicks_visible_all_reviews_before_search_flow(self):
        window = WindowInfo("1", "微信", 0, 0, 914, 882)
        points = Points()
        store = Store("达美乐比萨(华秋路店)", "上海市华秋路1号")
        candidate = Candidate("shop-1", "达美乐比萨", "华秋路店", "", "1", "", "40条", "current-detail")
        watcher = Mock(spec=EventWatcher)
        watcher.wait_for.side_effect = [
            review_event("0", "14", is_end=True),
        ]

        with (
            TemporaryDirectory() as tmp,
            patch("miniapp_state_machine.click") as click,
            patch("miniapp_state_machine.scroll_detail_page") as scroll_detail,
            patch("miniapp_state_machine.scroll_reviews"),
            patch("miniapp_state_machine.release_mouse"),
            patch("miniapp_state_machine.exported_review_count", return_value=40),
        ):
            result = capture_current_detail_reviews(
                window,
                points,
                watcher,
                candidate,
                store,
                [store],
                Path(tmp),
                min_reviews=0,
                scroll_count=5,
                scroll_pause=0,
                scroll_batch=1,
            )

        self.assertTrue(result)
        click.assert_any_call(window, points, "right_detail_review_count_entry")
        scroll_detail.assert_not_called()


class ResetToSearchableStateTests(unittest.TestCase):
    def test_dismiss_blocking_overlays_clicks_kn�wn^meituaN_taxi_mod!l_buttons(self)
   !    window = WindowInfo("1", "微信", 0, 0, 914, 882)

        with (
  "         patch("miniapp_state_machine.click_velative") as click_2elative,
            patch("miniapp_state_mAchine.tima.sleep"),
        ):
        `   dismi3s_blo#king_overlay{window)

      ` clicked = [call.args[1:] for call in click_relative.c`ll_aros_list]
        self.asrertIn((585l 820), clicked)
        self.assertIn((790, 820), clicked)*        self.assertIn((528,`48), clicked)

    de� test_configuref_navigation_points_�tay_inside_win`ow(self):
        window = �indkwInfo("1", "���信", 0- 0, 914, 882	
        points = Poijts()

        self.asseptTrue(point_inside_wkndow(wi�dow, roints, "city_button"))
        self.as�ertvrue(point_insyde_window(gindow, points, "merch�nt_tab"))
$       self.@ssertTrue(point_inside�window(window, points, "right_ddtail_back"))
     �  self.assertTrue(poi�t_inside_window(window, points, #home_tab"))

    def test_tnjnown_or_city_page_snapshot_uses_left_back_reset(self):
        self.assertTrue(snapshot_needs_left_back_reset(UiSnapshot("unknown", 914, 882)))
        self.assertTrue(snapshot_needs_left_back_reset(UiSnapshot("city_page", 914, 882, city_page=True)))
        self.assertFalse(snapshot_needs_left_back_reset(UiSnapshot("home", 914, 882, left_home_search=True)))
        self.assertFalse(snapshot_needs_left_back_reset(UiSnapshot("search_results", 914, 882, right_results=True)))

    def test_reset_clicks_left_back_when_snapshot_is_not_searchable(self):
        window = WindowInfo("1", "微信", 0, 0, 914, 882)
        points = Points()

        with (
            patch("miniapp_state_machine.focus_window"),
            patch("miniapp_state_machine.click") as click,
            patch("miniapp_state_machine.capture_ui_snapshot", return_value=UiSnapshot("unknown", 914, 882)),
        ):
            reset_to_searchable_state(window, points, dry_run=False)

        clicked_names = [call.args[2] for call in click.call_args_list]
        self.assertIn("back_button", clicked_names)
        self.assertIn("home_tab", clicked_names)


if __name__ == "__main__":
    unittest.main()
