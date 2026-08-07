import logging

from backend.accounts import (
    get_wechat_api_credentials,
    list_accounts,
    resolve_publish_account,
    update_wechat_api_status,
)
from backend.assets import get_platform_asset, save_platform_asset
from backend.logging_config import redact_url
from backend.platforms.base import PlatformPublisher
from backend.platforms.wechat_browser import WechatPublisher as BrowserPublisher
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


class WechatApiPublisher(PlatformPublisher):
    key = "wechat"
    name = "微信公众号"
    implemented = True
    content_types = ("article", "image")

    def __init__(self, settings, account):
        super().__init__(settings)
        self.account = account

    def is_configured(self):
        config = self.account.get("wechat") or {}
        return bool(config.get("app_id") and config.get("app_secret_configured"))

    def _client(self):
        if not self.is_configured():
            raise ValueError("请先配置该公众号账号的 AppID 和 AppSecret")
        credentials = get_wechat_api_credentials(self.account["id"])
        proxy_url = credentials["proxy_url"]
        logger.debug(
            "创建微信客户端 proxy_mode=%s api_connection_mode=%s base_api=%s",
            "configured" if proxy_url else "direct",
            credentials["api_connection_mode"],
            redact_url(credentials["base_api"]),
        )
        return CachedWechatClient(
            app_id=credentials["app_id"],
            app_secret=credentials["app_secret"],
            proxy_url=proxy_url,
            base_api=credentials["base_api"],
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
            "account_id": self.account["id"],
        }


def test_wechat_api_account(account_id, settings=None):
    account = resolve_publish_account("wechat", account_id, require_login=False)
    publisher = WechatApiPublisher(settings or {}, account)
    capabilities = {"credentials": False, "draft": False, "publish": False}
    errors = []
    try:
        client = publisher._client()
        token = client._get_access_token()
        capabilities["credentials"] = True
    except Exception as exc:
        update_wechat_api_status(account_id, "invalid", capabilities, str(exc))
        raise RuntimeError(f"公众号 API 凭据验证失败：{exc}") from exc

    checks = (
        ("draft", "GET", f"draft/count?access_token={token}", {}),
        (
            "publish",
            "POST",
            f"freepublish/batchget?access_token={token}",
            {"json": {"offset": 0, "count": 1, "no_content": 1}},
        ),
    )
    for key, method, endpoint, kwargs in checks:
        try:
            client._request_with_retry(method, endpoint, **kwargs)
            capabilities[key] = True
        except Exception as exc:
            label = "草稿" if key == "draft" else "发布"
            errors.append(f"{label}权限：{exc}")
    account = update_wechat_api_status(
        account_id,
        "valid",
        capabilities,
        "?".join(errors),
    )
    return {
        "message": "公众号 API 凭据有效，已完成接口权限检查",
        "account": account,
        "capabilities": capabilities,
    }


class WechatPublisher(PlatformPublisher):
    key = "wechat"
    name = "微信公众号"
    implemented = True
    content_types = ("article", "image")

    def is_configured(self):
        return any(
            account["status"] == "valid"
            or account.get("wechat", {}).get("app_secret_configured")
            for account in list_accounts(self.key)
        )

    def test_connection(self):
        accounts = list_accounts(self.key)
        if not accounts:
            raise RuntimeError("请先添加微信公众号账号")
        if len(accounts) > 1:
            raise RuntimeError("存在多个公众号账号，请在账号管理中分别检查")
        account = accounts[0]
        if account.get("wechat", {}).get("publish_method") == "api":
            return test_wechat_api_account(account["id"], self.settings)
        return BrowserPublisher(self.settings).test_connection()

    def publish(self, article, action="draft"):
        account_id = (article.get("platform_accounts") or {}).get(self.key)
        account = resolve_publish_account(
            self.key,
            account_id,
            require_login=False,
        )
        method = account.get("wechat", {}).get("publish_method", "browser")
        if method == "api":
            capabilities = account.get("wechat", {}).get("api_capabilities") or {}
            if action == "publish" and capabilities.get("publish") is not True:
                raise ValueError(
                    "该公众号 API 账号没有直接发布权限，请选择保存草稿"
                )
            return WechatApiPublisher(self.settings, account).publish(article, action)
        return BrowserPublisher(self.settings).publish(article, action)
