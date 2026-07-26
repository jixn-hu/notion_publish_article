import logging
import re
import time
from collections import Counter
from pathlib import Path

import markdown
from bs4 import BeautifulSoup

from backend.accounts import account_avatar_path, list_accounts, resolve_publish_account
from backend.browser import get_or_create_page, open_account_browser, replace_text
from backend.media import IMAGE_EXTENSIONS
from backend.platforms.base import PlatformPublisher
from backend.platforms.profile_utils import parse_compact_count


HOME_URL = "https://mp.csdn.net/"
EDITOR_URL = "https://mp.csdn.net/mp_blog/creation/editor"
LOGIN_SELECTORS = (
    "iframe[src*='passport.csdn.net']",
    "[class*='login-dialog']",
    "[class*='login-box']",
    "input[placeholder*='手机号']",
)
LOGIN_TEXT = "登录"
PROFILE_CARD_SELECTOR = ".home-exp-user-card"
PROFILE_NAME_SELECTOR = ".home-exp-user-card__head"
TITLE_SELECTOR = "textarea#txtTitle"
EDITOR_FRAME_SELECTOR = "iframe.cke_wysiwyg_frame"
EDITOR_BODY_SELECTOR = "body.cke_editable[contenteditable='true']"
AI_ASSISTANT_DRAWER_SELECTOR = ".edit-drawer-box.open"
AI_ASSISTANT_CLOSE_SELECTOR = ".edit-title-close"
SAVE_MESSAGE_SELECTOR = ".el_mcm-message, .el-message, [role='alert']"
IMAGE_BUTTON_SELECTOR = "a.cke_button__image, a.cke_button__imageoutside"
IMAGE_DRAWER_SELECTOR = ".el_mcm-drawer.rtl.open"
RECENT_DRAFT_CLOSE_SELECTOR = ".recent-draft-box .btn-close"
TAG_ADD_SELECTOR = "button.tag__btn-tag"
TAG_AREA_SELECTOR = ".mark_selection_title_el_tag"
TAG_INPUT_SELECTOR = "input[placeholder*='Enter键入可添加自定义标签']"
PUBLISH_ERROR_SELECTOR = (
    ".el_mcm-message--error:visible, .el-message--error:visible, "
    "[role='alert']:visible"
)
IMAGE_UPLOAD_TIMEOUT_MS = 2 * 60_000
PUBLISH_TIMEOUT_MS = 2 * 60_000
EDITOR_SAVE_TIMEOUT_MS = 60_000
CSDN_MAX_IMAGE_BYTES = 5 * 1024 * 1024

logger = logging.getLogger("mozhou.csdn")


def _is_logged_in(page):
    if "mp.csdn.net" not in page.url or "passport.csdn.net" in page.url:
        return False
    login_entry = page.get_by_text(LOGIN_TEXT, exact=True).first
    try:
        if login_entry.count() and login_entry.is_visible():
            return False
    except Exception:
        return False
    for selector in LOGIN_SELECTORS:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return False
        except Exception:
            return False
    profile_card = page.locator(PROFILE_CARD_SELECTOR).first
    try:
        return bool(profile_card.count() and profile_card.is_visible())
    except Exception:
        return False


def login_csdn_account(account, timeout_seconds=300):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if _is_logged_in(page):
                page.wait_for_timeout(2000)
                return
            page.wait_for_timeout(1500)
    raise RuntimeError("等待 CSDN 登录超时，请重新发起登录")


def check_csdn_account(account):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2000)
        return _is_logged_in(page)


def _csdn_count_before_label(text, label):
    match = re.search(
        rf"([\d.,]+(?:\.\d+)?[\u4e07\u4ebf]?)\s*{re.escape(label)}",
        text,
    )
    return parse_compact_count(match.group(1)) if match else None


def _csdn_count_after_label(text, label):
    match = re.search(
        rf"{re.escape(label)}\s*[:\uff1a]?\s*([\d.,]+(?:\.\d+)?[\u4e07\u4ebf]?)",
        text,
    )
    return parse_compact_count(match.group(1)) if match else None


def _csdn_profile_text(text):
    return {
        "platform_user_id": "",
        "works_count": _csdn_count_before_label(text, "\u539f\u521b"),
        "followers_count": _csdn_count_before_label(text, "\u7c89\u4e1d"),
        "read_count": _csdn_count_after_label(text, "\u603b\u9605\u8bfb\u91cf"),
        "favorites_count": _csdn_count_after_label(text, "\u6536\u85cf\u6570"),
    }


