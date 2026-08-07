import asyncio
import base64
import io
import sqlite3
import threading
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import backend.db
import backend.media
import backend.accounts
import backend.browser
import backend.proxies
import backend.app as app_module
from backend.assets import get_platform_asset, save_platform_asset
from backend.image_localizer import localize_remote_images
from backend.logging_config import redact_text, redact_url
from backend.notion_client import NotionClient, page_metadata
from backend.platforms.bilibili import (
    BilibiliPublisher,
    CREATOR_URL as BILIBILI_CREATOR_URL,
    LOGIN_URL as BILIBILI_LOGIN_URL,
    bilibili_account_url,
)
from backend.platforms.channels import (
    ChannelsPublisher,
    _channels_api_profile,
    _channels_text_profile,
)
from backend.platforms.csdn import _csdn_profile_text
from backend.platforms.douyin import DouyinPublisher
from backend.platforms.douyin import (
    _current_page as current_douyin_page,
    _douyin_text_profile,
)
from backend.platforms.xiaohongshu import (
    _parse_profile_count,
)
from backend.services import _upsert_synced_article


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_patch = patch.object(
            backend.db,
            "DB_PATH",
            Path(self.temp_dir.name) / "test.db",
        )
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.media_patch = patch.object(
            backend.media,
            "MEDIA_DIR",
            Path(self.temp_dir.name) / "media",
        )
        self.media_patch.start()
        self.addCleanup(self.media_patch.stop)
        self.avatar_patch = patch.object(
            backend.accounts,
            "AVATAR_ROOT",
            Path(self.temp_dir.name) / "account_avatars",
        )
        self.avatar_patch.start()
        self.addCleanup(self.avatar_patch.stop)
        self.migration_patch = patch.object(
            app_module,
            "migrate_legacy_config",
            return_value=None,
        )
        self.migration_patch.start()
        self.addCleanup(self.migration_patch.stop)
        self.client_context = TestClient(app_module.app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)

    def test_account_browser_reuses_active_context_for_same_account(self):
        context = Mock()
        account = {"id": 7}
        backend.browser._account_browser_session.context = context
        backend.browser._account_browser_session.account_id = 7
        try:
            with backend.browser.open_account_browser(account) as reused:
                self.assertIs(reused, context)
            with self.assertRaisesRegex(RuntimeError, "不能切换到其他账号"):
                with backend.browser.open_account_browser({"id": 8}):
                    pass
        finally:
            del backend.browser._account_browser_session.context
            del backend.browser._account_browser_session.account_id

    def test_bilibili_account_url_uses_login_until_account_is_valid(self):
        self.assertEqual(
            bilibili_account_url({"status": "pending"}),
            BILIBILI_LOGIN_URL,
        )
        self.assertEqual(
            bilibili_account_url({"status": "invalid"}),
            BILIBILI_LOGIN_URL,
        )
        self.assertEqual(
            bilibili_account_url({"status": "valid"}),
            BILIBILI_CREATOR_URL,
        )
        _, target_url, _ = backend.accounts._account_management_runtime(
            {"platform": "bilibili", "status": "invalid"}
        )
        self.assertEqual(target_url, BILIBILI_LOGIN_URL)

    def test_first_login_collects_from_current_page_then_closes_automatically(self):
        from contextlib import nullcontext

        account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "首次登录账号"},
        ).json()
        context = Mock()
        page = Mock()
        page.is_closed.return_value = False
        page.wait_for_timeout.side_effect = [
            None,
            RuntimeError("用户在登录成功提示期间关闭了浏览器"),
        ]
        context.pages = [page]
        profile = {"display_name": "首次登录账号", "followers_count": 12}
        checker = Mock(side_effect=[False, True])

        with (
            patch(
                "backend.accounts.open_account_browser",
                return_value=nullcontext(context),
            ) as browser_session,
            patch(
                "backend.accounts.get_or_create_page",
                return_value=page,
            ),
            patch(
                "backend.accounts._account_management_runtime",
                return_value=(object(), "https://mp.csdn.net/", checker),
            ),
            patch(
                "backend.accounts._fetch_account_profile",
                return_value=profile,
            ) as fetch_profile,
        ):
            response = self.client.post(f"/api/accounts/{account['id']}/login")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "valid")
        self.assertEqual(response.json()["profile"], profile)
        self.assertEqual(response.json()["management_mode"], "login")
        browser_session.assert_called_once()
        page.goto.assert_called_once_with(
            "https://mp.csdn.net/",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        fetch_profile.assert_called_once_with(
            unittest.mock.ANY,
            page=page,
        )
        self.assertEqual(
            [call.args[0] for call in page.wait_for_timeout.call_args_list],
            [2500, 2000],
        )

    def test_logged_in_account_checks_profile_then_closes_automatically(self):
        from contextlib import nullcontext

        account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "状态检查账号"},
        ).json()
        context = Mock()
        page = Mock()
        profile = {"display_name": "状态检查账号"}
        checker = Mock(return_value=True)

        with (
            patch(
                "backend.accounts.open_account_browser",
                return_value=nullcontext(context),
            ),
            patch(
                "backend.accounts.get_or_create_page",
                return_value=page,
            ),
            patch(
                "backend.accounts._account_management_runtime",
                return_value=(object(), "https://mp.csdn.net/", checker),
            ),
            patch(
                "backend.accounts._fetch_account_profile",
                return_value=profile,
            ),
        ):
            response = self.client.post(f"/api/accounts/{account['id']}/login")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["management_mode"], "check")
        page.goto.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in page.wait_for_timeout.call_args_list],
            [2500, 2000],
        )

    def test_account_login_reports_browser_closed_during_status_check(self):
        from contextlib import nullcontext

        account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "关闭登录页账号"},
        ).json()
        context = Mock()
        page = Mock()
        page.is_closed.side_effect = [False, True]
        page.wait_for_timeout.side_effect = [
            None,
            RuntimeError("target closed"),
        ]
        context.pages = [page]

        with (
            patch(
                "backend.accounts.open_account_browser",
                return_value=nullcontext(context),
            ),
            patch(
                "backend.accounts.get_or_create_page",
                return_value=page,
            ),
            patch(
                "backend.accounts._account_management_runtime",
                return_value=(
                    object(),
                    "https://mp.csdn.net/",
                    Mock(return_value=False),
                ),
            ),
        ):
            response = self.client.post(f"/api/accounts/{account['id']}/login")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "登录浏览器已关闭，尚未检测到登录成功",
        )

    def test_account_browser_view_uses_account_profile(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "CSDN 主账号"},
        ).json()
        with patch.object(
            backend.accounts,
            "open_account_dashboard",
            return_value={"platform": "csdn", "url": "https://mp.csdn.net/"},
        ) as launcher:
            response = self.client.post(f"/api/accounts/{account['id']}/browser")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["platform"], "csdn")
        launcher.assert_called_once_with(
            unittest.mock.ANY,
        )
        self.assertEqual(
            launcher.call_args.args[0]["profile_dir"],
            account["profile_dir"],
        )
    def test_wechat_account_browser_opens_canonical_dashboard(self):
        from backend.platforms.wechat_browser import _save_session_url

        account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "公众号主账号"},
        ).json()
        saved_url = (
            "https://mp.weixin.qq.com/cgi-bin/safecenterstatus?"
            "action=view&t=setting/safe-index&token=123456&lang=zh_CN"
        )
        dashboard_url = (
            "https://mp.weixin.qq.com/cgi-bin/home?"
            "t=home%2Findex&token=123456&lang=zh_CN"
        )
        _save_session_url(account, saved_url)
        with patch.object(
            backend.accounts,
            "open_account_dashboard",
            return_value={"platform": "wechat", "url": dashboard_url},
        ) as launcher:
            response = self.client.post(
                f"/api/accounts/{account['id']}/browser"
            )

        self.assertEqual(response.status_code, 200)
        launcher.assert_called_once_with(
            unittest.mock.ANY,
            dashboard_url,
        )

    def test_wechat_account_session_is_saved_as_dashboard(self):
        from backend.platforms.wechat_browser import (
            _load_session_url,
            record_account_session,
        )

        account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "公众号会话账号"},
        ).json()
        page = Mock()
        page.url = (
            "https://mp.weixin.qq.com/cgi-bin/safecenterstatus?"
            "action=view&t=setting/safe-index&token=654321&lang=zh_CN"
        )

        record_account_session(account, page)

        self.assertEqual(
            _load_session_url(account),
            "https://mp.weixin.qq.com/cgi-bin/home?"
            "t=home%2Findex&token=654321&lang=zh_CN",
        )

    def test_csdn_login_check_rejects_visible_login_entry(self):
        from backend.platforms.csdn import _is_logged_in

        class Locator:
            def __init__(self, count=0, visible=False):
                self._count = count
                self._visible = visible

            @property
            def first(self):
                return self

            def count(self):
                return self._count

            def is_visible(self):
                return self._visible

        class Page:
            url = "https://mp.csdn.net/mp_blog/creation/editor"

            def get_by_text(self, text, exact=False):
                return Locator(count=1, visible=True)

            def locator(self, selector):
                return Locator(count=1 if "manage/article" in selector else 0)

        self.assertFalse(_is_logged_in(Page()))

    def test_csdn_login_check_prefers_profile_card_over_toolbar_login(self):
        from backend.platforms.csdn import _is_logged_in

        class Locator:
            def __init__(self, count=0, visible=False):
                self._count = count
                self._visible = visible

            @property
            def first(self):
                return self

            def count(self):
                return self._count

            def is_visible(self):
                return self._visible

        class Page:
            url = "https://mp.csdn.net/"

            def get_by_text(self, text, exact=False):
                return Locator(count=1, visible=True)

            def locator(self, selector):
                return Locator(
                    count=1 if selector == ".home-exp-user-card" else 0,
                    visible=selector == ".home-exp-user-card",
                )

        self.assertTrue(_is_logged_in(Page()))

    def test_csdn_profile_extracts_current_home_layout(self):
        from backend.platforms.csdn import (
            PROFILE_NAME_SELECTOR,
            _is_logged_in,
            extract_csdn_profile,
        )

        class Locator:
            def __init__(
                self,
                count=0,
                visible=False,
                text="",
                attributes=None,
                children=None,
            ):
                self._count = count
                self._visible = visible
                self._text = text
                self._attributes = attributes or {}
                self._children = children or {}

            @property
            def first(self):
                return self

            def count(self):
                return self._count

            def is_visible(self):
                return self._visible

            def inner_text(self):
                return self._text

            def get_attribute(self, name):
                return self._attributes.get(name)

            def locator(self, selector):
                return self._children.get(selector, Locator())

        avatar = Locator(
            count=1,
            visible=True,
            attributes={"src": "https://i-avatar.csdnimg.cn/account.jpg"},
        )
        name = Locator(count=1, visible=True, text="小胡的第二大脑")
        main = Locator(
            count=1,
            visible=True,
            text=(
                "小胡的第二大脑\nLV.6\n304原创\n4517粉丝\n"
                "7732博客积分\n总阅读量\n7,940,382\n收藏数\n3,746"
            ),
            children={
                PROFILE_NAME_SELECTOR: name,
                "a.avatar-box img": avatar,
            },
        )
        empty = Locator()

        class Page:
            url = "https://mp.csdn.net/"

            def get_by_text(self, text, exact=False):
                return empty

            def locator(self, selector):
                if selector == "main":
                    return main
                return empty

        page = Page()
        self.assertTrue(_is_logged_in(page))
        profile = extract_csdn_profile(page)
        self.assertEqual(profile["display_name"], "小胡的第二大脑")
        self.assertEqual(profile["works_count"], 304)
        self.assertEqual(profile["followers_count"], 4517)
        self.assertEqual(profile["read_count"], 7940382)
        self.assertEqual(profile["favorites_count"], 3746)
        self.assertEqual(
            profile["avatar_url"],
            "https://i-avatar.csdnimg.cn/account.jpg",
        )
    def test_wechat_login_check_rejects_root_page_with_qr_frame(self):
        from backend.platforms.wechat_browser import _is_logged_in

        class Locator:
            @property
            def first(self):
                return self

            def count(self):
                return 0

            def is_visible(self):
                return False

        class Frame:
            url = "https://open.weixin.qq.com/connect/qrconnect?appid=test"

        class Page:
            url = "https://mp.weixin.qq.com/"
            frames = [Frame()]

            def locator(self, selector):
                return Locator()

        self.assertFalse(_is_logged_in(Page()))

    def test_wechat_login_check_rejects_empty_backend_shell(self):
        from backend.platforms.wechat_browser import _is_logged_in

        class Locator:
            @property
            def first(self):
                return self

            def count(self):
                return 1

            def is_visible(self):
                return True

            def inner_text(self):
                return ""

        class Frame:
            url = "https://mp.weixin.qq.com/cgi-bin/home"

        class Page:
            url = "https://mp.weixin.qq.com/cgi-bin/home?t=home/index&lang=zh_CN"
            frames = [Frame()]

            def locator(self, selector):
                return Locator()

        self.assertFalse(_is_logged_in(Page()))
    def test_wechat_login_check_accepts_authenticated_backend_token(self):
        from backend.platforms.wechat_browser import _is_logged_in

        class Locator:
            @property
            def first(self):
                return self

            def count(self):
                return 0

            def is_visible(self):
                return False

        class Frame:
            url = "https://mp.weixin.qq.com/cgi-bin/home"

        class Context:
            def cookies(self, url):
                return [
                    {"name": "slave_sid"},
                    {"name": "slave_user"},
                    {"name": "bizuin"},
                ]

        class Page:
            url = (
                "https://mp.weixin.qq.com/cgi-bin/home?"
                "t=home/index&lang=zh_CN&token=123456"
            )
            frames = [Frame()]
            context = Context()

            def locator(self, selector):
                return Locator()

        self.assertTrue(_is_logged_in(Page()))

    def test_wechat_login_check_accepts_backend_ui_when_cookies_change(self):
        from backend.platforms.wechat_browser import _is_logged_in

        class Locator:
            def __init__(self, visible=False, text=""):
                self._visible = visible
                self._text = text

            @property
            def first(self):
                return self

            def count(self):
                return int(self._visible)

            def is_visible(self):
                return self._visible

            def inner_text(self):
                return self._text

        class Context:
            def cookies(self, url):
                return [{"name": "bizuin"}]

        class Page:
            url = (
                "https://mp.weixin.qq.com/cgi-bin/home?"
                "t=home%2Findex&token=123456&lang=zh_CN"
            )
            frames = []
            context = Context()

            def locator(self, selector):
                if selector == ".weui-desktop-layout__side":
                    return Locator(True, "Content menu\nSettings")
                if selector == "[class*='qrcode']":
                    return Locator(True, "")
                return Locator()

        self.assertTrue(_is_logged_in(Page()))

    def test_wechat_session_requires_all_backend_cookies(self):
        from backend.platforms.wechat_browser import _has_authenticated_session

        page = Mock()
        page.context.cookies.return_value = [
            {"name": "slave_sid"},
            {"name": "slave_user"},
        ]
        self.assertFalse(_has_authenticated_session(page))

        page.context.cookies.return_value.append({"name": "bizuin"})
        self.assertTrue(_has_authenticated_session(page))
    def test_wechat_article_images_are_local_and_deduplicated(self):
        from backend.platforms.wechat_browser import _article_image_paths

        first = Path(self.temp_dir.name) / "cover.png"
        second = Path(self.temp_dir.name) / "body.jpg"
        video = Path(self.temp_dir.name) / "clip.mp4"
        first.write_bytes(b"image")
        second.write_bytes(b"image")
        video.write_bytes(b"video")
        article = {
            "cover_url": str(first),
            "content_md": (
                f"![cover]({first.as_posix()})\n"
                f"![body]({second.as_posix()})"
            ),
            "media_paths": [str(second), str(video)],
        }

        self.assertEqual(
            _article_image_paths(article),
            [first.resolve(), second.resolve()],
        )

    def test_wechat_article_keeps_inline_image_position(self):
        from bs4 import BeautifulSoup

        from backend.platforms.wechat_browser import _wechat_content_html

        cover = Path(self.temp_dir.name) / "cover.png"
        inline = Path(self.temp_dir.name) / "inline.png"
        cover.write_bytes(b"cover")
        inline.write_bytes(b"inline")
        article = {
            "article_type": "article",
            "content_md": (
                "First paragraph\n\n"
                f"![body image]({inline.as_posix()})\n\n"
                "Second paragraph"
            ),
        }

        content_html = _wechat_content_html(
            article,
            [cover.resolve(), inline.resolve()],
            [
                "https://mmbiz.qpic.cn/cover.png",
                "https://mmbiz.qpic.cn/inline.png",
            ],
        )
        document = BeautifulSoup(content_html, "html.parser")
        inline_image = document.find("img")

        self.assertEqual(
            inline_image.get("src"),
            "https://mmbiz.qpic.cn/inline.png",
        )
        self.assertNotIn("cover.png", content_html)
        self.assertLess(
            content_html.index("First paragraph"),
            content_html.index("<img"),
        )
        self.assertLess(
            content_html.index("<img"),
            content_html.index("Second paragraph"),
        )

    def test_wechat_image_post_places_all_images_before_text(self):
        from bs4 import BeautifulSoup

        from backend.platforms.wechat_browser import _wechat_content_html

        cover = Path(self.temp_dir.name) / "cover.png"
        inline = Path(self.temp_dir.name) / "inline.png"
        material = Path(self.temp_dir.name) / "material.png"
        for path in (cover, inline, material):
            path.write_bytes(b"image")
        article = {
            "article_type": "image",
            "content_md": (
                "First paragraph\n\n"
                f"![body image]({inline.as_posix()})\n\n"
                "Second paragraph"
            ),
        }
        uploaded_sources = [
            "https://mmbiz.qpic.cn/cover.png",
            "https://mmbiz.qpic.cn/inline.png",
            "https://mmbiz.qpic.cn/material.png",
        ]

        content_html = _wechat_content_html(
            article,
            [cover.resolve(), inline.resolve(), material.resolve()],
            uploaded_sources,
        )
        document = BeautifulSoup(content_html, "html.parser")
        top_level = [item for item in document.contents if item.name]

        self.assertEqual(
            [item.find("img").get("src") for item in top_level[:3]],
            uploaded_sources,
        )
        self.assertFalse(any(item.find("img") for item in top_level[3:]))
        self.assertEqual(
            document.get_text(" ", strip=True),
            "First paragraph Second paragraph",
        )
    def test_wechat_saved_draft_requires_appmsg_id(self):
        from backend.platforms.wechat_browser import _saved_draft_id

        self.assertEqual(
            _saved_draft_id(
                "https://mp.weixin.qq.com/cgi-bin/appmsg?"
                "t=media/appmsg_edit&appmsgid=100000004"
            ),
            "100000004",
        )
        self.assertEqual(
            _saved_draft_id(
                "https://mp.weixin.qq.com/cgi-bin/appmsg?"
                "t=media/appmsg_edit_v2&isNew=1"
            ),
            "",
        )

    def test_wechat_draft_waits_for_appmsgid_after_save(self):
        from backend.platforms.wechat_browser import _save_wechat_draft

        page = Mock()
        page.url = (
            "https://mp.weixin.qq.com/cgi-bin/appmsg?"
            "t=media/appmsg_edit_v2&isNew=1"
        )
        save_button = Mock()
        locator = Mock()
        locator.count.return_value = 1
        locator.nth.return_value = save_button
        save_button.is_visible.return_value = True
        page.get_by_role.return_value = locator
        save_button.click.side_effect = lambda: setattr(
            page,
            "url",
            "https://mp.weixin.qq.com/cgi-bin/appmsg?"
            "t=media/appmsg_edit&appmsgid=100000004",
        )

        result = _save_wechat_draft(page)

        page.get_by_role.assert_called_once_with(
            "button",
            name="保存为草稿",
            exact=True,
        )
        save_button.click.assert_called_once_with()
        self.assertIn("appmsgid=100000004", result)

    def test_wechat_cover_follows_manual_crop_sequence(self):
        from backend.platforms.wechat_browser import _select_wechat_cover

        page = Mock()
        selected_item = Mock()
        selected_item.is_visible.side_effect = [False, True]
        selected = Mock()
        selected.count.return_value = 1
        selected.nth.return_value = selected_item
        cover = Mock()
        hidden_from_content = Mock()
        hidden_from_content.is_visible.return_value = False
        visible_from_content = Mock()
        visible_from_content.is_visible.return_value = True
        from_content = Mock()
        from_content.count.return_value = 2
        from_content.nth.side_effect = [
            hidden_from_content,
            visible_from_content,
        ]
        image = Mock()
        next_button = Mock()
        confirm_button = Mock()

        def visible_locator(item):
            locator = Mock()
            locator.count.return_value = 1
            locator.nth.return_value = item
            item.is_visible.return_value = True
            return locator

        image_locator = visible_locator(image)
        cover_locator = visible_locator(cover)
        button_locators = {
            "\u4e0b\u4e00\u6b65": visible_locator(next_button),
            "\u786e\u8ba4": visible_locator(confirm_button),
        }

        def page_locator(selector):
            return {
                ".js_share_type_image": selected,
                ".js_cover_btn_area": cover_locator,
                "a.js_selectCoverFromContent": from_content,
                ".card_mask_global.apmsg_content_img_mask": image_locator,
            }[selector]

        page.locator.side_effect = page_locator
        page.get_by_role.side_effect = (
            lambda role, name, exact: button_locators[name]
        )

        _select_wechat_cover(page)

        cover.hover.assert_called_once_with()
        hidden_from_content.click.assert_not_called()
        visible_from_content.click.assert_called_once_with()
        image.click.assert_called_once_with()
        next_button.click.assert_called_once_with()
        confirm_button.click.assert_called_once_with()
    def test_wechat_publish_uses_v2_editor_and_waits_after_save(self):
        from contextlib import nullcontext

        from backend.platforms.wechat_browser import WechatPublisher

        page = Mock()
        article = {
            "title": "WeChat draft",
            "author": "Author",
            "content_md": "Body",
            "platform_accounts": {"wechat": 3},
        }
        editor_url = (
            "https://mp.weixin.qq.com/cgi-bin/appmsg?"
            "t=media/appmsg_edit_v2&action=edit&isNew=1&"
            "type=77&createType=0&token=123456&lang=zh_CN"
        )
        saved_url = (
            "https://mp.weixin.qq.com/cgi-bin/appmsg?"
            "t=media/appmsg_edit&appmsgid=100000004"
        )
        image = Path(self.temp_dir.name) / "cover.png"
        uploaded_sources = ["https://mmbiz.qpic.cn/cover.png"]
        publish_steps = []
        with (
            patch(
                "backend.platforms.wechat_browser.resolve_publish_account",
                return_value={"id": 3},
            ),
            patch(
                "backend.platforms.wechat_browser.open_account_browser",
                return_value=nullcontext(Mock()),
            ),
            patch(
                "backend.platforms.wechat_browser.get_or_create_page",
                return_value=page,
            ),
            patch(
                "backend.platforms.wechat_browser._new_article_url",
                return_value=editor_url,
            ),
            patch(
                "backend.platforms.wechat_browser._is_logged_in",
                return_value=True,
            ),
            patch(
                "backend.platforms.wechat_browser._fill_wechat_editor"
            ) as fill_editor,
            patch(
                "backend.platforms.wechat_browser._article_image_paths",
                return_value=[image],
            ),
            patch(
                "backend.platforms.wechat_browser._upload_wechat_images",
                return_value=uploaded_sources,
            ) as upload_images,
            patch(
                "backend.platforms.wechat_browser._select_wechat_cover",
                side_effect=lambda page: publish_steps.append("cover"),
            ) as select_cover,
            patch(
                "backend.platforms.wechat_browser._apply_wechat_content_layout",
                side_effect=lambda *args: publish_steps.append("layout"),
            ) as apply_layout,
            patch(
                "backend.platforms.wechat_browser._save_wechat_draft",
                side_effect=lambda page: publish_steps.append("save") or saved_url,
            ) as save_draft,
        ):
            result = WechatPublisher({}).publish(article, action="draft")

        page.goto.assert_called_once_with(
            editor_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        fill_editor.assert_called_once_with(page, article)
        upload_images.assert_called_once_with(page, [image])
        select_cover.assert_called_once_with(page)
        apply_layout.assert_called_once_with(
            page,
            article,
            [image],
            uploaded_sources,
        )
        save_draft.assert_called_once_with(page)
        self.assertEqual(publish_steps, ["cover", "layout", "save"])
        self.assertEqual(
            [call.args[0] for call in page.wait_for_timeout.call_args_list],
            [3000, 3000],
        )
        self.assertEqual(result["external_id"], saved_url)
        self.assertEqual(result["status"], "drafted")
    def test_wechat_profile_text_extracts_wechat_id(self):
        from backend.platforms.wechat_browser import _wechat_profile_text

        self.assertEqual(
            _wechat_profile_text("账号信息\n微信号：demo_account"),
            {
                "platform_user_id": "demo_account",
                "followers_count": None,
                "new_followers_count": None,
            },
        )
    def test_wechat_profile_text_extracts_follower_metrics(self):
        from backend.platforms.wechat_browser import _wechat_profile_text

        profile = _wechat_profile_text(
            "昨日关键指标 "
            "新关注人数 36 "
            "累计关注人数 1.2万"
        )

        self.assertEqual(profile["followers_count"], 12000)
        self.assertEqual(profile["new_followers_count"], 36)
    def test_health_and_platform_registry(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        platforms = self.client.get("/api/platforms").json()
        self.assertEqual(
            [item["key"] for item in platforms],
            [
                "wechat",
                "xiaohongshu",
                "douyin",
                "channels",
                "bilibili",
                "csdn",
            ],
        )
        self.assertTrue(all(item["implemented"] for item in platforms[:5]))
        self.assertTrue(platforms[5]["implemented"])
        self.assertEqual(
            {item["key"]: item["content_types"] for item in platforms},
            {
                "wechat": ["article", "image"],
                "xiaohongshu": ["image", "video"],
                "douyin": ["video"],
                "channels": ["video"],
                "bilibili": ["video"],
                "csdn": ["article"],
            },
        )

    def test_dashboard_sums_followers_across_accounts(self):
        wechat = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "公众号"},
        ).json()
        csdn = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "CSDN"},
        ).json()
        self.client.post(
            "/api/accounts",
            json={"platform": "douyin", "name": "未同步资料"},
        )
        backend.accounts.update_account_profile(
            wechat["id"],
            {"followers_count": 1200, "new_followers_count": 8},
        )
        backend.accounts.update_account_profile(
            csdn["id"],
            {"followers_count": 345},
        )

        dashboard = self.client.get("/api/dashboard")

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json()["total_followers"], 1545)
        self.assertEqual(dashboard.json()["follower_accounts"], 2)

    def test_publish_rejects_platform_that_does_not_support_content_type(self):
        article = self.client.post(
            "/api/articles",
            json={
                "title": "平台类型边界",
                "article_type": "article",
                "target_platforms": ["xiaohongshu"],
                "platform_actions": {"xiaohongshu": "publish"},
            },
        ).json()

        response = self.client.post(
            f"/api/articles/{article['id']}/publish",
            json={"platform_actions": None},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("不支持发布到：小红书", response.json()["detail"])

    def test_auto_publish_skips_platforms_that_do_not_support_content_type(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "xiaohongshu", "name": "图文平台账号"},
        ).json()
        self.client.put(
            "/api/settings",
            json={
                "values": {
                    "auto_publish_enabled": True,
                    "auto_publish_targets": {
                        "xiaohongshu": {
                            "enabled": True,
                            "account_id": account["id"],
                            "action": "publish",
                        }
                    },
                }
            },
        )
        article = self.client.post(
            "/api/articles",
            json={
                "title": "自动发布类型过滤",
                "article_type": "article",
                "publish_mode": "automatic",
            },
        ).json()

        response = self.client.post("/api/automation/publish")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["processed"], 0)
        detail = self.client.get(f"/api/articles/{article['id']}").json()
        self.assertEqual(detail["status"], "ready")
        self.assertEqual(detail["platform_states"], [])

    def test_browser_video_platform_accounts_and_content_boundary(self):
        for key in ("xiaohongshu", "douyin", "channels", "bilibili"):
            response = self.client.post(
                "/api/accounts",
                json={"platform": key, "name": f"{key}-主账号"},
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["platform"], key)

        settings = self.client.get("/api/settings").json()["values"]
        self.assertFalse(settings["douyin_enabled"])
        self.assertFalse(settings["channels_enabled"])
        self.assertFalse(settings["bilibili_enabled"])
        self.assertEqual(settings["bilibili_default_category"], "")
        self.assertEqual(settings["bilibili_copyright"], "")

        for publisher_class in (
            DouyinPublisher,
            ChannelsPublisher,
            BilibiliPublisher,
        ):
            publisher = publisher_class(settings)
            with self.assertRaisesRegex(ValueError, "首期仅支持视频内容"):
                publisher.publish({"article_type": "image"})

    def test_xiaohongshu_profile_is_saved_without_changing_login_status(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "xiaohongshu", "name": "资料测试账号"},
        ).json()
        from backend.accounts import update_account_status

        update_account_status(account["id"], "valid")
        profile = {
            "display_name": "小红书昵称",
            "platform_user_id": "123456",
            "avatar_url": "https://example.com/avatar.jpg",
            "avatar_cached": True,
            "following_count": 7,
            "followers_count": 240,
            "likes_and_collections_count": 3197,
        }
        with patch(
            "backend.accounts._fetch_account_profile",
            return_value=profile,
        ):
            response = self.client.post(
                f"/api/accounts/{account['id']}/profile"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "valid")
        self.assertEqual(response.json()["profile"], profile)
        self.assertTrue(response.json()["profile_synced_at"])
        self.assertEqual(response.json()["profile_error"], "")

        avatar_path = backend.accounts.account_avatar_path(response.json())
        avatar_path.parent.mkdir(parents=True)
        avatar_path.write_bytes(b"png-bytes")
        avatar_response = self.client.get(
            f"/api/accounts/{account['id']}/avatar"
        )
        self.assertEqual(avatar_response.status_code, 200)
        self.assertEqual(avatar_response.content, b"png-bytes")

    def test_xiaohongshu_compact_profile_counts(self):
        self.assertEqual(_parse_profile_count("1.2万"), 12000)
        self.assertEqual(_parse_profile_count("3,197"), 3197)
        self.assertIsNone(_parse_profile_count("暂无"))

    def test_csdn_profile_text_metrics(self):
        profile = _csdn_profile_text(
            "3\u539f\u521b 12\u7c89\u4e1d \u603b\u9605\u8bfb\u91cf 2.3\u4e07 \u6536\u85cf\u6570 9"
        )
        self.assertEqual(profile["works_count"], 3)
        self.assertEqual(profile["followers_count"], 12)
        self.assertEqual(profile["read_count"], 23000)
        self.assertEqual(profile["favorites_count"], 9)

    def test_csdn_publish_opens_editor_directly_and_closes_ai(self):
        from contextlib import nullcontext

        from backend.platforms.csdn import (
            CsdnPublisher,
            EDITOR_URL,
            TITLE_SELECTOR,
        )

        page = Mock()
        title_input = Mock()
        save = Mock()
        page.locator.return_value.first = title_input
        page.get_by_role.return_value.first = save
        article = {
            "title": "CSDN draft",
            "content_md": "Draft body",
            "platform_accounts": {"csdn": 2},
        }
        with (
            patch(
                "backend.platforms.csdn.resolve_publish_account",
                return_value={"id": 2},
            ),
            patch(
                "backend.platforms.csdn.open_account_browser",
                return_value=nullcontext(Mock()),
            ),
            patch("backend.platforms.csdn.get_or_create_page", return_value=page),
            patch("backend.platforms.csdn._close_recent_draft_prompt") as close_draft_prompt,
            patch("backend.platforms.csdn._close_ai_assistant") as close_ai,
            patch("backend.platforms.csdn.replace_text"),
            patch("backend.platforms.csdn._prepare_editor_html") as prepare_editor,
            patch("backend.platforms.csdn._wait_for_draft_saved") as wait_saved,
        ):
            result = CsdnPublisher({}).publish(article, action="draft")

        self.assertEqual(
            [call.args[0] for call in page.goto.call_args_list],
            [EDITOR_URL],
        )
        page.locator.assert_called_once_with(TITLE_SELECTOR)
        page.get_by_role.assert_called_once_with(
            "button", name="保存草稿", exact=True
        )
        close_draft_prompt.assert_called_once_with(page)
        close_ai.assert_called_once_with(page)
        prepare_editor.assert_called_once_with(page, "Draft body")
        wait_saved.assert_called_once_with(page)
        page.wait_for_timeout.assert_called_once_with(3000)
        self.assertEqual(result["status"], "drafted")

    def test_csdn_can_publish_directly_and_waits_before_closing(self):
        from contextlib import nullcontext

        from backend.platforms.csdn import CsdnPublisher

        page = Mock()
        title_input = Mock()
        page.locator.return_value.first = title_input
        article = {
            "title": "CSDN publish",
            "content_md": "Publish body",
            "tags": ["Python", "自动化"],
            "platform_accounts": {"csdn": 2},
        }
        with (
            patch(
                "backend.platforms.csdn.resolve_publish_account",
                return_value={"id": 2},
            ),
            patch(
                "backend.platforms.csdn.open_account_browser",
                return_value=nullcontext(Mock()),
            ),
            patch("backend.platforms.csdn.get_or_create_page", return_value=page),
            patch("backend.platforms.csdn._close_recent_draft_prompt"),
            patch("backend.platforms.csdn._close_ai_assistant"),
            patch("backend.platforms.csdn.replace_text"),
            patch("backend.platforms.csdn._prepare_editor_html"),
            patch("backend.platforms.csdn._fill_publish_tags") as fill_tags,
            patch("backend.platforms.csdn._publish_blog") as publish_blog,
        ):
            result = CsdnPublisher({}).publish(article, action="publish")

        fill_tags.assert_called_once_with(page, ["Python", "自动化"])
        publish_blog.assert_called_once_with(page)
        page.wait_for_timeout.assert_called_once_with(3000)
        self.assertEqual(result["status"], "published")

    def test_csdn_publish_does_not_retry_after_saving_message(self):
        from backend.platforms.csdn import _publish_blog

        page = Mock()
        submit = Mock()
        page.get_by_role.return_value.first = submit
        with (
            patch("backend.platforms.csdn._wait_for_editor_ready") as wait_ready,
            patch(
                "backend.platforms.csdn._wait_for_publish_success",
                side_effect=RuntimeError("CSDN 发布失败：文章正在保存，请耐心等待。"),
            ) as wait_success,
        ):
            with self.assertRaisesRegex(RuntimeError, "文章正在保存"):
                _publish_blog(page)

        self.assertEqual(wait_ready.call_count, 1)
        self.assertEqual(submit.click.call_count, 1)
        self.assertEqual(wait_success.call_count, 1)

    def test_csdn_publish_tags_accepts_existing_automatic_tag(self):
        from backend.platforms.csdn import _fill_publish_tags

        page = Mock()
        with patch(
            "backend.platforms.csdn._selected_publish_tags",
            return_value=["notion"],
        ):
            _fill_publish_tags(page, ["Notion入门", "效率工具"])

        page.get_by_role.assert_not_called()

    def test_csdn_uploads_local_images_before_setting_final_html(self):
        from backend.platforms.csdn import _prepare_editor_html

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "article.png"
            image_path.write_bytes(b"image")
            markdown_text = (
                f"Before\n\n![diagram]({image_path.as_posix()})\n\nAfter"
            )
            page = Mock()
            with (
                patch("backend.platforms.csdn._set_editor_html") as set_editor,
                patch(
                    "backend.platforms.csdn._upload_csdn_image",
                    return_value="https://img-blog.csdnimg.cn/article.png",
                ) as upload_image,
            ):
                final_html = _prepare_editor_html(page, markdown_text)

        self.assertEqual(set_editor.call_count, 2)
        self.assertNotIn("<img", set_editor.call_args_list[0].args[1])
        self.assertIn("https://img-blog.csdnimg.cn/article.png", final_html)
        self.assertEqual(set_editor.call_args_list[1].args[1], final_html)
        upload_image.assert_called_once_with(page, image_path.resolve())

    def test_csdn_rejects_missing_local_image_before_save(self):
        from backend.platforms.csdn import _prepare_editor_html

        missing = (Path(tempfile.gettempdir()) / "missing-csdn-image.png").as_posix()
        with self.assertRaisesRegex(ValueError, "本地配图不存在"):
            _prepare_editor_html(Mock(), f"![missing]({missing})")

    def test_csdn_closes_visible_ai_assistant(self):
        from backend.platforms.csdn import (
            AI_ASSISTANT_CLOSE_SELECTOR,
            AI_ASSISTANT_DRAWER_SELECTOR,
            _close_ai_assistant,
        )

        page = Mock()
        drawer = Mock()
        close = Mock()
        page.locator.return_value.first = drawer
        drawer.locator.return_value.first = close

        self.assertTrue(_close_ai_assistant(page))

        page.locator.assert_called_once_with(AI_ASSISTANT_DRAWER_SELECTOR)
        drawer.locator.assert_called_once_with(AI_ASSISTANT_CLOSE_SELECTOR)
        close.click.assert_called_once_with()
        drawer.wait_for.assert_any_call(state="hidden", timeout=5_000)

    def test_csdn_editor_targets_recorded_ckeditor_frame(self):
        from backend.platforms.csdn import (
            EDITOR_BODY_SELECTOR,
            EDITOR_FRAME_SELECTOR,
            _set_editor_html,
        )

        page = Mock()
        frame = Mock()
        editor = Mock()
        page.frame_locator.return_value = frame
        frame.locator.return_value.first = editor

        _set_editor_html(page, "<p>Draft body</p>")

        page.frame_locator.assert_called_once_with(EDITOR_FRAME_SELECTOR)
        frame.locator.assert_called_once_with(EDITOR_BODY_SELECTOR)
        editor.wait_for.assert_called_once_with(
            state="visible", timeout=30_000
        )
        editor.evaluate.assert_called_once()
        page.evaluate.assert_called_once()

    def test_douyin_profile_text_metrics(self):
        profile = _douyin_text_profile(
            "抖音号：dy123\n关注数 12\n粉丝数 1.2万\n"
            "作品数 31\n获赞数 8.6万"
        )
        self.assertEqual(profile["platform_user_id"], "dy123")
        self.assertEqual(profile["following_count"], 12)
        self.assertEqual(profile["followers_count"], 12000)
        self.assertEqual(profile["works_count"], 31)
        self.assertEqual(profile["likes_count"], 86000)

    def test_channels_profile_text_metrics(self):
        profile = _channels_text_profile(
            "视频号ID:\nwx-channel-1\n视频58\n关注者4654\n"
            "获赞数 2,406"
        )
        self.assertEqual(
            profile["platform_user_id"],
            "wx-channel-1",
        )
        self.assertEqual(profile["followers_count"], 4654)
        self.assertEqual(profile["works_count"], 58)
        self.assertEqual(profile["likes_count"], 2406)

    def test_channels_profile_api_metrics(self):
        profile = _channels_api_profile({
            "data": {
                "finderUser": {
                    "nickname": "视频号账号",
                    "uniqId": "sph-demo-id",
                    "headImgUrl": "https://example.com/avatar.png",
                    "feedsCount": 58,
                    "fansCount": 4654,
                },
            },
        })

        self.assertEqual(profile["display_name"], "视频号账号")
        self.assertEqual(profile["platform_user_id"], "sph-demo-id")
        self.assertEqual(
            profile["avatar_url"],
            "https://example.com/avatar.png",
        )
        self.assertEqual(profile["followers_count"], 4654)
        self.assertEqual(profile["works_count"], 58)
        self.assertIsNone(profile["likes_count"])

    def test_douyin_and_channels_profile_handlers_are_registered(self):
        self.assertIn(
            "wechat",
            backend.accounts.ACCOUNT_PROFILE_HANDLERS,
        )
        self.assertIn(
            "douyin",
            backend.accounts.ACCOUNT_PROFILE_HANDLERS,
        )
        self.assertIn(
            "channels",
            backend.accounts.ACCOUNT_PROFILE_HANDLERS,
        )

    def test_douyin_login_follows_replaced_page(self):
        closed_page = Mock()
        closed_page.is_closed.return_value = True
        replacement = Mock()
        replacement.is_closed.return_value = False
        context = Mock()
        context.pages = [closed_page, replacement]

        self.assertIs(
            current_douyin_page(context, closed_page),
            replacement,
        )

    def test_windows_browser_command_avoids_automation_warning_flags(self):
        command = backend.browser._native_browser_command(
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
            Path("D:/profiles/demo"),
            9333,
        )
        joined = " ".join(command)
        self.assertIn("--remote-debugging-port=9333", joined)
        self.assertIn("--remote-debugging-address=127.0.0.1", joined)
        self.assertIn("--disable-extensions", joined)
        for forbidden in backend.browser.FORBIDDEN_BROWSER_ARGS:
            self.assertNotIn(forbidden, joined)

    def test_browser_reuses_one_tab_and_closes_stale_tabs(self):
        stale = Mock()
        stale.is_closed.return_value = False
        stale.url = "https://example.com/old"
        blank = Mock()
        blank.is_closed.return_value = False
        blank.url = "about:blank"
        another = Mock()
        another.is_closed.return_value = False
        another.url = "https://example.com/another"
        context = Mock()
        context.pages = [stale, blank, another]

        selected = backend.browser.get_or_create_page(context)

        self.assertIs(selected, blank)
        stale.close.assert_called_once_with()
        another.close.assert_called_once_with()
        blank.close.assert_not_called()
        context.new_page.assert_not_called()

    def test_saved_proxy_can_be_tested_and_selected_by_account(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "douyin", "name": "代理测试账号"},
        ).json()
        self.assertEqual(account["proxy_url"], "")

        created = self.client.post(
            "/api/proxies",
            json={
                "name": "本地代理",
                "proxy_url": "SOCKS5://127.0.0.1:7890/",
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            created.json()["proxy_url"],
            "socks5://127.0.0.1:7890",
        )
        self.assertEqual(created.json()["status"], "pending")

        proxy_response = Mock()
        proxy_response.json.return_value = {"ip": "203.0.113.8"}
        proxy_response.raise_for_status.return_value = None
        with patch(
            "backend.proxies.requests.get",
            return_value=proxy_response,
        ):
            tested = self.client.post(
                f"/api/proxies/{created.json()['id']}/test"
            )
        self.assertEqual(tested.status_code, 200)
        self.assertEqual(tested.json()["status"], "valid")
        self.assertEqual(tested.json()["exit_ip"], "203.0.113.8")

        response = self.client.put(
            f"/api/accounts/{account['id']}/proxy",
            json={"proxy_id": created.json()["id"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proxy"]["name"], "本地代理")
        command = backend.browser._native_browser_command(
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
            Path("D:/profiles/demo"),
            9333,
            response.json()["proxy_url"],
        )
        self.assertIn(
            "--proxy-server=socks5://127.0.0.1:7890",
            command,
        )

        cleared = self.client.put(
            f"/api/accounts/{account['id']}/proxy",
            json={"proxy_id": None},
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["proxy_url"], "")
        self.assertIsNone(cleared.json()["proxy"])

        self.client.put(
            f"/api/accounts/{account['id']}/proxy",
            json={"proxy_id": created.json()["id"]},
        )
        deleted = self.client.delete(
            f"/api/proxies/{created.json()['id']}"
        )
        self.assertEqual(deleted.status_code, 200)
        refreshed = self.client.get("/api/accounts").json()[0]
        self.assertIsNone(refreshed["proxy_id"])
        self.assertIsNone(refreshed["proxy"])

    def test_saved_proxy_rejects_credentials_and_missing_port(self):
        for proxy_url in (
            "http://user:pass@127.0.0.1:7890",
            "http://127.0.0.1",
            "ftp://127.0.0.1:21",
        ):
            response = self.client.post(
                "/api/proxies",
                json={
                    "name": f"错误代理-{proxy_url}",
                    "proxy_url": proxy_url,
                },
            )
            self.assertEqual(response.status_code, 400)

    def test_http_proxy_is_used_for_both_http_and_https(self):
        value = "http://192.0.2.10:808"
        self.assertEqual(
            backend.proxies.requests_proxy_map(value),
            {
                "http": "http://192.0.2.10:808",
                "https": "http://192.0.2.10:808",
            },
        )

    def test_proxy_test_falls_back_when_ipify_tls_fails(self):
        created = self.client.post(
            "/api/proxies",
            json={
                "name": "TLS 回退测试",
                "proxy_url": "http://192.0.2.10:808",
            },
        ).json()
        ip_response = Mock(status_code=200, text="203.0.113.9\n")
        ip_response.raise_for_status.return_value = None
        https_response = Mock(status_code=200)
        with patch(
            "backend.proxies.requests.get",
            side_effect=[
                backend.proxies.requests.exceptions.SSLError(
                    "unexpected EOF"
                ),
                ip_response,
                https_response,
            ],
        ):
            tested = self.client.post(
                f"/api/proxies/{created['id']}/test"
            )

        self.assertEqual(tested.status_code, 200)
        self.assertEqual(tested.json()["status"], "valid")
        self.assertEqual(tested.json()["exit_ip"], "203.0.113.9")

    def test_compatible_proxy_prefix_still_applies_globally(self):
        value = "HTTPS:HTTP://192.0.2.10:808/"
        self.assertEqual(
            backend.proxies.normalize_proxy_url(value),
            "http://192.0.2.10:808",
        )
        self.assertEqual(
            backend.proxies.requests_proxy_map(value),
            {
                "http": "http://192.0.2.10:808",
                "https": "http://192.0.2.10:808",
            },
        )
        command = backend.browser._native_browser_command(
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
            Path("D:/profiles/demo"),
            9333,
            value,
        )
        self.assertIn(
            "--proxy-server=http://192.0.2.10:808",
            command,
        )

    def test_article_create_edit_and_list(self):
        created = self.client.post(
            "/api/articles",
            json={
                "title": "一篇测试稿件",
                "content_md": "# 正文",
                "target_platforms": ["wechat"],
            },
        )
        self.assertEqual(created.status_code, 201)
        article_id = created.json()["id"]
        self.assertEqual(
            created.json()["platform_actions"],
            {"wechat": "draft"},
        )

        updated = self.client.patch(
            f"/api/articles/{article_id}",
            json={"publish_mode": "automatic", "author": "测试作者"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["publish_mode"], "automatic")

        articles = self.client.get("/api/articles").json()
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["author"], "测试作者")

    def test_account_and_video_content_flow(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "xiaohongshu", "name": "主账号"},
        )
        self.assertEqual(account.status_code, 201)
        self.assertEqual(account.json()["status"], "pending")

        uploaded = self.client.post(
            "/api/media",
            files={"file": ("demo.mp4", b"video-bytes", "video/mp4")},
        )
        self.assertEqual(uploaded.status_code, 201)
        media_path = uploaded.json()["path"]
        self.assertTrue(Path(media_path).is_file())

        created = self.client.post(
            "/api/articles",
            json={
                "title": "视频测试",
                "article_type": "video",
                "media_paths": [media_path],
                "target_platforms": ["xiaohongshu"],
                "platform_actions": {"xiaohongshu": "publish"},
                "platform_accounts": {"xiaohongshu": account.json()["id"]},
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["article_type"], "video")
        self.assertEqual(created.json()["media_paths"], [media_path])
        self.assertEqual(
            created.json()["platform_accounts"],
            {"xiaohongshu": account.json()["id"]},
        )

    def test_settings_are_masked(self):
        saved = self.client.put(
            "/api/settings",
            json={
                "values": {
                    "notion_token": "secret-token",
                    "notion_proxy_url": "",
                    "notion_sync_interval_minutes": 10,
                }
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["values"]["notion_token"], "••••••••")

        settings = self.client.get("/api/settings").json()
        self.assertEqual(settings["values"]["notion_token"], "••••••••")
        self.assertEqual(settings["values"]["notion_sync_interval_minutes"], 10)

    def test_deprecated_notion_platform_field_setting_is_removed(self):
        with backend.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value, is_secret, updated_at)
                VALUES ('notion_field_published_platforms', '"已发布平台"', 0, 'now')
                """
            )

        settings = self.client.get("/api/settings").json()["values"]
        self.assertNotIn("notion_field_published_platforms", settings)
        response = self.client.put(
            "/api/settings",
            json={
                "values": {
                    "notion_field_published_platforms": "已发布平台",
                }
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_platform_publish_always_uses_the_main_draft(self):
        article = self.client.post(
            "/api/articles",
            json={"title": "主稿标题", "content_md": "主稿正文"},
        ).json()
        self.client.patch(
            f"/api/articles/{article['id']}",
            json={
                "ai_result": {
                    "platforms": {
                        "wechat": {
                            "title": "历史公众号标题",
                            "content_md": "历史公众号正文",
                            "tags": [],
                        }
                    }
                }
            },
        )

        publisher = Mock()
        publisher.implemented = True
        publisher.is_enabled.return_value = True
        publisher.is_configured.return_value = True
        publisher.publish.return_value = {
            "external_id": "draft-media-id",
            "status": "drafted",
        }
        with patch(
            "backend.services.get_platforms",
            return_value={"wechat": publisher},
        ):
            response = self.client.post(
                f"/api/articles/{article['id']}/publish",
                json={"platform_actions": {"wechat": "draft"}},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "drafted")
        publisher.publish.assert_called_once()
        published_article = publisher.publish.call_args.args[0]
        self.assertEqual(published_article["title"], "主稿标题")
        self.assertEqual(published_article["content_md"], "主稿正文")
        self.assertEqual(publisher.publish.call_args.kwargs["action"], "draft")
        detail = self.client.get(f"/api/articles/{article['id']}").json()
        self.assertEqual(detail["publish_records"][0]["action"], "draft")
    def test_article_list_contains_latest_publish_error(self):
        article = self.client.post(
            "/api/articles",
            json={"title": "失败原因测试", "content_md": "正文"},
        ).json()
        publisher = Mock()
        publisher.implemented = True
        publisher.is_enabled.return_value = True
        publisher.is_configured.return_value = True
        publisher.publish.side_effect = RuntimeError("invalid ip, not in whitelist")

        with patch(
            "backend.services.get_platforms",
            return_value={"wechat": publisher},
        ):
            response = self.client.post(
                f"/api/articles/{article['id']}/publish",
                json={"platform_actions": {"wechat": "draft"}},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "failed")
        listed = self.client.get("/api/articles").json()
        self.assertEqual(
            listed[0]["latest_publish_error"],
            "invalid ip, not in whitelist",
        )
        self.assertEqual(listed[0]["last_error"], "invalid ip, not in whitelist")

    def test_successful_article_platform_is_not_published_twice(self):
        article = self.client.post(
            "/api/articles",
            json={"title": "幂等发布", "content_md": "正文"},
        ).json()
        publisher = Mock()
        publisher.implemented = True
        publisher.is_enabled.return_value = True
        publisher.is_configured.return_value = True
        publisher.publish.return_value = {
            "external_id": "draft-1",
            "status": "drafted",
        }

        with patch(
            "backend.services.get_platforms",
            return_value={"wechat": publisher},
        ):
            first = self.client.post(
                f"/api/articles/{article['id']}/publish",
                json={"platform_actions": {"wechat": "draft"}},
            )
            second = self.client.post(
                f"/api/articles/{article['id']}/publish",
                json={"platform_actions": {"wechat": "draft"}},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        publisher.publish.assert_called_once()
        self.assertTrue(second.json()["results"][0]["skipped"])
        detail = self.client.get(f"/api/articles/{article['id']}").json()
        self.assertEqual(detail["platform_states"][0]["status"], "drafted")
        self.assertEqual(detail["platform_states"][0]["attempts"], 1)



    def test_platform_state_schema_migrates_to_account_identity(self):
        first_account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "迁移账号 A"},
        ).json()
        second_account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "迁移账号 B"},
        ).json()
        article = self.client.post(
            "/api/articles",
            json={"title": "状态迁移", "content_md": "正文"},
        ).json()
        with backend.db.connection() as conn:
            conn.execute(
                "DROP INDEX IF EXISTS idx_article_platform_states_target"
            )
            conn.execute("DROP TABLE article_platform_states")
            conn.execute(
                """
                CREATE TABLE article_platform_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    action TEXT NOT NULL,
                    account_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    external_id TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(article_id, platform)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO article_platform_states (
                    article_id, platform, action, account_id, status, attempts,
                    external_id, last_error, created_at, updated_at
                ) VALUES (?, 'csdn', 'draft', ?, 'drafted', 1, 'old', '', 'now', 'now')
                """,
                (article["id"], first_account["id"]),
            )

        backend.db.init_db()

        with backend.db.connection() as conn:
            schema = conn.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'table' AND name = 'article_platform_states'
                """
            ).fetchone()["sql"]
            preserved = conn.execute(
                "SELECT * FROM article_platform_states"
            ).fetchall()
            conn.execute(
                """
                INSERT INTO article_platform_states (
                    article_id, platform, action, account_id, status, attempts,
                    external_id, last_error, created_at, updated_at
                ) VALUES (?, 'csdn', 'draft', ?, 'drafted', 1, 'new', '', 'now', 'now')
                """,
                (article["id"], second_account["id"]),
            )
            count = conn.execute(
                "SELECT COUNT(*) FROM article_platform_states"
            ).fetchone()[0]
            account_foreign_key = next(
                row for row in conn.execute(
                    "PRAGMA foreign_key_list(article_platform_states)"
                ).fetchall()
                if row["from"] == "account_id"
            )

        self.assertNotIn("UNIQUE(article_id, platform)", schema)
        self.assertEqual(account_foreign_key["on_delete"], "CASCADE")
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0]["external_id"], "old")
        self.assertEqual(count, 2)

    def test_manual_publish_uses_shared_default_targets(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "默认发布账号"},
        ).json()
        self.client.put(
            "/api/settings",
            json={
                "values": {
                    "auto_publish_targets": {
                        "csdn": {
                            "enabled": True,
                            "account_id": account["id"],
                            "action": "draft",
                        }
                    }
                }
            },
        )
        article = self.client.post(
            "/api/articles",
            json={"title": "统一默认方案", "content_md": "正文"},
        ).json()
        publisher = Mock()
        publisher.name = "CSDN"
        publisher.implemented = True
        publisher.is_enabled.return_value = True
        publisher.is_configured.return_value = True
        publisher.supports_content_type.return_value = True
        publisher.publish.return_value = {
            "external_id": "default-draft",
            "status": "drafted",
            "account_id": account["id"],
        }

        with patch(
            "backend.services.get_platforms",
            return_value={"csdn": publisher},
        ):
            response = self.client.post(
                f"/api/articles/{article['id']}/publish",
                json={},
            )

        self.assertEqual(response.status_code, 200)
        publisher.publish.assert_called_once()
        published_article = publisher.publish.call_args.args[0]
        self.assertEqual(
            published_article["platform_accounts"]["csdn"],
            account["id"],
        )
        record = self.client.get(
            f"/api/articles/{article['id']}"
        ).json()["publish_records"][0]
        self.assertEqual(record["account_id"], account["id"])
        self.assertEqual(record["trigger_source"], "manual")

    def test_force_republish_records_a_new_attempt(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "重发账号"},
        ).json()
        article = self.client.post(
            "/api/articles",
            json={"title": "再次发布", "content_md": "正文"},
        ).json()
        publisher = Mock()
        publisher.name = "CSDN"
        publisher.implemented = True
        publisher.is_enabled.return_value = True
        publisher.is_configured.return_value = True
        publisher.supports_content_type.return_value = True
        publisher.publish.return_value = {
            "external_id": "republished-draft",
            "status": "drafted",
            "account_id": account["id"],
        }
        payload = {
            "platform_actions": {"csdn": "draft"},
            "platform_accounts": {"csdn": account["id"]},
        }

        with patch(
            "backend.services.get_platforms",
            return_value={"csdn": publisher},
        ):
            first = self.client.post(
                f"/api/articles/{article['id']}/publish",
                json=payload,
            )
            second = self.client.post(
                f"/api/articles/{article['id']}/publish",
                json={**payload, "force": True},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(publisher.publish.call_count, 2)
        detail = self.client.get(f"/api/articles/{article['id']}").json()
        self.assertEqual(detail["platform_states"][0]["attempts"], 2)
        self.assertEqual(len(detail["publish_records"]), 2)
        self.assertEqual(detail["publish_records"][0]["forced"], 1)
        self.assertEqual(
            detail["publish_records"][0]["trigger_source"],
            "republish",
        )
        self.assertEqual(detail["publish_records"][1]["forced"], 0)

    def test_same_platform_accounts_have_independent_states(self):
        first_account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "账号 A"},
        ).json()
        second_account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "账号 B"},
        ).json()
        article = self.client.post(
            "/api/articles",
            json={"title": "多账号发布", "content_md": "正文"},
        ).json()
        publisher = Mock()
        publisher.name = "CSDN"
        publisher.implemented = True
        publisher.is_enabled.return_value = True
        publisher.is_configured.return_value = True
        publisher.supports_content_type.return_value = True
        publisher.publish.side_effect = lambda published, action: {
            "external_id": f"draft-{published['platform_accounts']['csdn']}",
            "status": "drafted",
            "account_id": published["platform_accounts"]["csdn"],
        }

        with patch(
            "backend.services.get_platforms",
            return_value={"csdn": publisher},
        ):
            for account in (first_account, second_account):
                response = self.client.post(
                    f"/api/articles/{article['id']}/publish",
                    json={
                        "platform_actions": {"csdn": "draft"},
                        "platform_accounts": {"csdn": account["id"]},
                    },
                )
                self.assertEqual(response.status_code, 200)

        backend.db.init_db()
        detail = self.client.get(f"/api/articles/{article['id']}").json()
        self.assertEqual(publisher.publish.call_count, 2)
        self.assertEqual(
            {state["account_id"] for state in detail["platform_states"]},
            {first_account["id"], second_account["id"]},
        )

    def test_auto_publish_only_processes_ready_content(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "队列账号"},
        ).json()
        self.client.put(
            "/api/settings",
            json={
                "values": {
                    "auto_publish_enabled": True,
                    "auto_publish_targets": {
                        "csdn": {
                            "enabled": True,
                            "account_id": account["id"],
                            "action": "draft",
                        }
                    },
                }
            },
        )
        draft = self.client.post(
            "/api/articles",
            json={"title": "内容草稿", "content_md": "正文"},
        ).json()
        ready = self.client.post(
            "/api/articles",
            json={
                "title": "发布队列稿件",
                "content_md": "正文",
                "content_status": "ready",
            },
        ).json()
        publisher = Mock()
        publisher.name = "CSDN"
        publisher.implemented = True
        publisher.is_enabled.return_value = True
        publisher.is_configured.return_value = True
        publisher.supports_content_type.return_value = True
        publisher.publish.return_value = {
            "external_id": "queue-draft",
            "status": "drafted",
            "account_id": account["id"],
        }

        with patch(
            "backend.services.get_platforms",
            return_value={"csdn": publisher},
        ):
            first = self.client.post("/api/automation/publish")
            second = self.client.post("/api/automation/publish")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["processed"], 1)
        self.assertEqual(second.json()["processed"], 0)
        publisher.publish.assert_called_once()
        self.assertEqual(publisher.publish.call_args.args[0]["id"], ready["id"])
        progress = app_module.publish_progress.snapshot()
        self.assertEqual(progress["status"], "completed")
        self.assertTrue(any(
            "找到 0 篇待处理稿件" in event["message"]
            for event in progress["events"]
        ))
        draft_detail = self.client.get(
            f"/api/articles/{draft['id']}"
        ).json()
        self.assertEqual(draft_detail["content_status"], "draft")
        self.assertEqual(draft_detail["platform_states"], [])

    def test_platform_failure_does_not_stop_following_platform(self):
        article = self.client.post(
            "/api/articles",
            json={"title": "平台隔离", "content_md": "正文"},
        ).json()
        failed = Mock()
        failed.implemented = True
        failed.is_enabled.return_value = True
        failed.is_configured.return_value = True
        failed.publish.side_effect = RuntimeError("公众号失败")
        succeeded = Mock()
        succeeded.implemented = True
        succeeded.is_enabled.return_value = True
        succeeded.is_configured.return_value = True
        succeeded.publish.return_value = {
            "external_id": "csdn-1",
            "status": "drafted",
        }

        with patch(
            "backend.services.get_platforms",
            return_value={"wechat": failed, "csdn": succeeded},
        ):
            response = self.client.post(
                f"/api/articles/{article['id']}/publish",
                json={
                    "platform_actions": {
                        "wechat": "draft",
                        "csdn": "draft",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "partial")
        failed.publish.assert_called_once()
        succeeded.publish.assert_called_once()
        states = {
            item["platform"]: item
            for item in self.client.get(
                f"/api/articles/{article['id']}"
            ).json()["platform_states"]
        }
        self.assertEqual(states["wechat"]["status"], "failed")
        self.assertEqual(states["csdn"]["status"], "drafted")

    def test_auto_publish_uses_selected_account_and_waits_for_failed_retry(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "自动发布账号"},
        ).json()
        saved = self.client.put(
            "/api/settings",
            json={
                "values": {
                    "auto_publish_enabled": True,
                    "auto_publish_targets": {
                        "csdn": {
                            "enabled": True,
                            "account_id": account["id"],
                            "action": "draft",
                        }
                    },
                }
            },
        )
        self.assertEqual(saved.status_code, 200)
        article = self.client.post(
            "/api/articles",
            json={
                "title": "自动发布失败重试",
                "content_md": "正文",
                "publish_mode": "automatic",
            },
        ).json()
        publisher = Mock()
        publisher.implemented = True
        publisher.is_enabled.return_value = True
        publisher.is_configured.return_value = True
        publisher.publish.side_effect = RuntimeError("暂时失败")

        with patch(
            "backend.services.get_platforms",
            return_value={"csdn": publisher},
        ):
            first = self.client.post("/api/automation/publish")
            second = self.client.post("/api/automation/publish")

        self.assertEqual(first.json()["processed"], 1)
        self.assertEqual(second.json()["processed"], 0)
        publisher.publish.assert_called_once()
        published_article = publisher.publish.call_args.args[0]
        self.assertEqual(
            published_article["platform_accounts"]["csdn"],
            account["id"],
        )

        publisher.publish.side_effect = None
        publisher.publish.return_value = {
            "external_id": "retry-draft",
            "status": "drafted",
            "account_id": account["id"],
        }
        with patch(
            "backend.services.get_platforms",
            return_value={"csdn": publisher},
        ):
            retried = self.client.post(
                f"/api/articles/{article['id']}/platforms/csdn/retry"
            )

        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["status"], "drafted")
        state = self.client.get(
            f"/api/articles/{article['id']}"
        ).json()["platform_states"][0]
        self.assertEqual(state["attempts"], 2)
        self.assertEqual(state["status"], "drafted")
    def test_ai_enrichment_recommends_title_and_limits_tags(self):
        article = self.client.post(
            "/api/articles",
            json={
                "title": "原始主稿标题",
                "content_md": "原稿",
                "tags": ["原有标签"],
            },
        ).json()
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        ai_result = {
            "recommended_title": "AI 推荐标题",
            "tags": ["标签1", "标签2", "标签3", "标签4", "标签5", "标签6"],
            "summary": "文章摘要",
            "editor_notes": "",
        }
        with patch(
            "backend.services.AIContentService.enrich",
            return_value=ai_result,
        ):
            response = self.client.post(f"/api/articles/{article['id']}/enrich")

        self.assertEqual(response.status_code, 200)
        enriched = response.json()
        self.assertEqual(enriched["title"], "原始主稿标题")
        self.assertEqual(enriched["tags"], ["标签1", "标签2", "标签3", "标签4", "标签5"])
        self.assertEqual(
            enriched["ai_result"]["recommended_title"],
            "AI 推荐标题",
        )
        self.assertNotIn("platforms", enriched["ai_result"])

    def test_ai_enrichment_generates_local_cover_when_missing(self):
        article = self.client.post(
            "/api/articles",
            json={"title": "本地 AI 工作流", "content_md": "正文内容"},
        ).json()
        self.client.put(
            "/api/settings",
            json={
                "values": {
                    "ai_enabled": True,
                    "ai_image_model": "image-model",
                }
            },
        )
        generated_cover = Path(self.temp_dir.name) / "enriched-cover.png"
        generated_cover.write_bytes(b"\x89PNG\r\n\x1a\ncover")
        ai_result = {
            "recommended_title": "推荐标题",
            "cover_title": "本地AI工作流",
            "tags": ["AI", "工作流"],
            "summary": "摘要",
            "editor_notes": "",
        }

        with (
            patch(
                "backend.services.AIContentService.enrich",
                return_value=ai_result,
            ),
            patch(
                "backend.services.AIImageService.generate_images",
                return_value=[{"path": str(generated_cover.resolve())}],
            ) as generate_images,
        ):
            response = self.client.post(
                f"/api/articles/{article['id']}/enrich"
            )

        self.assertEqual(response.status_code, 200)
        enriched = response.json()
        self.assertEqual(
            enriched["cover_url"],
            str(generated_cover.resolve()),
        )
        self.assertIn(str(generated_cover.resolve()), enriched["media_paths"])
        self.assertEqual(
            enriched["ai_result"]["cover_generation"]["status"],
            "completed",
        )
        cover_plan = generate_images.call_args.args[0][0]
        self.assertEqual(cover_plan["cover_text"], "本地AI工作流")
        self.assertIn("必须且只能出现一次", cover_plan["prompt"])
        self.assertIn("本地AI工作流", cover_plan["prompt"])

    def test_ai_enrichment_rejects_duplicate_article_task(self):
        from backend import services
        from backend.settings import get_settings

        article = self.client.post(
            "/api/articles",
            json={"title": "并发加工", "content_md": "正文内容"},
        ).json()
        settings = get_settings()
        settings["ai_enabled"] = True
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def slow_enrich(_article):
            entered.set()
            release.wait(2)
            return {
                "recommended_title": "",
                "tags": ["并发测试"],
                "summary": "",
                "editor_notes": "",
                "cover_brief": "",
                "cover_title": "",
            }

        def run_first_task():
            try:
                services.enrich_article(article["id"], settings=settings)
            except Exception as exc:
                errors.append(exc)

        with patch(
            "backend.services.AIContentService.enrich",
            side_effect=slow_enrich,
        ):
            worker = threading.Thread(target=run_first_task)
            worker.start()
            self.assertTrue(entered.wait(1))
            with self.assertRaisesRegex(RuntimeError, "正在进行 AI 加工"):
                services.enrich_article(article["id"], settings=settings)
            release.set()
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    def test_ai_enrichment_discards_stale_cover_result(self):
        from backend import services
        from backend.settings import get_settings

        article = self.client.post(
            "/api/articles",
            json={"title": "封面竞争", "content_md": "正文内容"},
        ).json()
        settings = get_settings()
        settings.update({"ai_enabled": True, "ai_image_model": "image-model"})
        generated_cover = Path(self.temp_dir.name) / "stale-cover.png"
        generated_cover.write_bytes(b"stale")
        preserved_cover = Path(self.temp_dir.name) / "preserved-cover.png"
        preserved_cover.write_bytes(b"preserved")
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def delayed_generate(_plans):
            entered.set()
            release.wait(2)
            return [{"path": str(generated_cover.resolve())}]

        def run_stale_task():
            try:
                services._enrich_article(article["id"], settings=settings)
            except Exception as exc:
                errors.append(exc)

        enrichment = {
            "recommended_title": "",
            "tags": ["封面"],
            "summary": "",
            "editor_notes": "",
            "cover_brief": "",
            "cover_title": "",
        }
        with (
            patch(
                "backend.services.AIContentService.enrich",
                return_value=enrichment,
            ),
            patch(
                "backend.services.AIImageService.generate_images",
                side_effect=delayed_generate,
            ),
        ):
            worker = threading.Thread(target=run_stale_task)
            worker.start()
            self.assertTrue(entered.wait(1))
            services.update_article(
                article["id"],
                {
                    "cover_url": str(preserved_cover.resolve()),
                    "media_paths": [str(preserved_cover.resolve())],
                },
            )
            release.set()
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        updated = services.get_article(article["id"])
        self.assertEqual(updated["cover_url"], str(preserved_cover.resolve()))
        self.assertFalse(generated_cover.exists())

    def test_ai_enrichment_keeps_text_result_when_cover_generation_fails(self):
        article = self.client.post(
            "/api/articles",
            json={"title": "封面容错", "content_md": "正文内容"},
        ).json()
        self.client.put(
            "/api/settings",
            json={
                "values": {
                    "ai_enabled": True,
                    "ai_image_model": "image-model",
                }
            },
        )
        ai_result = {
            "recommended_title": "推荐标题",
            "tags": ["容错"],
            "summary": "摘要",
            "editor_notes": "",
        }

        with (
            patch(
                "backend.services.AIContentService.enrich",
                return_value=ai_result,
            ),
            patch(
                "backend.services.AIImageService.generate_images",
                side_effect=RuntimeError("图片服务暂不可用"),
            ),
        ):
            response = self.client.post(
                f"/api/articles/{article['id']}/enrich"
            )

        self.assertEqual(response.status_code, 200)
        enriched = response.json()
        self.assertEqual(enriched["tags"], ["容错"])
        self.assertEqual(enriched["cover_url"], "")
        self.assertEqual(
            enriched["ai_result"]["cover_generation"]["status"],
            "failed",
        )
        self.assertIn(
            "图片服务暂不可用",
            enriched["ai_result"]["cover_generation"]["message"],
        )

    def test_ai_enrichment_requires_one_to_five_tags(self):
        from backend.ai_service import AIContentService

        result = AIContentService._validate_result(
            {
                "recommended_title": "推荐标题",
                "tags": ["A", "A", "B", "C", "D", "E", "F"],
                "summary": "",
                "editor_notes": "",
                "cover_title": "精准封面标题",
            }
        )
        self.assertEqual(result["tags"], ["A", "B", "C", "D", "E"])
        self.assertEqual(result["cover_title"], "精准封面标题")
        with self.assertRaisesRegex(RuntimeError, "未生成有效标签"):
            AIContentService._validate_result(
                {
                    "recommended_title": "",
                    "tags": [],
                    "summary": "",
                    "editor_notes": "",
                }
            )
    def test_same_notion_source_overwrites_instead_of_inserting(self):
        first = self._notion_article("unique:100", "page-a", "第一版")
        action, article_id = _upsert_synced_article(first, "manual")
        self.assertEqual(action, "created")

        second = self._notion_article("unique:100", "page-b", "覆盖后的标题")
        action, updated_id = _upsert_synced_article(second, "manual")

        self.assertEqual(action, "updated")
        self.assertEqual(updated_id, article_id)
        articles = self.client.get("/api/articles").json()
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "覆盖后的标题")
        self.assertEqual(articles[0]["notion_page_id"], "page-b")

    def test_resync_without_cover_keeps_existing_cover(self):
        first = self._notion_article("unique:cover", "cover-page-a", "第一版")
        first["cover_url"] = "C:/media/generated-cover.png"
        _, article_id = _upsert_synced_article(first, "manual")

        second = self._notion_article("unique:cover", "cover-page-b", "第二版")
        action, updated_id = _upsert_synced_article(second, "manual")

        self.assertEqual(action, "updated")
        self.assertEqual(updated_id, article_id)
        article = self.client.get(f"/api/articles/{article_id}").json()
        self.assertEqual(article["cover_url"], "C:/media/generated-cover.png")

    def test_identity_conflict_keeps_existing_articles(self):
        _upsert_synced_article(
            self._notion_article("unique:100", "page-a", "文章 A"),
            "manual",
        )
        _upsert_synced_article(
            self._notion_article("unique:200", "page-b", "文章 B"),
            "manual",
        )

        with self.assertRaises(RuntimeError):
            _upsert_synced_article(
                self._notion_article("unique:100", "page-b", "冲突文章"),
                "manual",
            )

        self.assertEqual(len(self.client.get("/api/articles").json()), 2)

    def test_signed_image_url_reuses_cached_wechat_material(self):
        original = (
            "https://example.com/image.png?x-oss-process=style%2Fjixn"
            "&x-oss-signature=old-signature&x-oss-expires=100"
        )
        refreshed = (
            "https://example.com/image.png?x-oss-expires=200"
            "&x-oss-process=style%2Fjixn&x-oss-signature=new-signature"
        )
        save_platform_asset(
            original,
            "wechat",
            "existing-media-id",
            "https://mmbiz.qpic.cn/existing",
        )

        cached = get_platform_asset(refreshed, "wechat")

        self.assertEqual(cached["media_id"], "existing-media-id")
        self.assertTrue(cached["is_cached"])

    def test_notion_unique_id_becomes_source_key(self):
        page = {
            "id": "page-id",
            "url": "https://notion.so/page-id",
            "properties": {
                "唯一ID": {
                    "type": "unique_id",
                    "unique_id": {"prefix": "ART-", "number": 42},
                },
                "标题": {"type": "title", "title": [{"plain_text": "文章"}]},
                "文章类型": {
                    "type": "select",
                    "select": {"name": "图文"},
                },
            },
        }

        metadata = page_metadata(page, unique_property="唯一ID")

        self.assertEqual(
            metadata["source_key"],
            "notion:unique:唯一ID:ART-42",
        )

    def test_custom_notion_field_mapping(self):
        page = {
            "id": "custom-page",
            "url": "https://notion.so/custom-page",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "自定义标题"}]},
                "Format": {"type": "select", "select": {"name": "图文"}},
                "Byline": {"type": "select", "select": {"name": "作者甲"}},
                "Cover": {"type": "url", "url": "https://example.com/cover.png"},
                "Source": {"type": "url", "url": "https://example.com"},
                "Topics": {
                    "type": "multi_select",
                    "multi_select": [{"name": "标签甲"}],
                },
            },
        }
        mapping = {
            "title": "Name",
            "article_type": "Format",
            "author": "Byline",
            "cover_url": "Cover",
            "source_url": "Source",
            "tags": "Topics",
        }

        metadata = page_metadata(
            page,
            unique_property="",
            field_mapping=mapping,
        )

        self.assertEqual(metadata["title"], "自定义标题")
        self.assertEqual(metadata["article_type"], "image")
        self.assertEqual(metadata["author"], "作者甲")

    def test_notion_rejects_unsupported_article_type(self):
        page = {
            "id": "unsupported-type",
            "properties": {
                "标题": {"type": "title", "title": [{"plain_text": "测试"}]},
                "文章类型": {
                    "type": "select",
                    "select": {"name": "视频"},
                },
            },
        }

        with self.assertRaisesRegex(ValueError, "仅支持.*文章.*图文"):
            page_metadata(page)

    def test_notion_sync_marks_successful_pages_as_synced(self):
        page = {
            "id": "sync-page",
            "url": "https://notion.so/sync-page",
            "properties": {
                "标题": {
                    "type": "title",
                    "title": [{"plain_text": "待同步图文"}],
                },
                "文章类型": {
                    "type": "select",
                    "select": {"name": "图文"},
                },
            },
        }
        client = Mock()
        client.query_pages.return_value = [page]
        client.get_page_markdown.return_value = "# 正文"
        client.update_status.return_value = {"id": page["id"]}

        with patch("backend.services.notion_client", return_value=client):
            response = self.client.post("/api/sync/notion")

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["marked_synced"], 1)
        self.assertEqual(result["errors"], [])
        client.query_pages.assert_called_once_with(
            "待同步",
            status_field="状态",
        )
        client.update_status.assert_called_once_with(
            page["id"],
            status_field="状态",
            status="已同步",
        )
        article = self.client.get("/api/articles").json()[0]
        self.assertEqual(article["article_type"], "image")

    def test_notion_sync_localizes_cover_and_markdown_images(self):
        cover_url = "https://files.example.com/cover.png?X-Amz-Signature=old"
        body_url = "https://files.example.com/body.png?token=old"
        page = {
            "id": "local-image-page",
            "url": "https://notion.so/local-image-page",
            "properties": {
                "标题": {
                    "type": "title",
                    "title": [{"plain_text": "本地图片稿件"}],
                },
                "文章类型": {
                    "type": "select",
                    "select": {"name": "文章"},
                },
                "封面图片": {"type": "url", "url": cover_url},
            },
        }
        client = Mock()
        client.query_pages.return_value = [page]
        client.get_page_markdown.return_value = (
            f"# 正文\n\n![正文图片]({body_url})"
        )
        client.session = Mock()
        responses = []
        for marker in (b"cover", b"body"):
            response = Mock()
            response.iter_content.return_value = [
                b"\x89PNG\r\n\x1a\n" + marker
            ]
            responses.append(response)
        client.session.get.side_effect = responses

        with patch("backend.services.notion_client", return_value=client):
            response = self.client.post("/api/sync/notion")

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["images_downloaded"], 2)
        self.assertEqual(result["image_errors"], [])
        article = self.client.get("/api/articles").json()[0]
        self.assertFalse(article["cover_url"].startswith("http"))
        self.assertTrue(Path(article["cover_url"]).is_file())
        self.assertNotIn(body_url, article["content_md"])
        self.assertEqual(len(article["media_paths"]), 2)
        self.assertTrue(all(Path(path).is_file() for path in article["media_paths"]))

    def test_local_image_cache_reuses_refreshed_signed_url(self):
        first_url = (
            "https://files.example.com/image.png?"
            "x-oss-signature=old&x-oss-expires=100"
        )
        refreshed_url = (
            "https://files.example.com/image.png?"
            "x-oss-expires=200&x-oss-signature=new"
        )
        session = Mock()
        response = Mock()
        response.iter_content.return_value = [b"\x89PNG\r\n\x1a\nimage"]
        session.get.return_value = response

        first = localize_remote_images(
            f"![图]({first_url})",
            session=session,
            namespace="signed-page",
        )
        second = localize_remote_images(
            f"![图]({refreshed_url})",
            session=session,
            namespace="signed-page",
        )

        self.assertEqual(first["downloaded"], 1)
        self.assertEqual(second["reused"], 1)
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(first["paths"], second["paths"])

    def test_existing_article_image_localization_keeps_failed_url(self):
        cover_url = "https://files.example.com/cover.png"
        body_url = "https://files.example.com/body.png?token=secret"
        article = self.client.post(
            "/api/articles",
            json={
                "title": "旧稿图片迁移",
                "cover_url": cover_url,
                "content_md": f"![正文]({body_url})",
            },
        ).json()
        client = Mock()
        client.session = Mock()
        cover_response = Mock()
        cover_response.iter_content.return_value = [
            b"\x89PNG\r\n\x1a\ncover"
        ]
        failed_response = Mock()
        failed_response.raise_for_status.side_effect = RuntimeError("下载失败")
        client.session.get.side_effect = [cover_response, failed_response]

        with patch("backend.services.notion_client", return_value=client):
            response = self.client.post(
                f"/api/articles/{article['id']}/localize-images"
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["downloaded"], 1)
        self.assertEqual(len(result["errors"]), 1)
        localized = result["article"]
        self.assertTrue(Path(localized["cover_url"]).is_file())
        self.assertIn(body_url, localized["content_md"])
        self.assertNotIn("secret", result["errors"][0]["url"])

    def test_notion_sync_generates_missing_image_cover_from_content(self):
        page = {
            "id": "cover-page",
            "url": "https://notion.so/cover-page",
            "properties": {
                "标题": {
                    "type": "title",
                    "title": [{"plain_text": "春季城市骑行指南"}],
                },
                "文章类型": {
                    "type": "select",
                    "select": {"name": "图文"},
                },
            },
        }
        client = Mock()
        client.query_pages.return_value = [page]
        client.get_page_markdown.return_value = "# 路线建议\n\n选择河岸绿道，避开晚高峰。"
        generated_cover = Path(self.temp_dir.name) / "generated-cover.png"
        generated_cover.write_bytes(b"\x89PNG\r\n\x1a\ncover")
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True, "ai_image_model": "image-model"}},
        )

        with (
            patch("backend.services.notion_client", return_value=client),
            patch(
                "backend.services.AIImageService.generate_images",
                return_value=[{"path": str(generated_cover.resolve())}],
            ) as generate_images,
        ):
            response = self.client.post("/api/sync/notion")

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["covers_generated"], 1)
        self.assertEqual(result["cover_errors"], [])
        plan = generate_images.call_args.args[0][0]
        self.assertEqual(plan["content_kind"], "image_post")
        self.assertIn("春季城市骑行指南", plan["prompt"])
        self.assertIn("选择河岸绿道", plan["prompt"])
        article = self.client.get("/api/articles").json()[0]
        self.assertEqual(article["cover_url"], str(generated_cover.resolve()))
        self.assertEqual(article["media_paths"], [str(generated_cover.resolve())])
        client.update_status.assert_called_once()

    def test_notion_sync_continues_when_cover_generation_fails(self):
        page = {
            "id": "cover-error-page",
            "url": "https://notion.so/cover-error-page",
            "properties": {
                "标题": {
                    "type": "title",
                    "title": [{"plain_text": "没有封面的文章"}],
                },
                "文章类型": {
                    "type": "select",
                    "select": {"name": "文章"},
                },
            },
        }
        client = Mock()
        client.query_pages.return_value = [page]
        client.get_page_markdown.return_value = "正文"
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True, "ai_image_model": "image-model"}},
        )

        with (
            patch("backend.services.notion_client", return_value=client),
            patch(
                "backend.services.AIImageService.generate_images",
                side_effect=RuntimeError("图片服务暂不可用"),
            ),
        ):
            response = self.client.post("/api/sync/notion")

        result = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["marked_synced"], 1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["covers_generated"], 0)
        self.assertEqual(len(result["cover_errors"]), 1)
        self.assertIn("图片服务暂不可用", result["cover_errors"][0]["message"])
        self.assertEqual(self.client.get("/api/articles").json()[0]["cover_url"], "")
        client.update_status.assert_called_once()

    def test_custom_status_field_is_used_for_query_and_writeback(self):
        client = NotionClient("token", "database", data_source_id="source")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = [
            {"results": [], "has_more": False},
            {"id": "page"},
        ]
        with patch.object(client.session, "request", return_value=response) as request:
            client.query_pages("Queue", status_field="Workflow")
            query_payload = request.call_args.kwargs["json"]
            self.assertEqual(query_payload["filter"]["property"], "Workflow")

            client.mark_published(
                "page",
                status_field="Workflow",
                published_status="Done",
            )
            update_payload = request.call_args.kwargs["json"]["properties"]

        self.assertEqual(update_payload["Workflow"]["status"]["name"], "Done")
        self.assertEqual(set(update_payload), {"Workflow"})

    def test_log_redaction_hides_tokens_and_signed_url_values(self):
        url = (
            "https://example.com/image.png?x-oss-process=style/jixn"
            "&X-Amz-Signature=secret-signature&access_token=secret-token"
        )
        safe_url = redact_url(url)
        safe_error = redact_text(f"request failed: {url}")

        self.assertIn("x-oss-process=style%2Fjixn", safe_url)
        self.assertNotIn("secret-signature", safe_url)
        self.assertNotIn("secret-token", safe_url)
        self.assertNotIn("secret-signature", safe_error)
        self.assertNotIn("secret-token", safe_error)


    def test_frontend_index_is_not_cached(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-cache")

    def test_assistant_previews_and_saves_article(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        draft = {
            "title": "助手生成的文章",
            "summary": "文章摘要",
            "content_md": """## 正文

这是助手生成的内容。""",
            "tags": ["助手", "内容"],
            "image_plan": [],
        }
        with patch(
            "backend.assistant.AIContentService.generate_article",
            return_value=draft,
        ) as generate:
            preview = self.client.post(
                "/api/assistant/preview",
                json={
                    "target": "article",
                    "instruction": "写一篇内容工作流文章",
                    "article_type": "article",
                    "word_count": 1000,
                    "image_count": 0,
                },
            )

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["draft"]["title"], draft["title"])
        generate.assert_called_once()

        saved = self.client.post(
            "/api/assistant/execute",
            json={
                "target": "article",
                "draft": preview.json()["draft"],
                "article_type": "article",
                "image_count": 0,
                "references": preview.json()["references"],
            },
        )
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(saved.json()["destination"], "articles")
        self.assertEqual(saved.json()["item"]["title"], draft["title"])
        self.assertEqual(saved.json()["item"]["ai_result"]["source"], "assistant")
        self.assertEqual(len(self.client.get("/api/articles").json()), 1)

    def test_assistant_saves_article_before_generating_images(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        image_plan = {
            "position": "image:1",
            "alt": "后台配图",
            "purpose": "说明后台配图流程",
            "prompt": "内容工作台中的后台图片生成任务",
        }
        draft = {
            "title": "先保存文章再生成图片",
            "summary": "文章写入不应等待图片生成",
            "content_md": "## 正文\n\n文章正文。\n\n<!-- image:1 -->",
            "tags": ["AI", "配图"],
            "image_plan": [image_plan],
        }

        with (
            patch(
                "backend.assistant.AIImageService.generate_images",
                side_effect=AssertionError("文章保存不应同步生成图片"),
            ) as generate_images,
            patch("backend.app.generate_ai_article_images") as background_generate,
        ):
            response = self.client.post(
                "/api/assistant/execute",
                json={
                    "target": "article",
                    "draft": draft,
                    "article_type": "article",
                    "image_count": 1,
                },
            )

        self.assertEqual(response.status_code, 201)
        result = response.json()
        article = result["item"]
        generation = article["ai_result"]["image_generation"]
        self.assertEqual(generation["status"], "queued")
        self.assertEqual(
            article["ai_result"]["generated_images"][0]["status"],
            "pending",
        )
        self.assertIn("图片正在后台生成", result["message"])
        self.assertEqual(len(self.client.get("/api/articles").json()), 1)
        generate_images.assert_not_called()
        background_generate.assert_called_once_with(article["id"])

    def test_assistant_saves_news_note_and_generated_image(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        note_draft = {
            "title": "选题卡片",
            "summary": "用于后续写作",
            "content_md": """## 核心观点

内容应先归档。""",
            "tags": ["选题"],
            "source_name": "",
            "image_prompt": "",
        }
        with patch(
            "backend.assistant.AIContentService.generate_assistant_item",
            return_value=note_draft,
        ):
            preview = self.client.post(
                "/api/assistant/preview",
                json={"target": "note", "instruction": "整理一张选题卡片"},
            )
        note = self.client.post(
            "/api/assistant/execute",
            json={"target": "note", "draft": preview.json()["draft"]},
        )
        self.assertEqual(note.status_code, 201)
        self.assertEqual(note.json()["item"]["kind"], "note")

        oversized_note = {
            **note_draft,
            "summary": "摘要" * 100,
            "content_md": "单一知识点" * 300,
            "tags": [f"标签{index}" for index in range(8)],
        }
        guarded_note = self.client.post(
            "/api/assistant/execute",
            json={"target": "note", "draft": oversized_note},
        ).json()["item"]
        self.assertEqual(len(guarded_note["content_md"]), 1000)
        self.assertEqual(len(guarded_note["description"]), 120)
        self.assertEqual(len(guarded_note["tags"]), 5)

        news_draft = {
            "title": "行业资讯",
            "summary": "一条待核实的行业资讯",
            "content_md": """## 已知信息

仅整理用户提供的内容。""",
            "tags": ["行业"],
            "source_name": "示例来源",
            "image_prompt": "",
        }
        news = self.client.post(
            "/api/assistant/execute",
            json={
                "target": "news",
                "draft": news_draft,
                "source_url": "https://example.com/news/assistant",
            },
        )
        self.assertEqual(news.status_code, 201)
        self.assertEqual(news.json()["destination"], "news")
        self.assertEqual(
            self.client.get("/api/news").json()["items"][0]["source_name"],
            "示例来源",
        )

        image_bytes = bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"assistant"
        image_dir = backend.media.MEDIA_DIR / "ai"
        image_dir.mkdir(parents=True)
        generated_path = image_dir / "assistant.png"
        generated_path.write_bytes(image_bytes)
        image_draft = {
            "title": "内容工作流插图",
            "summary": "用于文章配图",
            "content_md": "",
            "tags": ["插图"],
            "source_name": "",
            "image_prompt": "明亮的编辑工作台，高质量摄影风格",
        }
        generated = {
            "position": "material:1",
            "alt": image_draft["title"],
            "purpose": image_draft["summary"],
            "prompt": image_draft["image_prompt"],
            "path": str(generated_path.resolve()),
        }
        with patch(
            "backend.assistant.AIImageService.generate_images",
            return_value=[generated],
        ):
            image = self.client.post(
                "/api/assistant/execute",
                json={"target": "image", "draft": image_draft},
            )

        self.assertEqual(image.status_code, 201)
        material = image.json()["item"]
        self.assertEqual(material["kind"], "image")
        self.assertFalse(generated_path.exists())
        self.assertTrue(Path(material["path"]).is_file())
        preview_file = self.client.get(
            f"/api/materials/{material['id']}/file"
        )
        self.assertEqual(preview_file.content, image_bytes)

    def test_assistant_chat_reads_safe_project_data(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        account = self.client.post(
            "/api/accounts",
            json={"platform": "csdn", "name": "内容账号"},
        ).json()
        with backend.db.connection() as conn:
            conn.execute(
                "UPDATE accounts SET profile_json = ? WHERE id = ?",
                (
                    '{"followers_count": 1234, "nickname": "墨流", '
                    '"cookie": "secret-cookie"}',
                    account["id"],
                ),
            )
        self.client.post(
            "/api/proxies",
            json={
                "name": "本地代理",
                "proxy_url": "http://127.0.0.1:7890",
            },
        )
        responses = [
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "accounts-call",
                        "type": "function",
                        "function": {
                            "name": "list_accounts",
                            "arguments": "{}",
                        },
                    },
                    {
                        "id": "proxies-call",
                        "type": "function",
                        "function": {
                            "name": "list_proxies",
                            "arguments": "{}",
                        },
                    },
                ],
            },
            {
                "content": "CSDN 账号已记录，当前状态为待检查。",
            },
        ]
        with patch(
            "backend.assistant.AIContentService.chat_with_tools",
            side_effect=responses,
        ) as chat:
            response = self.client.post(
                "/api/assistant/chat",
                json={"message": "看看我的账号和代理状态"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["kind"], "message")
        self.assertEqual([item["type"] for item in body["results"]], [
            "accounts",
            "proxies",
        ])
        profile = body["results"][0]["items"][0]["profile"]
        self.assertEqual(profile["followers_count"], 1234)
        self.assertNotIn("cookie", profile)
        self.assertNotIn("secret-cookie", str(body))
        self.assertEqual(
            body["results"][1]["items"][0]["proxy_url"],
            "http://***:7890",
        )
        self.assertEqual(chat.call_count, 2)
        second_messages = chat.call_args_list[1].args[0]
        self.assertEqual(
            [item["role"] for item in second_messages[-2:]],
            ["tool", "tool"],
        )

    def test_assistant_chat_requires_confirmation_before_creation(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        tool_response = {
            "content": None,
            "tool_calls": [{
                "id": "create-note-call",
                "type": "function",
                "function": {
                    "name": "create_note",
                    "arguments": '{"instruction": "解释什么是内容原子化"}',
                },
            }],
        }
        draft = {
            "title": "内容原子化",
            "summary": "一张卡片只保留一个可复用知识点",
            "content_md": "## 核心\n\n一张卡片只解释一个小点。",
            "tags": ["卡片笔记"],
            "source_name": "",
            "image_prompt": "",
        }
        with patch(
            "backend.assistant.AIContentService.chat_with_tools",
            return_value=tool_response,
        ), patch(
            "backend.assistant.AIContentService.generate_assistant_item",
            return_value=draft,
        ):
            response = self.client.post(
                "/api/assistant/chat",
                json={"message": "给我新建一张内容原子化卡片"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["kind"], "confirmation")
        self.assertEqual(body["action"]["target"], "note")
        self.assertEqual(
            self.client.get("/api/materials").json()["counts"]["all"],
            0,
        )

        saved = self.client.post(
            "/api/assistant/execute",
            json={
                "target": "note",
                "draft": body["action"]["preview"]["draft"],
            },
        )
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(saved.json()["item"]["kind"], "note")

    def test_assistant_chat_can_read_news_then_prepare_article(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        news = self.client.post(
            "/api/news",
            json={
                "title": "AI 内容工具更新",
                "source_name": "示例来源",
                "source_url": "https://example.com/ai-update",
                "summary": "工具新增结构化内容能力",
                "content_md": "## 更新\n\n新增结构化内容能力。",
                "tags": ["AI"],
            },
        ).json()
        responses = [
            {
                "content": None,
                "tool_calls": [{
                    "id": "news-call",
                    "type": "function",
                    "function": {
                        "name": "list_news",
                        "arguments": '{"limit": 5}',
                    },
                }],
            },
            {
                "content": None,
                "tool_calls": [{
                    "id": "article-call",
                    "type": "function",
                    "function": {
                        "name": "create_article",
                        "arguments": (
                            '{"instruction": "根据最近资讯写一篇分析文章", '
                            '"article_type": "article", "image_mode": "none", '
                            f'"news_ids": [{news["id"]}]' + "}"
                        ),
                    },
                }],
            },
        ]
        draft = {
            "title": "结构化内容能力正在进入工作流",
            "summary": "基于资讯整理的分析稿",
            "content_md": "## 变化\n\n结构化能力正在进入内容工作流。",
            "tags": ["AI", "内容工作流"],
            "image_plan": [],
        }
        with patch(
            "backend.assistant.AIContentService.chat_with_tools",
            side_effect=responses,
        ), patch(
            "backend.assistant.AIContentService.generate_article",
            return_value=draft,
        ):
            response = self.client.post(
                "/api/assistant/chat",
                json={"message": "根据最近 5 条资讯写一篇文章"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["kind"], "confirmation")
        self.assertEqual(body["results"][0]["type"], "news")
        self.assertEqual(
            body["action"]["preview"]["references"]["news_ids"],
            [news["id"]],
        )
        self.assertEqual(len(self.client.get("/api/articles").json()), 0)

    def test_generate_article_creates_local_image_draft(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        image_dir = backend.media.MEDIA_DIR / "ai"
        image_dir.mkdir(parents=True)
        first = image_dir / "cover.png"
        second = image_dir / "detail.png"
        first.write_bytes(b"\x89PNG\r\n\x1a\ncover")
        second.write_bytes(b"\x89PNG\r\n\x1a\ndetail")
        generated = {
            "title": "一篇生成稿",
            "summary": "生成摘要",
            "content_md": "开头\n\n<!-- image:1 -->\n\n结尾\n\n<!-- image:2 -->",
            "tags": ["AI", "写作"],
            "image_plan": [
                {
                    "position": "image:1",
                    "alt": "封面",
                    "prompt": "封面提示词",
                    "purpose": "封面",
                },
                {
                    "position": "image:2",
                    "alt": "细节",
                    "prompt": "细节提示词",
                    "purpose": "正文",
                },
            ],
        }
        images = [
            {**generated["image_plan"][0], "path": str(first.resolve())},
            {**generated["image_plan"][1], "path": str(second.resolve())},
        ]

        with (
            patch(
                "backend.services.AIContentService.generate_article",
                return_value=generated,
            ),
            patch(
                "backend.services.AIImageService.generate_images",
                side_effect=[[images[0]], [images[1]]],
            ),
        ):
            response = self.client.post(
                "/api/articles/generate",
                json={
                    "topic": "本地图片生成测试",
                    "article_type": "image",
                    "word_count": 700,
                    "image_count": 2,
                },
            )

        self.assertEqual(response.status_code, 201)
        draft = response.json()
        self.assertEqual(
            draft["ai_result"]["image_generation"]["status"],
            "queued",
        )
        article = self.client.get(
            f"/api/articles/{draft['id']}"
        ).json()
        self.assertEqual(article["article_type"], "image")
        self.assertEqual(article["media_paths"], [str(first.resolve()), str(second.resolve())])
        self.assertEqual(article["cover_url"], str(first.resolve()))
        self.assertIn(f"![封面]({first.resolve().as_posix()})", article["content_md"])
        self.assertNotIn("<!-- image:", article["content_md"])
        self.assertEqual(article["ai_result"]["source"], "generated")

    def test_generate_article_keeps_draft_when_an_image_fails(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        image_dir = backend.media.MEDIA_DIR / "ai"
        image_dir.mkdir(parents=True)
        cover = image_dir / "partial-cover.png"
        detail = image_dir / "partial-detail.png"
        cover.write_bytes(b"\x89PNG\r\n\x1a\ncover")
        detail.write_bytes(b"\x89PNG\r\n\x1a\ndetail")
        generated = {
            "title": "部分图片失败也保留",
            "summary": "生成摘要",
            "content_md": "正文\n\n<!-- image:1 -->\n\n<!-- image:2 -->",
            "tags": ["AI"],
            "image_plan": [
                {
                    "position": "image:1",
                    "alt": "封面",
                    "prompt": "封面提示词",
                    "purpose": "封面",
                },
                {
                    "position": "image:2",
                    "alt": "详情",
                    "prompt": "详情提示词",
                    "purpose": "正文",
                },
            ],
        }
        cover_result = {
            **generated["image_plan"][0],
            "path": str(cover.resolve()),
        }
        detail_result = {
            **generated["image_plan"][1],
            "path": str(detail.resolve()),
        }

        with (
            patch(
                "backend.services.AIContentService.generate_article",
                return_value=generated,
            ),
            patch(
                "backend.services.AIImageService.generate_images",
                side_effect=[[cover_result], RuntimeError("图片服务超时")],
            ),
        ):
            response = self.client.post(
                "/api/articles/generate",
                json={
                    "topic": "部分失败测试",
                    "article_type": "image",
                    "word_count": 700,
                    "image_count": 2,
                },
            )

        self.assertEqual(response.status_code, 201)
        draft = response.json()
        saved = self.client.get(f"/api/articles/{draft['id']}").json()
        generation = saved["ai_result"]["image_generation"]
        self.assertEqual(generation["status"], "partial")
        self.assertEqual(generation["succeeded"], 1)
        self.assertEqual(generation["failed"], 1)
        self.assertEqual(saved["media_paths"], [str(cover.resolve())])
        self.assertIn("<!-- image:2 -->", saved["content_md"])

        with patch(
            "backend.services.AIImageService.generate_images",
            return_value=[detail_result],
        ):
            retried = self.client.post(
                f"/api/articles/{draft['id']}/images/1/regenerate"
            )

        self.assertEqual(retried.status_code, 200)
        completed = retried.json()
        self.assertEqual(
            completed["ai_result"]["image_generation"]["status"],
            "completed",
        )
        self.assertEqual(
            completed["media_paths"],
            [str(cover.resolve()), str(detail.resolve())],
        )
        self.assertNotIn("<!-- image:", completed["content_md"])
    def test_material_library_file_note_edit_and_bulk_download(self):
        image_response = self.client.post(
            "/api/materials/files",
            files={"file": ("参考图.png", b"\x89PNG\r\n\x1a\nmaterial", "image/png")},
        )
        self.assertEqual(image_response.status_code, 201)
        image = image_response.json()
        note_response = self.client.post(
            "/api/materials/notes",
            json={
                "title": "采访要点",
                "content_md": "核心事实与表达边界",
                "description": "用于 AI 写作",
                "tags": ["采访", "事实"],
            },
        )
        self.assertEqual(note_response.status_code, 201)
        note = note_response.json()

        listed = self.client.get("/api/materials").json()
        self.assertEqual(listed["counts"]["all"], 2)
        self.assertEqual(listed["counts"]["image"], 1)
        self.assertEqual(listed["counts"]["note"], 1)

        updated = self.client.patch(
            f"/api/materials/{note['id']}",
            json={"title": "采访卡片", "content_md": "更新后的事实边界"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["title"], "采访卡片")

        preview = self.client.get(f"/api/materials/{image['id']}/file")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.content, b"\x89PNG\r\n\x1a\nmaterial")

        archive = self.client.post(
            "/api/materials/download",
            json={"ids": [image["id"], note["id"]]},
        )
        self.assertEqual(archive.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            names = bundle.namelist()
            self.assertIn("materials-manifest.json", names)
            self.assertTrue(any(name.endswith(".png") for name in names))
            self.assertTrue(any(name.endswith(".md") for name in names))

        bulk_ids = [image["id"], note["id"]]
        for index in range(20):
            response = self.client.post(
                "/api/materials/notes",
                json={
                    "title": f"批量素材 {index}",
                    "content_md": f"批量下载测试内容 {index}",
                },
            )
            self.assertEqual(response.status_code, 201)
            bulk_ids.append(response.json()["id"])
        bulk_archive = self.client.post(
            "/api/materials/download",
            json={"ids": bulk_ids},
        )
        self.assertEqual(bulk_archive.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(bulk_archive.content)) as bundle:
            self.assertEqual(len(bundle.namelist()), len(bulk_ids) + 1)

        image_path = Path(image["path"])
        deleted = self.client.delete(f"/api/materials/{image['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(image_path.exists())

    def test_storyboard_generation_receives_selected_material_context(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        note = self.client.post(
            "/api/materials/notes",
            json={
                "title": "产品事实",
                "content_md": "只允许使用本地部署和批量发布两个卖点",
                "tags": ["产品"],
            },
        ).json()
        storyboard = {
            "title": "素材驱动分镜",
            "summary": "摘要",
            "caption_md": "发布文案",
            "tags": ["产品"],
            "visual_style": {},
            "pages": [
                {
                    "index": 0,
                    "role": "cover",
                    "headline": "本地内容工作台",
                    "body": "",
                    "visual": "桌面工作场景",
                    "layout": "标题居中",
                }
            ],
        }
        with patch(
            "backend.services.AIContentService.generate_image_storyboard",
            return_value=storyboard,
        ) as generate:
            response = self.client.post(
                "/api/articles/generate-storyboard",
                json={
                    "topic": "产品介绍",
                    "article_type": "image",
                    "image_count": 1,
                    "material_ids": [note["id"]],
                },
            )

        self.assertEqual(response.status_code, 200)
        specification = generate.call_args.args[0]
        self.assertEqual(specification["material_ids"], [note["id"]])
        self.assertIn("本地部署和批量发布", specification["materials"])

    def test_article_list_filters_content_type(self):
        for title, article_type in [
            ("长文章", "article"),
            ("图文稿", "image"),
            ("视频稿", "video"),
        ]:
            response = self.client.post(
                "/api/articles",
                json={"title": title, "article_type": article_type},
            )
            self.assertEqual(response.status_code, 201)

        response = self.client.get(
            "/api/articles",
            params={"article_type": "image"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(item["title"], item["article_type"]) for item in response.json()],
            [("图文稿", "image")],
        )
    def test_generate_image_storyboard_returns_editable_pages(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        storyboard = {
            "title": "分镜标题",
            "summary": "分镜摘要",
            "caption_md": "发布文案",
            "tags": ["图文"],
            "visual_style": {
                "direction": "编辑设计",
                "palette": ["#ffffff", "#111111", "#d9483b"],
                "typography": "清晰中文黑体",
                "graphics": "扁平图形",
                "composition": "统一网格",
            },
            "pages": [
                {
                    "index": 0,
                    "role": "cover",
                    "headline": "封面",
                    "body": "",
                    "visual": "明确主体",
                    "layout": "居中标题",
                },
                {
                    "index": 1,
                    "role": "content",
                    "headline": "重点",
                    "body": "简短正文",
                    "visual": "信息图",
                    "layout": "上下结构",
                },
            ],
        }
        with patch(
            "backend.services.AIContentService.generate_image_storyboard",
            return_value=storyboard,
        ) as generate:
            response = self.client.post(
                "/api/articles/generate-storyboard",
                json={
                    "topic": "两页图文",
                    "article_type": "image",
                    "image_count": 2,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pages"][0]["role"], "cover")
        self.assertEqual(response.json()["pages"][1]["headline"], "重点")
        self.assertEqual(generate.call_args.args[0]["image_count"], 2)

    def test_generate_image_article_uses_reviewed_storyboard(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        image_dir = backend.media.MEDIA_DIR / "ai"
        image_dir.mkdir(parents=True)
        cover = image_dir / "story-cover.png"
        cover.write_bytes(b"\x89PNG\r\n\x1a\nstory-cover")
        storyboard = {
            "title": "确认后的标题",
            "summary": "确认后的摘要",
            "caption_md": "确认后的发布文案",
            "tags": ["分镜"],
            "visual_style": {
                "direction": "编辑设计",
                "palette": ["#ffffff", "#111111"],
                "typography": "清晰中文黑体",
                "graphics": "信息图",
                "composition": "统一网格",
            },
            "pages": [
                {
                    "index": 0,
                    "role": "cover",
                    "headline": "确认后的封面",
                    "body": "",
                    "visual": "明确主体",
                    "layout": "居中标题",
                },
            ],
        }

        def generated_images(plans):
            self.assertEqual(len(plans), 1)
            self.assertIn("全套统一视觉规范", plans[0]["prompt"])
            self.assertEqual(plans[0]["content_kind"], "image_post")
            self.assertIn("不是给文章配一张装饰插图", plans[0]["prompt"])
            self.assertIn("信息表达优先", plans[0]["prompt"])
            return [{**plans[0], "path": str(cover.resolve())}]

        with (
            patch(
                "backend.services.AIContentService.generate_article",
            ) as generate_article,
            patch(
                "backend.services.AIImageService.generate_images",
                side_effect=generated_images,
            ),
        ):
            response = self.client.post(
                "/api/articles/generate",
                json={
                    "topic": "已确认的图文",
                    "article_type": "image",
                    "word_count": 700,
                    "image_count": 1,
                    "storyboard": storyboard,
                },
            )

        self.assertEqual(response.status_code, 201)
        article = response.json()
        self.assertEqual(article["title"], "确认后的标题")
        self.assertEqual(article["ai_result"]["storyboard"]["pages"][0]["headline"], "确认后的封面")
        self.assertIn("确认后的发布文案", article["content_md"])
        generate_article.assert_not_called()

    def test_regenerate_ai_image_replaces_saved_references(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        image_dir = backend.media.MEDIA_DIR / "ai"
        image_dir.mkdir(parents=True)
        old_image = image_dir / "old.png"
        new_image = image_dir / "new.png"
        old_image.write_bytes(b"\x89PNG\r\n\x1a\nold")
        new_image.write_bytes(b"\x89PNG\r\n\x1a\nnew")
        old_source = old_image.resolve().as_posix()
        article = self.client.post(
            "/api/articles",
            json={
                "title": "可重绘图文",
                "article_type": "image",
                "content_md": f"![封面]({old_source})",
                "cover_url": str(old_image.resolve()),
                "media_paths": [str(old_image.resolve())],
            },
        ).json()
        ai_result = {
            "source": "generated",
            "image_plan": [
                {
                    "position": "image:1",
                    "alt": "封面",
                    "purpose": "cover",
                    "prompt": "保持统一风格的封面",
                }
            ],
            "generated_images": [
                {
                    "position": "image:1",
                    "alt": "封面",
                    "purpose": "cover",
                    "prompt": "保持统一风格的封面",
                    "path": str(old_image.resolve()),
                }
            ],
        }
        self.client.patch(
            f"/api/articles/{article['id']}",
            json={"ai_result": ai_result},
        )
        replacement = {
            **ai_result["image_plan"][0],
            "path": str(new_image.resolve()),
        }
        with (
            patch(
                "backend.services.AIImageService.generate_images",
                return_value=[replacement],
            ),
            patch("backend.services.MEDIA_DIR", backend.media.MEDIA_DIR),
        ):
            response = self.client.post(
                f"/api/articles/{article['id']}/images/0/regenerate"
            )

        self.assertEqual(response.status_code, 200)
        updated = response.json()
        self.assertEqual(updated["cover_url"], str(new_image.resolve()))
        self.assertEqual(updated["media_paths"], [str(new_image.resolve())])
        self.assertIn(new_image.resolve().as_posix(), updated["content_md"])
        self.assertFalse(old_image.exists())

    def test_article_first_image_is_prepared_as_wechat_cover(self):
        from backend.services import _prepare_generated_article_images

        generated = {
            "title": "AI 中转站安全选择指南",
            "cover_title": "安全选择AI渠道",
            "summary": "比较低价渠道背后的账号和数据风险。",
            "content_md": """## 先看风险

<!-- image:1 -->

## 再做选择

<!-- image:2 -->""",
            "tags": ["AI", "账号安全"],
            "image_plan": [
                {
                    "position": "image:1",
                    "alt": "低价渠道",
                    "prompt": "一张关于低价 AI 渠道的普通配图",
                    "purpose": "说明价格差异",
                },
                {
                    "position": "image:2",
                    "alt": "核对清单",
                    "prompt": "用户核对服务条款",
                    "purpose": "正文配图",
                },
            ],
        }

        prepared = _prepare_generated_article_images(generated, "article")

        cover = prepared["image_plan"][0]
        self.assertEqual(cover["position"], "cover")
        self.assertEqual(cover["content_kind"], "wechat_cover")
        self.assertIn("900×383", cover["prompt"])
        self.assertIn("低价 AI 渠道", cover["prompt"])
        self.assertIn("安全选择AI渠道", cover["prompt"])
        self.assertEqual(cover["cover_text"], "安全选择AI渠道")
        self.assertNotIn("<!-- image:1 -->", prepared["content_md"])
        self.assertIn("<!-- image:2 -->", prepared["content_md"])
        self.assertEqual(prepared["image_plan"][1], generated["image_plan"][1])

    def test_ai_image_service_normalizes_wechat_cover(self):
        from io import BytesIO

        from PIL import Image

        from backend.ai_generation import AIImageService

        source = BytesIO()
        Image.new("RGB", (1200, 800), "#2f6f5e").save(source, format="PNG")
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": [{
                "b64_json": base64.b64encode(source.getvalue()).decode("ascii")
            }],
        }
        service = AIImageService(
            {
                "ai_image_base_url": "",
                "ai_base_url": "https://example.test/v1",
                "ai_image_api_key": "",
                "ai_api_key": "secret",
                "ai_image_model": "image-model",
                "ai_image_size": "1024x1024",
                "ai_image_post_size": "1024x1536",
                "ai_cover_image_size": "1536x1024",
                "ai_proxy_url": "",
            }
        )

        with patch.object(
            service.session,
            "post",
            return_value=response,
        ) as post:
            generated = service.generate_images(
                [{
                    "position": "cover",
                    "alt": "公众号封面",
                    "prompt": "中央主体的公众号横向封面",
                    "content_kind": "wechat_cover",
                }]
            )[0]

        self.assertEqual(post.call_args.kwargs["json"]["size"], "1536x1024")
        self.assertEqual((generated["width"], generated["height"]), (900, 383))
        path = Path(generated["path"])
        with Image.open(path) as image:
            self.assertEqual(image.size, (900, 383))
    def test_ai_image_service_writes_valid_base64_image(self):
        from backend.ai_generation import AIImageService

        png = b"\x89PNG\r\n\x1a\n" + b"test-image"
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": [{"b64_json": base64.b64encode(png).decode("ascii")}],
        }
        service = AIImageService(
            {
                "ai_image_base_url": "",
                "ai_base_url": "https://example.test/v1",
                "ai_image_api_key": "",
                "ai_api_key": "secret",
                "ai_image_model": "image-model",
                "ai_image_size": "1024x1024",
                "ai_image_post_size": "1024x1536",
                "ai_proxy_url": "",
            }
        )
        with patch.object(
            service.session,
            "post",
            return_value=response,
        ) as post:
            images = service.generate_images(
                [{"position": "image:1", "alt": "测试图", "prompt": "一张测试图"}]
            )
            service.generate_images(
                [{
                    "position": "image:1",
                    "alt": "图文卡片",
                    "prompt": "一张图文信息卡",
                    "content_kind": "image_post",
                }]

            )

        self.assertEqual(post.call_args_list[0].kwargs["json"]["size"], "1024x1024")
        self.assertEqual(post.call_args_list[1].kwargs["json"]["size"], "1024x1536")

        path = Path(images[0]["path"])
        self.assertEqual(path.parent, (backend.media.MEDIA_DIR / "ai").resolve())
        self.assertEqual(path.read_bytes(), png)

    def test_media_preview_only_serves_images_under_media_root(self):
        image = backend.media.MEDIA_DIR / "ai" / "preview.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"\x89PNG\r\n\x1a\npreview")
        outside = Path(self.temp_dir.name) / "outside.png"
        outside.write_bytes(b"\x89PNG\r\n\x1a\noutside")

        response = self.client.get("/api/media/file", params={"path": str(image)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, image.read_bytes())

        response = self.client.get("/api/media/file", params={"path": str(outside)})
        self.assertEqual(response.status_code, 400)

        missing = backend.media.MEDIA_DIR / "missing.png"
        response = self.client.get("/api/media/file", params={"path": str(missing)})
        self.assertEqual(response.status_code, 404)

    def test_generate_article_validates_enabled_and_image_count(self):
        disabled = self.client.post(
            "/api/articles/generate",
            json={"topic": "未启用 AI", "article_type": "article"},
        )
        self.assertEqual(disabled.status_code, 400)
        self.assertIn("尚未启用", disabled.json()["detail"])

        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        invalid = self.client.post(
            "/api/articles/generate",
            json={
                "topic": "图文必须有图",
                "article_type": "image",
                "image_count": 0,
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("至少需要生成 1 张图片", invalid.json()["detail"])

    def test_rss_scheduler_runs_only_when_interval_is_due(self):
        from backend.scheduler import AutomationScheduler

        scheduled = AutomationScheduler()
        settings = {
            "notion_sync_enabled": False,
            "rss_enabled": True,
            "rss_scan_interval_minutes": 60,
            "auto_publish_enabled": False,
        }
        with (
            patch("backend.scheduler.get_settings", return_value=settings),
            patch(
                "backend.scheduler.scan_rss_feeds",
                return_value={"created": 1},
            ) as scan,
        ):
            asyncio.run(scheduled._tick())
            asyncio.run(scheduled._tick())

        scan.assert_called_once_with()
        self.assertIsNotNone(scheduled.last_rss_scan_at)
        self.assertIsNotNone(
            scheduled.status()["last_rss_scan_at"]
        )
    def test_rss_scan_imports_rss_and_atom_entries_incrementally(self):
        rss_url = "https://feeds.example.com/daily.xml"
        atom_url = "https://feeds.example.com/atom.xml"
        rss_payload = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>AI 每日资讯</title>
    <item>
      <title>模型发布新版本</title>
      <link>https://example.com/news/model-v2</link>
      <description><![CDATA[新版本提升了推理效率。]]></description>
      <content:encoded><![CDATA[<p>新版本提升了推理效率。</p><p>详细指标待核实。</p>]]></content:encoded>
      <dc:creator>编辑部</dc:creator>
      <pubDate>Sun, 27 Jul 2026 08:00:00 GMT</pubDate>
      <category>AI</category>
    </item>
  </channel>
</rss>""".encode()
        atom_payload = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>效率工具更新</title>
  <entry>
    <title>应用新增自动整理能力</title>
    <link rel="alternate" href="https://example.com/news/app-update" />
    <summary type="html">&lt;p&gt;应用上线了新的整理能力。&lt;/p&gt;</summary>
    <content type="html">&lt;p&gt;应用上线了新的整理能力。&lt;/p&gt;</content>
    <published>2026-07-27T09:30:00+08:00</published>
    <author><name>产品团队</name></author>
    <category term="效率工具" />
  </entry>
</feed>""".encode()
        settings_response = self.client.put(
            "/api/settings",
            json={
                "values": {
                    "rss_feed_urls": [rss_url, atom_url, rss_url],
                    "rss_enabled": True,
                    "rss_scan_interval_minutes": 30,
                }
            },
        )
        self.assertEqual(settings_response.status_code, 200)
        self.assertEqual(
            settings_response.json()["values"]["rss_feed_urls"],
            [rss_url, atom_url],
        )

        def feed_response(url):
            if "daily" in url:
                return rss_payload, rss_url
            return atom_payload, atom_url

        with patch("backend.rss._fetch_feed", side_effect=feed_response):
            first = self.client.post("/api/rss/scan")
            second = self.client.post("/api/rss/scan")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["created"], 2)
        self.assertEqual(first.json()["existing"], 0)
        self.assertEqual(second.json()["created"], 0)
        self.assertEqual(second.json()["existing"], 2)

        listing = self.client.get("/api/news").json()
        self.assertEqual(listing["counts"]["all"], 2)
        by_title = {item["title"]: item for item in listing["items"]}
        self.assertEqual(
            by_title["模型发布新版本"]["source_name"],
            "AI 每日资讯",
        )
        self.assertIn("详细指标待核实", by_title["模型发布新版本"]["content_md"])
        self.assertEqual(by_title["模型发布新版本"]["author"], "编辑部")
        self.assertEqual(
            by_title["应用新增自动整理能力"]["tags"],
            ["效率工具"],
        )
        health = self.client.get("/api/health").json()
        self.assertIsNotNone(health["scheduler"]["last_rss_scan_at"])

    def test_rss_scan_keeps_other_feeds_when_one_fails(self):
        good_url = "https://feeds.example.com/good.xml"
        bad_url = "https://feeds.example.com/bad.xml"
        payload = """<rss version="2.0"><channel><title>可用订阅</title>
<item><title>一条资讯</title><link>https://example.com/news/available</link>
<description>正文</description></item></channel></rss>""".encode()

        def feed_response(url):
            if "bad" in url:
                raise RuntimeError("订阅源暂时不可用")
            return payload, good_url

        with patch("backend.rss._fetch_feed", side_effect=feed_response):

            self.client.put(
                "/api/settings",
                json={"values": {"rss_feed_urls": [
                    "not-a-feed", bad_url, good_url
                ]}},
            )
            response = self.client.post("/api/rss/scan")

        result = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["created"], 1)
        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual(result["errors"][0]["url"], "not-a-feed")
        self.assertEqual(result["errors"][1]["url"], bad_url)
        self.assertEqual(
            self.client.get("/api/news").json()["counts"]["all"],
            1,
        )
    def test_news_library_crud_and_duplicate_url(self):
        created = self.client.post(
            "/api/news",
            json={
                "title": "行业更新",
                "source_name": "示例资讯",
                "source_url": "https://example.com/news/1#section",
                "summary": "一条可供 AI 参考的外部资讯。",
                "content_md": "正文事实与背景。",
                "tags": ["行业", "趋势"],
                "published_at": "2026-07-26T10:00",
            },
        )
        self.assertEqual(created.status_code, 201)
        item = created.json()
        self.assertEqual(item["source_url"], "https://example.com/news/1")
        self.assertEqual(item["tags"], ["行业", "趋势"])

        listing = self.client.get("/api/news", params={"q": "外部资讯"})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([row["id"] for row in listing.json()["items"]], [item["id"]])
        self.assertEqual(listing.json()["counts"], {"all": 1, "sources": 1})

        updated = self.client.patch(
            f"/api/news/{item['id']}",
            json={"summary": "已经人工校正的摘要", "author": "编辑部"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["author"], "编辑部")

        duplicate = self.client.post(
            "/api/news",
            json={
                "title": "重复资讯",
                "source_url": "https://example.com/news/1",
            },
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("已经采集", duplicate.json()["detail"])

        deleted = self.client.delete(f"/api/news/{item['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/news").json()["items"], [])

    def test_news_collect_extracts_public_web_page(self):
        html = """
        <html>
          <head>
            <title>普通标题</title>
            <meta property="og:title" content="采集标题">
            <meta property="og:site_name" content="示例站点">
            <meta name="description" content="采集摘要">
            <meta name="author" content="资讯作者">
            <meta property="article:published_time" content="2026-07-25T08:00:00+08:00">
          </head>
          <body>
            <nav>导航内容</nav>
            <article>
              <h1>采集标题</h1>
              <p>第一段有效正文，包含重要事实。</p>
              <p>第二段有效正文，提供更多背景。</p>
            </article>
          </body>
        </html>
        """
        response = Mock(
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=html.encode("utf-8"),
            encoding="utf-8",
        )
        response.raise_for_status.return_value = None
        with (
            patch("backend.news._validate_public_host"),
            patch("backend.news.requests.Session") as client_factory,
        ):
            client_factory.return_value.__enter__.return_value.get.return_value = response
            collected = self.client.post(
                "/api/news/collect",
                json={"url": "https://example.com/story"},
            )

        self.assertEqual(collected.status_code, 201)
        item = collected.json()
        self.assertEqual(item["title"], "采集标题")
        self.assertEqual(item["source_name"], "示例站点")
        self.assertEqual(item["author"], "资讯作者")
        self.assertIn("第一段有效正文", item["content_md"])
        self.assertNotIn("导航内容", item["content_md"])

    def test_generate_article_receives_and_links_news_context(self):
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        news = self.client.post(
            "/api/news",
            json={
                "title": "公开资料",
                "source_name": "官方站点",
                "source_url": "https://example.com/reference",
                "summary": "明确事实：产品于七月更新。",
                "content_md": "更新包含资讯引用能力。",
                "published_at": "2026-07-20",
            },
        ).json()
        generated = {
            "title": "资讯参考稿",
            "summary": "摘要",
            "content_md": "正文",
            "tags": ["资讯"],
            "image_plan": [],
        }
        with (
            patch(
                "backend.services.AIContentService.generate_article",
                return_value=generated,
            ) as generate,
            patch(
                "backend.services.AIImageService.generate_images",
                return_value=[],
            ),
        ):
            response = self.client.post(
                "/api/articles/generate",
                json={
                    "topic": "资讯引用测试",
                    "article_type": "article",
                    "word_count": 800,
                    "image_count": 0,
                    "news_ids": [news["id"]],
                },
            )

        self.assertEqual(response.status_code, 201)
        article = response.json()
        specification = generate.call_args.args[0]
        self.assertEqual(specification["news_ids"], [news["id"]])
        self.assertIn("产品于七月更新", specification["news"])
        self.assertIn("https://example.com/reference", specification["news"])
        self.assertEqual(article["ai_result"]["news_ids"], [news["id"]])
        with backend.db.connection() as conn:
            linked = conn.execute(
                "SELECT news_id FROM article_news WHERE article_id = ?",
                (article["id"],),
            ).fetchall()
        self.assertEqual([row["news_id"] for row in linked], [news["id"]])

    def test_delete_article_cascades_records_and_keeps_shared_ai_media(self):
        media_root = Path(self.temp_dir.name) / "media"
        ai_root = media_root / "ai"
        ai_root.mkdir(parents=True)
        exclusive = ai_root / "exclusive.png"
        shared = ai_root / "shared.png"
        exclusive.write_bytes(b"exclusive")
        shared.write_bytes(b"shared")
        with patch.object(backend.services, "MEDIA_DIR", media_root):
            first = self.client.post(
                "/api/articles",
                json={
                    "title": "待删除稿件",
                    "media_paths": [str(exclusive), str(shared)],
                    "cover_url": str(exclusive),
                },
            ).json()
            second = self.client.post(
                "/api/articles",
                json={
                    "title": "保留稿件",
                    "media_paths": [str(shared)],
                    "cover_url": str(shared),
                },
            ).json()
            with backend.db.connection() as conn:
                conn.execute(
                    "INSERT INTO publish_records "
                    "(article_id, platform, action, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (first["id"], "wechat", "draft", "success", backend.db.utc_now()),
                )

            response = self.client.delete(f"/api/articles/{first['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertEqual(response.json()["cleanup_warning"], "")
        self.assertFalse(exclusive.exists())
        self.assertTrue(shared.exists())
        self.assertEqual(
            self.client.get(f"/api/articles/{first['id']}").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/api/articles/{second['id']}").status_code,
            200,
        )
        with backend.db.connection() as conn:
            record_count = conn.execute(
                "SELECT COUNT(*) FROM publish_records WHERE article_id = ?",
                (first["id"],),
            ).fetchone()[0]
        self.assertEqual(record_count, 0)
        missing = self.client.delete(f"/api/articles/{first['id']}")
        self.assertEqual(missing.status_code, 404)

    def test_delete_account_cleans_private_state_and_article_selection(self):
        profile_root = Path(self.temp_dir.name) / "browser_profiles"
        with patch.object(backend.accounts, "PROFILE_ROOT", profile_root):
            account = self.client.post(
                "/api/accounts",
                json={"platform": "wechat", "name": "待删除公众号"},
            ).json()
            other = self.client.post(
                "/api/accounts",
                json={"platform": "wechat", "name": "保留公众号"},
            ).json()
            self.client.put(
                f"/api/accounts/{account['id']}/wechat",
                json={
                    "publish_method": "api",
                    "app_id": "wx-delete",
                    "app_secret": "delete-secret",
                },
            )
            profile_dir = Path(account["profile_dir"])
            profile_dir.mkdir(parents=True)
            (profile_dir / "Cookies").write_text("session", encoding="utf-8")
            avatar = backend.accounts.account_avatar_path(account)
            avatar.parent.mkdir(parents=True)
            avatar.write_bytes(b"avatar")
            article = self.client.post(
                "/api/articles",
                json={
                    "title": "账号引用清理",
                    "platform_accounts": {"wechat": account["id"]},
                },
            ).json()
            with backend.db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO article_platform_states (
                        article_id, platform, action, account_id, status,
                        attempts, created_at, updated_at
                    ) VALUES (?, 'wechat', 'draft', ?, 'drafted', 1, ?, ?)
                    """,
                    (
                        article["id"],
                        account["id"],
                        backend.db.utc_now(),
                        backend.db.utc_now(),
                    ),
                )

            response = self.client.delete(f"/api/accounts/{account['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertEqual(response.json()["cleanup_warning"], "")
        self.assertFalse(profile_dir.exists())
        self.assertFalse(avatar.exists())
        remaining = self.client.get("/api/accounts?platform=wechat").json()
        self.assertEqual([item["id"] for item in remaining], [other["id"]])
        refreshed = self.client.get(f"/api/articles/{article['id']}").json()
        self.assertNotIn("wechat", refreshed["platform_accounts"])
        with backend.db.connection() as conn:
            settings_count = conn.execute(
                "SELECT COUNT(*) FROM wechat_account_settings WHERE account_id = ?",
                (account["id"],),
            ).fetchone()[0]
            state_count = conn.execute(
                "SELECT COUNT(*) FROM article_platform_states WHERE account_id = ?",
                (account["id"],),
            ).fetchone()[0]
        self.assertEqual(settings_count, 0)
        self.assertEqual(state_count, 0)
        missing = self.client.delete(f"/api/accounts/{account['id']}")
        self.assertEqual(missing.status_code, 404)

    def test_wechat_account_api_settings_are_account_scoped_and_masked(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "wechat-api"},
        ).json()
        response = self.client.put(
            f"/api/accounts/{account['id']}/wechat",
            json={
                "publish_method": "api",
                "app_id": "wx-test-app",
                "app_secret": "secret-value",
            },
        )

        self.assertEqual(response.status_code, 200)
        config = response.json()["wechat"]
        self.assertEqual(config["publish_method"], "api")
        self.assertEqual(config["app_id"], "wx-test-app")
        self.assertTrue(config["app_secret_configured"])
        self.assertNotIn("app_secret_encrypted", response.json())
        credentials = backend.accounts.get_wechat_api_credentials(account["id"])
        self.assertEqual(credentials["app_secret"], "secret-value")
        with backend.db.connection() as conn:
            encrypted = conn.execute(
                "SELECT app_secret_encrypted FROM wechat_account_settings "
                "WHERE account_id = ?",
                (account["id"],),
            ).fetchone()[0]
        self.assertNotEqual(encrypted, "secret-value")

    def test_wechat_api_route_defaults_to_official_endpoint(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "wechat-direct"},
        ).json()

        self.assertEqual(account["wechat"]["api_connection_mode"], "direct")
        self.assertEqual(
            account["wechat"]["api_base_url"],
            "http://127.0.0.1:8701/wechat",
        )
        response = self.client.put(
            f"/api/accounts/{account['id']}/wechat",
            json={
                "publish_method": "api",
                "app_id": "wx-direct",
                "app_secret": "secret-value",
            },
        )
        self.assertEqual(response.status_code, 200)
        credentials = backend.accounts.get_wechat_api_credentials(account["id"])
        self.assertEqual(credentials["api_connection_mode"], "direct")
        self.assertEqual(
            credentials["base_api"],
            "https://api.weixin.qq.com/cgi-bin/",
        )

    def test_wechat_nginx_route_is_account_scoped(self):
        nginx_account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "wechat-nginx"},
        ).json()
        direct_account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "wechat-official"},
        ).json()
        response = self.client.put(
            f"/api/accounts/{nginx_account['id']}/wechat",
            json={
                "publish_method": "api",
                "api_connection_mode": "nginx",
                "api_base_url": "https://relay.example.com:8701/wechat/",
                "app_id": "wx-nginx",
                "app_secret": "secret-value",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["wechat"]["api_base_url"],
            "https://relay.example.com:8701/wechat",
        )
        credentials = backend.accounts.get_wechat_api_credentials(
            nginx_account["id"]
        )
        self.assertEqual(credentials["api_connection_mode"], "nginx")
        self.assertEqual(
            credentials["base_api"],
            "https://relay.example.com:8701/wechat/cgi-bin/",
        )
        refreshed_direct = self.client.get(
            f"/api/accounts?platform=wechat"
        ).json()
        direct_config = next(
            item["wechat"]
            for item in refreshed_direct
            if item["id"] == direct_account["id"]
        )
        self.assertEqual(direct_config["api_connection_mode"], "direct")

    def test_wechat_api_route_rejects_invalid_mode_and_urls(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "wechat-invalid-route"},
        ).json()
        invalid_values = [
            ("nginx", "ftp://relay.example.com/wechat"),
            ("nginx", "http://user:pass@relay.example.com/wechat"),
            ("nginx", "http://relay.example.com/wechat?token=secret"),
            ("nginx", "http://relay.example.com/wechat#fragment"),
            ("nginx", "http://relay.example.com:bad/wechat"),
            ("other", "http://relay.example.com/wechat"),
        ]
        for mode, url in invalid_values:
            with self.subTest(mode=mode, url=url):
                response = self.client.put(
                    f"/api/accounts/{account['id']}/wechat",
                    json={
                        "publish_method": "api",
                        "api_connection_mode": mode,
                        "api_base_url": url,
                    },
                )
                self.assertEqual(response.status_code, 400)

    def test_wechat_client_builds_direct_and_nginx_urls(self):
        from publish_gzh import WechatOfficialAccountPublisher

        direct = WechatOfficialAccountPublisher("app", "secret")
        nginx = WechatOfficialAccountPublisher(
            "app",
            "secret",
            base_api="http://127.0.0.1:8701/wechat/cgi-bin/",
        )

        self.assertEqual(
            direct._build_url("token"),
            "https://api.weixin.qq.com/cgi-bin/token",
        )
        self.assertEqual(
            nginx._build_url("material/add_material"),
            "http://127.0.0.1:8701/wechat/cgi-bin/material/add_material",
        )

    def test_wechat_settings_migration_adds_api_route_columns(self):
        legacy_db = Path(self.temp_dir.name) / "legacy-wechat-settings.db"
        with sqlite3.connect(legacy_db) as conn:
            conn.execute(
                """
                CREATE TABLE wechat_account_settings (
                    account_id INTEGER PRIMARY KEY,
                    publish_method TEXT NOT NULL DEFAULT 'browser',
                    app_id TEXT NOT NULL DEFAULT '',
                    app_secret_encrypted TEXT NOT NULL DEFAULT '',
                    api_status TEXT NOT NULL DEFAULT 'pending',
                    api_capabilities_json TEXT NOT NULL DEFAULT '{}',
                    api_last_error TEXT NOT NULL DEFAULT '',
                    api_last_checked_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

        with patch.object(backend.db, "DB_PATH", legacy_db):
            backend.db.init_db()
            with backend.db.connection() as conn:
                columns = {
                    row["name"]: row
                    for row in conn.execute(
                        "PRAGMA table_info(wechat_account_settings)"
                    ).fetchall()
                }

        self.assertIn("api_connection_mode", columns)
        self.assertIn("api_base_url", columns)
        self.assertEqual(columns["api_connection_mode"]["dflt_value"], "'direct'")
        self.assertEqual(
            columns["api_base_url"]["dflt_value"],
            "'http://127.0.0.1:8701/wechat'",
        )

    def test_wechat_api_test_records_independent_capabilities(self):
        account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "wechat-capabilities"},
        ).json()
        self.client.put(
            f"/api/accounts/{account['id']}/wechat",
            json={
                "publish_method": "api",
                "app_id": "wx-test-app",
                "app_secret": "secret-value",
            },
        )
        client = Mock()
        client._get_access_token.return_value = "token"
        client._request_with_retry.side_effect = [{}, {}]
        with patch(
            "backend.platforms.wechat.WechatApiPublisher._client",
            return_value=client,
        ):
            response = self.client.post(
                f"/api/accounts/{account['id']}/wechat/test"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["capabilities"],
            {"credentials": True, "draft": True, "publish": True},
        )
        refreshed = self.client.get("/api/accounts?platform=wechat").json()[0]
        self.assertEqual(refreshed["wechat"]["api_status"], "valid")

    def test_wechat_dispatcher_allows_api_only_account(self):
        from backend.platforms.wechat import WechatApiPublisher, WechatPublisher

        account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "api-only"},
        ).json()
        self.client.put(
            f"/api/accounts/{account['id']}/wechat",
            json={
                "publish_method": "api",
                "app_id": "wx-test-app",
                "app_secret": "secret-value",
            },
        )
        article = {
            "platform_accounts": {"wechat": account["id"]},
            "title": "test",
        }
        with patch.object(
            WechatApiPublisher,
            "publish",
            return_value={"status": "drafted", "external_id": "draft-id"},
        ) as publish:
            output = WechatPublisher({"wechat_enabled": True}).publish(
                article,
                "draft",
            )
        self.assertEqual(output["external_id"], "draft-id")
        publish.assert_called_once()

    def test_wechat_dispatcher_rejects_direct_publish_without_api_permission(self):
        from backend.platforms.wechat import WechatApiPublisher, WechatPublisher

        account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "draft-only-api"},
        ).json()
        self.client.put(
            f"/api/accounts/{account['id']}/wechat",
            json={
                "publish_method": "api",
                "app_id": "wx-test-app",
                "app_secret": "secret-value",
            },
        )
        backend.accounts.update_wechat_api_status(
            account["id"],
            "valid",
            {"credentials": True, "draft": True, "publish": False},
        )
        article = {
            "platform_accounts": {"wechat": account["id"]},
            "title": "test",
        }

        with (
            patch.object(WechatApiPublisher, "publish") as publish,
            self.assertRaisesRegex(ValueError, "没有直接发布权限"),
        ):
            WechatPublisher({"wechat_enabled": True}).publish(
                article,
                "publish",
            )
        publish.assert_not_called()

    def test_ai_image_modes_resolve_automatic_counts(self):
        from backend.services import resolve_ai_image_count

        self.assertEqual(resolve_ai_image_count("article", "auto", 1200), 2)
        self.assertEqual(resolve_ai_image_count("image", "auto", 700), 5)
        self.assertEqual(resolve_ai_image_count("article", "cover", 3000), 1)
        self.assertEqual(resolve_ai_image_count("article", "none", 3000), 0)
        with self.assertRaises(ValueError):
            resolve_ai_image_count("image", "none", 700)

    def test_wechat_api_publish_waits_until_async_job_succeeds(self):
        from publish_gzh import WechatArticlePublisher

        client = Mock()
        client._get_access_token.return_value = "token"
        client._request_with_retry.side_effect = [
            {"publish_status": 1},
            {"publish_status": 0, "article_id": "article-id"},
        ]
        publisher = WechatArticlePublisher(client)
        with patch("publish_gzh.time.sleep") as sleep:
            article_id = publisher.wait_for_publish_result(
                "publish-id",
                timeout_seconds=10,
                interval_seconds=0.01,
            )

        self.assertEqual(article_id, "article-id")
        self.assertEqual(client._request_with_retry.call_count, 2)
        sleep.assert_called_once_with(0.01)

    @staticmethod
    def _notion_article(source_key, page_id, title):
        return {
            "source_key": source_key,
            "notion_page_id": page_id,
            "notion_url": f"https://notion.so/{page_id}",
            "title": title,
            "author": "",
            "article_type": "article",
            "content_md": "正文",
            "cover_url": "",
            "source_url": "",
            "tags": [],
        }


if __name__ == "__main__":
    unittest.main()
