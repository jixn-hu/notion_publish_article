import time

import requests

import config


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2026-03-11"
REQUEST_TIMEOUT = 30

_session = requests.Session()


def _headers():
    return {
        "Authorization": f"Bearer {config.notion_token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_API_VERSION,
    }


def _proxies():
    # 保留原项目的默认代理；如不需要代理，请在 config.py 中设置 notion_proxy = None。
    proxy = getattr(config, "notion_proxy", "http://127.0.0.1:7890")
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _request(method, path, **kwargs):
    response = _session.request(
        method,
        f"{NOTION_API_BASE}{path}",
        headers=_headers(),
        proxies=_proxies(),
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            error = response.json()
            message = error.get("message", response.text)
            code = error.get("code", response.status_code)
        except ValueError:
            message = response.text
            code = response.status_code
        raise RuntimeError(f"Notion API 请求失败 [{code}]: {message}") from exc
    return response.json()


def _resolve_data_source_id():
    configured_id = getattr(config, "data_source_id", "")
    if configured_id:
        return configured_id

    database = _request("GET", f"/databases/{config.databases_id}")
    data_sources = database.get("data_sources", [])
    if not data_sources:
        raise RuntimeError("该 Notion 数据库没有可用的数据源，或 Integration 没有访问权限")
    if len(data_sources) > 1:
        raise RuntimeError(
            "该数据库包含多个数据源，请在 config.py 中设置 data_source_id"
        )
    return data_sources[0]["id"]


def _property(properties, name, property_type):
    prop = properties.get(name)
    if prop is None:
        raise ValueError(f"Notion 数据源缺少字段：{name}")
    if prop.get("type") != property_type:
        raise ValueError(
            f"Notion 字段“{name}”类型应为 {property_type}，实际为 {prop.get('type')}"
        )
    return prop.get(property_type)


def _select_name(properties, name):
    value = _property(properties, name, "select")
    return value["name"] if value else ""


def _page_to_fb_info(page):
    properties = page["properties"]
    title = _property(properties, "标题", "title") or []
    if not title:
        raise ValueError(f"Notion 页面 {page['id']} 的标题为空")

    return {
        "标题": "".join(item.get("plain_text", "") for item in title),
        "封面图片": _property(properties, "封面图片", "url") or "",
        "作者": _select_name(properties, "作者"),
        "文章类型": _select_name(properties, "文章类型"),
        "阅读原文": _property(properties, "阅读原文", "url")
        or "https://aiutools.fun/jixn/",
        "notion_url": page["url"],
        "page_id": page["id"],
        "标签": [
            item["name"] for item in (_property(properties, "标签", "multi_select") or [])
        ],
    }


def database_get_fb_info():
    """获取状态为“待发布”的所有页面。"""
    data_source_id = _resolve_data_source_id()
    pages = []
    start_cursor = None

    while True:
        payload = {
            "filter": {
                "property": "状态",
                "status": {"equals": "待发布"},
            },
            "page_size": 100,
        }
        if start_cursor:
            payload["start_cursor"] = start_cursor

        data = _request(
            "POST",
            f"/data_sources/{data_source_id}/query",
            json=payload,
        )
        pages.extend(data.get("results", []))

        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")
        if not start_cursor:
            raise RuntimeError("Notion API 返回 has_more=true，但未提供 next_cursor")

    return [_page_to_fb_info(page) for page in pages]


def database_update_fb_info(page_id):
    """将页面状态更新为“已发布”，并记录发布平台。"""
    payload = {
        "properties": {
            "状态": {"status": {"name": "已发布"}},
            "已发布平台": {
                "multi_select": [{"name": "微信公众号"}],
            },
        }
    }

    last_error = None
    for attempt in range(3):
        try:
            return _request("PATCH", f"/pages/{page_id}", json=payload)
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"更新文章状态失败: {last_error}") from last_error


def page_get_info(page_id):
    """通过 Notion 官方 Markdown API 获取页面内容。"""
    data = _request("GET", f"/pages/{page_id}/markdown")
    if data.get("truncated"):
        unknown_ids = data.get("unknown_block_ids", [])
        raise RuntimeError(
            f"Notion 页面内容不完整，存在 {len(unknown_ids)} 个未加载 Block，已停止发布"
        )
    return data["markdown"]
