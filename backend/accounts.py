import importlib
import json
import sqlite3
import shutil
import time
from pathlib import Path

from backend.browser import get_or_create_page, open_account_browser, open_account_dashboard
from backend.db import DATA_DIR, connection, utc_now
from backend.secret_store import decrypt_secret, encrypt_secret


SUPPORTED_ACCOUNT_PLATFORMS = {
    "wechat",
    "xiaohongshu",
    "douyin",
    "channels",
    "bilibili",
    "csdn",
}
ACCOUNT_PLATFORM_NAMES = {
    "wechat": "微信公众号",
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "channels": "视频号",
    "bilibili": "Bilibili",
    "csdn": "CSDN",
}
ACCOUNT_HANDLERS = {
    "wechat": (
        "backend.platforms.wechat_browser",
        "login_wechat_account",
        "check_wechat_account",
    ),
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
    "csdn": (
        "backend.platforms.csdn",
        "login_csdn_account",
        "check_csdn_account",
    ),
}
ACCOUNT_PROFILE_HANDLERS = {
    "wechat": (
        "backend.platforms.wechat_browser",
        "fetch_wechat_profile",
    ),
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
    "bilibili": (
        "backend.platforms.bilibili",
        "fetch_bilibili_profile",
    ),
    "csdn": (
        "backend.platforms.csdn",
        "fetch_csdn_profile",
    ),
}
ACCOUNT_MANAGEMENT_HANDLERS = {
    "wechat": (
        "backend.platforms.wechat_browser",
        "wechat_dashboard_url",
        "_is_logged_in",
    ),
    "xiaohongshu": (
        "backend.platforms.xiaohongshu",
        "PROFILE_URL",
        "_is_logged_in",
    ),
    "douyin": (
        "backend.platforms.douyin",
        "PROFILE_URL",
        "_is_logged_in",
    ),
    "channels": (
        "backend.platforms.channels",
        "PROFILE_URL",
        "_is_logged_in",
    ),
    "bilibili": (
        "backend.platforms.bilibili",
        "bilibili_account_url",
        "_is_logged_in",
    ),
    "csdn": (
        "backend.platforms.csdn",
        "HOME_URL",
        "_is_logged_in",
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
    if account["platform"] == "wechat":
        account["wechat"] = {
            "publish_method": account.pop("wechat_publish_method", None)
            or "browser",
            "app_id": account.pop("wechat_app_id", None) or "",
            "app_secret_configured": bool(
                account.pop("wechat_app_secret_encrypted", None)
            ),
            "api_status": account.pop("wechat_api_status", None) or "pending",
            "api_capabilities": json.loads(
                account.pop("wechat_api_capabilities_json", None) or "{}"
            ),
            "api_last_error": account.pop("wechat_api_last_error", None) or "",
            "api_last_checked_at": account.pop(
                "wechat_api_last_checked_at", None
            ),
        }
    else:
        for key in (
            "wechat_publish_method",
            "wechat_app_id",
            "wechat_app_secret_encrypted",
            "wechat_api_status",
            "wechat_api_capabilities_json",
            "wechat_api_last_error",
            "wechat_api_last_checked_at",
        ):
            account.pop(key, None)
    return account


ACCOUNT_SELECT = """
    SELECT accounts.*,
           proxies.name AS proxy_name,
           proxies.proxy_url AS selected_proxy_url,
           proxies.status AS proxy_status,
           wechat_account_settings.publish_method AS wechat_publish_method,
           wechat_account_settings.app_id AS wechat_app_id,
           wechat_account_settings.app_secret_encrypted
               AS wechat_app_secret_encrypted,
           wechat_account_settings.api_status AS wechat_api_status,
           wechat_account_settings.api_capabilities_json
               AS wechat_api_capabilities_json,
           wechat_account_settings.api_last_error AS wechat_api_last_error,
           wechat_account_settings.api_last_checked_at
               AS wechat_api_last_checked_at
    FROM accounts
    LEFT JOIN proxies ON proxies.id = accounts.proxy_id
    LEFT JOIN wechat_account_settings
        ON wechat_account_settings.account_id = accounts.id
"""


def list_accounts(platform=None):
    params = []
    where = ""
    if platform:
        where = "WHERE platform = ?"
        params.append(platform)
    with connection() as conn:
        rows = conn.execute(
            f"{ACCOUNT_SELECT} {where} "
            "ORDER BY accounts.platform, accounts.created_at",
            params,
        ).fetchall()
    return [_row_to_account(row) for row in rows]


def get_account(account_id):
    with connection() as conn:
        row = conn.execute(
            f"{ACCOUNT_SELECT} WHERE accounts.id = ?",
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
            if platform == "wechat":
                conn.execute(
                    """
                    INSERT INTO wechat_account_settings (
                        account_id, created_at, updated_at
                    ) VALUES (?, ?, ?)
                    """,
                    (account_id, now, now),
                )
    except sqlite3.IntegrityError as exc:
        raise ValueError("同平台下已存在同名账号") from exc
    return get_account(account_id)


def delete_account(account_id):
    account = get_account(account_id)
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, platform_accounts_json FROM articles"
        ).fetchall()
        for row in rows:
            selected = json.loads(row["platform_accounts_json"] or "{}")
            if str(selected.get(account["platform"], "")) != str(account_id):
                continue
            selected.pop(account["platform"], None)
            conn.execute(
                "UPDATE articles SET platform_accounts_json = ?, updated_at = ? "
                "WHERE id = ?",
                (json.dumps(selected, ensure_ascii=False), utc_now(), row["id"]),
            )
        cursor = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        if not cursor.rowcount:
            raise LookupError("账号不存在")

    cleanup_errors = []
    profile_dir = Path(account.get("profile_dir") or "")
    if profile_dir:
        try:
            resolved_profile = profile_dir.resolve()
            profile_root = PROFILE_ROOT.resolve()
            resolved_profile.relative_to(profile_root)
            if resolved_profile == profile_root:
                raise ValueError("账号目录不能是浏览器会话根目录")
            if resolved_profile.exists():
                shutil.rmtree(resolved_profile)
        except (OSError, ValueError) as exc:
            cleanup_errors.append(f"浏览器会话未完全清理：{exc}")

    avatar_path = account_avatar_path(account)
    try:
        avatar_path.unlink(missing_ok=True)
    except OSError as exc:
        cleanup_errors.append(f"账号头像未清理：{exc}")

    return {
        "id": account_id,
        "name": account["name"],
        "platform": account["platform"],
        "deleted": True,
        "cleanup_warning": "；".join(cleanup_errors),
    }

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


def update_wechat_account_settings(
    account_id,
    publish_method,
    app_id=None,
    app_secret=None,
):
    account = get_account(account_id)
    if account["platform"] != "wechat":
        raise ValueError("该账号不是微信公众号账号")
    publish_method = str(publish_method or "").strip().lower()
    if publish_method not in {"browser", "api"}:
        raise ValueError("公众号发布方式必须是 browser 或 api")
    now = utc_now()
    assignments = [
        "publish_method = ?",
        "api_status = 'pending'",
        "api_capabilities_json = '{}'",
        "api_last_error = ''",
        "api_last_checked_at = NULL",
        "updated_at = ?",
    ]
    params = [publish_method, now]
    if app_id is not None:
        assignments.append("app_id = ?")
        params.append(str(app_id).strip())
    if app_secret is not None:
        assignments.append("app_secret_encrypted = ?")
        params.append(encrypt_secret(app_secret))
    params.append(account_id)
    with connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO wechat_account_settings (
                account_id, created_at, updated_at
            ) VALUES (?, ?, ?)
            """,
            (account_id, now, now),
        )
        conn.execute(
            f"UPDATE wechat_account_settings SET {', '.join(assignments)} "
            "WHERE account_id = ?",
            params,
        )
    return get_account(account_id)


def get_wechat_api_credentials(account_id):
    account = get_account(account_id)
    if account["platform"] != "wechat":
        raise ValueError("该账号不是微信公众号账号")
    with connection() as conn:
        row = conn.execute(
            """
            SELECT app_id, app_secret_encrypted
            FROM wechat_account_settings
            WHERE account_id = ?
            """,
            (account_id,),
        ).fetchone()
    if not row or not row["app_id"] or not row["app_secret_encrypted"]:
        raise RuntimeError("请先配置该公众号账号的 AppID 和 AppSecret")
    return {
        "app_id": row["app_id"],
        "app_secret": decrypt_secret(row["app_secret_encrypted"]),
        "proxy_url": account.get("proxy_url", ""),
    }


def update_wechat_api_status(account_id, status, capabilities=None, error=""):
    now = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            """
            UPDATE wechat_account_settings
            SET api_status = ?, api_capabilities_json = ?,
                api_last_error = ?, api_last_checked_at = ?, updated_at = ?
            WHERE account_id = ?
            """,
            (
                status,
                json.dumps(capabilities or {}, ensure_ascii=False),
                str(error or ""),
                now,
                now,
                account_id,
            ),
        )
        if not cursor.rowcount:
            raise LookupError("公众号 API 配置不存在")
    return get_account(account_id)


def _fetch_account_profile(account, page=None):
    handler = ACCOUNT_PROFILE_HANDLERS.get(account["platform"])
    if not handler:
        raise NotImplementedError("该平台暂未接入账号资料同步")
    module_name, function_name = handler
    function = getattr(importlib.import_module(module_name), function_name)
    return function(account, page=page) if page is not None else function(account)


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


def _account_management_runtime(account):
    module_name, target_name, checker_name = ACCOUNT_MANAGEMENT_HANDLERS[
        account["platform"]
    ]
    module = importlib.import_module(module_name)
    target = getattr(module, target_name)
    target_url = target(account) if callable(target) else target
    return module, target_url, getattr(module, checker_name)


def _current_account_page(context, previous=None):
    try:
        pages = [page for page in context.pages if not page.is_closed()]
    except Exception:
        pages = []
    if not pages:
        return None
    if previous in pages:
        return previous
    return pages[-1]


def _sync_profile_from_page(account, page):
    if account["platform"] not in ACCOUNT_PROFILE_HANDLERS:
        return get_account(account["id"])
    try:
        profile = _fetch_account_profile(account, page=page)
        return update_account_profile(account["id"], profile)
    except Exception as exc:
        update_account_profile_error(account["id"], exc)
        return get_account(account["id"])


def _record_platform_session(module, account, page):
    recorder = getattr(module, "record_account_session", None)
    if recorder:
        recorder(account, page)



def login_account(account_id, timeout_seconds=300):
    account = get_account(account_id)
    try:
        module, target_url, is_logged_in = _account_management_runtime(account)
        with open_account_browser(account) as context:
            page = get_or_create_page(context)
            page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2500)

            if is_logged_in(page):
                _record_platform_session(module, account, page)
                update_account_status(account_id, "valid")
                result = _sync_profile_from_page(account, page)
                try:
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
                return {**result, "management_mode": "check"}

            update_account_status(account_id, "invalid", "等待用户完成登录")
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                page = _current_account_page(context, page)
                if page is None:
                    raise RuntimeError("登录浏览器已关闭，尚未检测到登录成功")
                if is_logged_in(page):
                    _record_platform_session(module, account, page)
                    update_account_status(account_id, "valid")
                    result = _sync_profile_from_page(account, page)
                    try:
                        page.wait_for_timeout(2000)
                    except Exception:
                        pass
                    return {**result, "management_mode": "login"}
                page.wait_for_timeout(1000)
            raise RuntimeError("等待账号登录超时，请重新打开账号管理")
    except Exception as exc:
        update_account_status(account_id, "invalid", str(exc))
        raise

def open_account_view(account_id):
    account = get_account(account_id)
    if account["platform"] == "wechat":
        module = importlib.import_module("backend.platforms.wechat_browser")
        return open_account_dashboard(
            account,
            module.wechat_dashboard_url(account),
        )
    return open_account_dashboard(account)

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


def resolve_publish_account(platform, account_id=None, require_login=True):
    if account_id is not None:
        account = get_account(int(account_id))
        if account["platform"] != platform:
            raise ValueError("所选账号与发布平台不匹配")
        if require_login and account["status"] != "valid":
            raise RuntimeError("所选账号尚未登录或登录状态已失效")
        return account

    accounts = [
        item
        for item in list_accounts(platform)
        if not require_login or item["status"] == "valid"
    ]
    if not accounts:
        platform_name = ACCOUNT_PLATFORM_NAMES.get(platform, platform)
        raise RuntimeError(f"请先添加并登录{platform_name}账号")
    if len(accounts) > 1:
        raise RuntimeError("存在多个可用账号，请在稿件中选择发布账号")
    return accounts[0]
