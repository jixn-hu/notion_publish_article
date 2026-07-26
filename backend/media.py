import re
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from backend.db import DATA_DIR


MEDIA_DIR = DATA_DIR / "media"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


def resolve_media_file(path):
    root = MEDIA_DIR.resolve()
    candidate = Path(str(path or "")).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("媒体文件路径超出本地素材目录") from exc
    if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError("仅支持预览本地图片")
    if not candidate.is_file():
        raise LookupError("媒体文件不存在")
    return candidate


def save_upload(upload: UploadFile, directory=None):
    original_name = Path(upload.filename or "").name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(
            "仅支持 jpg、jpeg、png、webp、gif、mp4、mov、m4v、webm 素材"
        )

    root = MEDIA_DIR.resolve()
    directory = Path(directory or root).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise ValueError("素材保存目录超出本地素材目录") from exc
    directory.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(original_name).stem).strip("-")
    stem = stem[:60] or "media"
    target = directory / f"{uuid4().hex[:12]}-{stem}{extension}"
    size = 0
    try:
        with target.open("xb") as output:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ValueError("单个素材不能超过 2 GB")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        upload.file.close()

    return {
        "name": original_name,
        "path": str(target.resolve()),
        "size": size,
        "kind": "image" if extension in IMAGE_EXTENSIONS else "video",
    }
