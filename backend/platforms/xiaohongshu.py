import re
import time
from pathlib import Path

import markdown
from bs4 import BeautifulSoup

from backend.accounts import (
    account_avatar_path,
    list_accounts,
    resolve_publish_account,
)
from backend.browser import (
    get_or_create_page,
    interaction_pause,
    open_account_browser,
    replace_text,
    typing_delay,
)
from backend.platforms.base import PlatformPublisher


CREATOR_BASE_URL = "https://creator.xiaohongshu.com"
LOGIN_URL = f"{CREATOR_BASE_URL}/login"
VIDEO_PUBLISH_URL = (
    f"{CREATOR_BASE_URL}/publish/publish?from=homepage&target=video"
)
IMAGE_PUBLISH_URL = (
    f"{CREATOR_BASE_URL}/publish/publish?from=homepage&target=image"
)
PROFILE_URL = f"{CREATOR_BASE_URL}/new/home"
LOGIN_BOX_SELECTOR = "div[class*='login-box']"
PUBLISH_SUCCESS_PATTERN = "**/publish/success?**"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}


def _is_logged_in(page):
    if "/login" in page.url:
        return False
    login_box = page.locator(LOGIN_BOX_SELECTOR).first
    if not login_box.count():
        return True
    try:
        return not login_box.is_visible()
    except Exception:
        return False


def login_xiaohongshu_account(account, timeout_seconds=300):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if _is_logged_in(page):
                page.wait_for_timeout(2000)
                return
            page.wait_for_timeout(1500)
    raise RuntimeError("等待小红书登录超时，请重新发起登录")