def extract_csdn_profile(page):
    card = page.locator(PROFILE_CARD_SELECTOR).first
    card.wait_for(state="visible", timeout=30_000)
    name = card.locator(PROFILE_NAME_SELECTOR).first
    name_lines = [
        line.strip()
        for line in (name.inner_text() if name.count() else "").splitlines()
        if line.strip()
    ]
    display_name = next(
        (line for line in name_lines if not re.fullmatch(r"LV\.\d+", line)),
        "",
    )
    if not display_name:
        raise RuntimeError("Unable to identify the CSDN account display name")
    avatar = card.locator("img").first
    profile = _csdn_profile_text(card.inner_text())
    profile.update(
        {
            "display_name": display_name,
            "avatar_url": avatar.get_attribute("src") if avatar.count() else "",
        }
    )
    return profile


def fetch_csdn_profile(account):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        if not _is_logged_in(page):
            raise RuntimeError("CSDN login status has expired; please log in again")
        profile = extract_csdn_profile(page)
        avatar = page.locator(f"{PROFILE_CARD_SELECTOR} img").first
        try:
            if not avatar.count() or not avatar.is_visible():
                raise RuntimeError("CSDN account avatar was not found")
            avatar_path = account_avatar_path(account)
            avatar_path.parent.mkdir(parents=True, exist_ok=True)
            avatar.screenshot(path=str(avatar_path))
            profile["avatar_cached"] = True
        except Exception:
            profile["avatar_cached"] = False
        return profile


def _html(markdown_text):
    return markdown.markdown(markdown_text or "")


def _set_editor_html(page, html):
    editor = (
        page.frame_locator(EDITOR_FRAME_SELECTOR)
        .locator(EDITOR_BODY_SELECTOR)
        .first
    )
    editor.wait_for(state="visible", timeout=30_000)
    editor.evaluate(
        """(node, value) => {
            node.focus();
            node.innerHTML = value;
            node.dispatchEvent(new InputEvent("input", { bubbles: true }));
            node.dispatchEvent(new Event("change", { bubbles: true }));
        }""",
        html,
    )
    page.evaluate(
        """() => {
            const instances = window.CKEDITOR?.instances || {};
            const editor = Object.values(instances)[0];
            if (editor) {
                editor.fire("change");
                editor.updateElement();
            }
        }"""
    )


def _locator_image_sources(locator):
    images = locator.locator("img")
    sources = []
    for index in range(images.count()):
        source = images.nth(index).get_attribute("src")
        if source:
            sources.append(source)
    return sources


def _editor_image_sources(page):
    editor = (
        page.frame_locator(EDITOR_FRAME_SELECTOR)
        .locator(EDITOR_BODY_SELECTOR)
        .first
    )
    return _locator_image_sources(editor)


def _is_remote_image(source):
    value = str(source or "").strip().lower()
    return value.startswith(("https://", "http://", "//"))


def _visible_image_button(page):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        buttons = page.locator(IMAGE_BUTTON_SELECTOR)
        for index in range(buttons.count()):
            button = buttons.nth(index)
            try:
                if button.is_visible():
                    return button
            except Exception:
                pass
        page.wait_for_timeout(250)
    raise RuntimeError("CSDN 图片上传按钮未加载，请稍后重试")


def _image_upload_drawer(page):
    drawer = page.locator(IMAGE_DRAWER_SELECTOR).filter(
        has_text=re.compile("图片上传")
    ).first
    try:
        if drawer.count() and drawer.is_visible():
            return drawer
    except Exception:
        pass
    _visible_image_button(page).click()
    drawer.wait_for(state="visible", timeout=10_000)
    return drawer


def _new_remote_source(before, after):
    before_counts = Counter(before)
    after_counts = Counter(after)
    return next(
        (
            source
            for source, count in after_counts.items()
            if _is_remote_image(source) and count > before_counts[source]
        ),
        "",
    )


def _upload_csdn_image(page, image_path):
    path = Path(image_path).resolve()
    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"CSDN 配图文件不存在或格式不支持: {path.name}")
    if path.stat().st_size > CSDN_MAX_IMAGE_BYTES:
        raise ValueError(f"CSDN 单张配图不能超过 5MB: {path.name}")

    drawer = _image_upload_drawer(page)
    upload = drawer.locator("input[type='file']").first
    upload.wait_for(state="attached", timeout=10_000)
    editor_before = _editor_image_sources(page)
    drawer_before = _locator_image_sources(drawer)
    logger.info("CSDN 图片上传开始 file=%s size=%s", path.name, path.stat().st_size)
    upload.set_input_files(str(path))

    deadline = time.monotonic() + IMAGE_UPLOAD_TIMEOUT_MS / 1000
    while time.monotonic() < deadline:
        remote_url = _new_remote_source(
            editor_before,
            _editor_image_sources(page),
        ) or _new_remote_source(
            drawer_before,
            _locator_image_sources(drawer),
        )
        if remote_url:
            logger.info("CSDN 图片上传完成 file=%s", path.name)
            return remote_url
        error = page.locator(
            ".el_mcm-message--error:visible, .el-message--error:visible"
        ).first
        try:
            if error.count() and error.is_visible():
                message = error.inner_text().strip()
                if message:
                    raise RuntimeError(f"CSDN 图片上传失败: {message}")
        except RuntimeError:
            raise
        except Exception:
            pass
        page.wait_for_timeout(500)
    raise RuntimeError(f"CSDN 图片上传超时，未取得远程地址: {path.name}")


