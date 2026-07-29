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
    parse_compact_count,
)
from backend.platforms.browser_video import (
    BrowserVideoPublisher,
    normalized_tags,
    plain_text,
)


CREATOR_URL = "https://creator.douyin.com/"
PROFILE_URL = "https://creator.douyin.com/creator-micro/home"
UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
MANAGE_URL_PATTERN = "**/creator-micro/content/manage**"
LOGIN_MARKERS = ("扫码登录", "手机号登录", "二维码失效")
PROFILE_NAME_SELECTORS = (
    "[class*='user-info'] [class*='name']",
    "[class*='user-card'] [class*='name']",
    "[class*='nickname']",
    "header [class*='user'] [class*='name']",
)
PROFILE_AVATAR_SELECTORS = (
    "[class*='user-info'] img",
    "[class*='user-card'] img",
    "[class*='avatar'] img",
    "img[class*='avatar']",
)


def _is_logged_in(page):
    if "/login" in page.url:
        return False
    for marker in LOGIN_MARKERS:
        locator = page.get_by_text(marker, exact=True).first
        try:
            if locator.count() and locator.is_visible():
                return False
        except Exception:
            return False
    return "creator.douyin.com/creator-micro" in page.url


def _current_page(context, page):
    if not page.is_closed():
        return page
    pages = [candidate for candidate in context.pages if not candidate.is_closed()]
    if pages:
        return pages[-1]
    raise RuntimeError("登录浏览器已关闭，未检测到抖音登录成功")


