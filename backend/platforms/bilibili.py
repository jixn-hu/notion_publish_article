import re
import time

from backend.accounts import account_avatar_path
from backend.browser import (
    get_or_create_page,
    interaction_pause,
    open_account_browser,
    replace_text,
)
from backend.platforms.browser_video import (
    BrowserVideoPublisher,
    normalized_tags,
    plain_text,
)
from backend.platforms.profile_utils import (
    first_visible_image,
    first_visible_text,
    metric_from_text,
    parse_compact_count,
)


LOGIN_URL = "https://passport.bilibili.com/login"
CREATOR_URL = "https://member.bilibili.com/creator/home"
UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"
SUCCESS_URL_PATTERNS = (
    "**/platform/upload-manager/**",
    "**/platform/upload/video/success**",
)
PROFILE_NAME_SELECTORS = (
    "[class*='user-info'] [class*='name']",
    "[class*='user-card'] [class*='name']",
    "[class*='nickname']",
    "[class*='user-name']",
    "header [class*='name']",
)
PROFILE_AVATAR_SELECTORS = (
    "[class*='user-info'] img",
    "[class*='user-card'] img",
    "[class*='avatar'] img",
    "img[class*='avatar']",
)
NAV_API_URL = "https://api.bilibili.com/x/web-interface/nav"
RELATION_API_URL = "https://api.bilibili.com/x/relation/stat?vmid={mid}"
NAVNUM_API_URL = "https://api.bilibili.com/x/space/navnum?mid={mid}"


def _is_logged_in(page):
    if "passport.bilibili.com" in page.url or "/login" in page.url:
        return False
    login = page.get_by_text("登录", exact=True).first
    try:
        if login.count() and login.is_visible():
            return False
    except Exception:
        return False
    return any(
        domain in page.url
        for domain in ("member.bilibili.com", "www.bilibili.com")
    )


def bilibili_account_url(account):
    return CREATOR_URL if account.get("status") == "valid" else LOGIN_URL


def login_bilibili_account(account, timeout_seconds=300):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if _is_logged_in(page):
                page.wait_for_timeout(2000)
                return
            page.wait_for_timeout(1500)
    raise RuntimeError("等待 Bilibili 登录超时，请重新发起登录")


