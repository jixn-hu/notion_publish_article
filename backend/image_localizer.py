import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

import backend.media as media
from backend.assets import canonical_asset_source
from backend.logging_config import redact_url


logger = logging.getLogger("mozhou.image_localizer")
MAX_REMOTE_IMAGE_BYTES = 25 * 1024 * 1024
MARKDOWN_IMAGE_SOURCE = re.compile(
    r"!\[[^\]]*\]\(\s*<?(https?://[^\s)>]+)",
    re.IGNORECASE,
)


def remote_image_sources(markdown, cover_url=""):
    sources = []
    cover = str(cover_url or "").strip()
    if _is_remote(cover):
        sources.append(cover)
    sources.extend(MARKDOWN_IMAGE_SOURCE.findall(str(markdown or "")))
    return list(dict.fromkeys(sources))


def localize_remote_images(
    markdown,
    cover_url="",
    *,
    media_paths=None,
    session=None,
    namespace="article",
):
    source_markdown = str(markdown or "")
    source_cover = str(cover_url or "").strip()
    source_media_paths = [
        str(path).strip()
        for path in (media_paths or [])
        if str(path).strip()
    ]
    sources = list(dict.fromkeys([
        *remote_image_sources(source_markdown, source_cover),
        *(path for path in source_media_paths if _is_remote(path)),
    ]))
    if not sources:
        local_paths = _existing_local_paths(
            source_markdown,
            source_cover,
            source_media_paths,
        )
        return {
            "markdown": source_markdown,
            "cover_url": source_cover,
            "media_paths": source_media_paths,
            "paths": local_paths,
            "downloaded": 0,
            "reused": 0,
            "errors": [],
        }

    client = session or requests.Session()
    if session is None:
        client.trust_env = False
    directory = media.MEDIA_DIR / "notion" / _safe_namespace(namespace)
    mapping = {}
    errors = []
    downloaded = 0
    reused = 0
    for source in sources:
        try:
            path, was_downloaded = _download_image(client, source, directory)
            mapping[source] = path
            if was_downloaded:
                downloaded += 1
            else:
                reused += 1
        except Exception as exc:
            logger.warning(
                "远程图片本地化失败 source=%s error=%s",
                redact_url(source),
                exc,
            )
            errors.append({"url": redact_url(source), "message": str(exc)})

    localized_markdown = source_markdown
    for source, path in mapping.items():
        localized_markdown = localized_markdown.replace(
            source,
            Path(path).as_posix(),
        )
    localized_cover = mapping.get(source_cover, source_cover)
    localized_media_paths = [
        mapping.get(path, path)
        for path in source_media_paths
    ]
    paths = list(dict.fromkeys([
        *mapping.values(),
        *_existing_local_paths(
            localized_markdown,
            localized_cover,
            localized_media_paths,
        ),
    ]))
    return {
        "markdown": localized_markdown,
        "cover_url": localized_cover,
        "media_paths": localized_media_paths,
        "paths": paths,
        "downloaded": downloaded,
        "reused": reused,
        "errors": errors,
    }


def _download_image(session, source, directory):
    canonical = canonical_asset_source(source)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if directory.exists():
        for existing in directory.glob(f"{digest}.*"):
            if existing.suffix.lower() in media.IMAGE_EXTENSIONS and existing.is_file():
                return str(existing.resolve()), False

    response = session.get(source, timeout=(15, 90), stream=True)
    try:
        response.raise_for_status()
        chunks = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_REMOTE_IMAGE_BYTES:
                raise RuntimeError("远程图片超过 25MB 限制")
            chunks.append(chunk)
        data = b"".join(chunks)
        extension = _image_extension(data)
    finally:
        response.close()

    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{digest}{extension}"
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        temporary.write_bytes(data)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return str(target.resolve()), True


def _image_extension(data):
    if not data:
        raise RuntimeError("远程图片内容为空")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"

    raise RuntimeError("远程地址返回的不是受支持的图片")


def _existing_local_paths(markdown, cover_url, media_paths=None):
    candidates = re.findall(
        r"!\[[^\]]*\]\(\s*<?([^\s)>]+)",
        str(markdown or ""),
    )
    if cover_url:
        candidates.append(str(cover_url))
    candidates.extend(media_paths or [])
    paths = []
    for value in candidates:
        if _is_remote(value):
            continue
        candidate = Path(value)
        if candidate.is_file():
            paths.append(str(candidate.resolve()))
    return list(dict.fromkeys(paths))


def _safe_namespace(value):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-")
    return cleaned[:80] or "article"


def _is_remote(value):
    return urlparse(str(value or "").strip()).scheme.lower() in {"http", "https"}
