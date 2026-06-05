# -*- coding: utf-8 -*-
"""Regression tests for configurable Clash ports and WSL Windows WeChat launch.

These tests intentionally inspect source text instead of importing project
modules. Some historical Python files in this repository contain null bytes,
which makes an import-based test fail before it can exercise this change.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ClashPortConfigTests(unittest.TestCase):
    def test_console_exposes_custom_clash_port(self):
        text = (ROOT / "manual_review_console.py").read_text(encoding="utf-8")

        self.assertIn("DEFAULT_CLASH_PORT = 7890", text)
        self.assertIn("clash_port: int = DEFAULT_CLASH_PORT", text)
        self.assertIn("self.clash_port = clash_port", text)
        self.assertIn("restore_clash_proxy(self.clash_port)", text)
        self.assertIn("--clash-port", text)
        self.assertNotIn("current_system_proxy_port() != 7890", text)

    def test_start_and_stop_scripts_expose_custom_clash_port(self):
        start_text = (ROOT / "start_mitm.sh").read_text(encoding="utf-8")
        stop_text = (ROOT / "stop_mitm.sh").read_text(encoding="utf-8")

        self.assertIn("CLASH_PORT=\"${CLASH_PORT:-7890}\"", start_text)
        self.assertIn("UPSTREAM_PROXY=\"${UPSTREAM_PROXY:-http://127.0.0.1:${CLASH_PORT}}\"", start_text)
        self.assertIn("CLASH_PORT=\"${CLASH_PORT:-7890}\"", stop_text)
        self.assertNotIn("port 7890", stop_text)

    def test_auto_pipeline_launcher_message_uses_custom_clash_port(self):
        text = (ROOT / "start.sh").read_text(encoding="utf-8")

        self.assertIn("CLASH_PORT=\"${CLASH_PORT:-7890}\"", text)
        self.assertIn("系统代理仍保持 ${CLASH_PORT}", text)


class WeChatScriptTests(unittest.TestCase):
    def test_restart_script_supports_custom_clash_port_and_windows_wechat(self):
        text = (ROOT / "restart_wechat_with_proxy.sh").read_text(encoding="utf-8")

        self.assertIn("CLASH_PORT=\"${CLASH_PORT:-7890}\"", text)
        self.assertIn("WECHAT_PLATFORM=\"${WECHAT_PLATFORM:-auto}\"", text)
        self.assertIn("WECHAT_WIN_EXE", text)
        self.assertIn("wslpath -w", text)
        self.assertIn("cmd.exe /C start", text)
        self.assertNotIn("http://127.0.0.1:7890", text)


if __name__ == "__main__":
    unittest.main()
