import logging

from backend.assets import get_platform_asset, save_platform_asset
from backend.logging_config import redact_url
from backend.platforms.base import PlatformPublisher
from publish_gzh import WechatArticlePublisher, WechatOfficialAccountPublisher


logger = logging.getLogger("mozhou.wechat")


class CachedWechatClient(WechatOfficialAccountPublisher):
    def upload_permanent_image(self, image_path, image_type="content"):
        cached = get_platform_asset(image_path, "wechat")
        if cached and (image_type != "content" or cached.get("url")):
            logger.info(
                "复用微信图片素材 type=%s source=%s",
                image_type,
                redact_url(image_path),
            )
            return cached

        logger.info(
            "上传新的微信图片素材 type=%s source=%s",
            image_type,
            redact_url(image_path),
        )
        uploaded = super().upload_permanent_image(image_path, image_type)
        return save_platform_asset(
            image_path,
            "wechat",
            uploaded["media_id"],
            uploaded.get("url", ""),
        )


class WechatPublisher(PlatformPublisher):
    key = "wechat"
    name = "微信公众号"
    implemented = True

    def is_configured(self):
        return bool(
            self.settings.get("wechat_app_id")
            and self.settings.get("wechat_app_secret")
        )

    def _client(self):
        if not self.is_configured():
            raise ValueError("请先配置微信公众号 AppID 和 AppSecret")
        proxy_url = self.settings.get("wechat_proxy_url", "")
        logger.debug(
            "创建微信客户端 proxy_mode=%s",
            "configured" if proxy_url else "direct",
        )
        return CachedWechatClient(
            app_id=self.settings["wechat_app_id"],
            app_secret=self.settings["wechat_app_secret"],
            proxy_url=proxy_url,
        )

    def test_connection(self):
        logger.info("开始测试微信公众号连接")
        client = self._client()
        client._get_access_token()
        logger.info("微信公众号连接测试成功")
        return {"message": "微信公众号凭据有效，Access Token 获取成功"}

    def publish(self, article, action="draft"):
        if action not in {"draft", "publish"}:
            raise ValueError("公众号动作必须是 draft 或 publish")
        publisher = WechatArticlePublisher(self._client())
        submit = action == "publish"
        logger.info(
            "微信公众号处理开始 title=%r type=%s action=%s content_chars=%s",
            article["title"],
            article["article_type"],
            action,
            len(article.get("content_md", "")),
        )
        if article["article_type"] == "image":
            external_id = publisher.publish_image_message(
                title=article["title"],
                md_content=article["content_md"],
                submit=submit,
            )
        else:
            if not article["cover_url"]:
                raise ValueError("公众号图文需要封面图片")
            external_id = publisher.publish_markdown_article(
                md_content=article["content_md"],
                title=article["title"],
                author=article["author"],
                content_source_url=article["source_url"],
                cover_image_path=article["cover_url"],
                submit=submit,
            )
        logger.info(
            "微信公众号处理完成 title=%r action=%s",
            article["title"],
            action,
        )
        return {
            "external_id": external_id,
            "status": "published" if submit else "drafted",
        }
