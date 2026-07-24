import ipaddress
import sqlite3
import time
from urllib.parse import urlsplit

import requests

from backend.db import connection, utc_now


IP_CHECKS = (
    ("https://api.ipify.org?format=json", "json"),
    ("http://icanhazip.com", "text"),
)
HTTPS_CHECK_URLS = (
    "https://www.baidu.com/",
    "https://www.bilibili.com/",
)


def parse_proxy_spec(value):
    value = str(value or "").strip()
    if not value:
        raise ValueError("代理地址不能为空")
    if len(value) > 300:
        raise ValueError("代理地址不能超过 300 个字符")
    prefix, separator, remainder = value.partition(":")
    if (
        separator
        and prefix.lower() in {"http", "https"}
        and remainder.lower().startswith(
            ("http://", "https://", "socks5://")
        )
    ):
        value = remainder
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("代理地址格式不正确") from exc
    if parsed.scheme.lower() not in {"http", "https", "socks5"}:
        raise ValueError("代理仅支持 http、https 或 socks5")
    if not parsed.hostname or port is None:
        raise ValueError("代理地址必须包含主机和端口")
    if parsed.username or parsed.password:
        raise ValueError("暂不支持在代理地址中填写账号密码")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("代理地址不能包含路径、查询参数或片段")
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    proxy_url = f"{parsed.scheme.lower()}://{host}:{port}"
    return proxy_url


def normalize_proxy_url(value):
    return parse_proxy_spec(value)


def requests_proxy_map(proxy_spec):
    proxy_url = parse_proxy_spec(proxy_spec)
    return {"http": proxy_url, "https": proxy_url}


def browser_proxy_rule(proxy_spec):
    return parse_proxy_spec(proxy_spec)


def _response_ip(response, response_format):
    if response_format == "json":
        value = str(response.json().get("ip") or "").strip()
    else:
        value = str(response.text or "").strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise RuntimeError("出口 IP 检测服务未返回有效 IP") from exc


def _check_exit_ip(proxies):
    errors = []
    for url, response_format in IP_CHECKS:
        try:
            response = requests.get(url, proxies=proxies, timeout=12)
            response.raise_for_status()
            return _response_ip(response, response_format), url.startswith(
                "https://"
            )
        except Exception as exc:
            errors.append(f"{urlsplit(url).netloc}: {exc}")
    raise RuntimeError("；".join(errors))


def _check_https_connectivity(proxies):
    errors = []
    for url in HTTPS_CHECK_URLS:
        try:
            response = requests.get(url, proxies=proxies, timeout=12)
            if response.status_code < 500:
                return
            response.raise_for_status()
        except Exception as exc:
            errors.append(f"{urlsplit(url).netloc}: {exc}")
    raise RuntimeError("HTTPS 连通性检测失败：" + "；".join(errors))


def _row_to_proxy(row):
    return dict(row)


def list_proxies():
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM proxies ORDER BY created_at, id"
        ).fetchall()
    return [_row_to_proxy(row) for row in rows]


def get_proxy(proxy_id):
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM proxies WHERE id = ?",
            (proxy_id,),
        ).fetchone()
    if not row:
        raise LookupError("代理不存在")
    return _row_to_proxy(row)


def create_proxy(name, proxy_url):
    name = str(name or "").strip()
    if not name:
        raise ValueError("代理名称不能为空")
    if len(name) > 50:
        raise ValueError("代理名称不能超过 50 个字符")
    proxy_url = normalize_proxy_url(proxy_url)
    now = utc_now()
    try:
        with connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO proxies (
                    name, proxy_url, status, created_at, updated_at
                ) VALUES (?, ?, 'pending', ?, ?)
                """,
                (name, proxy_url, now, now),
            )
            proxy_id = cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValueError("已存在同名代理") from exc
    return get_proxy(proxy_id)


def test_proxy(proxy_id):
    proxy = get_proxy(proxy_id)
    started = time.perf_counter()
    try:
        proxies = requests_proxy_map(proxy["proxy_url"])
        exit_ip, https_verified = _check_exit_ip(proxies)
        if not https_verified:
            _check_https_connectivity(proxies)
        latency_ms = round((time.perf_counter() - started) * 1000)
        with connection() as conn:
            conn.execute(
                """
                UPDATE proxies
                SET status = 'valid', exit_ip = ?, last_latency_ms = ?,
                    last_error = '', last_checked_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (exit_ip, latency_ms, utc_now(), utc_now(), proxy_id),
            )
        return get_proxy(proxy_id)
    except Exception as exc:
        with connection() as conn:
            conn.execute(
                """
                UPDATE proxies
                SET status = 'invalid', exit_ip = '',
                    last_latency_ms = NULL, last_error = ?,
                    last_checked_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(exc), utc_now(), utc_now(), proxy_id),
            )
        raise RuntimeError(f"代理测试失败: {exc}") from exc


def delete_proxy(proxy_id):
    get_proxy(proxy_id)
    with connection() as conn:
        conn.execute(
            """
            UPDATE accounts
            SET proxy_id = NULL, proxy_url = '', updated_at = ?
            WHERE proxy_id = ?
            """,
            (utc_now(), proxy_id),
        )
        conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
    return {"deleted": proxy_id}