def check_bilibili_account(account):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(CREATOR_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        return _is_logged_in(page)


def _payload_data(payload):
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _bilibili_api_profile(nav_payload, relation_payload=None, navnum_payload=None):
    nav = _payload_data(nav_payload)
    relation = _payload_data(relation_payload or {})
    navnum = _payload_data(navnum_payload or {})
    level_info = nav.get("level_info")
    if not isinstance(level_info, dict):
        level_info = {}
    return {
        "display_name": str(nav.get("uname") or "").strip(),
        "platform_user_id": str(nav.get("mid") or "").strip(),
        "avatar_url": str(nav.get("face") or "").strip(),
        "following_count": parse_compact_count(relation.get("following")),
        "followers_count": parse_compact_count(relation.get("follower")),
        "works_count": parse_compact_count(
            navnum.get("video")
            if navnum.get("video") is not None
            else navnum.get("archive")
        ),
        "level": parse_compact_count(level_info.get("current_level")),
    }


def _bilibili_text_profile(text):
    user_id = re.search(r"(?:UID|uid)\s*[:：]?\s*(\d+)", text)
    return {
        "platform_user_id": user_id.group(1) if user_id else "",
        "following_count": metric_from_text(text, ("关注数", "关注")),
        "followers_count": metric_from_text(
            text,
            ("粉丝总数", "粉丝数", "粉丝"),
        ),
        "works_count": metric_from_text(
            text,
            ("视频总数", "视频数", "稿件数", "作品数", "视频", "稿件", "作品"),
        ),
    }


def _bilibili_api_json(page, url):
    try:
        response = page.context.request.get(
            url,
            headers={"Referer": "https://www.bilibili.com/"},
            timeout=30_000,
        )
        if not response.ok:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def extract_bilibili_profile(page):
    body_text = page.locator("body").inner_text()
    nav_payload = _bilibili_api_json(page, NAV_API_URL)
    nav = _payload_data(nav_payload)
    mid = str(nav.get("mid") or "").strip()
    relation_payload = (
        _bilibili_api_json(page, RELATION_API_URL.format(mid=mid))
        if mid
        else {}
    )
    navnum_payload = (
        _bilibili_api_json(page, NAVNUM_API_URL.format(mid=mid))
        if mid
        else {}
    )
    api_profile = _bilibili_api_profile(
        nav_payload,
        relation_payload,
        navnum_payload,
    )
    text_profile = _bilibili_text_profile(body_text)
    profile = {
        "display_name": api_profile["display_name"] or first_visible_text(
            page,
            PROFILE_NAME_SELECTORS,
        ),
        "platform_user_id": (
            api_profile["platform_user_id"]
            or text_profile["platform_user_id"]
        ),
        "avatar_url": api_profile["avatar_url"],
        "following_count": (
            api_profile["following_count"]
            if api_profile["following_count"] is not None
            else text_profile["following_count"]
        ),
        "followers_count": (
            api_profile["followers_count"]
            if api_profile["followers_count"] is not None
            else text_profile["followers_count"]
        ),
        "works_count": (
            api_profile["works_count"]
            if api_profile["works_count"] is not None
            else text_profile["works_count"]
        ),
        "level": api_profile["level"],
    }
    avatar = first_visible_image(page, PROFILE_AVATAR_SELECTORS)
    if avatar is not None:
        profile["avatar_url"] = (
            profile["avatar_url"] or avatar.get_attribute("src") or ""
        )
        if not profile["display_name"]:
            profile["display_name"] = (
                avatar.get_attribute("alt") or ""
            ).strip()
    if not profile["display_name"]:
        raise RuntimeError("未能从 Bilibili 创作中心识别账号昵称")
    return profile


def _cache_bilibili_avatar(page, account, profile):
    avatar = first_visible_image(page, PROFILE_AVATAR_SELECTORS)
    injected = False
    try:
        if avatar is None:
            avatar_url = str(profile.get("avatar_url") or "").strip()
            if not avatar_url:
                raise RuntimeError("未找到 Bilibili 账号头像")
            page.evaluate(
                """url => {
                    document.querySelector(
                        'img[data-moflow-profile-avatar]'
                    )?.remove()
                    const image = document.createElement('img')
                    image.dataset.moflowProfileAvatar = 'true'
                    image.src = url
                    Object.assign(image.style, {
                        position: 'fixed',
                        left: '8px',
                        top: '8px',
                        width: '96px',
                        height: '96px',
                        objectFit: 'cover',
                        zIndex: '2147483647',
                        visibility: 'visible'
                    })
                    document.body.appendChild(image)
                }""",
                avatar_url,
            )
            injected = True
            avatar = page.locator("img[data-moflow-profile-avatar]").first
            page.wait_for_function(
                """() => {
                    const image = document.querySelector(
                        'img[data-moflow-profile-avatar]'
                    )
                    return Boolean(
                        image && image.complete && image.naturalWidth > 0
                    )
                }""",
                timeout=15_000,
            )
        avatar_path = account_avatar_path(account)
        avatar_path.parent.mkdir(parents=True, exist_ok=True)
        avatar.screenshot(path=str(avatar_path))
        return True
    except Exception:
        return False
    finally:
        if injected:
            try:
                page.locator(
                    "img[data-moflow-profile-avatar]"
                ).first.evaluate("node => node.remove()")
            except Exception:
                pass


def fetch_bilibili_profile(account, page=None):
    if page is None:
        with open_account_browser(account) as context:
            active_page = get_or_create_page(context)
            active_page.goto(
                CREATOR_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            active_page.wait_for_timeout(3000)
            return fetch_bilibili_profile(account, page=active_page)

    if not _is_logged_in(page):
        raise RuntimeError("Bilibili 登录状态已失效，请重新登录")
    profile = extract_bilibili_profile(page)
    profile["avatar_cached"] = _cache_bilibili_avatar(
        page,
        account,
        profile,
    )
    return profile


class BilibiliPublisher(BrowserVideoPublisher):
    key = "bilibili"
    name = "Bilibili"

    def check_account(self, account):
        return check_bilibili_account(account)

    def publish_video(self, page, article, video_path):
        category = str(
            self.settings.get("bilibili_default_category") or ""
        ).strip()
        copyright_type = str(
            self.settings.get("bilibili_copyright") or ""
        ).strip()
        if not category:
            raise ValueError("请先在设置中填写 Bilibili 默认分区")
        if copyright_type not in {"self", "repost"}:
            raise ValueError("请先在设置中选择 Bilibili 稿件类型")
        if copyright_type == "repost" and not article.get("source_url"):
            raise ValueError("转载稿件必须填写阅读原文 URL 作为转载来源")

        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1500)
        if not _is_logged_in(page):
            raise RuntimeError("Bilibili 登录状态已失效，请重新登录")

        upload = page.locator(
            "input[type='file'][accept*='video'], input[type='file']"
        ).first
        upload.wait_for(state="attached", timeout=60_000)
        upload.set_input_files(str(video_path))

        title_input = page.locator(
            "input[placeholder*='稿件标题'], input[placeholder*='标题']"
        ).first
        title_input.wait_for(state="visible", timeout=10 * 60_000)
        title = str(article.get("title") or "").strip()
        if not title:
            raise ValueError("标题不能为空")
        replace_text(page, title_input, title[:80])

        copyright_label = "自制" if copyright_type == "self" else "转载"
        copyright_option = page.get_by_text(copyright_label, exact=True).first
        copyright_option.wait_for(state="visible", timeout=30_000)
        interaction_pause(page)
        copyright_option.click()
        if copyright_type == "repost":
            source_input = page.locator(
                "input[placeholder*='转载'], input[placeholder*='来源']"
            ).first
            source_input.wait_for(state="visible", timeout=30_000)
            replace_text(
                page,
                source_input,
                str(article["source_url"]).strip(),
            )

        category_control = page.get_by_text("请选择分区", exact=False).first
        category_control.wait_for(state="visible", timeout=30_000)
        interaction_pause(page)
        category_control.click()
        category_option = page.get_by_text(category, exact=False).last
        category_option.wait_for(state="visible", timeout=30_000)
        interaction_pause(page)
        category_option.click()

        tags = normalized_tags(article.get("tags"))
        if not tags:
            raise ValueError("Bilibili 视频至少需要 1 个标签")
        tag_input = page.locator(
            "input[placeholder*='标签'], input[placeholder*='Enter创建标签']"
        ).first
        tag_input.wait_for(state="visible", timeout=30_000)
        for tag in tags:
            replace_text(page, tag_input, tag)
            tag_input.press("Enter")

        description = plain_text(article.get("content_md", ""))[:2000]
        if description:
            description_input = page.locator(
                "textarea[placeholder*='简介'], "
                ".ql-editor[contenteditable='true'], "
                "[contenteditable='true'][data-placeholder*='简介']"
            ).first
            description_input.wait_for(state="visible", timeout=30_000)
            replace_text(page, description_input, description)

        button = page.get_by_text(
            "立即投稿",
            exact=True,
        ).first
        if not button.count():
            button = page.get_by_text("提交稿件", exact=True).first
        deadline = time.monotonic() + 10 * 60
        while time.monotonic() < deadline:
            if button.count() and button.is_visible() and button.is_enabled():
                classes = button.get_attribute("class") or ""
                if "disabled" not in classes:
                    break
            page.wait_for_timeout(1500)
        else:
            raise RuntimeError("Bilibili 视频上传超时，或投稿按钮仍不可用")

        interaction_pause(page, 350, 900)
        button.click()
        for pattern in SUCCESS_URL_PATTERNS:
            try:
                page.wait_for_url(pattern, timeout=60_000)
                return
            except Exception:
                continue
        success = page.get_by_text("投稿成功", exact=False).first
        if not success.count() or not success.is_visible():
            error = page.locator(
                "[class*='error']:visible, [class*='toast']:visible"
            ).first
            message = error.inner_text().strip() if error.count() else ""
            raise RuntimeError(
                message or "未检测到 Bilibili 投稿成功页面，请在浏览器中确认结果"
            )
