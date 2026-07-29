import json
import math

from backend.db import connection, utc_now


MAX_NODES = 500
MAX_EDGES = 1000
NODE_TYPES = {"resource", "note", "group", "ai"}
RESOURCE_TYPES = {"article", "news", "material"}


def _number(value, default=0.0, minimum=-10_000_000, maximum=10_000_000):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    if not math.isfinite(number):
        number = float(default)
    return max(minimum, min(maximum, number))


def _text(value, limit):
    return str(value or "").strip()[:limit]


def _clean_node(raw):
    if not isinstance(raw, dict):
        raise ValueError("画布节点格式无效")
    node_id = _text(raw.get("id"), 100)
    node_type = _text(raw.get("type"), 30) or "note"
    if not node_id:
        raise ValueError("画布节点缺少 ID")
    if node_type not in NODE_TYPES:
        raise ValueError(f"不支持的画布节点类型: {node_type}")
    position = raw.get("position") if isinstance(raw.get("position"), dict) else {}
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    cleaned_data = json.loads(json.dumps(data, ensure_ascii=False))
    if node_type == "resource":
        resource_type = _text(cleaned_data.get("resourceType"), 30)
        if resource_type not in RESOURCE_TYPES:
            raise ValueError("资源节点类型无效")
        try:
            resource_id = int(cleaned_data.get("resourceId"))
        except (TypeError, ValueError) as exc:
            raise ValueError("资源节点缺少有效资源 ID") from exc
        if resource_id <= 0:
            raise ValueError("资源节点缺少有效资源 ID")
        cleaned_data["resourceType"] = resource_type
        cleaned_data["resourceId"] = resource_id
    node = {
        "id": node_id,
        "type": node_type,
        "position": {
            "x": _number(position.get("x")),
            "y": _number(position.get("y")),
        },
        "data": cleaned_data,
    }
    for key in ("width", "height"):
        if raw.get(key) is not None:
            node[key] = _number(raw[key], 240, 80, 3000)
    if raw.get("parentId"):
        node["parentId"] = _text(raw["parentId"], 100)
        node["extent"] = "parent"
    if raw.get("zIndex") is not None:
        node["zIndex"] = int(_number(raw["zIndex"], 0, -1000, 1000))
    return node


def _clean_edge(raw, node_ids):
    if not isinstance(raw, dict):
        raise ValueError("画布连线格式无效")
    edge_id = _text(raw.get("id"), 100)
    source = _text(raw.get("source"), 100)
    target = _text(raw.get("target"), 100)
    if not edge_id or source not in node_ids or target not in node_ids:
        raise ValueError("画布连线引用了不存在的节点")
    edge = {
        "id": edge_id,
        "source": source,
        "target": target,
        "type": _text(raw.get("type"), 30) or "smoothstep",
    }
    for key in ("sourceHandle", "targetHandle"):
        if raw.get(key):
            edge[key] = _text(raw[key], 100)
    if raw.get("label"):
        edge["label"] = _text(raw["label"], 120)
    if isinstance(raw.get("data"), dict):
        edge["data"] = json.loads(json.dumps(raw["data"], ensure_ascii=False))
    return edge


def validate_document(value):
    if not isinstance(value, dict):
        raise ValueError("画布文档格式无效")
    raw_nodes = value.get("nodes") or []
    raw_edges = value.get("edges") or []
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValueError("画布节点或连线格式无效")
    if len(raw_nodes) > MAX_NODES or len(raw_edges) > MAX_EDGES:
        raise ValueError("单张画布最多支持 500 个节点和 1000 条连线")
    nodes = [_clean_node(item) for item in raw_nodes]
    node_ids = {node["id"] for node in nodes}
    if len(node_ids) != len(nodes):
        raise ValueError("画布节点 ID 不能重复")
    edges = [_clean_edge(item, node_ids) for item in raw_edges]
    if len({edge["id"] for edge in edges}) != len(edges):
        raise ValueError("画布连线 ID 不能重复")
    viewport = value.get("viewport") if isinstance(value.get("viewport"), dict) else {}
    return {
        "nodes": nodes,
        "edges": edges,
        "viewport": {
            "x": _number(viewport.get("x")),
            "y": _number(viewport.get("y")),
            "zoom": _number(viewport.get("zoom"), 1, 0.1, 4),
        },
    }


def _row_to_canvas(row, include_document=True):
    item = dict(row)
    if include_document:
        item["document"] = validate_document(json.loads(item.pop("document_json")))
    else:
        document = json.loads(item.pop("document_json"))
        item["node_count"] = len(document.get("nodes") or [])
        item["edge_count"] = len(document.get("edges") or [])
    return item


def list_canvases():
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM canvases ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [_row_to_canvas(row, include_document=False) for row in rows]


def get_canvas(canvas_id):
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM canvases WHERE id = ?", (canvas_id,)
        ).fetchone()
    if not row:
        raise LookupError("画布不存在")
    return _row_to_canvas(row)


def create_canvas(values):
    title = _text(values.get("title"), 120) or "未命名画布"
    document = validate_document(values.get("document") or {})
    now = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO canvases (
                title, document_json, version, created_at, updated_at
            ) VALUES (?, ?, 1, ?, ?)
            """,
            (title, json.dumps(document, ensure_ascii=False), now, now),
        )
        canvas_id = cursor.lastrowid
    return get_canvas(canvas_id)


def update_canvas(canvas_id, values):
    current = get_canvas(canvas_id)
    expected_version = values.get("version")
    if expected_version is not None and int(expected_version) != current["version"]:
        raise ValueError("画布已在其他位置更新，请刷新后重试")
    title = current["title"]
    if "title" in values:
        title = _text(values.get("title"), 120)
        if not title:
            raise ValueError("画布名称不能为空")
    document = current["document"]
    if "document" in values:
        document = validate_document(values["document"])
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            UPDATE canvases
            SET title = ?, document_json = ?, version = version + 1, updated_at = ?
            WHERE id = ?
            """,
            (title, json.dumps(document, ensure_ascii=False), now, canvas_id),
        )
    return get_canvas(canvas_id)


def delete_canvas(canvas_id):
    get_canvas(canvas_id)
    with connection() as conn:
        conn.execute("DELETE FROM canvases WHERE id = ?", (canvas_id,))
    return {"deleted": True, "id": canvas_id}
