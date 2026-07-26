import base64
import io
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
from backend.logging_config import redact_text, redact_url
from backend.notion_client import NotionClient, page_metadata
from backend.platforms.bilibili import BilibiliPublisher
from backend.platforms.channels import (
    ChannelsPublisher,
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
    def test_wechat_account_browser_opens_saved_dashboard(self):
        from backend.platforms.wechat_browser import _save_session_url

        account = self.client.post(
            "/api/accounts",
            json={"platform": "wechat", "name": "公众号主账号"},
        ).json()
        dashboard_url = (
            "https://mp.weixin.qq.com/cgi-bin/home?"
            "t=home/index&lang=zh_CN&token=123456"
        )
        _save_session_url(account, dashboard_url)
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

    def test_csdn_login_check_accepts_visible_profile_card(self):
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
                return Locator()

            def locator(self, selector):
                return Locator(
                    count=1 if selector == ".home-exp-user-card" else 0,
                    visible=selector == ".home-exp-user-card",
                )

        self.assertTrue(_is_logged_in(Page()))

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
        selected = Mock()
        selected.first = selected
        selected.count.side_effect = [0, 1]
        selected.is_visible.return_value = True
        cover = Mock()
        cover.first = cover
        from_content = Mock()
        from_content.first = from_content
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
        button_locators = {
            "下一步": visible_locator(next_button),
            "确认": visible_locator(confirm_button),
        }

        def page_locator(selector):
            return {
                ".js_share_type_image": selected,
                ".js_cover_btn_area": cover,
                "a.js_selectCoverFromContent": from_content,
                ".card_mask_global.apmsg_content_img_mask": image_locator,
            }[selector]

        page.locator.side_effect = page_locator
        page.get_by_role.side_effect = (
            lambda role, name, exact: button_locators[name]
        )

        _select_wechat_cover(page)

        cover.click.assert_called_once_with()
        from_content.click.assert_called_once_with()
        image.click.assert_called_once_with()
        next_button.click.assert_called_once_with()
        confirm_button.click.assert_called_once_with()
    def test_wechat_publish_uses_v2_editor_and_waits_after_save(self):
        from contextlib import nullcontext

        from backend.platforms.wechat_browser import WechatPublisher

        page = Mock()
        article = {
            "title": "公众号草稿",
            "author": "作者",
            "content_md": "正文",
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
                return_value=1,
            ) as upload_images,
            patch(
                "backend.platforms.wechat_browser._select_wechat_cover"
            ) as select_cover,
            patch(
                "backend.platforms.wechat_browser._save_wechat_draft",
                return_value=saved_url,
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
        save_draft.assert_called_once_with(page)
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
            {"platform_user_id": "demo_account"},
        )
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

    def test_csdn_publish_retries_when_editor_is_still_saving(self):
        from backend.platforms.csdn import _publish_blog

        page = Mock()
        submit = Mock()
        page.get_by_role.return_value.first = submit
        with (
            patch("backend.platforms.csdn._wait_for_editor_ready") as wait_ready,
            patch(
                "backend.platforms.csdn._wait_for_publish_success",
                side_effect=[
                    RuntimeError("CSDN 发布失败：文章正在保存，请耐心等待。"),
                    None,
                ],
            ) as wait_success,
        ):
            _publish_blog(page)

        self.assertEqual(wait_ready.call_count, 2)
        self.assertEqual(submit.click.call_count, 2)
        self.assertEqual(wait_success.call_count, 2)
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

    def test_platform_action_can_save_a_draft(self):
        article = self.client.post(
            "/api/articles",
            json={"title": "草稿测试", "content_md": "正文"},
        ).json()
        self.client.patch(
            f"/api/articles/{article['id']}",
            json={
                "ai_result": {
                    "platforms": {
                        "wechat": {
                            "title": "公众号专用标题",
                            "content_md": "公众号专用正文",
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
        self.assertEqual(publisher.publish.call_args.kwargs["action"], "draft")
        self.assertEqual(
            publisher.publish.call_args.args[0]["title"],
            "公众号专用标题",
        )
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

    def test_ai_enrichment_stores_platform_variants(self):
        article = self.client.post(
            "/api/articles",
            json={"title": "AI 测试", "content_md": "原稿"},
        ).json()
        self.client.put(
            "/api/settings",
            json={"values": {"ai_enabled": True}},
        )
        ai_result = {
            "tags": ["自动标签"],
            "summary": "文章摘要",
            "editor_notes": "",
            "platforms": {
                "wechat": {
                    "title": "公众号标题",
                    "content_md": "公众号正文",
                    "tags": [],
                }
            },
        }
        with patch(
            "backend.services.AIContentService.enrich",
            return_value=ai_result,
        ):
            response = self.client.post(f"/api/articles/{article['id']}/enrich")

        self.assertEqual(response.status_code, 200)
        enriched = response.json()
        self.assertIn("自动标签", enriched["tags"])
        self.assertEqual(
            enriched["ai_result"]["platforms"]["wechat"]["title"],
            "公众号标题",
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
                "Format": {"type": "select", "select": {"name": "Gallery"}},
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
            article_value="Post",
            image_value="Gallery",
        )

        self.assertEqual(metadata["title"], "自定义标题")
        self.assertEqual(metadata["article_type"], "image")
        self.assertEqual(metadata["author"], "作者甲")

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
                return_value=images,
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
        article = response.json()
        self.assertEqual(article["article_type"], "image")
        self.assertEqual(article["media_paths"], [str(first.resolve()), str(second.resolve())])
        self.assertEqual(article["cover_url"], str(first.resolve()))
        self.assertIn(f"![封面]({first.resolve().as_posix()})", article["content_md"])
        self.assertNotIn("<!-- image:", article["content_md"])
        self.assertEqual(article["ai_result"]["source"], "generated")

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
                "ai_proxy_url": "",
            }
        )
        with patch.object(service.session, "post", return_value=response):
            images = service.generate_images(
                [{"position": "image:1", "alt": "测试图", "prompt": "一张测试图"}]
            )

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
