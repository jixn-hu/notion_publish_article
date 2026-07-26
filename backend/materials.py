import json
import mimetypes
import re
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

import backend.db as db
import backend.media as media
from backend.db import connection, utc_now


MATERIAL_KINDS = {"image", "video", "note"}

def library_dir():
    return media.MEDIA_DIR / "library"


def download_dir():
    return db.DB_PATH.parent / "downloads"


def _clean_tags(tags):
    if not isinstance(tags, list):
        return []
    cleaned = []
    for tag in tags:
        value = str(tag or "").strip()[:30]
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned[:12]


def _row_to_material(row):
    material = dict(row)
    material["tags"] = json.loads(material.pop("tags_json") or "[]")
    material["reference_count"] = int(material.get("reference_count") or 0)
    return material


def list_materials(kind=None, query=None):
    if kind and kind not in MATERIAL_KINDS:
        raise ValueError("素材类型必须是 image、video 或 note")
    clauses = []
    params = []
    if kind:
        clauses.append("m.kind = ?")
        params.append(kind)
    if query:
        clauses.append(
            "(m.title LIKE ? OR m.description LIKE ? OR m.content_md LIKE ?)"
        )
        term = f"%{str(query).strip()}%"
        params.extend([term, term, term])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT m.*, COUNT(am.article_id) AS reference_count
            FROM materials m
            LEFT JOIN article_materials am ON am.material_id = m.id
            {where}
            GROUP BY m.id
            ORDER BY m.updated_at DESC
            """,
            params,
        ).fetchall()
        count_rows = conn.execute(
            "SELECT kind, COUNT(*) AS total FROM materials GROUP BY kind"
        ).fetchall()
    counts = {"all": 0, "image": 0, "video": 0, "note": 0}
    for row in count_rows:
        counts[row["kind"]] = row["total"]
        counts["all"] += row["total"]
    return {"items": [_row_to_material(row) for row in rows], "counts": counts}


def get_material(material_id):
    with connection() as conn:
        row = conn.execute(
            """
            SELECT m.*, COUNT(am.article_id) AS reference_count
            FROM materials m
            LEFT JOIN article_materials am ON am.material_id = m.id
            WHERE m.id = ?
            GROUP BY m.id
            """,
            (material_id,),
        ).fetchone()
    if not row:
        raise LookupError("素材不存在")
    return _row_to_material(row)


def create_file_material(upload: UploadFile):
    uploaded = media.save_upload(upload, directory=library_dir())
    now = utc_now()
    title = Path(uploaded["name"]).stem.strip()[:120] or "未命名素材"
    mime_type = mimetypes.guess_type(uploaded["name"])[0] or ""
    try:
        with connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO materials (
                    kind, title, path, content_md, description, tags_json,
                    mime_type, size_bytes, created_at, updated_at
                ) VALUES (?, ?, ?, '', '', '[]', ?, ?, ?, ?)
                """,
                (
                    uploaded["kind"],
                    title,
                    uploaded["path"],
                    mime_type,
                    uploaded["size"],
                    now,
                    now,
                ),
            )
            material_id = cursor.lastrowid
    except Exception:
        Path(uploaded["path"]).unlink(missing_ok=True)
        raise
    return get_material(material_id)


