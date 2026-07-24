from pathlib import Path

from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    browser_errors = []
    browser = playwright.chromium.launch(
        headless=True,
        executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    )
    page = browser.new_page(viewport={"width": 1440, "height": 980})
    page.on("pageerror", lambda error: browser_errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            browser_errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.goto("http://127.0.0.1:8000")
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
    page.wait_for_selector(".settings-section h3")
    assert page.locator(".settings-section h3").nth(0).is_visible()
    assert page.locator(".settings-section h3").nth(1).is_visible()
    assert page.locator(".settings-section h3").nth(2).is_visible()
    assert page.locator(".mapping-row").count() == 8
    assert page.locator(".mapping-row input").nth(0).input_value() == "标题"

    screenshot = Path("C:/tmp/mozhou-publisher-settings.png")
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot), full_page=True)
    assert not browser_errors, browser_errors
    print(f"E2E passed; screenshot: {screenshot}")
    browser.close()
