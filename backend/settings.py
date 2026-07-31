import json

from backend.db import connection, utc_now


SECRET_MASK = "••••••••"
DEPRECATED_SETTING_KEYS = {
    "notion_field_published_platforms",
    "notion_value_article",
    "notion_value_image",
}

SETTING_DEFINITIONS = {
    "notion_token": {"default": "", "secret": True, "group": "notion"},
    "notion_database_id": {"default": "", "secret": False, "group": "notion"},
    "notion_data_source_id": {"default": "", "secret": False, "group": "notion"},
    "notion_unique_property": {
        "default": "唯一ID",
        "secret": False,
        "group": "notion",
    },
    "notion_proxy_url": {
        "default": "http://127.0.0.1:7890",
        "secret": False,
        "group": "notion",
    },
    "notion_sync_enabled": {"default": False, "secret": False, "group": "notion"},
    "notion_sync_interval_minutes": {
        "default": 5,
        "secret": False,
        "group": "notion",
    },
    "notion_pending_status": {
        "default": "待同步",
        "secret": False,
        "group": "notion",
    },
    "notion_synced_status": {
        "default": "已同步",
        "secret": False,
        "group": "notion",
    },
    "notion_published_status": {
        "default": "已发布",
        "secret": False,
        "group": "notion",
    },
    "notion_field_title": {"default": "标题", "secret": False, "group": "notion"},
    "notion_field_article_type": {
        "default": "文章类型",
        "secret": False,
        "group": "notion",
    },
    "notion_field_author": {"default": "作者", "secret": False, "group": "notion"},
    "notion_field_cover_url": {
        "default": "封面图片",
        "secret": False,
        "group": "notion",
    },
    "notion_field_source_url": {
        "default": "阅读原文",
        "secret": False,
        "group": "notion",
    },
    "notion_field_tags": {"default": "标签", "secret": False, "group": "notion"},
    "notion_field_status": {"default": "状态", "secret": False, "group": "notion"},
"wechat_enabled": {"default": False, "secret": False, "group": "wechat"},
    "wechat_app_id": {"default": "", "secret": False, "group": "wechat"},
    "wechat_app_secret": {"default": "", "secret": True, "group": "wechat"},
    "wechat_proxy_url": {"default": "", "secret": False, "group": "wechat"},
    "xiaohongshu_enabled": {
        "default": False,
        "secret": False,
        "group": "xiaohongshu",
    },
    "douyin_enabled": {
        "default": False,
        "secret": False,
        "group": "douyin",
    },
    "channels_enabled": {
        "default": False,
        "secret": False,
        "group": "channels",
    },
    "bilibili_enabled": {
        "default": False,
        "secret": False,
        "group": "bilibili",
    },
    "bilibili_default_category": {
        "default": "",
        "secret": False,
        "group": "bilibili",
    },
    "bilibili_copyright": {
        "default": "",
        "secret": False,
        "group": "bilibili",
    },
    "browser_executable_path": {
        "default": "",
        "secret": False,
        "group": "xiaohongshu",
    },
    "csdn_enabled": {"default": False, "secret": False, "group": "csdn"},
    "rss_feed_urls": {
        "default": [
            "https://justlovemaki.github.io/CloudFlare-AI-Insight-Daily/rss.xml",
            "http://feeds-origin.appinn.com/appinns",
        ],
        "secret": False,
        "group": "rss",
    },
    "rss_enabled": {"default": False, "secret": False, "group": "rss"},
    "rss_scan_interval_minutes": {
        "default": 60,
        "secret": False,
        "group": "rss",
    },
    "auto_publish_enabled": {
        "default": False,
        "secret": False,
        "group": "automation",
    },
    "auto_publish_interval_minutes": {
        "default": 5,
        "secret": False,
        "group": "automation",
    },
    "auto_publish_targets": {
        "default": {},
        "secret": False,
        "group": "automation",
    },    "default_publish_mode": {
        "default": "manual",
        "secret": False,
        "group": "automation",
    },
    "ai_enabled": {"default": False, "secret": False, "group": "ai"},
    "ai_auto_enrich_after_sync": {
        "default": False,
        "secret": False,
        "group": "ai",
    },
    "ai_auto_generate_cover_after_sync": {
        "default": True,
        "secret": False,
        "group": "ai",
    },
    "ai_base_url": {
        "default": "https://api.openai.com/v1",
        "secret": False,
        "group": "ai",
    },
    "ai_api_key": {"default": "", "secret": True, "group": "ai"},
    "ai_model": {"default": "", "secret": False, "group": "ai"},
    "ai_proxy_url": {"default": "", "secret": False, "group": "ai"},
    "ai_custom_prompt": {"default": "", "secret": False, "group": "ai"},
    "ai_image_base_url": {"default": "", "secret": False, "group": "ai"},
    "ai_image_api_key": {"default": "", "secret": True, "group": "ai"},
    "ai_image_model": {"default": "", "secret": False, "group": "ai"},
    "ai_image_size": {"default": "1024x1024", "secret": False, "group": "ai"},
    "ai_image_post_size": {"default": "1024x1536", "secret": False, "group": "ai"},
}


def _encode(value):
    return json.dumps(value, ensure_ascii=False)


def _decode(value):
    return json.loads(value)


