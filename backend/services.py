import json
import logging
from pathlib import Path
import threading
import time

from backend.ai_generation import AIImageService
from backend.ai_service import AIContentService
from backend.assets import sync_article_assets
from backend.db import connection, row_to_article, utc_now
from backend.media import MEDIA_DIR
from backend.materials import (
    format_material_context,
    get_material_references,
    link_article_materials,
)
from backend.news import (
    format_news_context,
    get_news_references,
    link_article_news,
)
from backend.notion_client import NotionClient, page_metadata
from backend.platforms import get_platforms
from backend.settings import get_settings


operation_lock = threading.Lock()
logger = logging.getLogger("mozhou.services")


def notion_client(settings=None):
    settings = settings or get_settings()
    return NotionClient(
        token=settings["notion_token"],
        database_id=settings["notion_database_id"],
        data_source_id=settings["notion_data_source_id"],
        proxy_url=settings["notion_proxy_url"],
    )


def notion_field_mapping(settings):
    return {
        "title": settings["notion_field_title"],
        "article_type": settings["notion_field_article_type"],
        "author": settings["notion_field_author"],
        "cover_url": settings["notion_field_cover_url"],
        "source_url": settings["notion_field_source_url"],
        "tags": settings["notion_field_tags"],
    }


def sync_from_notion():
    if not operation_lock.acquire(blocking=False):
        logger.warning("Notion 同步被跳过：操作锁正在占用")
        raise RuntimeError("已有同步或发布任务正在执行")
    started = time.perf_counter()
    try:
        settings = get_settings()
        logger.info(
            "Notion 同步开始 database_id=%s data_source_id=%s status_field=%s "
            "pending_status=%s default_publish_mode=%s ai_auto=%s",
            settings["notion_database_id"],
            settings["notion_data_source_id"] or "(自动解析)",
            settings["notion_field_status"],
            settings["notion_pending_status"],
            settings["default_publish_mode"],
            bool(
                settings["ai_enabled"]
                and settings["ai_auto_enrich_after_sync"]
            ),
        )
        client = notion_client(settings)
        pages = client.query_pages(
            settings["notion_pending_status"],
            status_field=settings["notion_field_status"],
        )
        result = {
            "total": len(pages),
            "created": 0,
            "updated": 0,
            "ai_enriched": 0,
            "errors": [],
            "ai_errors": [],
        }
        logger.info("Notion 同步筛选完成 matched=%s", len(pages))
        for index, page in enumerate(pages, start=1):
            page_id = page.get("id", "")
            page_started = time.perf_counter()
            try:
                logger.debug(
                    "开始处理 Notion 页面 index=%s/%s page_id=%s",
                    index,
                    len(pages),
                    page_id,
                )
                metadata = page_metadata(
                    page,
                    unique_property=settings["notion_unique_property"],
                    field_mapping=notion_field_mapping(settings),
                    article_value=settings["notion_value_article"],
                    image_value=settings["notion_value_image"],
                )
                logger.info(
                    "Notion 页面元数据已解析 index=%s/%s page_id=%s title=%r "
                    "type=%s source_key=%s tags=%s",
                    index,
                    len(pages),
                    page_id,
                    metadata["title"],
                    metadata["article_type"],
                    metadata["source_key"],
                    len(metadata["tags"]),
                )
                metadata["content_md"] = client.get_page_markdown(page["id"])
                action, article_id = _upsert_synced_article(
                    metadata, settings["default_publish_mode"]
                )
                assets = sync_article_assets(
                    article_id,
                    metadata["content_md"],
                    metadata["cover_url"],
                )
                result[action] += 1
                logger.info(
                    "Notion 页面同步成功 page_id=%s article_id=%s action=%s "
                    "content_chars=%s assets=%s elapsed_ms=%.1f",
                    page_id,
                    article_id,
                    action,
                    len(metadata["content_md"]),
                    len(assets),
                    (time.perf_counter() - page_started) * 1000,
                )
                if settings["ai_enabled"] and settings["ai_auto_enrich_after_sync"]:
                    try:
                        enrich_article(article_id, settings=settings)
                        result["ai_enriched"] += 1
                    except Exception as exc:
                        logger.exception(
                            "同步后 AI 加工失败 page_id=%s article_id=%s",
                            page_id,
                            article_id,
                        )
                        result["ai_errors"].append(
                            {"page_id": page_id, "message": str(exc)}
                        )
            except Exception as exc:
                logger.exception(
                    "Notion 页面同步失败 index=%s/%s page_id=%s elapsed_ms=%.1f",
                    index,
                    len(pages),
                    page_id,
                    (time.perf_counter() - page_started) * 1000,
                )
                result["errors"].append(
                    {
                        "page_id": page_id,
                        "message": str(exc),
                    }
                )
        logger.info(
            "Notion 同步结束 matched=%s created=%s updated=%s errors=%s "
            "ai_enriched=%s ai_errors=%s elapsed_ms=%.1f",
            result["total"],
            result["created"],
            result["updated"],
            len(result["errors"]),
            result["ai_enriched"],
            len(result["ai_errors"]),
            (time.perf_counter() - started) * 1000,
        )
        return result
    finally:
        operation_lock.release()


