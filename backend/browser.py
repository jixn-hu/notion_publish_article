from contextlib import contextmanager
from pathlib import Path
import random
import socket
import subprocess
from threading import Lock
import time
from urllib.request import urlopen

from backend.proxies import browser_proxy_rule
from backend.settings import get_settings


_browser_lock = Lock()
FORBIDDEN_BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--enable-automation",
]
KNOWN_BROWSER_PATHS = [
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
]


def _browser_executable_path():
    configured = str(get_settings().get("browser_executable_path") or "").strip()
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise RuntimeError(f"浏览器路径不存在: {path}")
        return path
    for path in KNOWN_BROWSER_PATHS:
        if path.is_file():
            return path
    raise RuntimeError(
        "未找到 Chrome 或 Edge，请在设置中填写浏览器可执行文件路径"
    )


def _available_debugging_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _native_browser_command(executable, profile_dir, port, proxy_url=""):
    command = [
        str(executable),
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    if proxy_url:
        command.insert(
            -1,
            f"--proxy-server={browser_proxy_rule(proxy_url)}",
        )
    lowered = [argument.lower() for argument in command]
    for forbidden in FORBIDDEN_BROWSER_ARGS:
        if any(argument.startswith(forbidden.lower()) for argument in lowered):
            raise RuntimeError(f"浏览器启动参数不允许包含 {forbidden}")
    return command


def _wait_for_debugging_endpoint(process, port, timeout_seconds=15):
    endpoint = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("浏览器进程已提前退出")
        try:
            with urlopen(f"{endpoint}/json/version", timeout=0.5):
                return endpoint
        except Exception:
            time.sleep(0.15)
    raise RuntimeError("等待浏览器调试连接超时")


def _close_native_browser(browser, context, process):
    try:
        page = next(
            (item for item in context.pages if not item.is_closed()),
            None,
        )
        if page is not None:
            session = context.new_cdp_session(page)
            session.send("Browser.close")
    except Exception:
        pass
    try:
        browser.close()
    except Exception:
        pass
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


@contextmanager
def open_account_browser(account):
    if not _browser_lock.acquire(blocking=False):
        raise RuntimeError("已有浏览器登录或发布任务正在执行")
    try:
        try:
            from patchright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Patchright 尚未安装，请先执行 pip install -r requirements.txt"
            ) from exc

        profile_dir = Path(account["profile_dir"])
        profile_dir.mkdir(parents=True, exist_ok=True)
        executable = _browser_executable_path()
        port = _available_debugging_port()
        command = _native_browser_command(
            executable,
            profile_dir,
            port,
            account.get("proxy_url") or "",
        )
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with sync_playwright() as patchright:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            try:
                endpoint = _wait_for_debugging_endpoint(process, port)
                browser = patchright.chromium.connect_over_cdp(endpoint)
                if not browser.contexts:
                    raise RuntimeError("浏览器未创建默认用户上下文")
                context = browser.contexts[0]
            except Exception as exc:
                if process.poll() is None:
                    process.terminate()
                raise RuntimeError(
                    "无法启动或连接 Chrome/Edge，请检查浏览器路径和账号配置目录"
                ) from exc
            try:
                yield context
            finally:
                _close_native_browser(browser, context, process)
    finally:
        _browser_lock.release()


def get_or_create_page(context):
    if context.pages:
        return context.pages[0]
    return context.new_page()


def interaction_pause(page, minimum_ms=220, maximum_ms=650):
    page.wait_for_timeout(random.randint(minimum_ms, maximum_ms))


def typing_delay(text):
    length = len(str(text or ""))
    if length > 500:
        return random.randint(6, 12)
    if length > 100:
        return random.randint(12, 25)
    return random.randint(35, 70)


def replace_text(page, locator, text):
    interaction_pause(page)
    locator.click()
    page.keyboard.press("Control+A")
    page.keyboard.type(str(text), delay=typing_delay(text))
    interaction_pause(page)