def create_note_material(values):
    title = str(values.get("title") or "").strip()[:120]
    content_md = str(values.get("content_md") or "").strip()[:20000]
    if not title:
        raise ValueError("卡片笔记标题不能为空")
    if not content_md:
        raise ValueError("卡片笔记内容不能为空")
    now = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO materials (
                kind, title, path, content_md, description, tags_json,
                mime_type, size_bytes, created_at, updated_at
            ) VALUES ('note', ?, '', ?, ?, ?, 'text/markdown', ?, ?, ?)
            """,
            (
                title,
                content_md,
                str(values.get("description") or "").strip()[:1000],
                json.dumps(_clean_tags(values.get("tags")), ensure_ascii=False),
                len(content_md.encode("utf-8")),
                now,
                now,
            ),
        )
        material_id = cursor.lastrowid
    return get_material(material_id)


def update_material(material_id, values):
    material = get_material(material_id)
    allowed = {"title", "description", "tags", "content_md"}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"不可更新字段: {', '.join(sorted(unknown))}")
    assignments = []
    params = []
    for key, value in values.items():
        if key == "title":
            value = str(value or "").strip()[:120]
            if not value:
                raise ValueError("素材标题不能为空")
        elif key == "description":
            value = str(value or "").strip()[:1000]
        elif key == "tags":
            key = "tags_json"
            value = json.dumps(_clean_tags(value), ensure_ascii=False)
        elif key == "content_md":
            if material["kind"] != "note":
                raise ValueError("只有卡片笔记可以修改正文")
            value = str(value or "").strip()[:20000]
            if not value:
                raise ValueError("卡片笔记内容不能为空")
            assignments.append("size_bytes = ?")
            params.append(len(value.encode("utf-8")))
        assignments.append(f"{key} = ?")
        params.append(value)
    if not assignments:
        return material
    assignments.append("updated_at = ?")
    params.extend([utc_now(), material_id])
    with connection() as conn:
        conn.execute(
            f"UPDATE materials SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
    return get_material(material_id)


def resolve_material_file(material_id):
    material = get_material(material_id)
    if material["kind"] == "note" or not material["path"]:
        raise ValueError("卡片笔记没有可预览文件")
    root = library_dir().resolve()
    path = Path(material["path"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("素材文件路径超出素材库目录") from exc
    if not path.is_file():
        raise LookupError("素材文件不存在")
    return material, path


def delete_material(material_id):
    material = get_material(material_id)
    with connection() as conn:
        conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))
    if material["path"]:
        path = Path(material["path"]).resolve()
        try:
            path.relative_to(library_dir().resolve())
        except ValueError:
            pass
        else:
            path.unlink(missing_ok=True)
    return {"deleted": True, "id": material_id}


def _archive_name(material, used):
    suffix = ".md" if material["kind"] == "note" else Path(material["path"]).suffix
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", material["title"]).strip(" ._")
    stem = stem[:80] or f"material-{material['id']}"
    name = f"{stem}{suffix}"
    if name.lower() in used:
        name = f"{stem}-{material['id']}{suffix}"
    used.add(name.lower())
    return name


def create_material_archive(material_ids):
    materials = get_material_references(material_ids, max_count=100)
    if not materials:
        raise ValueError("请至少选择一个素材")
    directory = download_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"materials-{uuid4().hex[:12]}.zip"
    used = set()
    manifest = []
    try:
        with zipfile.ZipFile(target, "w") as archive:
            for material in materials:
                name = _archive_name(material, used)
                if material["kind"] == "note":
                    archive.writestr(
                        name,
                        material["content_md"].encode("utf-8"),
                        compress_type=zipfile.ZIP_DEFLATED,
                    )
                else:
                    _, source = resolve_material_file(material["id"])
                    archive.write(source, arcname=name, compress_type=zipfile.ZIP_STORED)
                manifest.append(
                    {
                        "id": material["id"],
                        "kind": material["kind"],
                        "title": material["title"],
                        "description": material["description"],
                        "tags": material["tags"],
                        "file": name,
                    }
                )
            archive.writestr(
                "materials-manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                compress_type=zipfile.ZIP_DEFLATED,
            )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def get_material_references(material_ids, max_count=20):
    ordered_ids = []
    for value in material_ids or []:
        material_id = int(value)
        if material_id > 0 and material_id not in ordered_ids:
            ordered_ids.append(material_id)
    if len(ordered_ids) > max_count:
        raise ValueError(f"一次最多选择 {max_count} 个素材")
    if not ordered_ids:
        return []
    placeholders = ",".join("?" for _ in ordered_ids)
    with connection() as conn:
        rows = conn.execute(
            f"SELECT *, 0 AS reference_count FROM materials WHERE id IN ({placeholders})",
            ordered_ids,
        ).fetchall()
    found = {row["id"]: _row_to_material(row) for row in rows}
    missing = [material_id for material_id in ordered_ids if material_id not in found]
    if missing:
        raise ValueError(f"引用素材不存在: {', '.join(map(str, missing))}")
    return [found[material_id] for material_id in ordered_ids]


def format_material_context(materials):
    if not materials:
        return "未选择参考素材"
    blocks = []
    kind_labels = {"image": "图片", "video": "视频", "note": "卡片笔记"}
    for index, material in enumerate(materials, start=1):
        details = [
            f"{index}. [{kind_labels[material['kind']]}] {material['title']}",
        ]
        if material["description"]:
            details.append(f"说明：{material['description']}")
        if material["tags"]:
            details.append(f"标签：{'、'.join(material['tags'])}")
        if material["kind"] == "note":
            details.append(f"笔记内容：{material['content_md'][:3000]}")
        else:
            details.append(f"文件名：{Path(material['path']).name}")
        blocks.append("\n".join(details))
    return "\n\n".join(blocks)[:12000]


def link_article_materials(article_id, material_ids):
    references = get_material_references(material_ids)
    now = utc_now()
    with connection() as conn:
        conn.execute(
            "DELETE FROM article_materials WHERE article_id = ?",
            (article_id,),
        )
        for material in references:
            conn.execute(
                """
                INSERT INTO article_materials (article_id, material_id, created_at)
                VALUES (?, ?, ?)
                """,
                (article_id, material["id"], now),
            )
    return references