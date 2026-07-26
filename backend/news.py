import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from backend.db import connection, utc_now


MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_CONTENT_CHARS = 50000
MAX_REFERENCE_COUNT = 20
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _clean_tags(tags):
    if not isinstance(tags, list):
        return []
    cleaned = []
    for tag in tags:
        value = str(tag or "").strip()[:30]
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned[:12]


def _normalize_url(value):
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("资讯原文链接不能为空")
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("资讯链接必须是有效的 HTTP 或 HTTPS 地址")
    if parsed.username or parsed.password:
        raise ValueError("资讯链接不能包含账号信息")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("资讯链接不能指向本机或内网")
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        raise ValueError("资讯链接不能指向本机或内网")
    normalized = urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
    if len(normalized) > 2000:
        raise ValueError("资讯链接过长")
    return normalized


def _validate_public_host(url):
    host = urlsplit(url).hostname
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise RuntimeError("无法解析资讯网站地址") from exc
    if not addresses:
        raise RuntimeError("无法解析资讯网站地址")
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("资讯链接不能指向本机或内网")


def _row_to_news(row):
    item = dict(row)
    item["tags"] = json.loads(item.pop("tags_json") or "[]")
    item["reference_count"] = int(item.get("reference_count") or 0)
    return item


def list_news(query=None, source=None):
    clauses = []
    params = []
    if query:
        term = f"%{str(query).strip()}%"
        clauses.append(
            "(n.title LIKE ? OR n.summary LIKE ? OR n.content_md LIKE ? "
            "OR n.source_name LIKE ? OR n.author LIKE ?)"
        )
        params.extend([term, term, term, term, term])
    if source:
        clauses.append("n.source_name = ?")
        params.append(str(source).strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT n.*, COUNT(an.article_id) AS reference_count
            FROM news_items n
            LEFT JOIN article_news an ON an.news_id = n.id
            {where}
            GROUP BY n.id
            ORDER BY COALESCE(n.published_at, n.created_at) DESC, n.id DESC
            """,
            params,
        ).fetchall()
        source_rows = conn.execute(
            """
            SELECT source_name, COUNT(*) AS total
            FROM news_items
            GROUP BY source_name
            ORDER BY total DESC, source_name
            """
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
    return {
        "items": [_row_to_news(row) for row in rows],
        "counts": {
            "all": total,
            "sources": len(source_rows),
        },
        "sources": [
            {
                "name": row["source_name"] or "未知来源",
                "value": row["source_name"],
                "total": row["total"],
            }
            for row in source_rows
        ],
    }


def get_news(news_id):
    with connection() as conn:
        row = conn.execute(
            """
            SELECT n.*, COUNT(an.article_id) AS reference_count
            FROM news_items n
            LEFT JOIN article_news an ON an.news_id = n.id
            WHERE n.id = ?
            GROUP BY n.id
            """,
            (news_id,),
        ).fetchone()
    if not row:
        raise LookupError("资讯不存在")
    return _row_to_news(row)


def create_news(values):
    title = str(values.get("title") or "").strip()[:200]
    source_url = _normalize_url(values.get("source_url"))
    content = str(values.get("content_md") or "").strip()[:MAX_CONTENT_CHARS]
    summary = str(values.get("summary") or "").strip()[:1000]
    if not title:
        raise ValueError("资讯标题不能为空")
    now = utc_now()
    with connection() as conn:
        existing = conn.execute(
            "SELECT id FROM news_items WHERE source_url = ?",
            (source_url,),
        ).fetchone()
        if existing:
            raise ValueError("这条资讯已经采集过了")
        cursor = conn.execute(
            """
            INSERT INTO news_items (
                title, source_name, source_url, author, summary, content_md,
                tags_json, published_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                str(values.get("source_name") or "").strip()[:120],
                source_url,
                str(values.get("author") or "").strip()[:120],
                summary,
                content,
                json.dumps(_clean_tags(values.get("tags")), ensure_ascii=False),
                str(values.get("published_at") or "").strip()[:100] or None,
                now,
                now,
            ),
        )
        news_id = cursor.lastrowid
    return get_news(news_id)