def _upsert_synced_article(article, default_publish_mode):
    now = utc_now()
    with connection() as conn:
        source_match = conn.execute(
            "SELECT id FROM articles WHERE source_key = ?",
            (article["source_key"],),
        ).fetchone()
        page_match = conn.execute(
            "SELECT id FROM articles WHERE notion_page_id = ?",
            (article["notion_page_id"],),
        ).fetchone()
        if source_match and page_match and source_match["id"] != page_match["id"]:
            logger.error(
                "文章去重冲突 source_key=%s source_article_id=%s "
                "page_id=%s page_article_id=%s",
                article["source_key"],
                source_match["id"],
                article["notion_page_id"],
                page_match["id"],
            )
            raise RuntimeError(
                "Notion 唯一字段与 page_id 分别命中了不同文章，已停止同步以避免覆盖错误"
            )
        existing = source_match or page_match
        if existing:
            match_by = "source_key" if source_match else "notion_page_id"
            conn.execute(
                """
                UPDATE articles SET
                    source_key = ?, notion_page_id = ?, notion_url = ?,
                    title = ?, author = ?, article_type = ?,
                    content_md = ?, cover_url = ?, source_url = ?, tags_json = ?,
                    ai_result_json = '{}', ai_enriched_at = NULL,
                    last_synced_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    article["source_key"],
                    article["notion_page_id"],
                    article["notion_url"],
                    article["title"],
                    article["author"],
                    article["article_type"],
                    article["content_md"],
                    article["cover_url"],
                    article["source_url"],
                    json.dumps(article["tags"], ensure_ascii=False),
                    now,
                    now,
                    existing["id"],
                ),
            )
            logger.debug(
                "覆盖已有文章 article_id=%s matched_by=%s source_key=%s page_id=%s",
                existing["id"],
                match_by,
                article["source_key"],
                article["notion_page_id"],
            )
            return "updated", existing["id"]

        cursor = conn.execute(
            """
            INSERT INTO articles (
                source_key, notion_page_id, notion_url, title, author, article_type,
                content_md, cover_url, source_url, tags_json, publish_mode,
                target_platforms_json, platform_actions_json, status,
                last_synced_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?)
            """,
            (
                article["source_key"],
                article["notion_page_id"],
                article["notion_url"],
                article["title"],
                article["author"],
                article["article_type"],
                article["content_md"],
                article["cover_url"],
                article["source_url"],
                json.dumps(article["tags"], ensure_ascii=False),
                default_publish_mode,
                json.dumps(["wechat"], ensure_ascii=False),
                json.dumps({"wechat": "draft"}, ensure_ascii=False),
                now,
                now,
                now,
            ),
        )
        logger.debug(
            "创建同步文章 article_id=%s source_key=%s page_id=%s publish_mode=%s",
            cursor.lastrowid,
            article["source_key"],
            article["notion_page_id"],
            default_publish_mode,
        )
        return "created", cursor.lastrowid


def list_articles(status=None, query=None, article_type=None):
    clauses = []
    params = []
    if status and status != "all":
        clauses.append("a.status = ?")
        params.append(status)
    if article_type and article_type != "all":
        if article_type not in {"article", "image", "video"}:
            raise ValueError("内容类型必须是 article、image 或 video")
        clauses.append("a.article_type = ?")
        params.append(article_type)
    if query:
        clauses.append("(a.title LIKE ? OR a.author LIKE ?)")
        term = f"%{query}%"
        params.extend([term, term])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT a.*,
                (SELECT COUNT(*) FROM publish_records r
                 WHERE r.article_id = a.id) AS publish_count,
                (SELECT r.error FROM publish_records r
                 WHERE r.article_id = a.id AND r.error != ''
                 ORDER BY r.created_at DESC
                 LIMIT 1) AS latest_publish_error
            FROM articles a
            {where}
            ORDER BY a.updated_at DESC
            """,
            params,
        ).fetchall()
    return [row_to_article(row) for row in rows]


