from contextlib import asynccontextmanager
import logging
from pathlib import Path
import time
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.logging_config import configure_logging


from backend.ai_service import AIContentService
from backend.accounts import (
    account_avatar_path,
    check_account,
    create_account,
    get_account,
    list_accounts,
    login_account,
    open_account_view,
    refresh_account_profile,
    update_account_proxy,
)
from backend.db import init_db
from backend.media import resolve_media_file, save_upload
from backend.materials import (
    create_file_material,
    create_material_archive,
    create_note_material,
    delete_material,
    get_material,
    list_materials,
    resolve_material_file,
    update_material,
)
from backend.news import (
    collect_news,
    create_news,
    delete_news,
    get_news,
    list_news,
    update_news,
)
from backend.platforms import get_platforms
from backend.proxies import (
    create_proxy,
    delete_proxy,
    list_proxies,
    test_proxy,
)
from backend.scheduler import AutomationScheduler
from backend.services import (
    create_article,
    dashboard_summary,
    enrich_article,
    generate_ai_article,
    generate_ai_storyboard,
    get_article,
    list_articles,
    notion_client,
    publish_article,
    regenerate_ai_image,
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
    media_paths: list[str] = Field(default_factory=list)
    publish_mode: str = "manual"
    target_platforms: list[str] = Field(default_factory=lambda: ["wechat"])
    platform_actions: dict[str, str] = Field(
        default_factory=lambda: {"wechat": "draft"}
    )
    platform_accounts: dict[str, int] = Field(default_factory=dict)


class AIGeneratePayload(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    article_type: str = "article"
    author: str = Field(default="", max_length=50)
    audience: str = Field(default="", max_length=200)
    style: str = Field(default="", max_length=100)
    requirements: str = Field(default="", max_length=2000)
    word_count: int = Field(default=1200, ge=300, le=5000)
    image_count: int = Field(default=1, ge=0, le=9)
    storyboard: dict[str, Any] | None = None
    material_ids: list[int] = Field(default_factory=list, max_length=20)
    news_ids: list[int] = Field(default_factory=list, max_length=20)


class ArticleUpdatePayload(BaseModel):
    title: str | None = None
    author: str | None = None
    article_type: str | None = None
    content_md: str | None = None
    cover_url: str | None = None
    source_url: str | None = None
    tags: list[str] | None = None
    media_paths: list[str] | None = None
    publish_mode: str | None = None
    target_platforms: list[str] | None = None
    platform_actions: dict[str, str] | None = None
    platform_accounts: dict[str, int] | None = None
    ai_result: dict[str, Any] | None = None
    status: str | None = None


class MaterialNotePayload(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content_md: str = Field(min_length=1, max_length=20000)
    description: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=12)


class MaterialUpdatePayload(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    content_md: str | None = Field(default=None, max_length=20000)
    description: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = Field(default=None, max_length=12)


class MaterialDownloadPayload(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


class NewsPayload(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source_name: str = Field(default="", max_length=120)
    source_url: str = Field(min_length=8, max_length=2000)
    author: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=1000)
    content_md: str = Field(default="", max_length=50000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    published_at: str | None = Field(default=None, max_length=100)


class NewsUpdatePayload(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    source_name: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=2000)
    author: str | None = Field(default=None, max_length=120)
    summary: str | None = Field(default=None, max_length=1000)
    content_md: str | None = Field(default=None, max_length=50000)
    tags: list[str] | None = Field(default=None, max_length=12)
    published_at: str | None = Field(default=None, max_length=100)


class NewsCollectPayload(BaseModel):
    url: str = Field(min_length=8, max_length=2000)

class PublishPayload(BaseModel):
    platform_actions: dict[str, str] | None = None


class AccountPayload(BaseModel):
    platform: str
    name: str


class AccountProxyPayload(BaseModel):
    proxy_id: int | None = None


class ProxyPayload(BaseModel):
    name: str
    proxy_url: str


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


@app.get("/api/accounts")
def accounts_get(platform: str | None = None):
    return list_accounts(platform)


@app.post("/api/accounts", status_code=201)
def accounts_post(payload: AccountPayload):
    return api_call(create_account, payload.platform, payload.name)



@app.post("/api/accounts/{account_id}/browser")
def account_browser(account_id: int):
    return api_call(open_account_view, account_id)

@app.post("/api/accounts/{account_id}/login")
def account_login(account_id: int):
    return api_call(login_account, account_id)


@app.post("/api/accounts/{account_id}/check")
def account_check(account_id: int):
    return api_call(check_account, account_id)


@app.post("/api/accounts/{account_id}/profile")
def account_profile(account_id: int):
    return api_call(refresh_account_profile, account_id)


@app.put("/api/accounts/{account_id}/proxy")
def account_proxy(account_id: int, payload: AccountProxyPayload):
    return api_call(update_account_proxy, account_id, payload.proxy_id)


@app.get("/api/proxies")
def proxies_get():
    return list_proxies()


@app.post("/api/proxies", status_code=201)
def proxies_post(payload: ProxyPayload):
    return api_call(create_proxy, payload.name, payload.proxy_url)


@app.post("/api/proxies/{proxy_id}/test")
def proxy_test(proxy_id: int):
    return api_call(test_proxy, proxy_id)


@app.delete("/api/proxies/{proxy_id}")
def proxy_delete(proxy_id: int):
    return api_call(delete_proxy, proxy_id)


@app.get("/api/accounts/{account_id}/avatar")
def account_avatar(account_id: int):
    account = api_call(get_account, account_id)
    path = account_avatar_path(account)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="账号头像尚未同步")
    return FileResponse(path, media_type="image/png")


@app.post("/api/media", status_code=201)
def media_post(file: UploadFile = File(...)):
    return api_call(save_upload, file)


@app.get("/api/media/file")
def media_file(path: str = Query(min_length=1, max_length=1000)):
    return FileResponse(api_call(resolve_media_file, path))


@app.get("/api/materials")
def materials_get(
    kind: str | None = Query(default=None, max_length=20),
    q: str | None = Query(default=None, max_length=100),
):
    return api_call(list_materials, kind=kind, query=q)


@app.post("/api/materials/files", status_code=201)
def materials_file_post(file: UploadFile = File(...)):
    return api_call(create_file_material, file)


@app.post("/api/materials/notes", status_code=201)
def materials_note_post(payload: MaterialNotePayload):
    return api_call(create_note_material, payload.model_dump())


@app.post("/api/materials/download")
def materials_download(payload: MaterialDownloadPayload):
    archive = api_call(create_material_archive, payload.ids)
    return FileResponse(
        archive,
        media_type="application/zip",
        filename="materials.zip",
        background=BackgroundTask(archive.unlink, missing_ok=True),
    )


@app.get("/api/materials/{material_id}")
def material_get(material_id: int):
    return api_call(get_material, material_id)


@app.patch("/api/materials/{material_id}")
def material_patch(material_id: int, payload: MaterialUpdatePayload):
    return api_call(
        update_material,
        material_id,
        payload.model_dump(exclude_none=True),
    )


@app.delete("/api/materials/{material_id}")
def material_delete(material_id: int):
    return api_call(delete_material, material_id)


@app.get("/api/materials/{material_id}/file")
def material_file(material_id: int):
    material, path = api_call(resolve_material_file, material_id)
    return FileResponse(path, media_type=material["mime_type"] or None)


@app.get("/api/news")
def news_list_get(
    q: str | None = Query(default=None, max_length=100),
    source: str | None = Query(default=None, max_length=120),
):
    return api_call(list_news, query=q, source=source)


@app.post("/api/news", status_code=201)
def news_post(payload: NewsPayload):
    return api_call(create_news, payload.model_dump())


@app.post("/api/news/collect", status_code=201)
def news_collect_post(payload: NewsCollectPayload):
    return api_call(collect_news, payload.url)


@app.get("/api/news/{news_id}")
def news_get(news_id: int):
    return api_call(get_news, news_id)


@app.patch("/api/news/{news_id}")
def news_patch(news_id: int, payload: NewsUpdatePayload):
    return api_call(update_news, news_id, payload.model_dump(exclude_none=True))


@app.delete("/api/news/{news_id}")
def news_delete(news_id: int):
    return api_call(delete_news, news_id)

@app.get("/api/articles")
def articles_get(
    status: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    article_type: str | None = Query(default=None, max_length=20),
):
    return api_call(
        list_articles,
        status=status,
        query=q,
        article_type=article_type,
    )


@app.post("/api/articles", status_code=201)
def articles_post(payload: ArticlePayload):
    return api_call(create_article, payload.model_dump())


@app.post("/api/articles/generate-storyboard")
def articles_generate_storyboard(payload: AIGeneratePayload):
    values = payload.model_dump()
    values["article_type"] = "image"
    return api_call(generate_ai_storyboard, values)


@app.post("/api/articles/generate", status_code=201)
def articles_generate(payload: AIGeneratePayload):
    return api_call(generate_ai_article, payload.model_dump())

@app.get("/api/articles/{article_id}")
def article_get(article_id: int):
    return api_call(get_article, article_id)


@app.patch("/api/articles/{article_id}")
def article_patch(article_id: int, payload: ArticleUpdatePayload):
    values = payload.model_dump(exclude_none=True)
    return api_call(update_article, article_id, values)


@app.post("/api/articles/{article_id}/images/{image_index}/regenerate")
def article_image_regenerate(article_id: int, image_index: int):
    return api_call(regenerate_ai_image, article_id, image_index)

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
            if candidate.name == "index.html":
                return FileResponse(
                    candidate,
                    headers={"Cache-Control": "no-cache"},
                )
            return FileResponse(candidate)
        return FileResponse(
            FRONTEND_DIST / "index.html",
            headers={"Cache-Control": "no-cache"},
        )
