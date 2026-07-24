import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.db import connection, utc_now


logger = logging.getLogger("mozhou.assets")


VOLATILE_QUERY_KEYS = {
    "expires",
    "signature",
    "token",
    "x-oss-access-key-id",
    "x-oss-credential",
    "x-oss-date",
    "x-oss-expires",
    "x-oss-security-token",
    "x-oss-signature",
}


def canonical_asset_source(source):
    source = source.strip()
    if source.startswith(("http://", "https://")):
        parts = urlsplit(source)
        stable_query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in VOLATILE_QUERY_KEYS
            and not key.lower().startswith("x-amz-")
        ]
        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path,
                urlencode(sorted(stable_query)),
                "",
            )
        )
    return str(Path(source).resolve())


def asset_source_key(source):
    canonical = canonical_asset_source(source)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"asset:{digest}"


def extract_article_assets(markdown, cover_url=""):
    sources = re.findall(r"!\[[^\]]*\]\((?:<)?([^\s)>]+)", markdown or "")
    assets = [(source, "content") for source in sources]
    if cover_url:
        assets.append((cover_url, "cover"))

    unique = {}
    for source, kind in assets:
        key = asset_source_key(source)
        if key not in unique or kind == "cover":
            unique[key] = {
                "source_key": key,
                "source_url": source,
                "kind": kind,
            }
    return list(unique.values())


def sync_article_assets(article_id, markdown, cover_url=""):
    assets = extract_article_assets(markdown, cover_url)
    keys = [asset["source_key"] for asset in assets]
    now = utc_now()
    with connection() as conn:
        for asset in assets:
            conn.execute(
                """
                INSERT INTO article_assets (
                    article_id, source_key, source_url, kind, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(article_id, source_key) DO UPDATE SET
                    source_url = excluded.source_url,
                    kind = excluded.kind,
                    updated_at = excluded.updated_at
                """,
                (
                    article_id,
                    asset["source_key"],
                    asset["source_url"],
                    asset["kind"],
                    now,
                ),
            )
        if keys:
            placeholders = ",".join("?" for _ in keys)
            conn.execute(
                f"""
                DELETE FROM article_assets
                WHERE article_id = ? AND source_key NOT IN ({placeholders})
                """,
                [article_id, *keys],
            )
        else:
            conn.execute(
                "DELETE FROM article_assets WHERE article_id = ?",
                (article_id,),
            )
    logger.debug(
        "文章素材索引已同步 article_id=%s assets=%s cover=%s",
        article_id,
        len(assets),
        bool(cover_url),
    )
    return assets


def get_platform_asset(source, platform):
    key = asset_source_key(source)
    with connection() as conn:
        row = conn.execute(
            """
            SELECT media_id, media_url
            FROM platform_assets
            WHERE source_key = ? AND platform = ?
            """,
            (key, platform),
        ).fetchone()
    if not row:
        logger.debug(
            "平台素材缓存未命中 platform=%s source_key=%s", platform, key
        )
        return None
    logger.info("平台素材缓存命中 platform=%s source_key=%s", platform, key)
    return {
        "media_id": row["media_id"],
        "url": row["media_url"],
        "is_cached": True,
    }


def save_platform_asset(source, platform, media_id, media_url=""):
    key = asset_source_key(source)
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO platform_assets (
                source_key, platform, media_id, media_url, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key, platform) DO UPDATE SET
                media_id = CASE
                    WHEN platform_assets.media_id = '' THEN excluded.media_id
                    ELSE platform_assets.media_id
                END,
                media_url = CASE
                    WHEN platform_assets.media_url = '' THEN excluded.media_url
                    ELSE platform_assets.media_url
                END,
                updated_at = excluded.updated_at
            """,
            (key, platform, media_id, media_url, now, now),
        )
    logger.info(
        "平台素材缓存已保存 platform=%s source_key=%s has_media_url=%s",
        platform,
        key,
        bool(media_url),
    )
    return get_platform_asset(source, platform)