def login_douyin_account(account, timeout_seconds=300):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(CREATOR_URL, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            page = _current_page(context, page)
            if _is_logged_in(page):
                page.wait_for_timeout(2000)
                return
            try:
                page.wait_for_timeout(1500)
            except Exception as exc:
                try:
                    page = _current_page(context, page)
                except Exception:
                    raise RuntimeError(
                        "登录浏览器已关闭，未检测到抖音登录成功"
                    ) from exc
    raise RuntimeError("等待抖音登录超时，请重新发起登录")


def check_douyin_account(account):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        return _is_logged_in(page)


def _find_douyin_user(value):
    if isinstance(value, dict):
        if (
            any(key in value for key in ("nickname", "screen_name"))
            and any(
                key in value
                for key in (
                    "uid",
                    "unique_id",
                    "follower_count",
                    "avatar_thumb",
                )
            )
        ):
            return value
        for child in value.values():
            result = _find_douyin_user(child)
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_douyin_user(child)
            if result:
                return result
    return {}


def _douyin_avatar_url(user):
    for key in ("avatar_thumb", "avatar_medium", "avatar_larger"):
        value = user.get(key)
        if isinstance(value, dict):
            urls = value.get("url_list") or []
            if urls:
                return str(urls[0])
        elif isinstance(value, str) and value:
            return value
    return str(user.get("avatar_url") or "")


def _douyin_text_profile(text):
    user_id = re.search(
        r"抖音号\s*[:：]\s*([^\s]+)",
        text,
    )
    return {
        "platform_user_id": user_id.group(1).strip() if user_id else "",
        "following_count": metric_from_text(
            text,
            ("关注数", "关注"),
        ),
        "followers_count": metric_from_text(
            text,
            ("粉丝总数", "粉丝数", "粉丝"),
        ),
        "works_count": metric_from_text(
            text,
            ("作品总数", "作品数", "作品"),
        ),
        "likes_count": metric_from_text(
            text,
            ("获赞总数", "获赞数", "获赞"),
        ),
    }


def extract_douyin_profile(page):
    body_text = page.locator("body").inner_text()
    text_profile = _douyin_text_profile(body_text)
    try:
        payload = page.evaluate(
            """
            async () => {
              const response = await fetch(
                '/aweme/v1/creator/pc/user/info/',
                { credentials: 'include' }
              )
              if (!response.ok) return {}
              return await response.json()
            }
            """
        )
    except Exception:
        payload = {}
    user = _find_douyin_user(payload)

    display_name = str(
        user.get("nickname")
        or user.get("screen_name")
        or first_visible_text(page, PROFILE_NAME_SELECTORS)
    ).strip()
    profile = {
        "display_name": display_name,
        "platform_user_id": str(
            user.get("unique_id")
            or user.get("short_id")
            or user.get("douyin_id")
            or text_profile["platform_user_id"]
            or user.get("uid")
            or ""
        ).strip(),
        "avatar_url": _douyin_avatar_url(user),
        "following_count": parse_compact_count(
            user.get("following_count")
        ),
        "followers_count": parse_compact_count(
            user.get("follower_count")
            if user.get("follower_count") is not None
            else user.get("fans_count")
        ),
        "works_count": parse_compact_count(
            user.get("aweme_count")
            if user.get("aweme_count") is not None
            else user.get("works_count")
        ),
        "likes_count": parse_compact_count(
            user.get("total_favorited")
            if user.get("total_favorited") is not None
            else user.get("total_favorite")
        ),
    }
    for key in (
        "following_count",
        "followers_count",
        "works_count",
        "likes_count",
    ):
        if profile[key] is None:
            profile[key] = text_profile[key]
    if not profile["display_name"]:
        raise RuntimeError("未能从抖音创作中心识别账号昵称")
    return profile


def fetch_douyin_profile(account, page=None):
    if page is None:
        with open_account_browser(account) as context:
            active_page = get_or_create_page(context)
            active_page.goto(
                PROFILE_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            active_page.wait_for_timeout(3500)
            return fetch_douyin_profile(account, page=active_page)

    if not _is_logged_in(page):
        raise RuntimeError("抖音登录状态已失效，请重新登录")
    profile = extract_douyin_profile(page)
    avatar = first_visible_image(page, PROFILE_AVATAR_SELECTORS)
    try:
        if avatar is None:
            raise RuntimeError("未找到抖音账号头像")
        avatar_path = account_avatar_path(account)
        avatar_path.parent.mkdir(parents=True, exist_ok=True)
        avatar.screenshot(path=str(avatar_path))
        profile["avatar_cached"] = True
    except Exception:
        profile["avatar_cached"] = False
    return profile

class DouyinPublisher(BrowserVideoPublisher):
    key = "douyin"
    name = "抖音"

    def check_account(self, account):
        return check_douyin_account(account)

    def publish_video(self, page, article, video_path):
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1500)
        if not _is_logged_in(page):
            raise RuntimeError("抖音登录状态已失效，请重新登录")

        upload = page.locator(
            "div[class^='container'] input[type='file'], input[type='file']"
        ).first
        upload.wait_for(state="attached", timeout=60_000)
        upload.set_input_files(str(video_path))

        title_input = page.locator(
            "input[placeholder*='填写作品标题']"
        ).first
        title_input.wait_for(state="visible", timeout=10 * 60_000)
        title = str(article.get("title") or "").strip()
        if not title:
            raise ValueError("标题不能为空")
        replace_text(page, title_input, title[:30])

        body = plain_text(article.get("content_md", ""))
        tags = normalized_tags(article.get("tags"))
        suffix = " ".join(f"#{tag}" for tag in tags)
        description = "\n\n".join(
            value for value in (body, suffix) if value
        )[:2000]
        if description:
            editor = page.locator(
                "div.zone-container[contenteditable='true']"
            ).first
            editor.wait_for(state="visible", timeout=30_000)
            editor.click()
            page.keyboard.press("Control+A")
            page.keyboard.type(description, delay=typing_delay(description))

        page.get_by_text("重新上传", exact=True).first.wait_for(
            state="visible",
            timeout=10 * 60_000,
        )
        button = page.get_by_role("button", name="发布", exact=True).first
        button.wait_for(state="visible", timeout=60_000)
        interaction_pause(page, 350, 900)
        button.click()
        try:
            page.wait_for_url(MANAGE_URL_PATTERN, timeout=5 * 60_000)
        except Exception as exc:
            success = page.get_by_text("发布成功", exact=False).first
            if not success.count() or not success.is_visible():
                error = page.locator(
                    "[class*='error']:visible, [class*='toast']:visible"
                ).first
                message = error.inner_text().strip() if error.count() else ""
                raise RuntimeError(
                    message
                    or "未检测到抖音发布成功；如页面要求验证，请在浏览器中完成后重试"
                ) from exc
