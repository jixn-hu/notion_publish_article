import re
import time

from backend.accounts import account_avatar_path
from backend.browser import (
    get_or_create_page,
    interaction_pause,
    open_account_browser,
    replace_text,
    typing_delay,
)
from backend.platforms.profile_utils import (
    first_visible_image,
    first_visible_text,
    metric_from_text,
)
from backend.platforms.browser_video import (
    BrowserVideoPublisher,
    normalized_tags,
    plain_text,
)


PROFILE_URL = "https://channels.weixin.qq.com/platform/home"
UPLOAD_URL = "https://channels.weixin.qq.com/platform/post/create"
MANAGE_URL_PATTERN = "**/platform/post/list**"
PROFILE_NAME_SELECTORS = (
    "[class*='account'] [class*='name']",
    "[class*='user'] [class*='name']",
    "[class*='nickname']",
    "header [class*='name']",
)
PROFILE_AVATAR_SELECTORS = (
    "[class*='account'] img",
    "[class*='user'] img",
    "[class*='avatar'] img",
    "img[class*='avatar']",
)


def _is_logged_in(page):
    if "/login" in page.url:
        return False
    if any(
        "open.weixin.qq.com/connect/qrconnect" in frame.url
        for frame in page.frames
    ):
        return False
    return "/platform/" in page.url


def login_channels_account(account, timeout_seconds=300):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if _is_logged_in(page):
                page.wait_for_timeout(2000)
                return
            page.wait_for_timeout(1500)
    raise RuntimeError("等待视频号登录超时，请重新发起登录")


def check_channels_account(account):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        return _is_logged_in(page)


def _channels_text_profile(text):
    user_id = re.search(
        r"(?:视频号|微信号)(?:\s*(?:ID|id|账号))?\s*[:：]\s*([^\s]+)",
        text,
    )
    return {
        "platform_user_id": user_id.group(1).strip() if user_id else "",
        "followers_count": metric_from_text(
            text,
            ("有效关注人数", "关注者", "粉丝总数", "粉丝数", "粉丝"),
        ),
        "works_count": metric_from_text(
            text,
            ("发表视频数", "视频", "作品总数", "作品数", "内容数"),
        ),
        "likes_count": metric_from_text(
            text,
            ("获赞总数", "获赞数", "点赞数"),
        ),
    }


def extract_channels_profile(page):
    body_text = page.locator("html > body").first.inner_text()
    profile = _channels_text_profile(body_text)
    profile.update(
        {
            "display_name": first_visible_text(
                page,
                PROFILE_NAME_SELECTORS,
            ),
            "avatar_url": "",
            "following_count": None,
        }
    )
    avatar = first_visible_image(page, PROFILE_AVATAR_SELECTORS)
    if avatar is not None:
        profile["avatar_url"] = avatar.get_attribute("src") or ""
        if not profile["display_name"]:
            profile["display_name"] = (
                avatar.get_attribute("alt") or ""
            ).strip()
    if not profile["display_name"]:
        raise RuntimeError("未能从视频号助手识别账号昵称")
    return profile


def fetch_channels_profile(account):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3500)
        if not _is_logged_in(page):
            raise RuntimeError("视频号登录状态已失效，请重新登录")
        profile = extract_channels_profile(page)
        avatar = first_visible_image(page, PROFILE_AVATAR_SELECTORS)
        try:
            if avatar is None:
                raise RuntimeError("未找到视频号账号头像")
            avatar_path = account_avatar_path(account)
            avatar_path.parent.mkdir(parents=True, exist_ok=True)
            avatar.screenshot(path=str(avatar_path))
            profile["avatar_cached"] = True
        except Exception:
            profile["avatar_cached"] = False
        return profile


def _find_upload_input(page, timeout_seconds=60):
    deadline = time.monotonic() + timeout_seconds
    clicked_entry = False
    while time.monotonic() < deadline:
        for frame in page.frames:
            upload = frame.locator("input[type='file']").first
            if upload.count():
                return upload
        if not clicked_entry:
            entry = page.get_by_text("发表视频", exact=True).first
            if entry.count() and entry.is_visible():
                entry.click()
                clicked_entry = True
        page.wait_for_timeout(1000)
    raise RuntimeError("未找到视频号视频上传入口，请确认创作中心页面是否正常")


class ChannelsPublisher(BrowserVideoPublisher):
    key = "channels"
    name = "视频号"

    def check_account(self, account):
        return check_channels_account(account)

    def publish_video(self, page, article, video_path):
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1500)
        if not _is_logged_in(page):
            raise RuntimeError("视频号登录状态已失效，请重新登录")

        _find_upload_input(page).set_input_files(str(video_path))
        editor = page.locator("div.input-editor").first
        editor.wait_for(state="visible", timeout=10 * 60_000)

        title = str(article.get("title") or "").strip()
        if not title:
            raise ValueError("标题不能为空")
        editor.click()
        page.keyboard.type(title, delay=typing_delay(title))
        page.keyboard.press("Enter")
        for tag in normalized_tags(article.get("tags")):
            page.keyboard.type(f"#{tag}", delay=typing_delay(tag))
            page.keyboard.press("Space")
        body = plain_text(article.get("content_md", ""))
        if body:
            page.keyboard.press("Enter")
            body = body[:1500]
            page.keyboard.type(body, delay=typing_delay(body))

        short_title = page.locator("input[placeholder*='短标题']").first
        if not short_title.count():
            short_title_label = page.get_by_text("短标题", exact=True).first
            if short_title_label.count():
                short_title = short_title_label.locator(
                    "xpath=following::input[1]"
                )
        if short_title.count() and short_title.is_visible():
            replace_text(page, short_title, title[:16])

        button = page.locator(
            "div.form-btns button:has-text('发表')"
        ).first
        deadline = time.monotonic() + 10 * 60
        while time.monotonic() < deadline:
            upload_error = page.locator("div.status-msg.error").first
            if upload_error.count() and upload_error.is_visible():
                raise RuntimeError(upload_error.inner_text().strip())
            if button.count() and button.is_visible() and button.is_enabled():
                classes = button.get_attribute("class") or ""
                if "disabled" not in classes:
                    break
            page.wait_for_timeout(1500)
        else:
            raise RuntimeError("视频号视频上传超时，或“发表”按钮仍不可用")

        interaction_pause(page, 350, 900)
        button.click()
        try:
            page.wait_for_url(MANAGE_URL_PATTERN, timeout=3 * 60_000)
        except Exception as exc:
            success = page.get_by_text("发表成功", exact=False).first
            if not success.count() or not success.is_visible():
                raise RuntimeError(
                    "未检测到视频号发布成功页面，请在浏览器中确认结果"
                ) from exc