def update_news(news_id, values):
    get_news(news_id)
    allowed = {
        "title",
        "source_name",
        "source_url",
        "author",
        "summary",
        "content_md",
        "tags",
        "published_at",
    }
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"不可更新字段: {', '.join(sorted(unknown))}")
    limits = {
        "title": 200,
        "source_name": 120,
        "author": 120,
        "summary": 1000,
        "content_md": MAX_CONTENT_CHARS,
        "published_at": 100,
    }
    assignments = []
    params = []
    for key, value in values.items():
        if key == "tags":
            key = "tags_json"
            value = json.dumps(_clean_tags(value), ensure_ascii=False)
        elif key == "source_url":
            value = _normalize_url(value)
        else:
            value = str(value or "").strip()[: limits[key]]
            if key == "title" and not value:
                raise ValueError("资讯标题不能为空")
            if key == "published_at":
                value = value or None
        assignments.append(f"{key} = ?")
        params.append(value)
    if not assignments:
        return get_news(news_id)
    assignments.append("updated_at = ?")
    params.extend([utc_now(), news_id])
    try:
        with connection() as conn:
            conn.execute(
                f"UPDATE news_items SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise ValueError("这条资讯已经采集过了") from exc
        raise
    return get_news(news_id)


def delete_news(news_id):
    get_news(news_id)
    with connection() as conn:
        conn.execute("DELETE FROM news_items WHERE id = ?", (news_id,))
    return {"deleted": True, "id": news_id}


def _meta_content(document, *selectors):
    for selector in selectors:
        node = document.select_one(selector)
        if not node:
            continue
        value = (
            node.get("content")
            or node.get("datetime")
            or node.get_text(" ", strip=True)
        )
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _extract_page(html, url):
    document = BeautifulSoup(html, "html.parser")
    title = _meta_content(
        document,
        "meta[property='og:title']",
        "meta[name='twitter:title']",
        "title",
        "h1",
    )
    summary = _meta_content(
        document,
        "meta[property='og:description']",
        "meta[name='description']",
        "meta[name='twitter:description']",
    )
    source_name = _meta_content(
        document,
        "meta[property='og:site_name']",
        "meta[name='application-name']",
    )
    author = _meta_content(
        document,
        "meta[name='author']",
        "meta[property='article:author']",
        "[rel='author']",
    )
    published_at = _meta_content(
        document,
        "meta[property='article:published_time']",
        "meta[name='publishdate']",
        "meta[name='pubdate']",
        "time[datetime]",
    )
    for node in document.select(
        "script, style, noscript, iframe, nav, footer, header, form, button, aside"
    ):
        node.decompose()
    candidates = document.select("article, main, [role='main']")
    if not candidates and document.body:
        candidates = document.body.select("section, div")
    if candidates:
        container = max(
            candidates,
            key=lambda item: len(item.get_text("\n", strip=True)),
        )
    else:
        container = document.body or document
    lines = []
    for raw_line in container.get_text("\n", strip=True).splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if len(line) < 2 or line in lines[-3:]:
            continue
        lines.append(line)
    content = "\n\n".join(lines)[:MAX_CONTENT_CHARS]
    if not title and lines:
        title = lines[0][:200]
    if not source_name:
        source_name = urlsplit(url).hostname.removeprefix("www.")
    if not summary and content:
        summary = content[:300]
    return {
        "title": title[:200],
        "source_name": source_name[:120],
        "source_url": url,
        "author": author[:120],
        "summary": summary[:1000],
        "content_md": content,
        "published_at": published_at[:100] or None,
        "tags": [],
    }


def collect_news(url):
    current_url = _normalize_url(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/127.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    }
    with requests.Session() as client:
        client.headers.update(headers)
        for _ in range(6):
            _validate_public_host(current_url)
            try:
                response = client.get(
                    current_url,
                    timeout=20,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                raise RuntimeError("资讯网页连接失败，请检查网址和网络") from exc
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise RuntimeError("资讯网站返回了无效跳转")
                current_url = _normalize_url(urljoin(current_url, location))
                continue
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise RuntimeError(
                    f"资讯网站返回错误状态：{response.status_code}"
                ) from exc
            break
        else:
            raise RuntimeError("资讯网站跳转次数过多")
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and "text/plain" not in content_type:
        raise ValueError("该链接不是可采集的网页")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError("资讯网页内容过大")
    encoding = response.encoding or "utf-8"
    extracted = _extract_page(response.content.decode(encoding, errors="replace"), current_url)
    if not extracted["title"]:
        raise RuntimeError("未能从网页识别资讯标题")
    if not extracted["content_md"]:
        raise RuntimeError("未能从网页提取正文，请改用手工录入")
    return create_news(extracted)


def get_news_references(news_ids, max_count=MAX_REFERENCE_COUNT):
    ordered_ids = []
    for value in news_ids or []:
        news_id = int(value)
        if news_id > 0 and news_id not in ordered_ids:
            ordered_ids.append(news_id)
    if len(ordered_ids) > max_count:
        raise ValueError(f"一次最多选择 {max_count} 条资讯")
    if not ordered_ids:
        return []
    placeholders = ",".join("?" for _ in ordered_ids)
    with connection() as conn:
        rows = conn.execute(
            f"SELECT *, 0 AS reference_count FROM news_items WHERE id IN ({placeholders})",
            ordered_ids,
        ).fetchall()
    found = {row["id"]: _row_to_news(row) for row in rows}
    missing = [news_id for news_id in ordered_ids if news_id not in found]
    if missing:
        raise ValueError(f"引用资讯不存在: {', '.join(map(str, missing))}")
    return [found[news_id] for news_id in ordered_ids]


def format_news_context(items):
    if not items:
        return "未选择参考资讯"
    blocks = []
    for index, item in enumerate(items, start=1):
        details = [
            f"{index}. {item['title']}",
            f"来源：{item['source_name'] or '未知来源'}",
            f"原文：{item['source_url']}",
        ]
        if item["author"]:
            details.append(f"作者：{item['author']}")
        if item["published_at"]:
            details.append(f"发布时间：{item['published_at']}")
        if item["summary"]:
            details.append(f"摘要：{item['summary']}")
        if item["content_md"]:
            details.append(f"采集正文：{item['content_md'][:5000]}")
        blocks.append("\n".join(details))
    return "\n\n".join(blocks)[:18000]


def link_article_news(article_id, news_ids):
    references = get_news_references(news_ids)
    now = utc_now()
    with connection() as conn:
        conn.execute("DELETE FROM article_news WHERE article_id = ?", (article_id,))
        for item in references:
            conn.execute(
                """
                INSERT INTO article_news (article_id, news_id, created_at)
                VALUES (?, ?, ?)
                """,
                (article_id, item["id"], now),
            )
    return references
