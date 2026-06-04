# -*- coding: utf-8 -*-
"""auto_pipeline 模块的最小回归测试。

不依赖 PC 微信窗口；只验证那些"无 UI"的纯逻辑：
  - capture_audit.json missing_stores 解析
  - progress_summary 的健壮性
  - find_miniapp_window_id 在没有窗口时返回 None
  - port_listening 对实际 9092 状态的反应
  - run_export_and_audit 不会异常退出（即使 timeout 也走完）

执行：
  python3 -m unittest tests/test_auto_pipeline.py -v
"""

from __future__ import annotations

import json
import io
import argparse
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auto_pipeline as ap  # noqa: E402


class TestProgressSummary(unittest.TestCase):
    def test_missing_progress_returns_zeros(self):
        original = ap.PROGRESS
        try:
            ap.PROGRESS = ROOT / "output" / "definitely_not_a_real_progress.json"
            summary = ap.progress_summary()
            self.assertEqual(summary, {"completed": 0, "failed": 0, "partial": 0})
        finally:
            ap.PROGRESS = original

    def test_real_progress_parses(self):
        if not ap.PROGRESS.exists():
            self.skipTest("no live progress to test")
        summary = ap.progress_summary()
        self.assertGreaterEqual(summary["completed"], 0)
        self.assertGreaterEqual(summary["failed"], 0)


class TestPendingFromAudit(unittest.TestCase):
    def test_missing_stores_field_used(self):
        # 跑一次审计；保证 capture_audit.json 是新的
        pending = ap.list_pending_stores()
        self.assertIsInstance(pending, list)
        for name in pending:
            self.assertIsInstance(name, str)
            self.assertTrue(name.strip())


class TestWindowDetection(unittest.TestCase):
    def test_returns_none_or_string(self):
        wid = ap.find_miniapp_window_id()
        self.assertTrue(wid is None or isinstance(wid, str))

    def test_wait_for_window_with_zero_timeout_raises_only_after_negative(self):
        # 单元测试：用一个 1 秒超时来确认 timeout 路径会抛
        with (
            patch("auto_pipeline.find_miniapp_window_id", return_value=None),
            self.assertRaises(TimeoutError),
        ):
            ap.wait_for_window(timeout=1, poll=0.5)


class TestPortListening(unittest.TestCase):
    def test_returns_bool(self):
        self.assertIsInstance(ap.port_listening(9092), bool)

    def test_known_unused_port_false(self):
        # 65432 通常不会被占
        self.assertFalse(ap.port_listening(65432))


class TestExportAuditDoesNotCrash(unittest.TestCase):
    def test_returns_dict(self):
        summary = ap.run_export_and_audit()
        self.assertIsInstance(summary, dict)


