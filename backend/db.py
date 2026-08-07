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
                content_status TEXT NOT NULL DEFAULT 'draft',
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
                account_id INTEGER,
                trigger_source TEXT NOT NULL DEFAULT 'manual',
                forced INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                external_id TEXT,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                published_at TEXT,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS article_platform_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                action TEXT NOT NULL,
                account_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                external_id TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
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

            CREATE TABLE IF NOT EXISTS wechat_account_settings (
                account_id INTEGER PRIMARY KEY,
                publish_method TEXT NOT NULL DEFAULT 'browser',
                api_connection_mode TEXT NOT NULL DEFAULT 'direct',
                api_base_url TEXT NOT NULL DEFAULT 'http://127.0.0.1:8701/wechat',
                app_id TEXT NOT NULL DEFAULT '',
                app_secret_encrypted TEXT NOT NULL DEFAULT '',
                api_status TEXT NOT NULL DEFAULT 'pending',
                api_capabilities_json TEXT NOT NULL DEFAULT '{}',
                api_last_error TEXT NOT NULL DEFAULT '',
                api_last_checked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                path TEXT NOT NULL DEFAULT '',
                content_md TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                mime_type TEXT NOT NULL DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS article_materials (
                article_id INTEGER NOT NULL,
                material_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(article_id, material_id),
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(material_id) REFERENCES materials(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source_name TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL UNIQUE,
                author TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                content_md TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                published_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS article_news (
                article_id INTEGER NOT NULL,
                news_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(article_id, news_id),
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(news_id) REFERENCES news_items(id) ON DELETE CASCADE
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

            CREATE INDEX IF NOT EXISTS idx_materials_kind
                ON materials(kind, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_article_materials_material
                ON article_materials(material_id);
            CREATE INDEX IF NOT EXISTS idx_news_items_updated
                ON news_items(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_article_news_news
                ON article_news(news_id);
            CREATE INDEX IF NOT EXISTS idx_articles_status
                ON articles(status);
            CREATE INDEX IF NOT EXISTS idx_publish_records_article
                ON publish_records(article_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_article_platform_states_status
                ON article_platform_states(status, updated_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_article_platform_states_target
                ON article_platform_states(
                    article_id, platform, COALESCE(account_id, 0)
                );
            """
        )
        _migrate_platform_state_identity(conn)
        _ensure_columns(
            conn,
            "publish_records",
            {
                "action": "TEXT NOT NULL DEFAULT 'publish'",
                "account_id": "INTEGER",
                "trigger_source": "TEXT NOT NULL DEFAULT 'manual'",
                "forced": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        # 将旧发布记录迁移为平台状态，升级后也能避免重复发布。
        now = utc_now()
        conn.execute(
            """
            INSERT OR IGNORE INTO article_platform_states (
                article_id, platform, action, account_id, status, attempts,
                external_id, last_error, started_at, completed_at,
                created_at, updated_at
            )
            SELECT
                r.article_id,
                r.platform,
                r.action,
                r.account_id,
                r.status,
                (
                    SELECT COUNT(*) FROM publish_records counted
                    WHERE counted.article_id = r.article_id
                      AND counted.platform = r.platform
                      AND COALESCE(counted.account_id, 0) = COALESCE(r.account_id, 0)
                ),
                COALESCE(r.external_id, ''),
                r.error,
                NULL,
                r.published_at,
                r.created_at,
                ?
            FROM publish_records r
            WHERE r.id = (
                SELECT MAX(latest.id) FROM publish_records latest
                WHERE latest.article_id = r.article_id
                  AND latest.platform = r.platform
                  AND COALESCE(latest.account_id, 0) = COALESCE(r.account_id, 0)
            )
              AND r.status IN ('drafted', 'published', 'failed')
              AND NOT EXISTS (
                  SELECT 1 FROM article_platform_states state
                  WHERE state.article_id = r.article_id
                    AND state.platform = r.platform
                    AND COALESCE(state.account_id, 0) = COALESCE(r.account_id, 0)
              )
            """,
            (now,),
        )
        added_article_columns = _ensure_columns(
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
                "content_status": "TEXT NOT NULL DEFAULT 'draft'",
            },
        )
        if "content_status" in added_article_columns:
            conn.execute(
                """
                UPDATE articles
                SET content_status = CASE
                    WHEN publish_mode = 'automatic' THEN 'ready'
                    ELSE 'draft'
                END
                """
            )
            conn.execute(
                """
                UPDATE articles
                SET status = 'draft'
                WHERE content_status = 'draft' AND status = 'ready'
                """
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
        _ensure_columns(
            conn,
            "wechat_account_settings",
            {
                "api_connection_mode": "TEXT NOT NULL DEFAULT 'direct'",
                "api_base_url": (
                    "TEXT NOT NULL DEFAULT 'http://127.0.0.1:8701/wechat'"
                ),
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


def _migrate_platform_state_identity(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("article_platform_states",),
    ).fetchone()
    table_sql = "" if not row else str(row["sql"] or "").replace(" ", "").lower()
    if "unique(article_id,platform)" not in table_sql:
        return

    conn.executescript(
        """
        DROP INDEX IF EXISTS idx_article_platform_states_target;
        CREATE TABLE article_platform_states_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            action TEXT NOT NULL,
            account_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            external_id TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
        );
        INSERT INTO article_platform_states_v2 (
            id, article_id, platform, action, account_id, status, attempts,
            external_id, last_error, started_at, completed_at, created_at,
            updated_at
        )
        SELECT
            id, article_id, platform, action, account_id, status, attempts,
            external_id, last_error, started_at, completed_at, created_at,
            updated_at
        FROM article_platform_states;
        DROP TABLE article_platform_states;
        ALTER TABLE article_platform_states_v2 RENAME TO article_platform_states;
        CREATE INDEX idx_article_platform_states_status
            ON article_platform_states(status, updated_at);
        CREATE UNIQUE INDEX idx_article_platform_states_target
            ON article_platform_states(
                article_id, platform, COALESCE(account_id, 0)
            );
        """
    )


def _ensure_columns(conn, table, columns):
    existing = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    added = set()
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            added.add(name)
    return added


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
