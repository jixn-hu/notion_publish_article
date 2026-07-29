import re
from pathlib import Path

import markdown
from bs4 import BeautifulSoup

from backend.accounts import list_accounts, resolve_publish_account
from backend.browser import get_or_create_page, open_account_browser
from backend.media import VIDEO_EXTENSIONS
from backend.platforms.base import PlatformPublisher


def plain_text(markdown_text):
    html = markdown.markdown(markdown_text or "")
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def normalized_tags(values, limit=10):
    tags = []
    for value in values or []:
        tag = re.sub(r"^#+", "", str(value).strip())
        if tag:
            tags.append(tag)
        if len(tags) == limit:
            break
    return tags


class BrowserVideoPublisher(PlatformPublisher):
    implemented = True
    content_types = ("video",)

    def is_configured(self):
        return any(
            account["status"] == "valid"
            for account in list_accounts(self.key)
        )

    def test_connection(self):
        accounts = [
            account
            for account in list_accounts(self.key)
            if account["status"] == "valid"
        ]
        if not accounts:
            raise RuntimeError(f"请先在账号管理中添加并登录{self.name}账号")
        if not self.check_account(accounts[0]):
            raise RuntimeError(f"{self.name}登录状态已失效，请重新登录")
        return {
            "name": self.name,
            "message": f"账号“{accounts[0]['name']}”登录状态有效",
        }

    def publish(self, article, action="publish"):
        if action != "publish":
            raise ValueError(f"{self.name}浏览器发布暂不支持保存草稿")
        if article.get("article_type", "article") != "video":
            raise ValueError(f"{self.name}首期仅支持视频内容")

        account_id = (article.get("platform_accounts") or {}).get(self.key)
        account = resolve_publish_account(self.key, account_id)
        media_paths = article.get("media_paths") or []
        if len(media_paths) != 1:
            raise ValueError("视频内容必须且只能上传 1 个视频文件")
        video_path = Path(media_paths[0]).resolve()
        if not video_path.is_file():
            raise ValueError(f"素材文件不存在: {video_path.name}")
        if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError("视频内容的素材格式不正确")

        with open_account_browser(account) as context:
            page = get_or_create_page(context)
            self.publish_video(page, article, video_path)
            return {
                "status": "published",
                "external_id": page.url,
                "account_id": account["id"],
            }

    def check_account(self, account):
        raise NotImplementedError

    def publish_video(self, page, article, video_path):
        raise NotImplementedError
