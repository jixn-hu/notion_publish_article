import importlib
import json
import sqlite3
from pathlib import Path

from backend.db import DATA_DIR, connection, utc_now


SUPPORTED_ACCOUNT_PLATFORMS = {
    "xiaohongshu",
    "douyin",
    "channels",
    "bilibili",
}
ACCOUNT_PLATFORM_NAMES = {
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "channels": "视频号",
    "bilibili": "Bilibili",
}
ACCOUNT_HANDLERS = {
    "xiaohongshu": (
        "backend.platforms.xiaohongshu",
        "login_xiaohongshu_account",
        "check_xiaohongshu_account",
    ),
    "douyin": (
        "backend.platforms.douyin",
        "login_douyin_account",
        "check_douyin_account",
    ),
    "channels": (
        "backend.platforms.channels",
        "login_channels_account",
        "check_channels_account",
    ),
    "bilibili": (
        "backend.platforms.bilibili",
        "login_bilibili_account",
        "check_bilibili_account",
    ),
}
ACCOUNT_PROFILE_HANDLERS = {
    "xiaohongshu": (
        "backend.platforms.xiaohongshu",
        "fetch_xiaohongshu_profile",
    ),
    "douyin": (
        "backend.platforms.douyin",
        "fetch_douyin_profile",
    ),
    "channels": (
        "backend.platforms.channels",
        "fetch_channels_profile",
    ),
}
PROFILE_ROOT = DATA_DIR / "browser_profiles"
AVATAR_ROOT = DATA_DIR / "account_avatars"


def account_avatar_path(account):
    return AVATAR_ROOT / f"{account['platform']}-{account['id']}.png"


def _row_to_account(row):
    account = dict(row)
    selected_proxy_url = account.pop("selected_proxy_url", "") or ""
    proxy_name = account.pop("proxy_name", "") or ""
    proxy_status = account.pop("proxy_status", "") or ""
    if account.get("proxy_id"):
        account["proxy"] = {
            "id": account["proxy_id"],
            "name": proxy_name,
            "proxy_url": selected_proxy_url,
            "status": proxy_status,
        }
    else:
        account["proxy"] = None
    account["proxy_url"] = selected_proxy_url or account.get("proxy_url", "")
    account["profile"] = json.loads(account.pop("profile_json") or "{}")
    return account


def list_accounts(platform=None):
    params = []
    where = ""
    if platform:
        where = "WHERE platform = ?"
        params.append(platform)
    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT accounts.*,
                   proxies.name AS proxy_name,
                   proxies.proxy_url AS selected_proxy_url,
                   proxies.status AS proxy_status
            FROM accounts
            LEFT JOIN proxies ON proxies.id = accounts.proxy_id
            {where}
            ORDER BY accounts.platform, accounts.created_at
            """,
            params,
        ).fetchall()
    return [_row_to_account(row) for row in rows]


def get_account(account_id):
    with connection() as conn:
        row = conn.execute(
            """
            SELECT accounts.*,
                   proxies.name AS proxy_name,
                   proxies.proxy_url AS selected_proxy_url,
                   proxies.status AS proxy_status
            FROM accounts
            LEFT JOIN proxies ON proxies.id = accounts.proxy_id
            WHERE accounts.id = ?
            """,
            (account_id,),
        ).fetchone()
    if not row:
        raise LookupError("账号不存在")
    return _row_to_account(row)


def create_account(platform, name):
    platform = str(platform or "").strip().lower()
    name = str(name or "").strip()
    if platform not in SUPPORTED_ACCOUNT_PLATFORMS:
        raise ValueError("该平台暂不支持添加浏览器账号")
    if not name:
        raise ValueError("账号名称不能为空")
    if len(name) > 50:
        raise ValueError("账号名称不能超过 50 个字符")

    now = utc_now()
    try:
        with connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO accounts (
                    platform, name, status, created_at, updated_at
                ) VALUES (?, ?, 'pending', ?, ?)
                """,
                (platform, name, now, now),
            )
            account_id = cursor.lastrowid
            profile_dir = PROFILE_ROOT / platform / str(account_id)
            conn.execute(
                "UPDATE accounts SET profile_dir = ? WHERE id = ?",
                (str(profile_dir.resolve()), account_id),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("同平台下已存在同名账号") from exc
    return get_account(account_id)


def update_account_status(account_id, status, error=""):
    now = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            """
            UPDATE accounts
            SET status = ?, last_error = ?, last_checked_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, str(error or ""), now, now, account_id),
        )
        if not cursor.rowcount:
            raise LookupError("账号不存在")
    return get_account(account_id)


def update_account_profile(account_id, profile):
    now = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            """
            UPDATE accounts
            SET profile_json = ?, profile_synced_at = ?,
                profile_error = '', updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(profile, ensure_ascii=False),
                now,
                now,
                account_id,
            ),
        )
        if not cursor.rowcount:
            raise LookupError("账号不存在")
    return get_account(account_id)


