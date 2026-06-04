import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_shop_uuid_resolver import collect_candidates, resolve_stores
from review_exporter import Store


class AutoShopUuidResolverTests(unittest.TestCase):
    def test_collect_candidates_normalizes_meituan_takeout_shop_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            payload = {
                "data": {
                    "result": {
                        "takeoutShopList": [
                            {
                                "shopId": 1190298541,
                                "shopName": "达美乐比萨代购(武汉K11店)",
                                "schema": "/waimai/pages/restaurant/restaurant?poi_id=-100&poi_id_str=bX2CZcTm_kItbtLD3FqiSwI",
                                "commentsCount": "128",
                            }
                        ]
                    }
                }
            }
            (log_dir / "search_031719.json").write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            candidates = collect_candidates(log_dir)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].uuid, "1190298541")
        self.assertEqual(candidates[0].name, "达美乐比萨")
        self.assertEqual(candidates[0].branch, "武汉K11店")
        self.assertEqual(candidates[0].review_count, "128")

    def test_resolve_stores_matches_meituan_takeout_alias_to_excel_name(self):
        stores = [Store("达美乐比萨(武汉K11店)", "武汉市江汉区青年路518号K11")]
        candidates = [
            type(
                "CandidateLike",
                (),
                {
                    "uuid": "1190298541",
                    "name": "达美乐比萨代购(武汉K11店)",
                    "branch": "",
                    "address_hint": "",
                    "city_id": "",
                    "region": "",
                    "review_count": "128",
                    "source": "search_031719.json",
                },
            )()
        ]

        resolved, needs_manual = resolve_stores(
            stores=stores,
            candidates=candidates,
            known_map={},
            min_score=90,
        )

        self.assertEqual(resolved, {"达美乐比萨(武汉K11店)": "1190298541"})
        self.assertEqual(needs_manual, [])

    def test_collect_candidates_supports_independent_meituan_poi_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            payload = {
                "data": {
                    "searchResult": [
                        {
                            "poiId": "1144412936",
                            "poiName": "达美乐比萨(武汉万象城店)",
                            "regionName": "武汉万象城",
                            "address": "建设大道店",
                        }
                    ]
                }
            }
            (log_dir / "search_mt.json").write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            candidates = collect_candidates(log_dir)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].uuid, "1144412936")
        self.assertEqual(candidates[0].name, "达美乐比萨")
        self.assertEqual(candidates[0].branch, "武汉万象城店")


if __name__ == "__main__":
    unittest.main()
