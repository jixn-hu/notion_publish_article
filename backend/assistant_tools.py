from pathlib import Path
from urllib.parse import quote, urlsplit

from backend.accounts import list_accounts
from backend.materials import get_material, list_materials
from backend.news import get_news, list_news
from backend.platforms import get_platforms
from backend.proxies import list_proxies
from backend.services import dashboard_summary, get_article, list_articles
from backend.settings import get_settings


CREATION_TOOL_TARGETS = {
    "create_article": "article",
    "create_news": "news",
    "create_note": "note",
    "create_image": "image",
}

ASSISTANT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_dashboard",
            "description": "读取墨流工作台汇总，包括稿件、发布状态和全网粉丝数。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_articles",
            "description": "搜索或列出稿件。需要完整正文时再调用 get_article。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "标题或作者关键词"},
                    "status": {"type": "string", "description": "稿件状态，留空表示全部"},
                    "article_type": {
                        "type": "string",
                        "enum": ["article", "image", "video"],
                        "description": "文章、图文或视频",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_article",
            "description": "按 ID 读取一篇稿件的正文、媒体、发布目标和平台状态。",
            "parameters": {
                "type": "object",
                "properties": {"article_id": {"type": "integer", "minimum": 1}},
                "required": ["article_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_accounts",
            "description": "读取平台账号及公开资料、登录状态和粉丝数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "enum": [
                            "wechat",
                            "xiaohongshu",
                            "douyin",
                            "channels",
                            "bilibili",
                            "csdn",
                        ],
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_news",
            "description": "搜索或列出资讯库，可用于后续创作参考。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "source": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "按 ID 读取一条资讯的正文和来源。",
            "parameters": {
                "type": "object",
                "properties": {"news_id": {"type": "integer", "minimum": 1}},
                "required": ["news_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_materials",
            "description": "搜索或列出素材库中的图片、视频和原子卡片笔记。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "kind": {"type": "string", "enum": ["image", "video", "note"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_material",
            "description": "按 ID 读取素材详情或卡片笔记正文。",
            "parameters": {
                "type": "object",
                "properties": {"material_id": {"type": "integer", "minimum": 1}},
                "required": ["material_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_platforms",
            "description": "读取各发布平台的启用状态、能力和支持的内容类型。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_proxies",
            "description": "读取代理配置和检测状态，代理地址会被脱敏。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_configuration",
            "description": "读取墨流配置状态。密钥、令牌和敏感地址始终脱敏。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_article",
            "description": "根据要求生成文章或图文稿件。只生成确认草稿，不会直接写入。",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string", "description": "选题、观点和写作要求"},
                    "article_type": {"type": "string", "enum": ["article", "image"]},
                    "author": {"type": "string"},
                    "audience": {"type": "string"},
                    "style": {"type": "string"},
                    "requirements": {"type": "string"},
                    "word_count": {"type": "integer", "minimum": 300, "maximum": 5000},
                    "image_mode": {"type": "string", "enum": ["auto", "cover", "none"]},
                    "material_ids": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "maxItems": 20,
                    },
                    "news_ids": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "maxItems": 20,
                    },
                },
                "required": ["instruction"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_news",
            "description": "整理并新建一条资讯。先生成确认草稿，不会直接写入。",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                    "source_url": {"type": "string"},
                    "source_name": {"type": "string"},
                },
                "required": ["instruction", "source_url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "把一个小知识点整理成单一、原子化卡片笔记。先生成确认草稿。",
            "parameters": {
                "type": "object",
                "properties": {"instruction": {"type": "string"}},
                "required": ["instruction"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_image",
            "description": "设计并生成一张图片素材。先生成图片方案供确认。",
            "parameters": {
                "type": "object",
                "properties": {"instruction": {"type": "string"}},
                "required": ["instruction"],
                "additionalProperties": False,
            },
        },
    },
]


def _limit(value, default=8):
    try:
        return max(1, min(20, int(value or default)))
    except (TypeError, ValueError):
        return default


def _clip(value, length):
    return str(value or "")[:length]


def _safe_mapping(value):
    if not isinstance(value, dict):
        return {}
    blocked = ("secret", "token", "cookie", "credential", "password", "profile_dir")
    clean = {}
    for key, item in value.items():
        if any(part in str(key).lower() for part in blocked):
            continue
        if isinstance(item, dict):
            clean[key] = _safe_mapping(item)
        elif isinstance(item, list):
            clean[key] = [
                _safe_mapping(entry) if isinstance(entry, dict) else entry
                for entry in item[:20]
            ]
        else:
            clean[key] = item
    return clean


def _article_summary(article):
    return {
        "id": article["id"],
        "title": article["title"],
        "author": article.get("author") or "",
        "article_type": article.get("article_type") or "article",
        "status": article.get("status") or "",
        "tags": (article.get("tags") or [])[:8],
        "publish_mode": article.get("publish_mode") or "manual",
        "target_platforms": article.get("target_platforms") or [],
        "updated_at": article.get("updated_at"),
        "platform_states": [
            {
                "platform": state.get("platform"),
                "status": state.get("status"),
                "action": state.get("action"),
                "last_error": _clip(state.get("last_error"), 300),
            }
            for state in (article.get("platform_states") or [])
        ],
    }


def _account_summary(account):
    wechat = account.get("wechat") or {}
    return {
        "id": account["id"],
        "platform": account.get("platform"),
        "name": account.get("name"),
        "status": account.get("status"),
        "profile": _safe_mapping(account.get("profile") or {}),
        "proxy": {
            "id": (account.get("proxy") or {}).get("id"),
            "name": (account.get("proxy") or {}).get("name"),
            "status": (account.get("proxy") or {}).get("status"),
        } if account.get("proxy") else None,
        "wechat": {
            "publish_method": wechat.get("publish_method"),
            "app_secret_configured": bool(wechat.get("app_secret_configured")),
            "api_status": wechat.get("api_status"),
            "api_capabilities": wechat.get("api_capabilities") or {},
        } if account.get("platform") == "wechat" else None,
        "updated_at": account.get("updated_at"),
        "avatar_url": f"/api/accounts/{account['id']}/avatar",
    }


def _news_summary(item):
    return {
        "id": item["id"],
        "title": item.get("title"),
        "source_name": item.get("source_name"),
        "source_url": item.get("source_url"),
        "summary": _clip(item.get("summary"), 500),
        "tags": (item.get("tags") or [])[:8],
        "published_at": item.get("published_at"),
        "created_at": item.get("created_at"),
    }


def _material_summary(item):
    path = str(item.get("path") or "")
    return {
        "id": item["id"],
        "kind": item.get("kind"),
        "title": item.get("title"),
        "description": _clip(item.get("description"), 500),
        "tags": (item.get("tags") or [])[:8],
        "filename": Path(path).name if path else "",
        "size_bytes": item.get("size_bytes") or 0,
        "updated_at": item.get("updated_at"),
        "preview_url": f"/api/materials/{item['id']}/file"
        if item.get("kind") in {"image", "video"} else "",
    }


def _redact_proxy_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        if not parsed.scheme or not parsed.hostname:
            return "已配置" if value else ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://***{port}"
    except ValueError:
        return "已配置" if value else ""


def run_read_tool(name, arguments, settings=None):
    arguments = arguments if isinstance(arguments, dict) else {}
    settings = settings or get_settings()

    if name == "get_dashboard":
        dashboard = dashboard_summary()
        return {
            "type": "dashboard",
            "title": "工作台概览",
            "metrics": {
                "total_articles": dashboard.get("total", 0),
                "total_followers": dashboard.get("total_followers", 0),
                "follower_accounts": dashboard.get("follower_accounts", 0),
                "by_status": dashboard.get("by_status") or {},
            },
            "recent_records": (dashboard.get("recent_records") or [])[:8],
        }

    if name == "list_articles":
        items = list_articles(
            status=arguments.get("status"),
            query=arguments.get("query"),
            article_type=arguments.get("article_type"),
        )[:_limit(arguments.get("limit"))]
        return {
            "type": "articles",
            "title": f"稿件 {len(items)} 篇",
            "items": [_article_summary(item) for item in items],
        }

    if name == "get_article":
        article = get_article(int(arguments.get("article_id") or 0))
        item = _article_summary(article)
        item.update({
            "content_md": _clip(article.get("content_md"), 50000),
            "cover_url": article.get("cover_url") or "",
            "cover_preview_url": (
                f"/api/media/file?path={quote(str(article.get('cover_url') or ''))}"
                if article.get("cover_url") and not str(article["cover_url"]).startswith(("http://", "https://"))
                else article.get("cover_url") or ""
            ),
            "source_url": article.get("source_url") or "",
            "media_paths": (article.get("media_paths") or [])[:20],
        })
        return {"type": "article", "title": article["title"], "item": item}

    if name == "list_accounts":
        items = list_accounts(arguments.get("platform"))
        return {
            "type": "accounts",
            "title": f"账号 {len(items)} 个",
            "items": [_account_summary(item) for item in items],
        }

    if name == "list_news":
        result = list_news(
            query=arguments.get("query"),
            source=arguments.get("source"),
        )
        items = result["items"][:_limit(arguments.get("limit"))]
        return {
            "type": "news",
            "title": f"资讯 {len(items)} 条",
            "items": [_news_summary(item) for item in items],
        }

    if name == "get_news":
        news = get_news(int(arguments.get("news_id") or 0))
        item = _news_summary(news)
        item["content_md"] = _clip(news.get("content_md"), 50000)
        return {"type": "news_detail", "title": news["title"], "item": item}

    if name == "list_materials":
        result = list_materials(
            kind=arguments.get("kind"),
            query=arguments.get("query"),
        )
        items = result["items"][:_limit(arguments.get("limit"))]
        return {
            "type": "materials",
            "title": f"素材 {len(items)} 项",
            "items": [_material_summary(item) for item in items],
        }

    if name == "get_material":
        material = get_material(int(arguments.get("material_id") or 0))
        item = _material_summary(material)
        if material.get("kind") == "note":
            item["content_md"] = _clip(material.get("content_md"), 20000)
        return {"type": "material", "title": material["title"], "item": item}

    if name == "list_platforms":
        items = [publisher.status() for publisher in get_platforms(settings).values()]
        return {
            "type": "platforms",
            "title": "发布平台",
            "items": [_safe_mapping(item) for item in items],
        }

    if name == "list_proxies":
        items = []
        for proxy in list_proxies():
            items.append({
                "id": proxy.get("id"),
                "name": proxy.get("name"),
                "proxy_url": _redact_proxy_url(proxy.get("proxy_url")),
                "status": proxy.get("status"),
                "exit_ip": proxy.get("exit_ip") or "",
                "last_latency_ms": proxy.get("last_latency_ms"),
                "last_checked_at": proxy.get("last_checked_at"),
                "last_error": _clip(proxy.get("last_error"), 300),
            })
        return {"type": "proxies", "title": f"代理 {len(items)} 个", "items": items}

    if name == "get_system_configuration":
        masked = get_settings(mask_secrets=True)
        for key in list(masked):
            if key.endswith("_proxy_url"):
                masked[key] = _redact_proxy_url(masked[key])
        return {
            "type": "configuration",
            "title": "系统配置",
            "values": masked,
        }

    raise ValueError(f"AI 助手不支持工具: {name}")
