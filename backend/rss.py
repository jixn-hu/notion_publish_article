import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

from backend.news import (
    MAX_CONTENT_CHARS,
    REDIRECT_STATUSES,
    _normalize_url,
    _validate_public_host,
    create_news,
)
from backend.settings import get_settings


MAX_FEED_BYTES = 5 * 1024 * 1024
MAX_FEED_ENTRIES = 200
MAX_FEED_URLS = 50


def _local_name(tag):
    return str(tag or "").rsplit("}", 1)[-1].lower()


def _children(node, *names):
    expected = {name.lower() for name in names}
    return [child for child in list(node) if _local_name(child.tag) in expected]


def _first(node, *names):
    matches = _children(node, *names)
    return matches[0] if matches else None


def _first_of(node, *names):
    for name in names:
        match = _first(node, name)
        if match is not None:
            return match
    return None


def _text(node):
    if node is None:
        return ""
    return " ".join(
        part.strip()
        for part in node.itertext()
        if part and part.strip()
    ).strip()


def _raw_content(node):
    if node is None:
        return ""
    parts = [node.text or ""]
    parts.extend(
        ET.tostring(child, encoding="unicode", method="html")
        for child in list(node)
    )
    return "".join(parts).strip()


def _content_markdown(value):
    document = BeautifulSoup(str(value or ""), "html.parser")
    for node in document.select("script, style, iframe, noscript"):
        node.decompose()
    lines = []
    for raw in document.get_text("\n", strip=True).splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return "\n\n".join(lines)[:MAX_CONTENT_CHARS]


