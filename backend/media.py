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


def save_upload(upload: UploadFile):
    original_name = Path(upload.filename or "").name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(
            "仅支持 jpg、jpeg、png、webp、gif、mp4、mov、m4v、webm 素材"
        )

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(original_name).stem).strip("-")
    stem = stem[:60] or "media"
    target = MEDIA_DIR / f"{uuid4().hex[:12]}-{stem}{extension}"
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
