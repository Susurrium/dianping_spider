import json
import tempfile
import unittest
from pathlib import Path

from review_exporter import (
    build_export_rows,
    capture_is_full_review,
    extract_review_text,
    extract_reviews_from_capture,
    load_stores_from_xlsx,
    resolve_shop_uuid,
)


class ReviewExporterTests(unittest.TestCase):
    def test_loads_store_rows_from_existing_excel_without_openpyxl(self):
        stores = load_stores_from_xlsx(Path("达美乐_门店爬虫.xlsx"))

        self.assertGreaterEqual(len(stores), 300)
        self.assertEqual(stores[0].name, "达美乐比萨(逸仙路店)")
        self.assertEqual(stores[0].address, "上海逸仙路519号1层08室")

    def test_extracts_text_from_mini_program_rich_review_body(self):
        review_body = {
            "children": [
                {
                    "name": "div",
                    "children": [
                        {"type": "text", "text": "第一段"},
                        {"type": "text", "text": "第二段"},
                    ],
                }
            ]
        }

        self.assertEqual(extract_review_text({"reviewBody": review_body}), "第一段第二段")

    def test_resolves_lowercase_shopuuid_and_nested_referer(self):
        capture = {
            "params": {
                "shopuuid": "abc123",
                "mtsiReferrer": "pages%2Fpoi%2Fpoi%3FshopUuid%3Dnested999",
            },
            "data": {},
        }

        self.assertEqual(resolve_shop_uuid(capture), "abc123")

    def test_resolves_poi_id_str_from_params(self):
        capture = {
            "params": {
                "poi_id_str": "bX2CZcTm_kItbtLD3FqiSwI",
            },
            "data": {},
        }

        self.assertEqual(resolve_shop_uuid(capture), "bX2CZcTm_kItbtLD3FqiSwI")

    def test_extracts_reviews_from_shop_review_info_and_list_shapes(self):
        capture = {
            "params": {"shopUuid": "shop-1"},
            "data": {
                "shopReviewInfo": {
                    "reviewList": [
                        {
                            "reviewId": "r1",
                            "userNickName": "用户A",
                            "star": 5,
                            "accurateStar": 46,
                            "addTime": "2026-05-03T03:11:04.000Z",
                            "reviewBody": {"children": [{"type": "text", "text": "很好吃"}]},
                        }
                    ]
                },
                "list": [
                    {
                        "mainId": "r2",
                        "feedUser": {"userName": "用户B"},
                        "time": "5月3日",
                        "content": "<span>还会再来</span>",
                        "shopPoiRelevant": {"title": "达美乐比萨(测试店)"},
                    }
                ],
            },
        }

        reviews = extract_reviews_from_capture(capture, Path("review_shop-1.json"))

        self.assertEqual(len(reviews), 2)
        self.assertEqual(reviews[0].publisher, "用户A")
        self.assertEqual(reviews[0].publish_time, "2026-05-03 11:11:04")
        self.assertEqual(reviews[0].user_score, "5")
        self.assertEqual(reviews[1].publisher, "用户B")
        self.assertEqual(reviews[1].text, "还会再来")
        self.assertEqual(reviews[1].store_name, "达美乐比萨(测试店)")

    def test_extracts_reviews_from_comment_list_shape(self):
        capture = {
            "params": {"poi_id_str": "poi-1"},
            "data": {
                "commentList": [
                    {
                        "commentId": "c1",
                        "nickname": "用户C",
                        "commentTime": "2026-05-03T03:11:04.000Z",
                        "comment": "值得再来",
                        "poiName": "达美乐比萨(武汉万象城店)",
                        "score": 4.5,
                    }
                ]
            },
        }

        reviews = extract_reviews_from_capture(capture, Path("review_poi-1.json"))

        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].review_id, "c1")
        self.assertEqual(reviews[0].publisher, "用户C")
        self.assertEqual(reviews[0].text, "值得再来")
        self.assertEqual(reviews[0].user_score, "4.5")
        self.assertEqual(reviews[0].store_name, "达美乐比萨(武汉万象城店)")

    def test_build_export_rows_maps_store_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            capture = {
                "params": {"shopuuid": "shop-1"},
                "data": {
                    "list": [
                        {
                            "mainId": "same",
                            "feedUser": {"userName": "用户A"},
                            "time": "5月3日",
                            "content": "第一条",
                            "star": 4,
                        },
                        {
                            "mainId": "same",
                            "feedUser": {"userName": "用户A"},
                            "time": "5月3日",
                            "content": "第一条",
                            "star": 4,
                        },
                    ]
                },
            }
            (log_dir / "review_shop-1_20260521.json").write_text(
                json.dumps(capture, ensure_ascii=False),
                encoding="utf-8",
            )

            rows, stats = build_export_rows(
                stores=[],
                log_dir=log_dir,
                explicit_uuid_map={"达美乐比萨(测试店)": "shop-1"},
            )

        self.assertEqual(
            rows,
            [{"门店": "达美乐比萨(测试店)", "发布时间": "5月3日", "发布人": "用户A", "评分": "4", "文字": "第一条"}],
        )
        self.assertEqual(stats["review_files"], 1)
        self.assertEqual(stats["reviews_exported"], 1)

    def test_build_export_rows_filters_non_excel_stores_when_excel_scope_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            capture = {
                "params": {"shopuuid": "shop-2"},
                "storeName": "无关店铺",
                "data": {
                    "list": [
                        {
                            "mainId": "r1",
                            "feedUser": {"userName": "用户A"},
                            "time": "5月3日",
                            "content": "不应导出",
                            "shopPoiRelevant": {"title": "无关店铺"},
                        }
                    ]
                },
            }
            (log_dir / "review_shop-2_20260521.json").write_text(
                json.dumps(capture, ensure_ascii=False),
                encoding="utf-8",
            )

            rows, stats = build_export_rows(
                stores=[type("StoreLike", (), {"name": "达美乐比萨(测试店)", "address": "测试地址"})()],
                log_dir=log_dir,
                explicit_uuid_map={},
            )

        self.assertEqual(rows, [])
        self.assertEqual(stats["reviews_exported"], 0)
        self.assertEqual(stats["stores_with_reviews"], 0)
        self.assertEqual(stats["stores_missing_reviews"], 1)

    def test_build_export_rows_matches_meituan_takeout_store_alias_without_uuid_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            capture = {
                "url": "https://m.dianping.com/ugc/review/shop/shopreview?shopId=1190298541",
                "storeName": "达美乐比萨代购(武汉K11店)",
                "params": {"shopId": "1190298541"},
                "data": {
                    "shopReviewInfo": {
                        "reviewList": [
                            {
                                "reviewId": "r1",
                                "userNickName": "用户A",
                                "lastTimeStr": "5月3日",
                                "reviewBody": {"children": [{"type": "text", "text": "还会再点"}]},
                                "star": 5,
                            }
                        ],
                        "reviewTotalCount": 1,
                        "isEnd": True,
                    }
                },
            }
            (log_dir / "review_1190298541_20260521.json").write_text(
                json.dumps(capture, ensure_ascii=False),
                encoding="utf-8",
            )

            rows, stats = build_export_rows(
                stores=[type("StoreLike", (), {"name": "达美乐比萨(武汉K11店)", "address": "测试地址"})()],
                log_dir=log_dir,
                explicit_uuid_map={},
            )

        self.assertEqual(
            rows,
            [{"门店": "达美乐比萨(武汉K11店)", "发布时间": "5月3日", "发布人": "用户A", "评分": "5", "文字": "还会再点"}],
        )
        self.assertEqual(stats["reviews_exported"], 1)
        self.assertEqual(stats["stores_with_reviews"], 1)

    def test_build_export_rows_tracks_complete_vs_partial_reviews(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            partial_capture = {
                "url": "https://mapi.dianping.com/mapi/review/outsideshopreviewlist.bin",
                "params": {"shopuuid": "shop-partial"},
                "data": {
                    "shopReviewInfo": {
                        "reviewList": [
                            {"reviewId": "p1", "userNickName": "用户P", "time": "5月3日", "content": "只有详情页评价"}
                        ],
                        "isEnd": False,
                    }
                },
            }
            full_capture = {
                "url": "https://mapi.dianping.com/mapi/review/outsidesiftedreviewlist.bin",
                "params": {"referid": "shop-full", "start": "0"},
                "data": {
                    "list": [
                        {"mainId": "f1", "feedUser": {"userName": "用户F"}, "time": "5月3日", "content": "全量分页评价"}
                    ],
                    "isEnd": True,
                },
            }
            (log_dir / "review_shop-partial_20260521.json").write_text(json.dumps(partial_capture), encoding="utf-8")
            (log_dir / "review_shop-full_20260521.json").write_text(json.dumps(full_capture), encoding="utf-8")

            rows, stats = build_export_rows(
                stores=[
                    type("StoreLike", (), {"name": "达美乐比萨(部分店)", "address": "测试地址"})(),
                    type("StoreLike", (), {"name": "达美乐比萨(完整店)", "address": "测试地址"})(),
                ],
                log_dir=log_dir,
                explicit_uuid_map={
                    "达美乐比萨(部分店)": "shop-partial",
                    "达美乐比萨(完整店)": "shop-full",
                },
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(stats["stores_with_reviews"], 2)
        self.assertEqual(stats["stores_with_complete_reviews"], 1)
        self.assertEqual(stats["stores_with_partial_reviews"], 1)
        self.assertEqual(stats["stores_missing_reviews"], 1)
        self.assertEqual(stats["partial_review_stores"], ["达美乐比萨(部分店)"])

    def test_capture_is_full_review_requires_sifted_endpoint(self):
        self.assertFalse(capture_is_full_review({"url": "https://mapi.dianping.com/mapi/review/outsideshopreviewlist.bin"}))
        self.assertTrue(capture_is_full_review({"url": "https://mapi.dianping.com/mapi/review/outsidesiftedreviewlist.bin"}))


if __name__ == "__main__":
    unittest.main()
