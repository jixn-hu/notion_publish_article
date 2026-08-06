import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

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
from backend.media import IMAGE_EXTENSIONS
from backend.platforms.base import PlatformPublisher
from backend.platforms.profile_utils import first_visible_image, metric_from_text


HOME_URL = "https://mp.weixin.qq.com/"
DASHBOARD_URL = "https://mp.weixin.qq.com/cgi-bin/home?t=home/index"
ARTICLE_URL = "https://mp.weixin.qq.com/cgi-bin/appmsg"
NEW_ARTICLE_URL = (
    f"{ARTICLE_URL}?t=media/appmsg_edit_v2&action=edit"
    "&isNew=1&type=77&createType=0"
)
TITLE_SELECTOR = (
    "#js_title_main .title-editor__input "
    ".ProseMirror[contenteditable='true']"
)
EDITOR_SELECTOR = (
    "#edui1 .ProseMirror[contenteditable='true']"
    ":not([data-placeholder])"
)
AUTHOR_SELECTOR = "input#author"
IMAGE_UPLOAD_SELECTOR = "input[type='file'][accept*='image']"
COVER_AREA_SELECTOR = ".js_cover_btn_area"
COVER_FROM_CONTENT_SELECTOR = "a.js_selectCoverFromContent"
COVER_IMAGE_SELECTOR = ".card_mask_global.apmsg_content_img_mask"
IMAGE_UPLOAD_TIMEOUT_SECONDS = 3 * 60
DRAFT_SAVE_TIMEOUT_SECONDS = 2 * 60
PUBLISH_TIMEOUT_SECONDS = 5 * 60
SESSION_FILE_NAME = "wechat_session.json"
AUTH_COOKIE_NAMES = {"slave_sid", "slave_user", "bizuin"}
LOGIN_FRAME_URL_PARTS = (
    "open.weixin.qq.com/connect/qrconnect",
    "open.weixin.qq.com/cgi-bin/mpqrconnect",
)
LOGIN_SELECTORS = (
    "iframe[src*='open.weixin.qq.com']",
    "[class*='login_qrcode']",
    "[class*='login__type']",
    "[class*='qrcode']",
)
AUTHENTICATED_SELECTORS = (
    ".weui-desktop-layout__side",
    ".weui-desktop-menu",
    ".weui-desktop-account",
    "#js_main_nav",
)
PROFILE_NAME_SELECTORS = (
    ".acount_box-nickname",
    ".weui-desktop-account__nickname",
    ".weui-desktop-account__name",
    ".weui-desktop-account__info",
    "[class*='account'] [class*='nickname']",
    ".weui-desktop-layout__side [class*='name']",
)
PROFILE_AVATAR_SELECTORS = (
    "img.weui-desktop-account__thumb",
    ".weui-desktop-account__avatar img",
    "img.weui-desktop-account__avatar",
    ".weui-desktop-account__thumb img",
    ".weui-desktop-account img[class*='avatar']",
    "img[class*='account'][class*='avatar']",
)


logger = logging.getLogger("mozhou.wechat_browser")


def _visible(page, selector):
    locator = page.locator(selector).first
    try:
        return bool(locator.count() and locator.is_visible())
    except Exception:
        return False


def _visible_text(page, selector):
    locator = page.locator(selector).first
    try:
        return bool(
            locator.count()
            and locator.is_visible()
            and locator.inner_text().strip()
        )
    except Exception:
        return False

def _has_authenticated_session(page):
    try:
        names = {
            cookie.get("name")
            for cookie in page.context.cookies(HOME_URL)
        }
    except Exception:
        return False
    return AUTH_COOKIE_NAMES.issubset(names)


def _session_path(account):
    return Path(account["profile_dir"]) / SESSION_FILE_NAME


def _save_session_url(account, url):
    if not _has_backend_token(url):
        raise RuntimeError("公众号后台会话地址无效，请重新登录")
    path = _session_path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"dashboard_url": url}, ensure_ascii=False),
        encoding="utf-8",
    )


def record_account_session(account, page):
    dashboard_url = _url_with_backend_token(page.url, DASHBOARD_URL)
    if not dashboard_url:
        raise RuntimeError("公众号后台会话地址无效，请重新登录")
    _save_session_url(account, dashboard_url)


def _load_session_url(account):
    path = _session_path(account)
    try:
        url = json.loads(path.read_text(encoding="utf-8")).get(
            "dashboard_url",
            "",
        )
    except (OSError, ValueError, TypeError):
        return ""
    return url if _has_backend_token(url) else ""


