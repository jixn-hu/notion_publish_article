import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


def normalize_notion_markdown(value):
    """Convert HTML blocks returned by Notion into plain Markdown."""
    source = str(value or "")
    if "<" not in source or ">" not in source:
        return source

    source, protected = _protect_markdown(source)
    document = BeautifulSoup(source, "html.parser")
    rendered = "".join(_render_node(node) for node in document.contents)
    for placeholder, original in protected:
        rendered = rendered.replace(placeholder, original)
    rendered = re.sub(r"[ \t]+\n", "\n", rendered)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered.strip()


def _protect_markdown(source):
    protected = []

    def stash(match):
        placeholder = f"MOZHOU_MARKDOWN_PROTECTED_{len(protected)}_"
        protected.append((placeholder, match.group(0)))
        return placeholder

    source = re.sub(
        r"(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$",
        stash,
        source,
    )
    source = re.sub(r"(`+)(.+?)\1", stash, source, flags=re.DOTALL)
    source = re.sub(r"<(?:https?://|mailto:)[^<>\n]+>", stash, source)
    return source, protected


def _render_node(node):
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()
    if name == "table":
        return _render_table(node)
    if name == "callout":
        return _render_callout(node)
    if name == "br":
        return "\n"
    if name in {"strong", "b"}:
        return f"**{_render_children(node).strip()}**"
    if name in {"em", "i"}:
        return f"*{_render_children(node).strip()}*"
    if name == "del":
        return f"~~{_render_children(node).strip()}~~"
    if name == "code":
        content = _render_children(node).strip()
        marker = "``" if "`" in content else "`"
        return f"{marker}{content}{marker}"
    if name == "a":
        label = _render_children(node).strip()
        href = str(node.get("href") or "").strip()
        return f"[{label}]({href})" if href else label
    if name == "img":
        src = str(node.get("src") or "").strip()
        alt = str(node.get("alt") or "").strip()
        return f"![{alt}]({src})" if src else ""
    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return f"\n\n{'#' * int(name[1])} {_render_children(node).strip()}\n\n"
    if name == "blockquote":
        return _as_blockquote(_render_children(node))
    if name in {"ul", "ol"}:
        return _render_list(node, ordered=name == "ol")
    if name == "li":
        return _render_children(node).strip()
    if name == "hr":
        return "\n\n---\n\n"
    if name in {"p", "div", "section", "article", "figure", "figcaption"}:
        return f"\n\n{_render_children(node).strip()}\n\n"
    if name == "details":
        return f"\n\n{_render_children(node).strip()}\n\n"
    if name == "summary":
        return f"**{_render_children(node).strip()}**\n\n"
    return _render_children(node)


def _render_children(node):
    return "".join(_render_node(child) for child in node.contents)


def _render_table(table):
    rows = []
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            cells = row.find_all(["th", "td"])
        rows.append([_table_cell(cell) for cell in cells])
    rows = [row for row in rows if row]
    if not rows:
        return ""

    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = [
        _markdown_table_row(rows[0]),
        _markdown_table_row(["---"] * width),
        *(_markdown_table_row(row) for row in rows[1:]),
    ]
    content = "\n".join(lines)
    return f"\n\n{content}\n\n"


def _table_cell(cell):
    content = _render_children(cell).strip()
    content = re.sub(r"\s*\n\s*", " ", content)
    content = re.sub(r"[ \t]{2,}", " ", content)
    return content.replace("|", r"\|")


def _markdown_table_row(cells):
    return "| " + " | ".join(cells) + " |"


def _render_callout(callout):
    icon = str(callout.get("icon") or "").strip()
    content = _render_children(callout).strip()
    if icon:
        content = f"{icon} {content}" if content else icon
    return _as_blockquote(content)


def _as_blockquote(content):
    lines = str(content or "").strip().splitlines() or [""]
    quoted = "\n".join(f"> {line.strip()}" if line.strip() else ">" for line in lines)
    return f"\n\n{quoted}\n\n"


def _render_list(list_node, ordered=False):
    lines = []
    for index, item in enumerate(list_node.find_all("li", recursive=False), 1):
        marker = f"{index}." if ordered else "-"
        content = _render_children(item).strip().replace("\n", " ")
        lines.append(f"{marker} {content}")
    content = "\n".join(lines)
    return f"\n\n{content}\n\n" if lines else ""
