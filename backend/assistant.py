import json
from pathlib import Path

from backend.ai_generation import AIImageService
from backend.ai_service import AIContentService
from backend.db import connection, utc_now
from backend.materials import (
    create_generated_image_material,
    create_note_material,
    format_material_context,
    get_material_references,
    link_article_materials,
)
from backend.news import (
    create_news,
    format_news_context,
    get_news_references,
    link_article_news,
)
from backend.services import (
    _insert_generated_images,
    create_article,
    get_article,
    resolve_ai_image_count,
)
from backend.settings import get_settings


ASSISTANT_TARGETS = {"article", "news", "note", "image"}


def preview_assistant(values, settings=None):
    settings = settings or get_settings()
    if not settings["ai_enabled"]:
        raise RuntimeError("AI 内容生成尚未启用")
    target = str(values.get("target") or "").strip()
    instruction = str(values.get("instruction") or "").strip()
    if target not in ASSISTANT_TARGETS:
        raise ValueError("助手目标必须是 article、news、note 或 image")
    if len(instruction) < 2:
        raise ValueError("请告诉小助手你想创建什么内容")

    if target != "article":
        draft = AIContentService(settings).generate_assistant_item(
            target,
            instruction,
            source_url=str(values.get("source_url") or "").strip(),
        )
        return {"target": target, "draft": draft}

    article_type = str(values.get("article_type") or "article").strip()
    if article_type not in {"article", "image"}:
        raise ValueError("文章类型必须是 article 或 image")
    image_count = resolve_ai_image_count(
        article_type,
        values.get("image_mode", "auto"),
        values.get("word_count", 1200),
    )

    material_ids = values.get("material_ids") or []
    materials = get_material_references(material_ids)
    news_ids = values.get("news_ids") or []
    news = get_news_references(news_ids)
    specification = {
        "topic": instruction,
        "article_type": article_type,
        "audience": str(values.get("audience") or "").strip(),
        "style": str(values.get("style") or "").strip(),
        "requirements": str(values.get("requirements") or "").strip(),
        "word_count": int(values.get("word_count") or 1200),
        "image_count": image_count,
        "materials": format_material_context(materials),
        "material_ids": [item["id"] for item in materials],
        "news": format_news_context(news),
        "news_ids": [item["id"] for item in news],
    }
    draft = AIContentService(settings).generate_article(specification)
    return {
        "target": target,
        "image_count": image_count,
        "image_mode": values.get("image_mode", "auto"),
        "draft": draft,
        "references": {
            "material_ids": specification["material_ids"],
            "news_ids": specification["news_ids"],
        },
    }


def execute_assistant(values, settings=None):
    settings = settings or get_settings()
    if not settings["ai_enabled"]:
        raise RuntimeError("AI 内容生成尚未启用")
    target = str(values.get("target") or "").strip()
    draft = values.get("draft")
    if target not in ASSISTANT_TARGETS:
        raise ValueError("助手目标类型无效")
    if not isinstance(draft, dict):
        raise ValueError("请先生成并确认预览")

    if target == "article":
        item = _save_article(draft, values, settings)
        return {
            "target": target,
            "destination": "articles",
            "item": item,
            "message": "AI 稿件已写入内容库",
        }

    if target == "note":
        clean = AIContentService.validate_assistant_item(target, draft)
        item = create_note_material(
            {
                "title": clean["title"],
                "content_md": clean["content_md"],
                "description": clean["summary"],
                "tags": clean["tags"],
            }
        )
        return {
            "target": target,
            "destination": "materials",
            "item": item,
            "message": "卡片笔记已写入素材库",
        }

    if target == "news":
        clean = AIContentService.validate_assistant_item(target, draft)
        source_url = str(values.get("source_url") or "").strip()
        if not source_url:
            raise ValueError("新建资讯必须提供原始来源链接")
        item = create_news(
            {
                "title": clean["title"],
                "source_name": str(values.get("source_name") or "").strip()
                or clean["source_name"],
                "source_url": source_url,
                "summary": clean["summary"],
                "content_md": clean["content_md"],
                "tags": clean["tags"],
            }
        )
        return {
            "target": target,
            "destination": "news",
            "item": item,
            "message": "资讯已写入资讯库",
        }

    clean = AIContentService.validate_assistant_item(target, draft)
    generated = AIImageService(settings).generate_images(
        [
            {
                "position": "material:1",
                "alt": clean["title"],
                "purpose": clean["summary"],
                "prompt": clean["image_prompt"],
            }
        ]
    )[0]
    item = create_generated_image_material(
        generated,
        {
            "title": clean["title"],
            "description": clean["summary"],
            "tags": clean["tags"],
        },
    )
    return {
        "target": target,
        "destination": "materials",
        "item": item,
        "message": "AI 图片已生成并写入素材库",
    }


def _save_article(draft, values, settings):
    article_type = str(values.get("article_type") or "article").strip()
    image_count = int(values.get("image_count") or 0)
    if article_type not in {"article", "image"}:
        raise ValueError("文章类型必须是 article 或 image")
    if image_count < 0 or image_count > 9:
        raise ValueError("配图数量必须在 0-9 之间")
    if article_type == "image" and image_count < 1:
        raise ValueError("图文内容至少需要 1 张图片")
    generated = AIContentService._validate_generated_article(draft, image_count)
    references = values.get("references") or {}
    materials = get_material_references(references.get("material_ids") or [])
    news = get_news_references(references.get("news_ids") or [])
    material_ids = [item["id"] for item in materials]
    news_ids = [item["id"] for item in news]

    images = AIImageService(settings).generate_images(generated["image_plan"])
    content_md = _insert_generated_images(generated["content_md"], images)
    media_paths = [image["path"] for image in images]
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
    ai_result = {
        "source": "assistant",
        "summary": generated["summary"],
        "editor_notes": "AI 生成初稿，请在发布前核对事实、图片与平台要求。",
        "tags": generated["tags"],
        "image_mode": values.get("image_mode", "auto"),
        "image_count": image_count,
        "image_plan": generated["image_plan"],
        "generated_images": images,
        "material_ids": material_ids,
        "news_ids": news_ids,
        "platforms": {},
    }
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
    return get_article(article["id"])