def ensure_defaults():
    now = utc_now()
    with connection() as conn:
        workflow_migration_needed = conn.execute(
            "SELECT 1 FROM settings WHERE key = 'notion_synced_status'"
        ).fetchone() is None
        if workflow_migration_needed:
            migrations = {
                "notion_pending_status": ("待发布", "待同步"),
            }
            for key, (old_value, new_value) in migrations.items():
                conn.execute(
                    "UPDATE settings SET value = ?, updated_at = ? "
                    "WHERE key = ? AND value = ?",
                    (_encode(new_value), now, key, _encode(old_value)),
                )
        for key in DEPRECATED_SETTING_KEYS:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        for key, definition in SETTING_DEFINITIONS.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO settings(key, value, is_secret, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    key,
                    _encode(definition["default"]),
                    int(definition["secret"]),
                    now,
                ),
            )


def migrate_legacy_config():
    """首次启动时将旧 config.py 的值迁移到本地设置库。"""
    try:
        import config as legacy
    except ImportError:
        return

    mapping = {
        "notion_token": "notion_token",
        "notion_database_id": "databases_id",
        "notion_data_source_id": "data_source_id",
        "notion_proxy_url": "notion_proxy",
        "wechat_app_id": "gzh_app_id",
        "wechat_app_secret": "gzh_app_secret",
    }
    current = get_settings()
    values = {}
    for new_key, old_key in mapping.items():
        old_value = getattr(legacy, old_key, None)
        if old_value is not None and not current.get(new_key):
            values[new_key] = old_value
    if values:
        update_settings(values)


def get_settings(mask_secrets=False):
    ensure_defaults()
    with connection() as conn:
        rows = conn.execute("SELECT key, value, is_secret FROM settings").fetchall()
    result = {}
    for row in rows:
        value = _decode(row["value"])
        if mask_secrets and row["is_secret"] and value:
            value = SECRET_MASK
        result[row["key"]] = value
    return result


def update_settings(values):
    values = {
        key: value
        for key, value in values.items()
        if key not in DEPRECATED_SETTING_KEYS
    }
    unknown = set(values) - set(SETTING_DEFINITIONS)
    if unknown:
        raise ValueError(f"未知配置项: {', '.join(sorted(unknown))}")

    current = get_settings()
    now = utc_now()
    with connection() as conn:
        for key, value in values.items():
            if value == SECRET_MASK:
                continue
            definition = SETTING_DEFINITIONS[key]
            expected_type = type(definition["default"])
            if expected_type is bool and not isinstance(value, bool):
                raise ValueError(f"{key} 必须是布尔值")
            if expected_type is int and (
                not isinstance(value, int) or isinstance(value, bool) or value < 1
            ):
                raise ValueError(f"{key} 必须是大于 0 的整数")
            if expected_type is str and not isinstance(value, str):
                raise ValueError(f"{key} 必须是字符串")
            if expected_type is list:
                if not isinstance(value, list) or any(
                    not isinstance(item, str) for item in value
                ):
                    raise ValueError(f"{key} 必须是字符串列表")
                cleaned = []
                for item in value:
                    item = item.strip()
                    if item and item not in cleaned:
                        cleaned.append(item[:2000])
                if len(cleaned) > 50:
                    raise ValueError("RSS 订阅源最多配置 50 个")
                value = cleaned
            if expected_type is dict:
                if not isinstance(value, dict):
                    raise ValueError(f"{key} 必须是对象")
                if key == "auto_publish_targets":
                    from backend.accounts import get_account

                    cleaned = {}
                    valid_platforms = {
                        "wechat", "xiaohongshu", "douyin", "channels",
                        "bilibili", "csdn",
                    }
                    for platform, target in value.items():
                        if platform not in valid_platforms:
                            raise ValueError(f"未知自动发布平台: {platform}")
                        if not isinstance(target, dict):
                            raise ValueError("自动发布平台配置必须是对象")
                        enabled = target.get("enabled", False)
                        account_id = target.get("account_id")
                        action = target.get("action", "publish")
                        if not isinstance(enabled, bool):
                            raise ValueError("自动发布平台启用状态必须是布尔值")
                        if enabled and (
                            not isinstance(account_id, int)
                            or isinstance(account_id, bool)
                            or account_id < 1
                        ):
                            raise ValueError("已启用平台必须选择发布账号")
                        if action not in {"draft", "publish"}:
                            raise ValueError("自动发布动作必须是 draft 或 publish")
                        if platform not in {"wechat", "csdn"} and action == "draft":
                            raise ValueError("该平台暂不支持保存草稿")
                        if account_id is not None:
                            account = get_account(account_id)
                            if account["platform"] != platform:
                                raise ValueError("所选账号与自动发布平台不匹配")
                        cleaned[platform] = {
                            "enabled": enabled,
                            "account_id": account_id,
                            "action": action,
                        }
                    value = cleaned
            current[key] = value
            conn.execute(
                """
                UPDATE settings
                SET value = ?, is_secret = ?, updated_at = ?
                WHERE key = ?
                """,
                (_encode(value), int(definition["secret"]), now, key),
            )
    return get_settings(mask_secrets=True)


def get_setting_metadata():
    return {
        key: {
            "secret": definition["secret"],
            "group": definition["group"],
        }
        for key, definition in SETTING_DEFINITIONS.items()
    }
