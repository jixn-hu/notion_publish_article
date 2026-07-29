import unittest
from unittest.mock import Mock, patch

from backend.markdown_utils import normalize_notion_markdown
from backend.notion_client import NotionClient


class NotionMarkdownTests(unittest.TestCase):
    def test_html_blocks_are_converted_to_plain_markdown(self):
        source = """## 视图
<table header-row="true">
<tr><td>快捷键</td><td>作用</td></tr>
<tr><td>`Ctrl/⌘ + \\`</td><td>侧边栏</td></tr>
</table>
**做法：** 保留后续 Markdown。
<callout icon="💡" color="blue_bg">
    **进阶：** 使用动态日期。
</callout>
## 后续标题
- [ ] 后续任务
"""

        result = normalize_notion_markdown(source)

        self.assertIn("| 快捷键 | 作用 |", result)
        self.assertIn("| --- | --- |", result)
        self.assertIn("| `Ctrl/⌘ + \\` | 侧边栏 |", result)
        self.assertIn("> 💡 **进阶：** 使用动态日期。", result)
        self.assertIn("\n\n## 后续标题\n", result)
        self.assertIn("- [ ] 后续任务", result)
        self.assertNotRegex(result, r"<[^>]+>")

    def test_inline_html_is_also_converted(self):
        source = "<p><strong>重点</strong>与<a href=\"https://example.com\">链接</a></p>"

        result = normalize_notion_markdown(source)

        self.assertEqual(result, "**重点**与[链接](https://example.com)")

    def test_markdown_code_and_autolinks_are_preserved(self):
        source = "`<table>`\n\n<https://example.com/path>\n\n```html\n<div>示例</div>\n```"

        result = normalize_notion_markdown(source)

        self.assertEqual(result, source)

    def test_official_markdown_endpoint_returns_normalized_content(self):
        client = NotionClient("token", "database", data_source_id="source")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "markdown": (
                '<table header-row="true"><tr><td>列名</td></tr>'
                '<tr><td>内容</td></tr></table>\n## 后续'
            ),
            "truncated": False,
        }

        with patch.object(client.session, "request", return_value=response):
            result = client.get_page_markdown("page-id")

        self.assertIn("| 列名 |", result)
        self.assertIn("\n\n## 后续", result)
        self.assertNotIn("<table", result)


if __name__ == "__main__":
    unittest.main()
