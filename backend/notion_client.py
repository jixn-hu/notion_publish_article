import logging
import time

import requests

from backend.markdown_utils import normalize_notion_markdown


logger = logging.getLogger("mozhou.notion")

NETWORK_ATTEMPTS = 3
NETWORK_RETRY_DELAYS = (1, 2)


class NotionClient:
    API_BASE = "https://api.notion.com/v1"
    API_VERSION = "2026-03-11"

    def __init__(
        self,
        token,
        database_id,
        data_source_id="",
        proxy_url="",
        timeout=30,
    ):
        self.token = token.strip()
        self.database_id = database_id.strip()
        self.data_source_id = data_source_id.strip()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False
        if proxy_url.strip():
            self.session.proxies.update(
                {"http": proxy_url.strip(), "https": proxy_url.strip()}
            )

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": self.API_VERSION,
        }

    def _request(self, method, path, **kwargs):
        started = time.perf_counter()
        logger.debug("Notion 请求开始 method=%s path=%s", method, path)
        for attempt in range(1, NETWORK_ATTEMPTS + 1):
            try:
                response = self.session.request(
                    method,
                    f"{self.API_BASE}{path}",
                    headers=self.headers,
                    timeout=self.timeout,
                    **kwargs,
                )
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < NETWORK_ATTEMPTS:
                    delay = NETWORK_RETRY_DELAYS[attempt - 1]
                    logger.warning(
                        "Notion 网络请求中断，准备重试 method=%s path=%s "
                        "attempt=%s/%s delay_seconds=%s error_type=%s",
                        method,
                        path,
                        attempt,
                        NETWORK_ATTEMPTS,
                        delay,
                        type(exc).__name__,
                    )
                    time.sleep(delay)
                    continue
                logger.error(
                    "Notion 网络请求失败 method=%s path=%s attempts=%s "
                    "elapsed_ms=%.1f error_type=%s",
                    method,
                    path,
                    NETWORK_ATTEMPTS,
                    (time.perf_counter() - started) * 1000,
                    type(exc).__name__,
                )
                raise RuntimeError(
                    "Notion 网络连接失败，已重试 3 次，请检查网络或代理设置"
                ) from exc
            except requests.RequestException as exc:
                logger.error(
                    "Notion 网络请求无法发送 method=%s path=%s "
                    "elapsed_ms=%.1f error_type=%s",
                    method,
                    path,
                    (time.perf_counter() - started) * 1000,
                    type(exc).__name__,
                )
                raise RuntimeError(
                    "Notion 网络请求无法发送，请检查网络或代理设置"
                ) from exc
        logger.debug(
            "Notion 请求完成 method=%s path=%s status=%s elapsed_ms=%.1f",
            method,
            path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            try:
                error = response.json()
                code = error.get("code", response.status_code)
                message = error.get("message", response.text)
            except ValueError:
                code = response.status_code
                message = response.text
            logger.error(
                "Notion API 返回错误 method=%s path=%s status=%s code=%s message=%s",
                method,
                path,
                response.status_code,
                code,
                message,
            )
            raise RuntimeError(f"Notion API [{code}]: {message}") from exc
        return response.json()

    def resolve_data_source_id(self):
        if self.data_source_id:
            logger.debug("使用已配置的 Notion Data Source ID=%s", self.data_source_id)
            return self.data_source_id
        if not self.database_id:
            raise ValueError("请先配置 Notion Database ID")
        database = self._request("GET", f"/databases/{self.database_id}")
        data_sources = database.get("data_sources", [])
        if not data_sources:
            raise RuntimeError("数据库没有可访问的数据源")
        if len(data_sources) > 1:
            raise RuntimeError("数据库包含多个数据源，请配置 Data Source ID")
        resolved = data_sources[0]["id"]
        logger.info(
            "从 Database 解析 Notion Data Source ID database_id=%s data_source_id=%s",
            self.database_id,
            resolved,
        )
        return resolved

    def test_connection(self):
        if not self.token:
            raise ValueError("请先配置 Notion Token")
        data_source_id = self.resolve_data_source_id()
        data = self._request("GET", f"/data_sources/{data_source_id}")
        title = "".join(
            item.get("plain_text", "") for item in data.get("title", [])
        )
        return {"data_source_id": data_source_id, "name": title or "已连接"}

    def get_schema(self):
        data_source_id = self.resolve_data_source_id()
        data = self._request("GET", f"/data_sources/{data_source_id}")
        return {
            "data_source_id": data_source_id,
            "fields": [
                {
                    "name": name,
                    "type": definition.get("type", "unknown"),
                    "id": definition.get("id", ""),
                }
                for name, definition in data.get("properties", {}).items()
            ],
        }

    def query_pages(self, pending_status="待发布", status_field="状态"):
        data_source_id = self.resolve_data_source_id()
        logger.info(
            "查询 Notion 待同步页面 data_source_id=%s status_field=%s equals=%s",
            data_source_id,
            status_field,
            pending_status,
        )
        pages = []
        cursor = None
        page_number = 0
        while True:
            page_number += 1
            payload = {
                "filter": {
                    "property": status_field,
                    "status": {"equals": pending_status},
                },
                "page_size": 100,
            }
            if cursor:
                payload["start_cursor"] = cursor
            data = self._request(
                "POST",
                f"/data_sources/{data_source_id}/query",
                json=payload,
            )
            batch = data.get("results", [])
            pages.extend(batch)
            logger.debug(
                "Notion 查询分页 page=%s batch=%s accumulated=%s has_more=%s",
                page_number,
                len(batch),
                len(pages),
                bool(data.get("has_more")),
            )
            if not data.get("has_more"):
                logger.info("Notion 待同步页面查询完成 total=%s", len(pages))
                return pages
            cursor = data.get("next_cursor")
            if not cursor:
                raise RuntimeError("Notion 分页响应缺少 next_cursor")

    def get_page_markdown(self, page_id):
        logger.debug("读取 Notion Markdown page_id=%s", page_id)
        data = self._request("GET", f"/pages/{page_id}/markdown")
        if data.get("truncated"):
            count = len(data.get("unknown_block_ids", []))
            raise RuntimeError(f"页面内容不完整，仍有 {count} 个 Block 未加载")
        markdown = normalize_notion_markdown(data["markdown"])
        logger.debug(
            "Notion Markdown 读取完成 page_id=%s chars=%s",
            page_id,
            len(markdown),
        )
        return markdown

    def update_status(
        self,
        page_id,
        status_field="状态",
        status="已同步",
    ):
        logger.info(
            "回写 Notion 状态 page_id=%s status=%s",
            page_id,
            status,
        )
        properties = {
            status_field: {"status": {"name": status}},
        }
        return self._request(
            "PATCH",
            f"/pages/{page_id}",
            json={"properties": properties},
        )

    def mark_published(
        self,
        page_id,
        status_field="状态",
        published_status="已发布",
    ):
        return self.update_status(
            page_id,
            status_field=status_field,
            status=published_status,
        )


def _property(properties, name, expected_type, required=True):
    prop = properties.get(name)
    if prop is None:
        if required:
            raise ValueError(f"Notion 缺少“{name}”字段")
        return None
    actual_type = prop.get("type")
    if actual_type != expected_type:
        raise ValueError(
            f"Notion 字段“{name}”应为 {expected_type}，实际为 {actual_type}"
        )
    return prop.get(expected_type)


DEFAULT_FIELD_MAPPING = {
    "title": "标题",
    "article_type": "文章类型",
    "author": "作者",
    "cover_url": "封面图片",
    "source_url": "阅读原文",
    "tags": "标签",
}


def page_metadata(
    page,
    unique_property="唯一ID",
    field_mapping=None,
):
    properties = page["properties"]
    fields = {**DEFAULT_FIELD_MAPPING, **(field_mapping or {})}
    title_parts = _property(properties, fields["title"], "title") or []
    title = "".join(item.get("plain_text", "") for item in title_parts).strip()
    if not title:
        raise ValueError(f"页面 {page['id']} 的标题为空")

    author_value = _property(
        properties, fields["author"], "select", required=False
    )
    type_value = _property(properties, fields["article_type"], "select")
    tags_value = (
        _property(properties, fields["tags"], "multi_select", required=False) or []
    )
    cover_url = (
        _property(properties, fields["cover_url"], "url", required=False) or ""
    )
    source_url = (
        _property(properties, fields["source_url"], "url", required=False) or ""
    )
    notion_type = type_value["name"] if type_value else ""
    type_mapping = {
        "文章": "article",
        "图文": "image",
    }
    if notion_type not in type_mapping:
        raise ValueError(
            f"页面 {page['id']} 的文章类型“{notion_type or '空'}”无效，"
            "仅支持“文章”和“图文”"
        )

    return {
        "source_key": _page_source_key(page, properties, unique_property),
        "notion_page_id": page["id"],
        "notion_url": page.get("url", ""),
        "title": title,
        "author": author_value["name"] if author_value else "",
        "article_type": type_mapping[notion_type],
        "cover_url": cover_url,
        "source_url": source_url,
        "tags": [item["name"] for item in tags_value],
    }


def _page_source_key(page, properties, unique_property):
    prop = properties.get(unique_property) if unique_property else None
    if prop:
        prop_type = prop.get("type")
        value = prop.get(prop_type)
        if prop_type == "unique_id" and value:
            prefix = value.get("prefix") or ""
            number = value.get("number")
            if number is not None:
                return f"notion:unique:{unique_property}:{prefix}{number}"
        if prop_type in {"rich_text", "title"} and value:
            text = "".join(item.get("plain_text", "") for item in value).strip()
            if text:
                return f"notion:unique:{unique_property}:{text}"
        if prop_type == "number" and value is not None:
            return f"notion:unique:{unique_property}:{value}"
    return f"notion:page:{page['id']}"