class TestMitmEnsure(unittest.TestCase):
    def test_start_shell_script_does_not_start_upstream_loop(self):
        text = (ROOT / "start.sh").read_text(encoding="utf-8")

        self.assertNotIn("--mode upstream:http://127.0.0.1:7890/", text)
        self.assertNotIn("upstream:", text)

    def test_already_listening_no_op(self):
        # 假设外部已经启动了 mitmdump（pipeline 启动前提条件）
        if not ap.port_listening(9092):
            self.skipTest("mitm 未运行；该测试只验证已运行情况下不会重启")
        # 不应该抛异常
        ap.ensure_mitmdump()

    def test_start_command_uses_no_upstream_in_clash_rule_mode(self):
        command = ap.build_mitmdump_command()

        self.assertIn("--listen-port", command)
        self.assertNotIn("--mode", command)
        self.assertNotIn("upstream:", " ".join(command))

    def test_build_mitmdump_env_strips_inherited_proxy_variables(self):
        env = ap.build_mitmdump_env(
            {
                "PATH": "/bin",
                "http_proxy": "http://127.0.0.1:7890/",
                "HTTPS_PROXY": "http://127.0.0.1:7890/",
                "all_proxy": "socks5://127.0.0.1:7891/",
            },
            search_rewrite=True,
        )

        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["DP_SEARCH_REWRITE"], "1")
        self.assertNotIn("http_proxy", env)
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertNotIn("all_proxy", env)

    def test_search_rewrite_env_detection_reads_mitmdump_pid(self):
        with (
            patch("auto_pipeline.find_mitmdump_pid", return_value=123),
            patch("auto_pipeline.Path.read_bytes", return_value=b"PATH=/bin\x00DP_SEARCH_REWRITE=0\x00"),
        ):
            self.assertFalse(ap.active_mitmdump_has_search_rewrite())

        with (
            patch("auto_pipeline.find_mitmdump_pid", return_value=123),
            patch("auto_pipeline.Path.read_bytes", return_value=b"DP_SEARCH_REWRITE=1\x00"),
        ):
            self.assertTrue(ap.active_mitmdump_has_search_rewrite())

    def test_mitmdump_env_detection_rejects_inherited_proxy_variables(self):
        with (
            patch("auto_pipeline.find_mitmdump_pid", return_value=123),
            patch("auto_pipeline.Path.read_bytes", return_value=b"DP_SEARCH_REWRITE=1\x00http_proxy=http://127.0.0.1:7890/\x00"),
        ):
            self.assertFalse(ap.active_mitmdump_env_is_safe(require_search_rewrite=True))

        with (
            patch("auto_pipeline.find_mitmdump_pid", return_value=123),
            patch("auto_pipeline.Path.read_bytes", return_value=b"DP_SEARCH_REWRITE=1\x00PATH=/bin\x00"),
        ):
            self.assertTrue(ap.active_mitmdump_env_is_safe(require_search_rewrite=True))

    def test_mitmdump_process_match_ignores_shell_command_text(self):
        self.assertTrue(
            ap.is_dianping_mitmdump_argv(
                [
                    "/usr/bin/python3",
                    "/usr/bin/mitmdump",
                    "--listen-port",
                    "9092",
                    "--set",
                    "ssl_insecure=true",
                    "-s",
                    str(ROOT / "dianping_interceptor.py"),
                ],
                ap.DEFAULT_PROXY_PORT,
            )
        )
        self.assertFalse(
            ap.is_dianping_mitmdump_argv(
                [
                    "/usr/bin/python3",
                    "/usr/bin/mitmdump",
                    "--listen-port",
                    "9092",
                    "--set",
                    "ssl_insecure=true",
                    "--mode",
                    "transparent",
                    "-s",
                    str(ROOT / "dianping_interceptor.py"),
                ],
                ap.DEFAULT_PROXY_PORT,
            )
        )
        self.assertFalse(
            ap.is_dianping_mitmdump_argv(
                [
                    "/bin/bash",
                    "-c",
                    "pgrep -af 'mitmdump.*dianping_interceptor.py --listen-port 9092'",
                ],
                ap.DEFAULT_PROXY_PORT,
            )
        )

    def test_ensure_mitmdump_restarts_existing_without_search_rewrite_when_required(self):
        fake_proc = unittest.mock.Mock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 4321

        with (
            patch("auto_pipeline.port_listening", side_effect=[True, False, True]),
            patch("auto_pipeline.active_mitmdump_has_search_rewrite", return_value=False),
            patch("auto_pipeline.find_mitmdump_pid", return_value=111),
            patch("auto_pipeline.stop_mitmdump_on_port") as stop_port,
            patch("auto_pipeline.subprocess.Popen", return_value=fake_proc) as popen,
        ):
            ap.ensure_mitmdump(require_search_rewrite=True)

        stop_port.assert_called_once_with(ap.DEFAULT_PROXY_PORT)
        self.assertEqual(popen.call_args.kwargs["env"]["DP_SEARCH_REWRITE"], "1")


