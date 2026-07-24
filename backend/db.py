import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "publisher.db"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                is_secret INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT,
                notion_page_id TEXT UNIQUE,
                notion_url TEXT,
                title TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                article_type TEXT NOT NULL DEFAULT 'article',
                content_md TEXT NOT NULL DEFAULT '',
                cover_url TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                media_paths_json TEXT NOT NULL DEFAULT '[]',
                publish_mode TEXT NOT NULL DEFAULT 'manual',
                target_platforms_json TEXT NOT NULL DEFAULT '["wechat"]',
                platform_actions_json TEXT NOT NULL DEFAULT '{"wechat":"draft"}',
                platform_accounts_json TEXT NOT NULL DEFAULT '{}',
                ai_result_json TEXT NOT NULL DEFAULT '{}',
                ai_enriched_at TEXT,
                status TEXT NOT NULL DEFAULT 'ready',
                last_error TEXT NOT NULL DEFAULT '',
                last_synced_at TEXT,
                published_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS publish_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT 'publish',
                status TEXT NOT NULL,
                external_id TEXT,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                published_at TEXT,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                proxy_url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                exit_ip TEXT NOT NULL DEFAULT '',
                last_latency_ms INTEGER,
                last_error TEXT NOT NULL DEFAULT '',
                last_checked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                name TEXT NOT NULL,
                profile_dir TEXT NOT NULL DEFAULT '',
                proxy_url TEXT NOT NULL DEFAULT '',
                proxy_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                last_error TEXT NOT NULL DEFAULT '',
                last_checked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(proxy_id) REFERENCES proxies(id),
                UNIQUE(platform, name)
            );

            CREATE TABLE IF NOT EXISTS article_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                source_key TEXT NOT NULL,
                source_url TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'content',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                UNIQUE(article_id, source_key)
            );

            CREATE TABLE IF NOT EXISTS platform_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL,
                platform TEXT NOT NULL,
                media_id TEXT NOT NULL,
                media_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source_key, platform)
            );

            CREATE INDEX IF NOT EXISTS idx_articles_status
                ON articles(status);
            CREATE INDEX IF NOT EXISTS idx_publish_records_article
                ON publish_records(article_id, created_at DESC);
            """
        )
        _ensure_columns(
            conn,
            "articles",
            {
                "source_key": "TEXT",
                "platform_actions_json": (
                    "TEXT NOT NULL DEFAULT '{\"wechat\":\"draft\"}'"
                ),
                "ai_result_json": "TEXT NOT NULL DEFAULT '{}'",
                "ai_enriched_at": "TEXT",
                "media_paths_json": "TEXT NOT NULL DEFAULT '[]'",
                "platform_accounts_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        )
        _ensure_columns(
            conn,
            "publish_records",
            {"action": "TEXT NOT NULL DEFAULT 'publish'"},
        )
        _ensure_columns(
            conn,
            "accounts",
            {
                "profile_json": "TEXT NOT NULL DEFAULT '{}'",
                "profile_synced_at": "TEXT",
                "profile_error": "TEXT NOT NULL DEFAULT ''",
                "proxy_url": "TEXT NOT NULL DEFAULT ''",
                "proxy_id": "INTEGER",
            },
        )
        conn.execute(
            """
            UPDATE articles
            SET source_key = 'notion:page:' || notion_page_id
            WHERE source_key IS NULL AND notion_page_id IS NOT NULL
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_source_key
            ON articles(source_key)
            WHERE source_key IS NOT NULL
            """
        )


def _ensure_columns(conn, table, columns):
    existing = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def row_to_article(row):
    article = dict(row)
    article["tags"] = json.loads(article.pop("tags_json") or "[]")
    article["target_platforms"] = json.loads(
        article.pop("target_platforms_json") or "[]"
    )
    article["platform_actions"] = json.loads(
        article.pop("platform_actions_json") or "{}"
    )
    article["media_paths"] = json.loads(article.pop("media_paths_json") or "[]")
    article["platform_accounts"] = json.loads(
        article.pop("platform_accounts_json") or "{}"
    )
    article["ai_result"] = json.loads(article.pop("ai_result_json") or "{}")
    return article