def _published_at(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw[:100]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _feed_link(entry, feed_url, atom=False):
    if atom:
        links = _children(entry, "link")
        preferred = next(
            (
                link
                for link in links
                if str(link.attrib.get("rel") or "alternate").lower()
                == "alternate"
                and link.attrib.get("href")
            ),
            None,
        )
        node = preferred if preferred is not None else next(
            (link for link in links if link.attrib.get("href")),
            None,
        )
        value = node.attrib.get("href") if node is not None else ""
    else:
        value = _text(_first(entry, "link"))
        if not value:
            guid = _first(entry, "guid")
            is_permalink = str(
                guid.attrib.get("isPermaLink") if guid is not None else ""
            ).lower()
            if guid is not None and is_permalink != "false":
                value = _text(guid)
    if not value:
        return ""
    return urljoin(feed_url, value.strip())


def parse_feed(payload, feed_url):
    if not payload:
        raise RuntimeError("RSS 返回内容为空")
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("RSS 内容超过 5MB 限制")
    prefix = payload[:2048].lower()
    if b"<!doctype" in prefix or b"<!entity" in prefix:
        raise ValueError("RSS 包含不受支持的文档声明")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("RSS XML 格式无效") from exc

    root_name = _local_name(root.tag)
    if root_name in {"rss", "rdf"}:
        channel = _first(root, "channel")
        channel = channel if channel is not None else root
        feed_title = _text(_first(channel, "title"))
        entries = _children(channel, "item")
        if root_name == "rdf" and not entries:
            entries = _children(root, "item")
        atom = False
    elif root_name == "feed":
        channel = root
        feed_title = _text(_first(root, "title"))
        entries = _children(root, "entry")
        atom = True
    else:
        raise ValueError("该地址不是可识别的 RSS 或 Atom 订阅源")

    hostname = (urlsplit(feed_url).hostname or "").removeprefix("www.")
    source_name = (feed_title or hostname or "RSS 订阅")[:120]
    items = []
    for entry in entries[:MAX_FEED_ENTRIES]:
        title = _text(_first(entry, "title"))[:200]
        link = _feed_link(entry, feed_url, atom=atom)
        if not title or not link:
            continue
        try:
            normalized_link = _normalize_url(link)
        except ValueError:
            continue

        if atom:
            content_node = _first_of(entry, "content", "summary")
            summary_node = _first(entry, "summary")
            published = _text(_first_of(entry, "published", "updated"))
            author_node = _first(entry, "author")
            author = _text(_first(author_node, "name")) if author_node is not None else ""
            category_nodes = _children(entry, "category")
            tags = [
                str(node.attrib.get("term") or _text(node)).strip()
                for node in category_nodes
            ]
        else:
            content_node = _first_of(entry, "encoded", "description")
            summary_node = _first(entry, "description")
            published = _text(
                _first_of(entry, "pubdate", "published", "date")
            )
            author = _text(_first_of(entry, "creator", "author"))
            tags = [_text(node) for node in _children(entry, "category")]

        content_md = _content_markdown(_raw_content(content_node))
        summary = _content_markdown(_raw_content(summary_node))[:1000]
        if not summary:
            summary = content_md[:300]
        items.append(
            {
                "title": title,
                "source_name": source_name,
                "source_url": normalized_link,
                "author": author[:120],
                "summary": summary,
                "content_md": content_md,
                "tags": [tag for tag in tags if tag][:12],
                "published_at": _published_at(published),
            }
        )
    return {
        "title": source_name,
        "url": feed_url,
        "items": items,
        "entry_count": len(entries),
    }


def _fetch_feed(url):
    current_url = _normalize_url(url)
    headers = {
        "User-Agent": "MoFlow RSS Reader/1.0",
        "Accept": (
            "application/rss+xml, application/atom+xml, application/xml, "
            "text/xml, text/plain;q=0.8, */*;q=0.2"
        ),
    }
    with requests.Session() as client:
        client.headers.update(headers)
        for _ in range(6):
            _validate_public_host(current_url)
            try:
                response = client.get(
                    current_url,
                    timeout=30,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                raise RuntimeError("RSS 连接失败，请检查地址和网络") from exc
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise RuntimeError("RSS 服务返回了无效跳转")
                current_url = _normalize_url(urljoin(current_url, location))
                continue
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise RuntimeError(
                    f"RSS 服务返回错误状态：{response.status_code}"
                ) from exc
            break
        else:
            raise RuntimeError("RSS 跳转次数过多")
    if len(response.content) > MAX_FEED_BYTES:
        raise ValueError("RSS 内容超过 5MB 限制")
    return response.content, current_url


def scan_rss_feeds(feed_urls=None):
    if feed_urls is None:
        feed_urls = get_settings().get("rss_feed_urls") or []
    if not isinstance(feed_urls, list):
        raise ValueError("RSS 地址配置必须是列表")

    raw_urls = []
    for value in feed_urls:
        raw = str(value or "").strip()
        if raw and raw not in raw_urls:
            raw_urls.append(raw)
    if len(raw_urls) > MAX_FEED_URLS:
        raise ValueError(f"最多配置 {MAX_FEED_URLS} 个 RSS 订阅源")

    result = {
        "feeds": [],
        "feed_count": len(raw_urls),
        "created": 0,
        "existing": 0,
        "ignored": 0,
        "errors": [],
    }
    normalized_urls = set()
    for raw_url in raw_urls:
        try:
            url = _normalize_url(raw_url)
            if url in normalized_urls:
                continue
            normalized_urls.add(url)
            payload, final_url = _fetch_feed(url)
            parsed = parse_feed(payload, final_url)
            feed_result = {
                "url": url,
                "title": parsed["title"],
                "entries": parsed["entry_count"],
                "created": 0,
                "existing": 0,
                "ignored": parsed["entry_count"] - len(parsed["items"]),
            }
            for item in parsed["items"]:
                try:
                    create_news(item)
                    feed_result["created"] += 1
                except ValueError as exc:
                    if "已经采集过" in str(exc):
                        feed_result["existing"] += 1
                    else:
                        feed_result["ignored"] += 1
            result["created"] += feed_result["created"]
            result["existing"] += feed_result["existing"]
            result["ignored"] += feed_result["ignored"]
            result["feeds"].append(feed_result)
        except (ValueError, RuntimeError) as exc:
            result["errors"].append({"url": raw_url, "error": str(exc)})
    return result