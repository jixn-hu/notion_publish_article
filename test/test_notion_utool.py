import unittest
from unittest.mock import Mock, patch

import notion_utool


def property_value(property_type, value):
    return {"type": property_type, property_type: value}


class NotionUtoolTests(unittest.TestCase):
    def setUp(self):
        self.request = patch.object(notion_utool._session, "request").start()
        self.addCleanup(patch.stopall)

    def response(self, data):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = data
        return response

    def test_queries_the_database_data_source(self):
        page = {
            "id": "page-id",
            "url": "https://notion.so/page-id",
            "properties": {
                "标题": property_value(
                    "title", [{"plain_text": "测试文章"}]
                ),
                "封面图片": property_value("url", "https://example.com/cover.jpg"),
                "作者": property_value("select", {"name": "作者"}),
                "文章类型": property_value("select", {"name": "图文"}),
                "阅读原文": property_value("url", None),
                "标签": property_value("multi_select", [{"name": "测试"}]),
            },
        }
        self.request.side_effect = [
            self.response({"data_sources": [{"id": "source-id", "name": "默认"}]}),
            self.response({"results": [page], "has_more": False}),
        ]

        with patch.object(notion_utool.config, "data_source_id", "", create=True):
            result = notion_utool.database_get_fb_info()

        self.assertEqual(result[0]["标题"], "测试文章")
        self.assertEqual(
            self.request.call_args_list[1].args[:2],
            ("POST", f"{notion_utool.NOTION_API_BASE}/data_sources/source-id/query"),
        )
        self.assertEqual(
            self.request.call_args_list[1].kwargs["headers"]["Notion-Version"],
            "2026-03-11",
        )

    def test_reads_page_with_official_markdown_endpoint(self):
        self.request.return_value = self.response(
            {
                "object": "page_markdown",
                "markdown": "# 标题",
                "truncated": False,
                "unknown_block_ids": [],
            }
        )

        result = notion_utool.page_get_info("page-id")

        self.assertEqual(result, "# 标题")
        self.assertIn("/pages/page-id/markdown", self.request.call_args.args[1])

    def test_updates_page_with_valid_property_payload(self):
        self.request.return_value = self.response({"id": "page-id"})

        notion_utool.database_update_fb_info("page-id")

        payload = self.request.call_args.kwargs["json"]
        self.assertEqual(
            payload["properties"]["已发布平台"]["multi_select"],
            [{"name": "微信公众号"}],
        )


if __name__ == "__main__":
    unittest.main()