def create_article(values):
    now = utc_now()
    title = str(values.get("title", "")).strip()
    if not title:
        raise ValueError("文章标题不能为空")
    article_type = values.get("article_type", "article")
    if article_type not in {"article", "image", "video"}:
        raise ValueError("article_type 必须是 article、image 或 video")
    publish_mode = values.get("publish_mode", "manual")
    if publish_mode not in {"manual", "automatic"}:
        raise ValueError("publish_mode 必须是 manual 或 automatic")

    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO articles (
                title, author, article_type, content_md, cover_url, source_url,
                tags_json, media_paths_json, publish_mode, target_platforms_json,
                platform_actions_json, platform_accounts_json, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
            """,
            (
                title,
                values.get("author", ""),
                article_type,
                values.get("content_md", ""),
                values.get("cover_url", ""),
                values.get("source_url", ""),
                json.dumps(values.get("tags", []), ensure_ascii=False),
                json.dumps(values.get("media_paths", []), ensure_ascii=False),
                publish_mode,
                json.dumps(
                    values.get("target_platforms", ["wechat"]),
                    ensure_ascii=False,
                ),
                json.dumps(
                    values.get("platform_actions", {"wechat": "draft"}),
                    ensure_ascii=False,
                ),
                json.dumps(
                    values.get("platform_accounts", {}),
                    ensure_ascii=False,
                ),
                now,
                now,
            ),
        )
        article_id = cursor.lastrowid
    article = get_article(article_id)
    sync_article_assets(article_id, article["content_md"], article["cover_url"])
    return article


def get_article(article_id, include_records=True):
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        if not row:
            raise LookupError("文章不存在")
        article = row_to_article(row)
        if include_records:
            records = conn.execute(
                """
                SELECT * FROM publish_records
                WHERE article_id = ?
                ORDER BY created_at DESC
                """,
                (article_id,),
            ).fetchall()
            article["publish_records"] = [dict(record) for record in records]
        return article


def update_article(article_id, values):
    allowed = {
        "title",
        "author",
        "article_type",
        "content_md",
        "cover_url",
        "source_url",
        "media_paths",
        "publish_mode",
        "target_platforms",
        "platform_actions",
        "platform_accounts",
        "status",
        "tags",
        "ai_result",
    }
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"不可更新字段: {', '.join(sorted(unknown))}")
    if "article_type" in values and values["article_type"] not in {
        "article",
        "image",
        "video",
    }:
        raise ValueError("article_type 必须是 article、image 或 video")
    if "publish_mode" in values and values["publish_mode"] not in {
        "manual",
        "automatic",
    }:
        raise ValueError("publish_mode 必须是 manual 或 automatic")
    if "platform_actions" in values:
        invalid_actions = set(values["platform_actions"].values()) - {
            "draft",
            "publish",
        }
        if invalid_actions:
            raise ValueError("平台动作必须是 draft 或 publish")
    if "platform_accounts" in values:
        invalid_account_ids = [
            value
            for value in values["platform_accounts"].values()
            if not isinstance(value, int) or isinstance(value, bool) or value < 1
        ]
        if invalid_account_ids:
            raise ValueError("平台账号 ID 必须是正整数")

    column_map = {
        "target_platforms": "target_platforms_json",
        "platform_actions": "platform_actions_json",
        "platform_accounts": "platform_accounts_json",
        "media_paths": "media_paths_json",
        "tags": "tags_json",
        "ai_result": "ai_result_json",
    }
    assignments = []
    params = []
    for key, value in values.items():
        column = column_map.get(key, key)
        if key in {
            "target_platforms",
            "platform_actions",
            "platform_accounts",
            "media_paths",
            "tags",
            "ai_result",
        }:
            value = json.dumps(value, ensure_ascii=False)
        assignments.append(f"{column} = ?")
        params.append(value)
    assignments.append("updated_at = ?")
    params.append(utc_now())
    params.append(article_id)

    with connection() as conn:
        cursor = conn.execute(
            f"UPDATE articles SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        if not cursor.rowcount:
            raise LookupError("文章不存在")
    article = get_article(article_id)
    if {"content_md", "cover_url"} & set(values):
        sync_article_assets(article_id, article["content_md"], article["cover_url"])
    return article


def publish_article(article_id, requested_actions=None):
    if not operation_lock.acquire(blocking=False):
        logger.warning("文章发布被跳过：操作锁正在占用 article_id=%s", article_id)
        raise RuntimeError("已有同步或发布任务正在执行")
    started = time.perf_counter()
    try:
        article = get_article(article_id, include_records=False)
        if requested_actions is not None:
            actions = requested_actions
        else:
            actions = {
                key: article["platform_actions"].get(
                    key, "draft" if key in {"wechat", "csdn"} else "publish"
                )
                for key in article["target_platforms"]
            }
        platforms = list(actions)
        if not platforms:
            raise ValueError("请至少选择一个发布平台")
        if set(actions.values()) - {"draft", "publish"}:
            raise ValueError("平台动作必须是 draft 或 publish")

        settings = get_settings()
        publishers = get_platforms(settings)
        unknown = set(platforms) - set(publishers)
        if unknown:
            raise ValueError(f"未知平台: {', '.join(sorted(unknown))}")

        logger.info(
            "文章发布开始 article_id=%s title=%r article_type=%s "
            "publish_mode=%s actions=%s",
            article_id,
            article["title"],
            article["article_type"],
            article["publish_mode"],
            actions,
        )
        _set_article_status(article_id, "publishing", "")
        results = []
        for platform_key in platforms:
            publisher = publishers[platform_key]
            platform_action = actions[platform_key]
            platform_started = time.perf_counter()
            try:
                logger.info(
                    "平台发布开始 article_id=%s platform=%s action=%s "
                    "implemented=%s enabled=%s configured=%s",
                    article_id,
                    platform_key,
                    platform_action,
                    publisher.implemented,
                    publisher.is_enabled(),
                    publisher.is_configured(),
                )
                if not publisher.implemented:
                    raise NotImplementedError(f"{publisher.name}发布能力尚未实现")
                if not publisher.is_enabled():
                    raise RuntimeError(f"{publisher.name}尚未启用")
                if not publisher.is_configured():
                    raise RuntimeError(f"{publisher.name}配置不完整")
                output = publisher.publish(
                    _article_for_platform(article, platform_key),
                    action=platform_action,
                )
                result_status = output.get(
                    "status",
                    "drafted" if platform_action == "draft" else "published",
                )
                _record_publish(
                    article_id,
                    platform_key,
                    platform_action,
                    result_status,
                    output.get("external_id", ""),
                    "",
                )
                results.append(
                    {
                        "platform": platform_key,
                        "action": platform_action,
                        "status": result_status,
                        "external_id": output.get("external_id", ""),
                        "account_id": output.get("account_id"),
                    }
                )
                logger.info(
                    "平台发布成功 article_id=%s platform=%s action=%s "
                    "status=%s elapsed_ms=%.1f",
                    article_id,
                    platform_key,
                    platform_action,
                    result_status,
                    (time.perf_counter() - platform_started) * 1000,
                )
            except Exception as exc:
                logger.exception(
                    "平台发布失败 article_id=%s platform=%s action=%s "
                    "elapsed_ms=%.1f",
                    article_id,
                    platform_key,
                    platform_action,
                    (time.perf_counter() - platform_started) * 1000,
                )
                _record_publish(
                    article_id,
                    platform_key,
                    platform_action,
                    "failed",
                    "",
                    str(exc),
                )
                results.append(
                    {
                        "platform": platform_key,
                        "action": platform_action,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        successful = [
            item for item in results if item["status"] in {"published", "drafted"}
        ]
        if len(successful) == len(results):
            success_statuses = {item["status"] for item in successful}
            if success_statuses == {"drafted"}:
                final_status = "drafted"
            elif success_statuses == {"published"}:
                final_status = "published"
            else:
                final_status = "completed"
            error = ""
        elif successful:
            final_status = "partial"
            error = "部分平台发布失败"
        else:
            final_status = "failed"
            error = "; ".join(item["error"] for item in results)
        _set_article_status(article_id, final_status, error)
        logger.info(
            "文章发布结束 article_id=%s final_status=%s success=%s total=%s "
            "elapsed_ms=%.1f",
            article_id,
            final_status,
            len(successful),
            len(results),
            (time.perf_counter() - started) * 1000,
        )

        if final_status == "published" and article.get("notion_page_id"):
            try:
                notion_client(settings).mark_published(
                    article["notion_page_id"],
                    status_field=settings["notion_field_status"],
                    published_status=settings["notion_published_status"],
                )
            except Exception as exc:
                logger.exception(
                    "发布成功但 Notion 状态回写失败 article_id=%s page_id=%s",
                    article_id,
                    article["notion_page_id"],
                )
                results.append(
                    {
                        "platform": "notion",
                        "status": "warning",
                        "error": f"发布成功，但 Notion 状态回写失败: {exc}",
                    }
                )
        return {"article_id": article_id, "status": final_status, "results": results}
    finally:
        operation_lock.release()


def _article_for_platform(article, platform_key):
    variant = article.get("ai_result", {}).get("platforms", {}).get(platform_key, {})
    if not variant:
        return article
    platform_article = dict(article)
    if variant.get("title"):
        platform_article["title"] = variant["title"]
    if variant.get("content_md"):
        platform_article["content_md"] = variant["content_md"]
    return platform_article


def _insert_generated_images(markdown, images):
    content = str(markdown or "").strip()
    appended = []
    for image in images:
        alt = str(image.get("alt") or "文章配图").replace("]", "")
        source = Path(image["path"]).as_posix()
        image_markdown = f"![{alt}]({source})"
        marker = f"<!-- {image['position']} -->"
        if marker in content:
            content = content.replace(marker, image_markdown, 1)
        else:
            appended.append(image_markdown)
    if appended:
        content = "\n\n".join([content, *appended]).strip()
    return content


def generate_ai_storyboard(values, settings=None):
    settings = settings or get_settings()
    if not settings["ai_enabled"]:
        raise RuntimeError("AI 内容生成尚未启用")
    page_count = int(values.get("image_count") or 5)
    if page_count < 1 or page_count > 9:
        raise ValueError("图文分镜页数必须在 1-9 之间")
    material_ids = values.get("material_ids") or []
    references = get_material_references(material_ids)
    news_ids = values.get("news_ids") or []
    news_references = get_news_references(news_ids)
    specification = {
        "topic": str(values["topic"]).strip(),
        "audience": str(values.get("audience") or "").strip(),
        "style": str(values.get("style") or "").strip(),
        "requirements": str(values.get("requirements") or "").strip(),
        "image_count": page_count,
        "materials": format_material_context(references),
        "material_ids": [material["id"] for material in references],
        "news": format_news_context(news_references),
        "news_ids": [item["id"] for item in news_references],
    }
    logger.info(
        "AI 图文分镜生成开始 topic=%r pages=%s model=%s",
        specification["topic"],
        page_count,
        settings["ai_model"] or "(未配置)",
    )
    return AIContentService(settings).generate_image_storyboard(specification)


def generate_ai_article(values, settings=None):
    settings = settings or get_settings()
    if not settings["ai_enabled"]:
        raise RuntimeError("AI 内容生成尚未启用")
    article_type = values.get("article_type", "article")
    image_count = int(values.get("image_count") or 0)
    if article_type not in {"article", "image"}:
        raise ValueError("AI 生成仅支持 article 或 image")
    if article_type == "image" and image_count < 1:
        raise ValueError("图文内容至少需要生成 1 张图片")

    material_ids = values.get("material_ids") or []
    references = get_material_references(material_ids)
    news_ids = values.get("news_ids") or []
    news_references = get_news_references(news_ids)
    started = time.perf_counter()
    logger.info(
        "AI 文章生成开始 type=%s topic=%r words=%s images=%s model=%s",
        article_type,
        values["topic"],
        values["word_count"],
        image_count,
        settings["ai_model"] or "(未配置)",
    )
    specification = {
        "topic": str(values["topic"]).strip(),
        "article_type": article_type,
        "audience": str(values.get("audience") or "").strip(),
        "style": str(values.get("style") or "").strip(),
        "requirements": str(values.get("requirements") or "").strip(),
        "word_count": int(values["word_count"]),
        "image_count": image_count,
        "materials": format_material_context(references),
        "material_ids": [material["id"] for material in references],
        "news": format_news_context(news_references),
        "news_ids": [item["id"] for item in news_references],
    }
    storyboard = None
    if article_type == "image" and values.get("storyboard"):
        storyboard = AIContentService.validate_image_storyboard(
            values["storyboard"],
            expected_pages=image_count,
        )
        generated = {
            "title": storyboard["title"],
            "summary": storyboard["summary"],
            "content_md": "\n\n".join(
                [
                    storyboard["caption_md"],
                    *[
                        f"<!-- image:{index} -->"
                        for index in range(1, len(storyboard["pages"]) + 1)
                    ],
                ]
            ),
            "tags": storyboard["tags"],
            "image_plan": AIContentService.image_plan_from_storyboard(
                storyboard,
                specification,
            ),
        }
    else:
        generated = AIContentService(settings).generate_article(specification)

    images = AIImageService(settings).generate_images(generated["image_plan"])
    content_md = _insert_generated_images(generated["content_md"], images)
    media_paths = [image["path"] for image in images]
    ai_result = {
        "source": "generated",
        "summary": generated["summary"],
        "editor_notes": "AI 生成初稿，请在发布前核对事实、图片与平台要求。",
        "tags": generated["tags"],
        "image_plan": generated["image_plan"],
        "generated_images": images,
        "material_ids": [material["id"] for material in references],
        "news_ids": [item["id"] for item in news_references],
        "platforms": {},
    }
    if storyboard:
        ai_result["storyboard"] = storyboard
    try:
        article = create_article(
            {
                "title": generated["title"],
                "author": str(values.get("author") or "").strip(),
                "article_type": article_type,
                "content_md": content_md,
                "cover_url": media_paths[0] if media_paths else "",
                "tags": generated["tags"],
                "media_paths": media_paths,
                "publish_mode": "manual",
                "target_platforms": ["wechat"],
                "platform_actions": {"wechat": "draft"},
            }
        )
    except Exception:
        for image in images:
            Path(image["path"]).unlink(missing_ok=True)
        raise

    link_article_materials(article["id"], material_ids)
    link_article_news(article["id"], news_ids)
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            UPDATE articles
            SET ai_result_json = ?, ai_enriched_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(ai_result, ensure_ascii=False),
                now,
                now,
                article["id"],
            ),
        )
    logger.info(
        "AI 文章生成完成 article_id=%s type=%s images=%s elapsed_ms=%.1f",
        article["id"],
        article_type,
        len(images),
        (time.perf_counter() - started) * 1000,
    )
    return get_article(article["id"])


def regenerate_ai_image(article_id, image_index, settings=None):
    settings = settings or get_settings()
    if not settings["ai_enabled"]:
        raise RuntimeError("AI 内容生成尚未启用")
    article = get_article(article_id, include_records=False)
    image_plan = article.get("ai_result", {}).get("image_plan") or []
    generated_images = list(
        article.get("ai_result", {}).get("generated_images") or []
    )
    if image_index < 0 or image_index >= len(image_plan):
        raise ValueError("图片序号超出可重绘范围")

    replacement = AIImageService(settings).generate_images([image_plan[image_index]])[0]
    old_path = (
        generated_images[image_index].get("path")
        if image_index < len(generated_images)
        else ""
    )
    while len(generated_images) <= image_index:
        generated_images.append({})
    generated_images[image_index] = replacement

    media_paths = list(article.get("media_paths") or [])
    while len(media_paths) <= image_index:
        media_paths.append("")
    media_paths[image_index] = replacement["path"]

    content_md = article.get("content_md") or ""
    if old_path:
        content_md = content_md.replace(
            Path(old_path).as_posix(),
            Path(replacement["path"]).as_posix(),
        )
    ai_result = dict(article.get("ai_result") or {})
    ai_result["generated_images"] = generated_images
    values = {
        "content_md": content_md,
        "media_paths": media_paths,
        "ai_result": ai_result,
    }
    if image_index == 0:
        values["cover_url"] = replacement["path"]
    try:
        updated = update_article(article_id, values)
    except Exception:
        Path(replacement["path"]).unlink(missing_ok=True)
        raise

    if old_path:
        old_file = Path(old_path).resolve()
        try:
            old_file.relative_to((MEDIA_DIR / "ai").resolve())
        except ValueError:
            pass
        else:
            old_file.unlink(missing_ok=True)
    return updated


def enrich_article(article_id, settings=None):
    settings = settings or get_settings()
    if not settings["ai_enabled"]:
        raise RuntimeError("AI 内容加工尚未启用")
    article = get_article(article_id, include_records=False)
    started = time.perf_counter()
    logger.info(
        "AI 内容加工开始 article_id=%s title=%r model=%s",
        article_id,
        article["title"],
        settings["ai_model"] or "(未配置)",
    )
    result = AIContentService(settings).enrich(article)
    merged_tags = list(dict.fromkeys(article["tags"] + result["tags"]))
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            UPDATE articles
            SET tags_json = ?, ai_result_json = ?, ai_enriched_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(merged_tags, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                now,
                now,
                article_id,
            ),
        )
    logger.info(
        "AI 内容加工完成 article_id=%s new_tags=%s platforms=%s elapsed_ms=%.1f",
        article_id,
        len(result["tags"]),
        ",".join(result.get("platforms", {}).keys()),
        (time.perf_counter() - started) * 1000,
    )
    return get_article(article_id)


def _record_publish(article_id, platform, action, status, external_id, error):
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO publish_records (
                article_id, platform, action, status, external_id, error,
                created_at, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                platform,
                action,
                status,
                external_id,
                error,
                now,
                now if status in {"published", "drafted"} else None,
            ),
        )


def _set_article_status(article_id, status, error):
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            UPDATE articles
            SET status = ?, last_error = ?, published_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                error,
                now if status in {"published", "completed"} else None,
                now,
                article_id,
            ),
        )


def run_auto_publish():
    settings = get_settings()
    if not settings["auto_publish_enabled"]:
        logger.info("自动发布检查结束：功能未启用 processed=0")
        return {"processed": 0, "results": []}
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id FROM articles
            WHERE publish_mode = 'automatic' AND status = 'ready'
            ORDER BY created_at
            """
        ).fetchall()
        excluded = conn.execute(
            """
            SELECT publish_mode, status, COUNT(*) AS count
            FROM articles
            GROUP BY publish_mode, status
            ORDER BY publish_mode, status
            """
        ).fetchall()
    logger.info(
        "自动发布筛选完成 eligible=%s inventory=%s",
        len(rows),
        [
            {
                "publish_mode": row["publish_mode"],
                "status": row["status"],
                "count": row["count"],
            }
            for row in excluded
        ],
    )
    results = []
    for row in rows:
        results.append(publish_article(row["id"]))
    logger.info("自动发布执行结束 processed=%s", len(results))
    return {"processed": len(results), "results": results}


def dashboard_summary():
    with connection() as conn:
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM articles GROUP BY status"
        ).fetchall()
        recent_rows = conn.execute(
            """
            SELECT r.*, a.title
            FROM publish_records r
            JOIN articles a ON a.id = r.article_id
            ORDER BY r.created_at DESC
            LIMIT 8
            """
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    return {
        "total": total,
        "by_status": {row["status"]: row["count"] for row in status_rows},
        "recent_records": [dict(row) for row in recent_rows],
    }
