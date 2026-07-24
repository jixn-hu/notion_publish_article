from contextlib import asynccontextmanager
import logging
from pathlib import Path
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.logging_config import configure_logging


from backend.ai_service import AIContentService
from backend.db import init_db
from backend.platforms import get_platforms
from backend.scheduler import AutomationScheduler
from backend.services import (
    create_article,
    dashboard_summary,
    enrich_article,
    get_article,
    list_articles,
    notion_client,
    publish_article,
    run_auto_publish,
    sync_from_notion,
    update_article,
)
from backend.settings import (
    get_setting_metadata,
    get_settings,
    migrate_legacy_config,
    update_settings,
)


configure_logging()
logger = logging.getLogger("mozhou.api")
scheduler = AutomationScheduler()


@asynccontextmanager
async def lifespan(_app):
    init_db()
    get_settings()
    migrate_legacy_config()
    scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(
    title="墨舟 · 内容发布台",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_log(request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.exception(
            "HTTP 请求异常 method=%s path=%s elapsed_ms=%.1f",
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000
    log = logger.debug if request.url.path == "/api/health" else logger.info
    log(
        "HTTP 请求完成 method=%s path=%s status=%s elapsed_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SettingsPayload(BaseModel):
    values: dict[str, Any]


class ArticlePayload(BaseModel):
    title: str
    author: str = ""
    article_type: str = "article"
    content_md: str = ""
    cover_url: str = ""
    source_url: str = ""
    tags: list[str] = Field(default_factory=list)
    publish_mode: str = "manual"
    target_platforms: list[str] = Field(default_factory=lambda: ["wechat"])
    platform_actions: dict[str, str] = Field(
        default_factory=lambda: {"wechat": "draft"}
    )


class ArticleUpdatePayload(BaseModel):
    title: str | None = None
    author: str | None = None
    article_type: str | None = None
    content_md: str | None = None
    cover_url: str | None = None
    source_url: str | None = None
    tags: list[str] | None = None
    publish_mode: str | None = None
    target_platforms: list[str] | None = None
    platform_actions: dict[str, str] | None = None
    ai_result: dict[str, Any] | None = None
    status: str | None = None


class PublishPayload(BaseModel):
    platform_actions: dict[str, str] | None = None


def api_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/health")
def health():
    return {"status": "ok", "scheduler": scheduler.status()}


@app.get("/api/dashboard")
def dashboard():
    return dashboard_summary()


@app.get("/api/settings")
def settings_get():
    return {
        "values": get_settings(mask_secrets=True),
        "metadata": get_setting_metadata(),
    }


@app.put("/api/settings")
def settings_put(payload: SettingsPayload):
    return {"values": api_call(update_settings, payload.values)}


@app.post("/api/connections/notion/test")
def notion_test():
    return api_call(notion_client().test_connection)


@app.get("/api/connections/notion/schema")
def notion_schema():
    return api_call(notion_client().get_schema)


@app.post("/api/connections/ai/test")
def ai_test():
    return api_call(AIContentService(get_settings()).test_connection)


@app.get("/api/platforms")
def platforms_get():
    settings = get_settings()
    return [platform.status() for platform in get_platforms(settings).values()]


@app.post("/api/platforms/{platform_key}/test")
def platform_test(platform_key: str):
    platforms = get_platforms(get_settings())
    if platform_key not in platforms:
        raise HTTPException(status_code=404, detail="平台不存在")
    return api_call(platforms[platform_key].test_connection)


@app.get("/api/articles")
def articles_get(
    status: str | None = None,
    q: str | None = Query(default=None, max_length=100),
):
    return list_articles(status=status, query=q)


@app.post("/api/articles", status_code=201)
def articles_post(payload: ArticlePayload):
    return api_call(create_article, payload.model_dump())


@app.get("/api/articles/{article_id}")
def article_get(article_id: int):
    return api_call(get_article, article_id)


@app.patch("/api/articles/{article_id}")
def article_patch(article_id: int, payload: ArticleUpdatePayload):
    values = payload.model_dump(exclude_none=True)
    return api_call(update_article, article_id, values)


@app.post("/api/articles/{article_id}/publish")
def article_publish(article_id: int, payload: PublishPayload):
    return api_call(publish_article, article_id, payload.platform_actions)


@app.post("/api/articles/{article_id}/enrich")
def article_enrich(article_id: int):
    return api_call(enrich_article, article_id)


@app.post("/api/sync/notion")
def sync_notion():
    return api_call(sync_from_notion)


@app.post("/api/automation/publish")
def automation_publish():
    return api_call(run_auto_publish)


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="frontend-assets",
    )

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        candidate = FRONTEND_DIST / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
