import os
from pathlib import Path

from patchright.sync_api import sync_playwright


with sync_playwright() as playwright:
    base_url = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8021")
    browser_errors = []
    browser = playwright.chromium.launch(
        headless=True,
        executable_path=(
            "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
        ),
    )
    page = browser.new_page(viewport={"width": 1440, "height": 980})
    page.on("pageerror", lambda error: browser_errors.append(str(error)))
    page.goto(base_url)
    page.wait_for_load_state("networkidle")

    assert page.get_by_role("heading", name="工作台").is_visible()
    assert page.get_by_text("Notion 是内容源").is_visible()

    page.locator("nav button").nth(1).click()
    page.locator(".library-toolbar .vermilion").click()
    assert page.locator(".editor-drawer h2").is_visible()
    assert page.locator(".platform-action-row select").nth(0).input_value() == "draft"
    assert page.locator(".ai-editor-panel").is_visible()
    page.locator(".editor-drawer footer .ghost").click()

    page.locator("nav button").nth(2).click()
    assert page.get_by_role("heading", name="账号管理").is_visible()
    assert page.get_by_text("一个账号，").is_visible()
    assert page.get_by_role("button", name="＋ 添加小红书账号").is_visible()
    platform_select = page.locator(".account-create select")
    assert platform_select.locator("option").count() == 6
    platform_select.select_option("bilibili")
    assert page.get_by_role("button", name="查看账号").first.is_visible()
    assert page.get_by_role("button", name="＋ 添加Bilibili账号").is_visible()
    account_screenshot = Path("artifacts/mozhou-publisher-accounts.png")
    account_screenshot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(account_screenshot), full_page=True)

    page.locator("nav button").nth(3).click()
    page.wait_for_selector(".settings-section h3")
    assert page.locator(".settings-section h3").nth(0).is_visible()
    assert page.locator(".settings-section h3").nth(1).is_visible()
    assert page.locator(".settings-section h3").nth(2).is_visible()
    assert page.get_by_role("heading", name="浏览器发布通道").is_visible()
    assert page.get_by_text("启用抖音", exact=True).is_visible()
    assert page.get_by_text("启用视频号", exact=True).is_visible()
    assert page.get_by_text("启用Bilibili", exact=True).is_visible()
    assert page.locator(".mapping-row").count() == 8
    assert page.locator(".mapping-row input").nth(0).input_value() == "标题"

    page.locator("nav button").nth(4).click()
    page.wait_for_selector(".settings-section h3")
    assert page.get_by_role("heading", name="自动发布").is_visible()

    screenshot = Path("artifacts/mozhou-publisher-settings.png")
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot), full_page=True)
    assert not browser_errors, browser_errors
    print(f"E2E passed; screenshot: {screenshot}")
    browser.close()