class TestRescueHooks(unittest.TestCase):
    def test_release_mouse_sends_mouseup_before_move(self):
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            return unittest.mock.Mock(returncode=0)

        with patch("auto_pipeline.subprocess.run", side_effect=fake_run):
            ap.release_mouse()

        self.assertEqual(calls[0], ["xdotool", "mouseup", "1"])
        self.assertEqual(calls[1], ["xdotool", "mouseup", "2"])
        self.assertEqual(calls[2], ["xdotool", "mouseup", "3"])
        self.assertEqual(calls[3], ["xdotool", "mouseup", "4"])
        self.assertEqual(calls[4], ["xdotool", "mouseup", "5"])
        self.assertEqual(calls[-1], ["xdotool", "mousemove", "20", "20"])

    def test_store_run_aborts_when_network_health_fails(self):
        class FakeProc:
            pid = 12345
            returncode = None
            stdout = io.StringIO("[1/1] #001 达美乐比萨(测试店) | 上海测试路1号\n")

            def poll(self):
                return None

        with (
            patch("auto_pipeline.time.time", side_effect=[0, 1, 2]),
            patch("auto_pipeline.subprocess.Popen", return_value=FakeProc()),
            patch("auto_pipeline.read_available_stdout", return_value=[]),
            patch("auto_pipeline.guard_split_proxy_health", return_value=False) as guard,
            patch("auto_pipeline._terminate_tree") as terminate_tree,
            patch("auto_pipeline.rescue_runtime") as rescue_runtime,
        ):
            result = ap.run_one_store(store_timeout=30, health_check_interval=0)

        self.assertEqual(result["status"], "network_failed")
        guard.assert_called()
        terminate_tree.assert_called_once()
        rescue_runtime.assert_called_once()

    def test_store_timeout_runs_runtime_rescue(self):
        class FakeProc:
            pid = 12345
            returncode = None
            stdout = None

            def poll(self):
                return None

        with (
            patch("auto_pipeline.time.time", side_effect=[0, 999, 1000, 1001]),
            patch("auto_pipeline.subprocess.Popen", return_value=FakeProc()),
            patch("auto_pipeline.guard_split_proxy_health", return_value=True),
            patch("auto_pipeline._terminate_tree") as terminate_tree,
            patch("auto_pipeline.rescue_runtime") as rescue_runtime,
        ):
            result = ap.run_one_store(store_timeout=1)

        self.assertEqual(result["status"], "timeout")
        terminate_tree.assert_called_once()
        rescue_runtime.assert_called_once()

    def test_rescue_runtime_restores_7890_and_releases_mouse(self):
        with (
            patch("auto_pipeline.restore_clash_proxy") as restore_proxy,
            patch("auto_pipeline.release_mouse") as release_mouse,
            patch("auto_pipeline.ensure_clash_rule_ok", return_value=True) as ensure_rule,
        ):
            ap.rescue_runtime()

        restore_proxy.assert_called_once()
        release_mouse.assert_called_once()
        ensure_rule.assert_called_once_with(auto_enable=True, include_search_domains=False)

    def test_nonzero_store_run_runs_runtime_rescue(self):
        class FakeProc:
            pid = 12345
            returncode = 2
            stdout = io.StringIO("[1/1] #001 达美乐比萨(测试店) | 上海测试路1号\n")

            def poll(self):
                return self.returncode

        with (
            patch("auto_pipeline.subprocess.Popen", return_value=FakeProc()),
            patch("auto_pipeline.rescue_runtime") as rescue_runtime,
        ):
            result = ap.run_one_store(store_timeout=30)

        self.assertEqual(result["status"], "nonzero")
        self.assertEqual(result["store"], "达美乐比萨(测试店)")
        rescue_runtime.assert_called_once()

    def test_nonzero_store_run_logs_full_child_output_tail(self):
        traceback_text = "\n".join(
            [
                "Traceback (most recent call last):",
                '  File "miniapp_state_machine.py", line 10, in <module>',
                "RuntimeError: screenshot failed",
            ]
        )

        class FakeProc:
            pid = 12345
            returncode = 1
            stdout = io.StringIO(traceback_text + "\n")

            def poll(self):
                return self.returncode

        events = []

        def fake_log_event(kind, **fields):
            events.append((kind, fields))

        with (
            patch("auto_pipeline.subprocess.Popen", return_value=FakeProc()),
            patch("auto_pipeline.rescue_runtime"),
            patch("auto_pipeline.log_event", side_effect=fake_log_event),
        ):
            result = ap.run_one_store(store_timeout=30)

        output_events = [fields for kind, fields in events if kind == "store_run_child_output"]
        self.assertTrue(output_events)
        self.assertIn("RuntimeError: screenshot failed", output_events[-1]["output_tail"])
        self.assertIn("Traceback", result["output_tail"])

    def test_store_timeout_not_blocked_by_silent_child_stdout(self):
        command = (
            "import time,sys; "
            "print('[1/1] #001 达美乐比萨(测试店) | 上海测试路1号', flush=True); "
            "time.sleep(5)"
        )
        started = time.time()
        with (
            patch.object(ap, "PYTHON", sys.executable),
            patch.object(ap, "ROOT", ROOT),
            patch.object(ap, "_terminate_tree") as terminate_tree,
            patch.object(ap, "rescue_runtime") as rescue_runtime,
            patch.object(
                ap,
                "build_store_command",
                return_value=[sys.executable, "-c", command],
            ),
        ):
            result = ap.run_one_store(store_timeout=1)

        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["store"], "达美乐比萨(测试店)")
        self.assertLess(time.time() - started, 4)
        terminate_tree.assert_called_once()
        rescue_runtime.assert_called_once()


