import tempfile
import unittest
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
        self.assertFalse(platforms[5]["implemented"])

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
            "视频号 ID：wx-channel-1\n有效关注人数 3.4万\n"
            "发表视频数 18\n获赞数 2,406"
        )
        self.assertEqual(
            profile["platform_user_id"],
            "wx-channel-1",
        )
        self.assertEqual(profile["followers_count"], 34000)
        self.assertEqual(profile["works_count"], 18)
        self.assertEqual(profile["likes_count"], 2406)

    def test_douyin_and_channels_profile_handlers_are_registered(self):
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
        for forbidden in backend.browser.FORBIDDEN_BROWSER_ARGS:
            self.assertNotIn(forbidden, joined)

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

    def test_scheme_scoped_proxy_format_is_normalized_for_chromium(self):
        value = "HTTPS:HTTP://192.0.2.10:808/"
        self.assertEqual(
            backend.proxies.normalize_proxy_url(value),
            "https:http://192.0.2.10:808",
        )
        self.assertEqual(
            backend.proxies.requests_proxy_map(value),
            {"https": "http://192.0.2.10:808"},
        )
        command = backend.browser._native_browser_command(
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
            Path("D:/profiles/demo"),
            9333,
            value,
        )
        self.assertIn(
            "--proxy-server=https=http://192.0.2.10:808",
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