def check_xiaohongshu_account(account):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(VIDEO_PUBLISH_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        return _is_logged_in(page)


def _parse_profile_count(text):
    value = str(text or "").replace(",", "").strip()
    multiplier = 1
    if value.endswith("万"):
        value = value[:-1]
        multiplier = 10_000
    elif value.endswith("亿"):
        value = value[:-1]
        multiplier = 100_000_000
    try:
        return int(float(value) * multiplier)
    except ValueError:
        return None


def _profile_count(card_text, label):
    match = re.search(rf"([\d.,万亿]+)\s*{re.escape(label)}", card_text)
    return _parse_profile_count(match.group(1)) if match else None


def extract_xiaohongshu_profile(page):
    card = page.locator("[class*='personal']").first
    card.wait_for(state="visible", timeout=30_000)
    card_text = card.inner_text()

    name = page.locator("[class*='user-info']").first
    display_name = name.inner_text().strip() if name.count() else ""
    user_id_match = re.search(r"小红书账号\s*[:：]\s*([^\s]+)", card_text)
    avatar = card.locator("img[src*='/avatar/']").first
    avatar_url = avatar.get_attribute("src") if avatar.count() else ""

    profile = {
        "display_name": display_name,
        "platform_user_id": (
            user_id_match.group(1).strip() if user_id_match else ""
        ),
        "avatar_url": avatar_url or "",
        "following_count": _profile_count(card_text, "关注数"),
        "followers_count": _profile_count(card_text, "粉丝数"),
        "likes_and_collections_count": _profile_count(
            card_text,
            "获赞与收藏",
        ),
    }
    if not profile["display_name"] or not profile["platform_user_id"]:
        raise RuntimeError("未能从小红书创作首页识别账号昵称或账号 ID")
    return profile


def fetch_xiaohongshu_profile(account, page=None):
    if page is None:
        with open_account_browser(account) as context:
            active_page = get_or_create_page(context)
            active_page.goto(
                PROFILE_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            active_page.wait_for_timeout(2500)
            return fetch_xiaohongshu_profile(account, page=active_page)

    if not _is_logged_in(page):
        raise RuntimeError("小红书登录状态已失效，请重新登录")
    profile = extract_xiaohongshu_profile(page)
    avatar = page.locator(
        "[class*='personal'] img[src*='/avatar/']"
    ).first
    try:
        avatar_path = account_avatar_path(account)
        avatar_path.parent.mkdir(parents=True, exist_ok=True)
        avatar.screenshot(path=str(avatar_path))
        profile["avatar_cached"] = True
    except Exception:
        profile["avatar_cached"] = False
    return profile

def _plain_text(markdown_text):
    html = markdown.markdown(markdown_text or "")
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def _validated_media_paths(article):
    paths = []
    for value in article.get("media_paths") or []:
        path = Path(value).resolve()
        if not path.is_file():
            raise ValueError(f"素材文件不存在: {path.name}")
        paths.append(path)
    return paths


class XiaohongshuPublisher(PlatformPublisher):
    key = "xiaohongshu"
    name = "小红书"
    implemented = True
    content_types = ("image", "video")

    def is_configured(self):
        return any(
            item["status"] == "valid"
            for item in list_accounts(self.key)
        )

    def test_connection(self):
        accounts = [
            item
            for item in list_accounts(self.key)
            if item["status"] == "valid"
        ]
        if not accounts:
            raise RuntimeError("请先在账号管理中添加并登录小红书账号")
        if not check_xiaohongshu_account(accounts[0]):
            raise RuntimeError("小红书登录状态已失效，请重新登录")
        return {
            "name": self.name,
            "message": f"账号“{accounts[0]['name']}”登录状态有效",
        }

    def publish(self, article, action="publish"):
        if action != "publish":
            raise ValueError("小红书浏览器发布暂不支持保存草稿")

        content_type = article.get("article_type", "article")
        if content_type not in {"image", "video"}:
            raise ValueError("小红书首期仅支持图文和视频内容")
        account_id = (article.get("platform_accounts") or {}).get(self.key)
        account = resolve_publish_account(self.key, account_id)
        media_paths = _validated_media_paths(article)

        if content_type == "video":
            if len(media_paths) != 1:
                raise ValueError("视频内容必须且只能上传 1 个视频文件")
            if media_paths[0].suffix.lower() not in VIDEO_EXTENSIONS:
                raise ValueError("视频内容的素材格式不正确")
        else:
            if not media_paths:
                raise ValueError("图文内容至少需要 1 张图片")
            if any(path.suffix.lower() not in IMAGE_EXTENSIONS for path in media_paths):
                raise ValueError("图文内容只能包含图片素材")

        with open_account_browser(account) as context:
            page = get_or_create_page(context)
            target_url = (
                VIDEO_PUBLISH_URL if content_type == "video" else IMAGE_PUBLISH_URL
            )
            page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1500)
            if not _is_logged_in(page):
                raise RuntimeError("小红书登录状态已失效，请重新登录")

            self._upload_media(page, content_type, media_paths)
            self._fill_content(page, article)
            self._submit(page)
            return {
                "status": "published",
                "external_id": page.url,
                "account_id": account["id"],
            }

    @staticmethod
    def _upload_media(page, content_type, media_paths):
        if content_type == "video":
            upload = page.locator(
                "input[type='file'][accept*='video'], "
                "div[class^='upload-content'] input.upload-input"
            ).first
            files = str(media_paths[0])
            wait_timeout = 10 * 60_000
        else:
            upload = page.locator(
                "input[type='file'][accept*='image'], "
                "div[class^='upload-content'] input.upload-input"
            ).first
            files = [str(path) for path in media_paths]
            wait_timeout = 3 * 60_000

        upload.wait_for(state="attached", timeout=30_000)
        upload.set_input_files(files)
        page.locator("input[placeholder*='填写标题']").first.wait_for(
            state="visible",
            timeout=wait_timeout,
        )

    @staticmethod
    def _fill_content(page, article):
        title = str(article.get("title") or "").strip()
        if not title:
            raise ValueError("标题不能为空")
        replace_text(
            page,
            page.locator("input[placeholder*='填写标题']").first,
            title[:20],
        )

        body = _plain_text(article.get("content_md", ""))
        tags = [
            re.sub(r"^#+", "", str(tag).strip())
            for tag in (article.get("tags") or [])[:10]
            if str(tag).strip()
        ]
        suffix = " ".join(f"#{tag}" for tag in tags)
        description = "\n\n".join(item for item in [body, suffix] if item)[:1000]
        if description:
            editor = page.locator(
                "p[data-placeholder*='输入正文描述'], "
                "[contenteditable='true'][data-placeholder*='正文']"
            ).first
            editor.wait_for(state="visible", timeout=30_000)
            editor.click()
            page.keyboard.press("Control+A")
            page.keyboard.type(description, delay=typing_delay(description))

    @staticmethod
    def _submit(page):
        button = page.locator("button:has-text('发布')").filter(
            has_not_text="定时发布"
        ).first
        button.wait_for(state="visible", timeout=60_000)
        interaction_pause(page, 350, 900)
        button.click()
        try:
            page.wait_for_url(PUBLISH_SUCCESS_PATTERN, timeout=60_000)
        except Exception as exc:
            success = page.locator("text=发布成功").first
            if not success.count() or not success.is_visible():
                error = page.locator(
                    "[class*='error']:visible, [class*='toast']:visible"
                ).first
                message = ""
                if error.count():
                    message = error.inner_text().strip()
                raise RuntimeError(
                    message or "未检测到小红书发布成功页面，请在浏览器中确认结果"
                ) from exc
