import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dianping_events import build_event


class DianpingEventsTests(unittest.TestCase):
    def test_takeout_search_event_normalizes_meituan_candidate_name(self):
        event = build_event(
            url="https://m.dianping.com/wx/program/minitakeoutsearch.bin?selectedCityId=16&keyword=%E8%BE%BE%E7%BE%8E%E4%B9%90",
            params={"selectedCityId": "16", "keyword": "达美乐"},
            data={
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
            },
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["type"], "takeout_search")
        self.assertEqual(event["cityId"], "16")
        self.assertEqual(event["candidate_count"], 1)
        self.assertEqual(
            event["candidates"],
            [
                {
                    "rank": "0",
                    "uuid": "1190298541",
                    "name": "达美乐比萨",
                    "branch": "武汉K11店",
                    "address": "",
                    "region": "",
                    "cityId": "",
                    "reviewCount": "128",
                    "shopId": "1190298541",
                    "poiIdStr": "bX2CZcTm_kItbtLD3FqiSwI",
                }
            ],
        )

    def test_review_event_resolves_poi_id_str_when_shop_id_is_missing(self):
        event = build_event(
            url="https://example.meituan.com/api/shopreview?poi_id_str=bX2CZcTm_kItbtLD3FqiSwI",
            params={"poi_id_str": "bX2CZcTm_kItbtLD3FqiSwI"},
            data={"shopReviewInfo": {"reviewList": [], "reviewTotalCount": 0}},
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["type"], "review")
        self.assertEqual(event["shopuuid"], "bX2CZcTm_kItbtLD3FqiSwI")

    def test_independent_meituan_web_comment_url_is_treated_as_review(self):
        event = build_event(
            url="https://web.meituan.com/web/poi/1144412936/comments?riskLevel=71&optimusCode=10",
            params={"shopId": "1144412936"},
            data={"data": {"list": [{"reviewId": "r1", "userNickName": "用户A", "content": "好吃"}]}},
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["type"], "review")
        self.assertEqual(event["shopuuid"], "1144412936")
        self.assertEqual(event["review_count"], 1)

    def test_independent_meituan_search_event_extracts_poi_candidates(self):
        event = build_event(
            url="https://apimobile.meituan.com/group/v4/poi/search/miniprogram/191?csecappid=wxde8ac0a21135c07d",
            params={"csecappid": "wxde8ac0a21135c07d"},
            data={
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
            },
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["type"], "takeout_search")
        self.assertEqual(event["candidate_count"], 1)
        self.assertEqual(event["candidates"][0]["uuid"], "1144412936")
        self.assertEqual(event["candidates"][0]["name"], "达美乐比萨")
        self.assertEqual(event["candidates"][0]["branch"], "武汉万象城店")


if __name__ == "__main__":
    unittest.main()