def wechat_dashboard_url(account):
    return (
        _url_with_backend_token(_load_session_url(account), DASHBOARD_URL)
        or HOME_URL
    )


def _url_with_backend_token(session_url, target_url):
    if not _has_backend_token(session_url):
        return ""
    token = parse_qs(urlparse(session_url).query)["token"][0]
    parsed = urlparse(target_url)
    query = parse_qs(parsed.query)
    query["token"] = [token]
    query.setdefault("lang", ["zh_CN"])
    return urlunparse(
        parsed._replace(query=urlencode(query, doseq=True))
    )


def _authenticated_url(account, target_url):
    return _url_with_backend_token(_load_session_url(account), target_url)


def _has_backend_token(url):
    parsed = urlparse(str(url or ""))
    if parsed.hostname != "mp.weixin.qq.com" or not parsed.path.startswith(
        "/cgi-bin/"
    ):
        return False
    token = parse_qs(parsed.query).get("token", [])
    return any(str(value).strip() not in {"", "0"} for value in token)


def _is_logged_in(page):
    url = str(page.url or "")
    parsed = urlparse(url)
    if parsed.hostname != "mp.weixin.qq.com" or "login" in parsed.path.lower():
        return False
    try:
        if any(
            marker in str(frame.url or "")
            for frame in page.frames
            for marker in LOGIN_FRAME_URL_PARTS
        ):
            return False
    except Exception:
        return False
    has_backend_ui = any(
        _visible_text(page, selector)
        for selector in AUTHENTICATED_SELECTORS + PROFILE_NAME_SELECTORS
    )
    if _has_backend_token(url) and has_backend_ui:
        return True
    if any(_visible(page, selector) for selector in LOGIN_SELECTORS):
        return False
    return _has_authenticated_session(page) and (
        _has_backend_token(url) or has_backend_ui
    )


def login_wechat_account(account, timeout_seconds=300):
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if _is_logged_in(page):
                record_account_session(account, page)
                page.wait_for_timeout(2000)
                return
            page.wait_for_timeout(1500)
    raise RuntimeError(
        "等待微信公众号登录超时：未检测到公众号后台账号信息，"
        "请扫码并等待后台首页完全打开后再试"
    )


def check_wechat_account(account):
    target_url = wechat_dashboard_url(account)
    if target_url == HOME_URL:
        return False
    with open_account_browser(account) as context:
        page = get_or_create_page(context)
        page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)
        return _is_logged_in(page)

def _wechat_profile_text(text):
    match = re.search(r"微信号\s*[:：]\s*([^\s]+)", str(text or ""))
    return {
        "platform_user_id": match.group(1).strip() if match else "",
        "followers_count": metric_from_text(
            text,
            (
                "累计关注人数",
                "总用户数",
                "用户总数",
                "关注用户数",
            ),
        ),
        "new_followers_count": metric_from_text(
            text,
            (
                "新关注人数",
                "昨日新增关注",
                "新增关注人数",
            ),
        ),
    }


def _profile_name(page):
    ignored = {"公众号", "订阅号", "服务号", "退出登录", "账号详情"}
    for selector in PROFILE_NAME_SELECTORS:
        locator = page.locator(selector).first
        try:
            if not locator.count() or not locator.is_visible():
                continue
            lines = [
                line.strip()
                for line in locator.inner_text().splitlines()
                if line.strip()
            ]
            name = next((line for line in lines if line not in ignored), "")
            if name:
                return name
        except Exception:
            continue
    return ""


def extract_wechat_profile(page):
    display_name = _profile_name(page)
    if not display_name:
        raise RuntimeError("未能从公众号后台识别账号名称")
    profile = _wechat_profile_text(page.locator("body").inner_text())
    profile.update({"display_name": display_name, "avatar_url": ""})
    avatar = first_visible_image(page, PROFILE_AVATAR_SELECTORS)
    if avatar is not None:
        profile["avatar_url"] = avatar.get_attribute("src") or ""
    return profile


def fetch_wechat_profile(account, page=None):
    if page is None:
        target_url = wechat_dashboard_url(account)
        if target_url == HOME_URL:
            raise RuntimeError("缺少公众号后台会话，请重新登录")
        with open_account_browser(account) as context:
            active_page = get_or_create_page(context)
            active_page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            active_page.wait_for_timeout(3000)
            return fetch_wechat_profile(account, page=active_page)

    if not _is_logged_in(page):
        raise RuntimeError("微信公众号登录状态已失效，请重新登录")
    profile = extract_wechat_profile(page)
    avatar = first_visible_image(page, PROFILE_AVATAR_SELECTORS)
    try:
        if avatar is None:
            raise RuntimeError("未找到公众号账号头像")
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