def update_account_profile_error(account_id, error):
    with connection() as conn:
        cursor = conn.execute(
            """
            UPDATE accounts
            SET profile_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (str(error or ""), utc_now(), account_id),
        )
        if not cursor.rowcount:
            raise LookupError("账号不存在")
    return get_account(account_id)


def update_account_proxy(account_id, proxy_id):
    if proxy_id is not None:
        try:
            proxy_id = int(proxy_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("代理 ID 格式不正确") from exc
    with connection() as conn:
        if proxy_id is not None:
            proxy = conn.execute(
                "SELECT id FROM proxies WHERE id = ?",
                (proxy_id,),
            ).fetchone()
            if not proxy:
                raise LookupError("代理不存在")
        cursor = conn.execute(
            """
            UPDATE accounts
            SET proxy_id = ?, proxy_url = '', updated_at = ?
            WHERE id = ?
            """,
            (proxy_id, utc_now(), account_id),
        )
        if not cursor.rowcount:
            raise LookupError("账号不存在")
    return get_account(account_id)


def _fetch_account_profile(account):
    handler = ACCOUNT_PROFILE_HANDLERS.get(account["platform"])
    if not handler:
        raise NotImplementedError("该平台暂未接入账号资料同步")
    module_name, function_name = handler
    return getattr(importlib.import_module(module_name), function_name)(account)


def refresh_account_profile(account_id):
    account = get_account(account_id)
    if account["status"] != "valid":
        raise RuntimeError("请先登录账号，再同步账号资料")
    try:
        return update_account_profile(
            account_id,
            _fetch_account_profile(account),
        )
    except Exception as exc:
        update_account_profile_error(account_id, exc)
        raise


def _refresh_profile_without_changing_login_status(account_id):
    try:
        return refresh_account_profile(account_id)
    except Exception:
        return get_account(account_id)


def login_account(account_id):
    account = get_account(account_id)
    try:
        module_name, login_name, _ = ACCOUNT_HANDLERS[account["platform"]]
        login_handler = getattr(importlib.import_module(module_name), login_name)
        login_handler(account)
        update_account_status(account_id, "valid")
        return _refresh_profile_without_changing_login_status(account_id)
    except Exception as exc:
        update_account_status(account_id, "invalid", str(exc))
        raise


def check_account(account_id):
    account = get_account(account_id)
    try:
        module_name, _, check_name = ACCOUNT_HANDLERS[account["platform"]]
        check_handler = getattr(importlib.import_module(module_name), check_name)
        valid = check_handler(account)
        if not valid:
            raise RuntimeError("登录状态已失效，请重新登录")
        update_account_status(account_id, "valid")
        return _refresh_profile_without_changing_login_status(account_id)
    except Exception as exc:
        update_account_status(account_id, "invalid", str(exc))
        raise


def resolve_publish_account(platform, account_id=None):
    if account_id is not None:
        account = get_account(int(account_id))
        if account["platform"] != platform:
            raise ValueError("所选账号与发布平台不匹配")
        if account["status"] != "valid":
            raise RuntimeError("所选账号尚未登录或登录状态已失效")
        return account

    accounts = [
        item
        for item in list_accounts(platform)
        if item["status"] == "valid"
    ]
    if not accounts:
        platform_name = ACCOUNT_PLATFORM_NAMES.get(platform, platform)
        raise RuntimeError(f"请先添加并登录{platform_name}账号")
    if len(accounts) > 1:
        raise RuntimeError("存在多个可用账号，请在稿件中选择发布账号")
    return accounts[0]