class TestClashCheck(unittest.TestCase):
    def test_returns_bool(self):
        self.assertIsInstance(ap.ensure_clash_rule_ok(), bool)

    def test_ensure_clash_rule_defaults_to_api_only_domains(self):
        rules_payload = {
            "rules": [
                {"type": "DomainSuffix", "payload": "mapi.dianping.com", "proxy": "DP-MITM"},
                {"type": "DomainSuffix", "payload": "mapi.meituan.com", "proxy": "DP-MITM"},
                {"type": "DomainSuffix", "payload": "mapi.sankuai.com", "proxy": "DP-MITM"},
            ]
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        fake_response = FakeResponse()

        with patch("urllib.request.urlopen", return_value=fake_response):
            fake_response.read = lambda: json.dumps(rules_payload).encode("utf-8")
            fake_response.getcode = lambda: 200
            fake_response.info = lambda: {}

            self.assertTrue(ap.ensure_clash_rule_ok(auto_enable=False))

    def test_build_store_command_can_request_search_domain_rewrite(self):
        command = ap.build_store_command(include_search_domains=True)

        self.assertIn("--rewrite-search", command)

    def test_build_store_command_defaults_to_safe_api_only_mode(self):
        command = ap.build_store_command()

        self.assertNotIn("--rewrite-search", command)

    def test_build_store_command_runs_state_machine_unbuffered(self):
        command = ap.build_store_command()

        self.assertEqual(command[0], ap.PYTHON)
        self.assertEqual(command[1], "-u")
        self.assertTrue(command[2].endswith("miniapp_state_machine.py"))

    def test_start_script_uses_api_only_split_rule(self):
        text = (ROOT / "start.sh").read_text(encoding="utf-8")

        self.assertIn("include_search_domains=False", text)
        self.assertNotIn("include_search_domains=True", text)

    def test_split_proxy_health_probe_checks_cn_and_dianping_domains_via_7890(self):
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            return unittest.mock.Mock(returncode=0, stdout="HTTP/1.1 200 OK\n")

        with patch("auto_pipeline.subprocess.run", side_effect=fake_run):
            self.assertTrue(ap.split_proxy_health_probe())

        joined = "\n".join(" ".join(command) for command in calls)
        self.assertIn("http://127.0.0.1:7890", joined)
        self.assertIn("https://www.baidu.com/", joined)
        self.assertNotIn("https://m.dianping.com/", joined)
        self.assertNotIn("https://catfront.dianping.com/", joined)

    def test_split_proxy_health_probe_failure_rolls_back_dianping_rule(self):
        with (
            patch("auto_pipeline.split_proxy_health_probe", return_value=False),
            patch("auto_pipeline.restore_clash_proxy") as restore_proxy,
            patch("manual_review_console.disable_clash_mitm_rule") as disable_rule,
        ):
            self.assertFalse(ap.guard_split_proxy_health())

        restore_proxy.assert_called_once()
        disable_rule.assert_called_once()

    def test_split_proxy_health_probe_transient_failure_retries_before_rollback(self):
        with (
            patch("auto_pipeline.split_proxy_health_probe", side_effect=[False, True]) as probe,
            patch("auto_pipeline.time.sleep") as sleep,
            patch("auto_pipeline.restore_clash_proxy") as restore_proxy,
        ):
            self.assertTrue(ap.guard_split_proxy_health())

        self.assertEqual(probe.call_count, 2)
        sleep.assert_called_once()
        restore_proxy.assert_not_called()

    def test_search_rewrite_requires_search_domain_split(self):
        rules = [
            {"type": "DomainSuffix", "payload": "mapi.dianping.com", "proxy": "DP-MITM"},
            {"type": "DomainSuffix", "payload": "mapi.meituan.com", "proxy": "DP-MITM"},
            {"type": "DomainSuffix", "payload": "mapi.sankuai.com", "proxy": "DP-MITM"},
        ]

        self.assertTrue(ap.clash_rule_has_required_dp_mitm_domains(rules, include_search_domains=False))
        self.assertFalse(ap.clash_rule_has_required_dp_mitm_domains(rules, include_search_domains=True))

        rules.append({"type": "DomainSuffix", "payload": "m.dianping.com", "proxy": "DP-MITM"})
        self.assertTrue(ap.clash_rule_has_required_dp_mitm_domains(rules, include_search_domains=True))


class TestChildIdleWatchdog(unittest.TestCase):
    def test_file_progress_marker_changes_when_events_file_grows(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"

            missing = ap.file_progress_marker(path)
            path.write_text('{"type":"search"}\n', encoding="utf-8")
            first = ap.file_progress_marker(path)
            path.write_text('{"type":"search"}\n{"type":"review"}\n', encoding="utf-8")
            second = ap.file_progress_marker(path)

        self.assertNotEqual(missing, first)
        self.assertNotEqual(first, second)

    def test_store_run_aborts_when_child_and_events_are_idle(self):
        class FakeStdout:
            def fileno(self):
                return 999999

            def read(self):
                return ""

        class FakeProc:
            pid = 12345
            returncode = None
            stdout = FakeStdout()

            def poll(self):
                return None

        with (
            patch("auto_pipeline.time.time", side_effect=[0, 1, 11, 12]),
            patch("auto_pipeline.subprocess.Popen", return_value=FakeProc()),
            patch("auto_pipeline.read_available_stdout", return_value=[]),
            patch("auto_pipeline.file_progress_marker", return_value=(0, 0)),
            patch("auto_pipeline.guard_split_proxy_health", return_value=True),
            patch("auto_pipeline._terminate_tree") as terminate_tree,
            patch("auto_pipeline.rescue_runtime") as rescue_runtime,
        ):
            result = ap.run_one_store(
                store_timeout=30,
                health_check_interval=100,
                child_idle_timeout=10,
            )

        self.assertEqual(result["status"], "ui_stalled")
        terminate_tree.assert_called_once()
        rescue_runtime.assert_called_once()


class TestPipelineLimitAccounting(unittest.TestCase):
    def test_limit_counts_any_store_attempt_not_just_success_or_timeout(self):
        namespace = argparse.Namespace(
            limit=1,
            store_timeout=30,
            audit_every=0,
            health_check_interval=20,
            child_idle_timeout=45,
            dry_run=False,
            no_window_wait=True,
            max_rounds=0,
            include_search_domains=False,
        )

        with (
            patch("auto_pipeline.argparse.ArgumentParser.parse_args", return_value=namespace),
            patch("auto_pipeline.ensure_mitmdump"),
            patch("auto_pipeline.ensure_clash_rule_ok", return_value=True),
            patch("auto_pipeline.guard_split_proxy_health", return_value=True),
            patch("auto_pipeline.list_pending_stores", return_value=["达美乐比萨(测试店)"]),
            patch("auto_pipeline.run_one_store", return_value={"status": "ui_stalled", "store": "达美乐比萨(测试店)", "returncode": -11, "duration_s": 45}) as run_one,
            patch("auto_pipeline.run_export_and_audit", return_value={"stores_missing": 1, "reviews_exported": 0}),
        ):
            exit_code = ap.main()

        self.assertEqual(exit_code, 0)
        run_one.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