def _new_article_url(account):
    timestamp = int(time.time() * 1000)
    return _authenticated_url(
        account,
        f"{NEW_ARTICLE_URL}&timestamp={timestamp}",
    )


def _local_image_path(source):
    value = str(source or "").strip()
    if not value or value.startswith(("http://", "https://", "//", "data:", "blob:")):
        return None
    if value.lower().startswith("file://"):
        value = value[7:].lstrip("/")
    path = Path(value).resolve()
    if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
        return path
    return None


def _article_image_paths(article):
    candidates = [article.get("cover_url")]
    document = BeautifulSoup(
        markdown.markdown(article.get("content_md") or ""),
        "html.parser",
    )
    candidates.extend(image.get("src") for image in document.find_all("img"))
    candidates.extend(article.get("media_paths") or [])

    paths = []
    seen = set()
    for source in candidates:
        path = _local_image_path(source)
        if path is None:
            continue
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            paths.append(path)
    return paths


def _fill_wechat_editor(page, article):
    title = str(article.get("title") or "").strip()
    if not title:
        raise ValueError("标题不能为空")
    if len(title) > 64:
        raise ValueError("公众号标题不能超过 64 个字符")
    body = _plain_text(article.get("content_md", ""))
    if not body:
        raise ValueError("公众号正文不能为空")

    title_input = page.locator(TITLE_SELECTOR).first
    title_input.wait_for(state="visible", timeout=30_000)
    replace_text(page, title_input, title)

    editor = _first_visible(page.locator(EDITOR_SELECTOR), 30)
    editor.click()
    page.keyboard.press("Control+A")
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line:
            page.keyboard.type(line, delay=min(typing_delay(line), 20))
        if index < len(lines) - 1:
            page.keyboard.press("Enter")

    author = str(article.get("author") or "").strip()
    if len(author) > 16:
        raise ValueError("公众号作者不能超过 16 个字符")
    if author:
        author_input = page.locator(AUTHOR_SELECTOR).first
        author_input.wait_for(state="visible", timeout=10_000)
        replace_text(page, author_input, author)
    interaction_pause(page, 700, 1200)
    return editor


def _remote_editor_image_sources(page):
    images = _first_visible(page.locator(EDITOR_SELECTOR), 10).locator("img")
    sources = []
    for index in range(images.count()):
        source = str(
            images.nth(index).get_attribute("data-src")
            or images.nth(index).get_attribute("src")
            or ""
        ).strip()
        if source.lower().startswith(("http://", "https://", "//")):
            sources.append(source)
    return sources


def _upload_wechat_images(page, paths):
    if not paths:
        return []
    editor = _first_visible(page.locator(EDITOR_SELECTOR), 10)
    editor.click()
    page.keyboard.press("Control+End")
    interaction_pause(page, 400, 800)
    upload = page.locator(IMAGE_UPLOAD_SELECTOR).first
    upload.wait_for(state="attached", timeout=30_000)
    before = len(_remote_editor_image_sources(page))
    logger.info("公众号正文图片上传开始 count=%s", len(paths))
    upload.set_input_files([str(path) for path in paths])

    deadline = time.monotonic() + IMAGE_UPLOAD_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        sources = _remote_editor_image_sources(page)
        uploaded_sources = sources[before:]
        if len(uploaded_sources) >= len(paths):
            page.wait_for_timeout(3000)
            logger.info("公众号正文图片上传完成 count=%s", len(uploaded_sources))
            return uploaded_sources[:len(paths)]
        error = page.get_by_text(
            re.compile(r"上传.*失败|图片.*失败|图片.*过大"),
            exact=False,
        ).first
        try:
            if error.count() and error.is_visible():
                message = error.inner_text().strip()
                if message:
                    raise RuntimeError(f"公众号图片上传失败：{message}")
        except RuntimeError:
            raise
        except Exception:
            pass
        page.wait_for_timeout(500)
    raise RuntimeError("公众号图片上传超时，请检查图片格式、大小和网络")


