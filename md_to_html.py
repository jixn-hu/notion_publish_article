import markdown
from bs4 import BeautifulSoup


BASE_STYLE = (
    'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",'
    '"Microsoft YaHei",sans-serif;font-size:16px;line-height:1.8;'
    'color:#2f3337;word-break:break-word;padding:0 4px;'
)

TAG_STYLES = {
    "p": "margin:0 0 16px;line-height:1.8;text-align:justify;color:#2f3337;",
    "h1": (
        "margin:30px 0 18px;padding-left:12px;border-left:4px solid #1677ff;"
        "font-size:24px;line-height:1.45;font-weight:700;color:#1f2328;"
    ),
    "h2": (
        "margin:30px 0 16px;padding:10px 12px;background-color:#f3f7fb;"
        "border-left:4px solid #1677ff;font-size:20px;line-height:1.5;"
        "font-weight:700;color:#1f2328;"
    ),
    "h3": (
        "margin:26px 0 14px;font-size:18px;line-height:1.55;"
        "font-weight:700;color:#1f2328;"
    ),
    "h4": (
        "margin:22px 0 12px;font-size:17px;line-height:1.55;"
        "font-weight:700;color:#1f2328;"
    ),
    "h5": (
        "margin:20px 0 10px;font-size:16px;line-height:1.55;"
        "font-weight:700;color:#1f2328;"
    ),
    "h6": (
        "margin:20px 0 10px;font-size:15px;line-height:1.55;"
        "font-weight:700;color:#5f6368;"
    ),
    "ul": "margin:0 0 18px;padding-left:24px;color:#2f3337;",
    "ol": "margin:0 0 18px;padding-left:24px;color:#2f3337;",
    "li": "margin:6px 0;line-height:1.75;padding-left:2px;",
    "strong": "font-weight:700;color:#1f2328;",
    "b": "font-weight:700;color:#1f2328;",
    "em": "font-style:italic;color:#4f5358;",
    "i": "font-style:italic;color:#4f5358;",
    "a": "color:#1677ff;text-decoration:underline;",
    "img": (
        "display:block;width:100%;max-width:100%;height:auto;"
        "margin:18px auto 22px;border-radius:6px;"
    ),
    "blockquote": (
        "margin:20px 0;padding:14px 16px;background-color:#f6f8fa;"
        "border-left:4px solid #8c959f;color:#57606a;"
    ),
    "hr": "margin:28px 0;border:0;border-top:1px solid #e5e7eb;",
    "pre": (
        "margin:20px 0;padding:16px;overflow-x:auto;background-color:#f6f8fa;"
        "border:1px solid #e5e7eb;border-radius:6px;white-space:pre-wrap;"
        "word-break:break-word;line-height:1.65;"
    ),
    "code": (
        'font-family:Consolas,Monaco,"Courier New",monospace;font-size:14px;'
        "padding:2px 5px;background-color:#f3f4f6;border-radius:4px;"
        "color:#c7254e;"
    ),
    "table": (
        "width:100%;margin:20px 0;border-collapse:collapse;"
        "font-size:14px;line-height:1.6;"
    ),
    "thead": "background-color:#f3f7fb;",
    "th": (
        "padding:10px 8px;border:1px solid #dfe3e8;"
        "font-weight:700;text-align:left;color:#1f2328;"
    ),
    "td": "padding:10px 8px;border:1px solid #dfe3e8;text-align:left;",
}


def _append_style(tag, style):
    current = str(tag.get("style") or "").strip()
    tag["style"] = f"{current.rstrip(';')};{style}" if current else style


def md_to_wechat_html(md_content):
    """Convert Markdown to HTML that keeps its layout after WeChat sanitizes it."""
    rendered = markdown.markdown(
        str(md_content or ""),
        extensions=["extra"],
    )
    source = BeautifulSoup(rendered, "html.parser")
    document = BeautifulSoup("", "html.parser")
    wrapper = document.new_tag("section")
    wrapper["style"] = BASE_STYLE
    document.append(wrapper)
    for child in list(source.contents):
        wrapper.append(child.extract())

    for tag in wrapper.find_all(True):
        tag.attrs.pop("class", None)
        tag.attrs.pop("id", None)
        style = TAG_STYLES.get(tag.name)
        if style:
            _append_style(tag, style)

    for paragraph in wrapper.find_all("p"):
        meaningful = [item for item in paragraph.contents if str(item).strip()]
        if meaningful and all(getattr(item, "name", None) == "img" for item in meaningful):
            paragraph["style"] = "margin:0;line-height:1;"

    for code in wrapper.find_all("code"):
        if code.parent and code.parent.name == "pre":
            code["style"] = (
                'font-family:Consolas,Monaco,"Courier New",monospace;'
                "font-size:14px;color:#24292f;background-color:transparent;"
                "padding:0;"
            )

    return str(wrapper)
