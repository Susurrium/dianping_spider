import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MeituanEntrypointsTests(unittest.TestCase):
    def test_meituan_interceptor_sets_capture_namespace(self):
        old = os.environ.get("DP_CAPTURE_NAMESPACE")
        old_appids = os.environ.get("DP_CAPTURE_APPIDS")
        try:
            os.environ.pop("DP_CAPTURE_NAMESPACE", None)
            os.environ.pop("DP_CAPTURE_APPIDS", None)
            fake_http = MagicMock()
            fake_module = MagicMock(http=fake_http)
            with patch.dict(sys.modules, {"mitmproxy": fake_module, "mitmproxy.http": fake_http}):
                module = importlib.import_module("meituan_miniapp_interceptor")
                self.assertEqual(os.environ.get("DP_CAPTURE_NAMESPACE"), "meituan")
                self.assertEqual(os.environ.get("DP_CAPTURE_APPIDS"), "wxde8ac0a21135c07d")
                self.assertTrue(hasattr(module, "response"))
        finally:
            sys.modules.pop("meituan_miniapp_interceptor", None)
            sys.modules.pop("dianping_interceptor", None)
            if old is None:
                os.environ.pop("DP_CAPTURE_NAMESPACE", None)
            else:
                os.environ["DP_CAPTURE_NAMESPACE"] = old
            if old_appids is None:
                os.environ.pop("DP_CAPTURE_APPIDS", None)
            else:
                os.environ["DP_CAPTURE_APPIDS"] = old_appids

    def test_meituan_scripts_compile(self):
        for path in [
            ROOT / "meituan_shop_id_resolver.py",
            ROOT / "meituan_review_exporter.py",
            ROOT / "meituan_miniapp_interceptor.py",
        ]:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")


if __name__ == "__main__":
    unittest.main()
