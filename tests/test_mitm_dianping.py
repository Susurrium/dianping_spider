import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MitmDianpingTests(unittest.TestCase):
    def _load_module(self):
        fake_http = MagicMock()
        fake_module = MagicMock(http=fake_http)
        with patch.dict(sys.modules, {"mitmproxy": fake_module, "mitmproxy.http": fake_http}):
            import importlib

            sys.modules.pop("mitm_dianping", None)
            return importlib.import_module("mitm_dianping")

    def test_extract_score_normalizes_scaled_values(self):
        module = self._load_module()

        self.assertEqual(module.extract_score({"star": 50}), "5")
        self.assertEqual(module.extract_score({"accurateStar": 35}), "3.5")
        self.assertEqual(module.extract_score({"score": 4.5}), "4.5")

    def test_merge_updates_existing_review_with_missing_score(self):
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            target = {"idx": 97, "name": "达美乐比萨(天河购书中心店)"}
            existing_path = out_dir / "097_达美乐比萨(天河购书中心店).json"
            existing_path.write_text(
                json.dumps(
                    [
                        {
                            "门店": target["name"],
                            "发布时间": "1月1日",
                            "发布人": "用户A",
                            "文字": "很好吃",
                        }
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            rows = [
                {
                    "门店": target["name"],
                    "发布时间": "1月1日",
                    "发布人": "用户A",
                    "顾客评分": "4.5",
                    "评分": "4.5",
                    "文字": "很好吃",
                }
            ]

            with patch.object(module, "OUT_DIR", out_dir):
                total, new_count = module.merge_rows(target, rows)

            merged = json.loads(existing_path.read_text(encoding="utf-8"))
            self.assertEqual(total, 1)
            self.assertEqual(new_count, 0)
            self.assertEqual(merged[0]["顾客评分"], "4.5")
            self.assertEqual(merged[0]["评分"], "4.5")


if __name__ == "__main__":
    unittest.main()
