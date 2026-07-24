import json

from backend.db import connection, utc_now


SECRET_MASK = "••••••••"
DEPRECATED_SETTING_KEYS = {"notion_field_published_platforms"}

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
        "default": "待发布",
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
    "notion_value_article": {
        "default": "图文",
        "secret": False,
        "group": "notion",
    },
    "notion_value_image": {
        "default": "图片",
        "secret": False,
        "group": "notion",
    },
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
    "default_publish_mode": {
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
    "ai_base_url": {
        "default": "https://api.openai.com/v1",
        "secret": False,
        "group": "ai",
    },
    "ai_api_key": {"default": "", "secret": True, "group": "ai"},
    "ai_model": {"default": "", "secret": False, "group": "ai"},
    "ai_proxy_url": {"default": "", "secret": False, "group": "ai"},
    "ai_custom_prompt": {"default": "", "secret": False, "group": "ai"},
}


def _encode(value):
    return json.dumps(value, ensure_ascii=False)


def _decode(value):
    return json.loads(value)


def ensure_defaults():
    now = utc_now()
    with connection() as conn:
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