def _local_image_path(source):
    value = str(source or "").strip()
    if not value or _is_remote_image(value) or value.startswith(("data:", "blob:")):
        return None
    if value.lower().startswith("file://"):
        value = value[7:].lstrip("/")
    path = Path(value).resolve()
    if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
        return path
    return None


def _prepare_editor_html(page, markdown_text):
    html = _html(markdown_text)
    final_document = BeautifulSoup(html, "html.parser")
    local_images = []
    for image in final_document.find_all("img"):
        source = str(image.get("src") or "").strip()
        path = _local_image_path(source)
        if path:
            local_images.append(path)
        elif source and not _is_remote_image(source) and not source.startswith(
            ("data:", "blob:")
        ):
            raise ValueError(f"CSDN 本地配图不存在或格式不支持: {source}")
    if not local_images:
        _set_editor_html(page, html)
        return html

    staging_document = BeautifulSoup(html, "html.parser")
    for image in staging_document.find_all("img"):
        if _local_image_path(image.get("src")):
            image.decompose()
    _set_editor_html(page, str(staging_document))

    remote_urls = {}
    for path in local_images:
        key = str(path)
        if key not in remote_urls:
            remote_urls[key] = _upload_csdn_image(page, path)

    for image in final_document.find_all("img"):
        path = _local_image_path(image.get("src"))
        if path:
            image["src"] = remote_urls[str(path)]
    final_html = str(final_document)
    _set_editor_html(page, final_html)
    return final_html


def _close_ai_assistant(page):
    drawer = page.locator(AI_ASSISTANT_DRAWER_SELECTOR).first
    try:
        drawer.wait_for(state="visible", timeout=2_000)
    except Exception:
        return False
    close = drawer.locator(AI_ASSISTANT_CLOSE_SELECTOR).first
    close.wait_for(state="visible", timeout=5_000)
    close.click()
    drawer.wait_for(state="hidden", timeout=5_000)
    return True


def _wait_for_draft_saved(page):
    success = page.locator(SAVE_MESSAGE_SELECTOR).filter(
        has_text=re.compile(r"(保存|草稿).*(成功|完成)|已保存")
    ).first
    try:
        success.wait_for(state="visible", timeout=15_000)
        return
    except Exception:
        error = page.locator(
            ".el_mcm-message--error, .el-message--error, [role='alert']"
        ).first
        try:
            if error.count() and error.is_visible():
                message = error.inner_text().strip()
                if message:
                    raise RuntimeError(f"CSDN 保存草稿失败：{message}")
        except RuntimeError:
            raise
        except Exception:
            pass
    raise RuntimeError("CSDN 未确认草稿保存成功，请检查标题、正文及必填项")


def _close_recent_draft_prompt(page):
    close = page.locator(RECENT_DRAFT_CLOSE_SELECTOR).first
    try:
        if not close.count() or not close.is_visible():
            return False
        close.click()
        close.wait_for(state="hidden", timeout=5_000)
        return True
    except Exception:
        return False


def _selected_publish_tags(page):
    area = page.locator(TAG_AREA_SELECTOR).first
    try:
        values = area.inner_text().splitlines()
    except Exception:
        return []
    return [
        value.strip()
        for value in values
        if value.strip() and value.strip() != "添加文章标签"
    ]


def _fill_publish_tags(page, tags):
    if _selected_publish_tags(page):
        return

    normalized = []
    for value in tags or []:
        tag = re.sub(r"^#+", "", str(value).strip())[:20]
        if tag and tag not in normalized:
            normalized.append(tag)
    if not normalized:
        raise ValueError("CSDN 直接发布至少需要一个文章标签")

    add = page.get_by_role("button", name="添加文章标签", exact=True).first
    add.wait_for(state="visible", timeout=15_000)
    add.click()
    input_box = page.locator(TAG_INPUT_SELECTOR).first
    input_box.wait_for(state="visible", timeout=10_000)
    for tag in normalized[:8]:
        if not input_box.is_visible():
            add.click()
            input_box.wait_for(state="visible", timeout=10_000)
        replace_text(page, input_box, tag)
        page.wait_for_timeout(800)
        input_box.press("ArrowDown")
        input_box.press("Enter")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if _selected_publish_tags(page):
                return
            page.wait_for_timeout(200)
    raise RuntimeError("CSDN 未能添加任何文章标签")

