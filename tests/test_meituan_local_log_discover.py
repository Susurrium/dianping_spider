import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meituan_local_log_discover import parse_log_text, summarize_records


class MeituanLocalLogDiscoverTests(unittest.TestCase):
    def test_parse_log_text_extracts_url_status_and_poi_id(self):
        text = (
            "2026-6-4 3:3:43 [info] request:  200; reqInfo: "
            "GET {https%3A%2F%2Fapimobile.meituan.com%2Fgroup%2Fv4%2Fpoi%2Fsearch%2Fminiprogram%2F191%3F"
            "riskLevel%3D71%26optimusCode%3D10%26csecappid%3Dwxde8ac0a21135c07d} {}\n"
            "2026-6-4 3:3:49 [info] request:  200; reqInfo: "
            "GET {https%3A%2F%2Fapimeishi.meituan.com%2Fmeishi%2Fweixinapp%2Fv1%2Fpoi%2FrecommendDishList%2F1144412936%3F"
            "riskLevel%3D71%26optimusCode%3D10} {}\n"
        )

        records = parse_log_text(text)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["status"], "200")
        self.assertEqual(records[0]["path"], "/group/v4/poi/search/miniprogram/191")
        self.assertEqual(records[0]["poi_id"], "")
        self.assertEqual(records[1]["poi_id"], "1144412936")

    def test_summarize_records_counts_paths_and_status(self):
        records = [
            {"url": "u1", "path": "/group/v4/poi/search/miniprogram/191", "status": "200", "poi_id": "191"},
            {"url": "u2", "path": "/group/v4/poi/search/miniprogram/191", "status": "403", "poi_id": "191"},
            {"url": "u3", "path": "/web/poi/1144412936/comments", "status": "200", "poi_id": "1144412936"},
        ]

        summary = summarize_records(records)

        self.assertEqual(summary["total_records"], 3)
        self.assertEqual(summary["status_codes"], {"200": 2, "403": 1})
        self.assertEqual(summary["poi_ids"], ["1144412936", "191"])
        self.assertEqual(summary["paths"][0]["path"], "/group/v4/poi/search/miniprogram/191")


if __name__ == "__main__":
    unittest.main()
