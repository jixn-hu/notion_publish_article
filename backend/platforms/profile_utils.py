import re


def parse_compact_count(value):
    value = str(value or "").replace(",", "").replace("+", "").strip()
    multiplier = 1
    if value.endswith("万"):
        value = value[:-1]
        multiplier = 10_000
    elif value.endswith("亿"):
        value = value[:-1]
        multiplier = 100_000_000
    try:
        return int(float(value) * multiplier)
    except (TypeError, ValueError):
        return None


def metric_from_text(text, labels):
    number = r"([\d.,]+(?:\.\d+)?[万亿]?\+?)"
    for label in labels:
        escaped = re.escape(label)
        patterns = (
            rf"{escaped}\s*[:：]?\s*{number}",
            rf"{number}\s*{escaped}",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return parse_compact_count(match.group(1))
    return None


def first_visible_text(page, selectors):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                value = locator.inner_text().strip()
                if value:
                    return value
        except Exception:
            continue
    return ""


def first_visible_image(page, selectors):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return locator
        except Exception:
            continue
    return None