def _wechat_content_html(article, image_paths, uploaded_sources):
    if len(image_paths) != len(uploaded_sources):
        raise RuntimeError("公众号正文图片上传结果数量不一致")
    source_by_path = {
        str(Path(path).resolve()).lower(): source
        for path, source in zip(image_paths, uploaded_sources)
    }
    document = BeautifulSoup(
        markdown.markdown(article.get("content_md") or ""),
        "html.parser",
    )
    inline_sources = []
    for image in document.find_all("img"):
        source = str(image.get("src") or "").strip()
        local_path = _local_image_path(source)
        if local_path is not None:
            uploaded = source_by_path.get(str(local_path).lower())
            if not uploaded:
                raise RuntimeError(
                    f"公众号正文图片未完成上传：{local_path.name}"
                )
            image["src"] = uploaded
            image["data-src"] = uploaded
            source = uploaded
        if source and source not in inline_sources:
            inline_sources.append(source)

    if article.get("article_type", "article") != "image":
        return str(document).strip()

    top_sources = list(dict.fromkeys(uploaded_sources + inline_sources))
    for image in list(document.find_all("img")):
        parent = image.parent
        image.decompose()
        if (
            parent is not None
            and parent.name == "p"
            and not parent.get_text(strip=True)
            and not parent.find(True)
        ):
            parent.decompose()

    layout = BeautifulSoup("", "html.parser")
    for source in top_sources:
        paragraph = layout.new_tag("p")
        image = layout.new_tag("img")
        image["src"] = source
        image["data-src"] = source
        paragraph.append(image)
        layout.append(paragraph)
    for child in list(document.contents):
        layout.append(child.extract())
    return str(layout).strip()


def _apply_wechat_content_layout(page, article, image_paths, uploaded_sources):
    content_html = _wechat_content_html(article, image_paths, uploaded_sources)
    if not content_html:
        raise ValueError("公众号正文不能为空")
    editor = _first_visible(page.locator(EDITOR_SELECTOR), 10)
    editor.click()
    editor.evaluate(
        """
        (node, html) => {
          node.focus();
          const selection = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(node);
          selection.removeAllRanges();
          selection.addRange(range);
          const inserted = document.execCommand("insertHTML", false, html);
          if (!inserted) node.innerHTML = html;
          node.dispatchEvent(new Event("input", { bubbles: true }));
        }
        """,
        content_html,
    )
    page.wait_for_timeout(1000)
    rendered = str(editor.inner_html() or "").strip()
    expected_images = len(BeautifulSoup(content_html, "html.parser").find_all("img"))
    if not rendered or editor.locator("img").count() < expected_images:
        raise RuntimeError("公众号正文排版写入失败，请稍后重试")
    logger.info(
        "公众号正文排版完成 type=%s images=%s",
        article.get("article_type", "article"),
        expected_images,
    )
    return content_html


def _currently_visible(locator):
    try:
        count = locator.count()
    except Exception:
        return None
    for index in range(count):
        item = locator.nth(index)
        try:
            if item.is_visible():
                return item
        except Exception:
            continue
    return None

def _first_visible(locator, timeout_seconds=30):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for index in range(locator.count()):
            item = locator.nth(index)
            try:
                if item.is_visible():
                    return item
            except Exception:
                continue
        time.sleep(0.2)
    raise RuntimeError("公众号页面控件未加载，请稍后重试")


def _select_wechat_cover(page):
    selected = page.locator(".js_share_type_image")
    if _currently_visible(selected) is not None:
        return

    cover = _first_visible(page.locator(COVER_AREA_SELECTOR), 30)
    cover.scroll_into_view_if_needed()
    choices = page.locator(COVER_FROM_CONTENT_SELECTOR)
    from_content = None
    for _attempt in range(3):
        cover.hover()
        page.wait_for_timeout(350)
        from_content = _currently_visible(choices)
        if from_content is not None:
            break
        cover.click()
        page.wait_for_timeout(500)
        from_content = _currently_visible(choices)
        if from_content is not None:
            break
    if from_content is None:
        raise RuntimeError("公众号封面菜单未展开，请稍后重试")

    from_content.click()
    image = _first_visible(page.locator(COVER_IMAGE_SELECTOR), 15)
    image.click()
    next_button = _first_visible(
        page.get_by_role("button", name="下一步", exact=True),
        15,
    )
    next_button.click()
    confirm = _first_visible(
        page.get_by_role("button", name="确认", exact=True),
        15,
    )
    confirm.click()

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _currently_visible(selected) is not None:
            return
        page.wait_for_timeout(250)
    raise RuntimeError("公众号未能从正文选择封面，请检查正文图片")

def _saved_draft_id(url):
    parsed = urlparse(str(url or ""))
    if parsed.hostname != "mp.weixin.qq.com" or parsed.path != "/cgi-bin/appmsg":
        return ""
    values = parse_qs(parsed.query).get("appmsgid", [])
    return next(
        (value for value in values if str(value).strip() not in {"", "0"}),
        "",
    )


