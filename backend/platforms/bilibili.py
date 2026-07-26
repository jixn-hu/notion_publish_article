import time

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


CREATOR_URL = "https://member.bilibili.com/creator/home"
UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"
SUCCESS_URL_PATTERNS = (
    "**/platform/upload-manager/**",
    "**/platform/upload/video/success**",
)


def _is_logged_in(page):
    if "passport.bilibili.com" in page.url or "/login" in page.url:
        return False
    login = page.get_by_text("登录", exact=True).first
    try:
        if login.count() and login.is_visible():
            return False
    except Exception:
        return False
    return "member.bilibili.com" in page.url


def login_bilibili_account(account, timeout_seconds=300):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(CREATOR_URL, wait_until="domcontentloaded", timeout=60_000)
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
        page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        return _is_logged_in(page)


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