def _wait_for_publish_success(page):
    deadline = time.monotonic() + PUBLISH_TIMEOUT_MS / 1000
    success_pattern = re.compile(r"发布成功|已发布")
    published_url_pattern = re.compile(
        r"blog\.csdn\.net/.+/article/details/\d+|"
        r"mp\.csdn\.net/mp_blog/manage/article"
    )
    while time.monotonic() < deadline:
        current_url = page.url
        if published_url_pattern.search(current_url):
            return current_url
        success = page.get_by_text(success_pattern, exact=False).first
        try:
            if success.count() and success.is_visible():
                return current_url
        except Exception:
            pass
        error = page.locator(PUBLISH_ERROR_SELECTOR).first
        try:
            if error.count() and error.is_visible():
                message = error.inner_text().strip()
                if message:
                    raise RuntimeError(f"CSDN 发布失败：{message}")
        except RuntimeError:
            raise
        except Exception:
            pass
        page.wait_for_timeout(500)
    raise RuntimeError("CSDN 未确认发布成功，请在浏览器中检查文章标签和发布设置")

def _wait_for_editor_ready(page, initial_delay_ms=5_000):
    page.wait_for_timeout(initial_delay_ms)
    deadline = time.monotonic() + EDITOR_SAVE_TIMEOUT_MS / 1000
    stable_since = None
    saving_pattern = re.compile(r"文章正在保存|正在保存")
    while time.monotonic() < deadline:
        saving = page.get_by_text(saving_pattern, exact=False).first
        try:
            is_saving = bool(saving.count() and saving.is_visible())
        except Exception:
            is_saving = False
        if is_saving:
            stable_since = None
        elif stable_since is None:
            stable_since = time.monotonic()
        elif time.monotonic() - stable_since >= 3:
            return
        page.wait_for_timeout(500)
    raise RuntimeError("CSDN 文章长时间处于保存中，请稍后重试")


def _publish_blog(page):
    submit = page.get_by_role("button", name="发布博客", exact=True).first
    submit.wait_for(state="visible", timeout=30_000)
    for attempt in range(3):
        _wait_for_editor_ready(
            page,
            initial_delay_ms=5_000 if attempt == 0 else 7_000,
        )
        submit.click()
        try:
            return _wait_for_publish_success(page)
        except RuntimeError as exc:
            if "文章正在保存" not in str(exc) or attempt == 2:
                raise
            logger.info("CSDN 编辑器仍在保存，等待后重试发布 attempt=%s", attempt + 2)

class CsdnPublisher(PlatformPublisher):
    key = "csdn"
    name = "CSDN"
    implemented = True

    def is_configured(self):
        return any(account["status"] == "valid" for account in list_accounts(self.key))

    def test_connection(self):
        accounts = [item for item in list_accounts(self.key) if item["status"] == "valid"]
        if not accounts:
            raise RuntimeError("请先在账号管理中添加并登录 CSDN 账号")
        if not check_csdn_account(accounts[0]):
            raise RuntimeError("CSDN 登录状态已失效，请重新登录")
        return {"name": self.name, "message": f"账号“{accounts[0]['name']}”登录状态有效"}

    def publish(self, article, action="draft"):
        if action not in {"draft", "publish"}:
            raise ValueError("CSDN 发布动作必须是 draft 或 publish")
        account_id = (article.get("platform_accounts") or {}).get(self.key)
        account = resolve_publish_account(self.key, account_id)
        with open_account_browser(account) as context:
            page = get_or_create_page(context)
            page.goto(EDITOR_URL, wait_until="domcontentloaded", timeout=60_000)
            title = str(article.get("title") or "").strip()
            if not title:
                raise ValueError("标题不能为空")
            title_input = page.locator(TITLE_SELECTOR).first
            try:
                title_input.wait_for(state="visible", timeout=30_000)
            except Exception as exc:
                if "passport.csdn.net" in page.url or "mp.csdn.net" not in page.url:
                    raise RuntimeError(
                        "CSDN 登录状态已失效，请重新登录"
                    ) from exc
                raise RuntimeError(
                    "CSDN 文章编辑器加载失败，请稍后重试"
                ) from exc
            _close_recent_draft_prompt(page)
            _close_ai_assistant(page)
            replace_text(page, title_input, title)
            _prepare_editor_html(page, article.get("content_md", ""))
            if action == "draft":
                submit = page.get_by_role(
                    "button", name="保存草稿", exact=True
                ).first
                submit.wait_for(state="visible", timeout=30_000)
                submit.click()
                _wait_for_draft_saved(page)
                result_status = "drafted"
            else:
                _fill_publish_tags(page, article.get("tags"))
                _publish_blog(page)
                result_status = "published"
            page.wait_for_timeout(3000)
            return {
                "status": result_status,
                "external_id": page.url,
                "account_id": account["id"],
            }