def _visible_publish_error(page):
    candidates = page.locator(
        ".weui-desktop-dialog:visible, .weui-desktop-toast:visible, "
        ".weui-desktop-msg:visible, [role='alert']:visible"
    )
    pattern = re.compile(r"失败|错误|不能为空|请选择|请设置|未完成")
    for index in range(candidates.count()):
        try:
            text = candidates.nth(index).inner_text().strip()
            if text and pattern.search(text):
                return text
        except Exception:
            continue
    return ""


def _save_wechat_draft(page):
    save = _first_visible(
        page.get_by_role("button", name="保存为草稿", exact=True),
        30,
    )
    save.click()

    deadline = time.monotonic() + DRAFT_SAVE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        draft_id = _saved_draft_id(page.url)
        if draft_id:
            return page.url
        error = _visible_publish_error(page)
        if error:
            raise RuntimeError(f"公众号保存草稿失败：{error}")
        page.wait_for_timeout(500)
    raise RuntimeError("公众号未确认草稿保存成功，请在浏览器中检查必填项")


def _publish_wechat_article(page):
    publish = _first_visible(
        page.get_by_role(
            "button",
            name=re.compile(r"^(\u53d1\u8868|\u53d1\u5e03)$"),
        ),
        30,
    )
    publish.click()
    interaction_pause(page, 800, 1300)

    dialog = page.locator(".weui-desktop-dialog:visible")
    if dialog.count():
        confirm = dialog.get_by_role(
            "button",
            name=re.compile(r"^(\u53d1\u8868|\u786e\u8ba4\u53d1\u5e03|\u786e\u8ba4)$"),
        )
        try:
            if confirm.count() == 1 and confirm.is_visible():
                confirm.click()
        except Exception:
            pass

    success = page.get_by_text(
        re.compile(r"\u53d1\u8868\u6210\u529f|\u53d1\u5e03\u6210\u529f|\u5df2\u53d1\u8868"),
        exact=False,
    )
    deadline = time.monotonic() + PUBLISH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            if success.count() and success.first.is_visible():
                page.wait_for_timeout(3000)
                return page.url
        except Exception:
            pass
        error = _visible_publish_error(page)
        if error:
            raise RuntimeError(f"\u516c\u4f17\u53f7\u53d1\u8868\u5931\u8d25\uff1a{error}")
        page.wait_for_timeout(1000)
    raise RuntimeError(
        "\u516c\u4f17\u53f7\u53d1\u8868\u5c1a\u672a\u5b8c\u6210\uff0c\u8bf7\u5728\u6253\u5f00\u7684\u6d4f\u89c8\u5668\u4e2d\u626b\u7801\u9a8c\u8bc1\u5e76\u786e\u8ba4\u7ed3\u679c"
    )

class WechatPublisher(PlatformPublisher):
    key = "wechat"
    name = "微信公众号"
    implemented = True

    def is_configured(self):
        return any(account["status"] == "valid" for account in list_accounts(self.key))

    def test_connection(self):
        accounts = [item for item in list_accounts(self.key) if item["status"] == "valid"]
        if not accounts:
            raise RuntimeError("请先在账号管理中添加并登录微信公众号账号")
        if not check_wechat_account(accounts[0]):
            raise RuntimeError("微信公众号登录状态已失效，请重新登录")
        return {"name": self.name, "message": f"账号“{accounts[0]['name']}”登录状态有效"}

    def publish(self, article, action="draft"):
        if action not in {"draft", "publish"}:
            raise ValueError("公众号动作必须是 draft 或 publish")
        account_id = (article.get("platform_accounts") or {}).get(self.key)
        account = resolve_publish_account(self.key, account_id)
        with open_account_browser(account) as context:
            page = get_or_create_page(context)
            article_url = _new_article_url(account)
            if not article_url:
                raise RuntimeError("缺少公众号后台会话，请重新登录")
            page.goto(
                article_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(3000)
            if not _is_logged_in(page):
                raise RuntimeError("微信公众号登录状态已失效，请重新登录")

            _fill_wechat_editor(page, article)
            image_paths = _article_image_paths(article)
            uploaded_sources = _upload_wechat_images(page, image_paths)
            if uploaded_sources:
                _select_wechat_cover(page)
            _apply_wechat_content_layout(
                page, article, image_paths, uploaded_sources
            )
            external_url = _save_wechat_draft(page)
            status = "drafted"
            if action == "publish":
                external_url = _publish_wechat_article(page)
                status = "published"
            page.wait_for_timeout(3000)
            return {
                "status": status,
                "external_id": external_url,
                "account_id": account["id"],
            }
