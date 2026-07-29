from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import threading
import uuid


MAX_OPERATIONS = 20
MAX_EVENTS = 100


class PublishProgressStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._operations = OrderedDict()
        self._active_id = None

    def begin(self, kind, title, *, total=0, article_id=None):
        operation_id = uuid.uuid4().hex
        now = _now()
        operation = {
            "id": operation_id,
            "kind": kind,
            "title": str(title or "发布任务"),
            "article_id": article_id,
            "status": "running",
            "current": 0,
            "total": max(0, int(total or 0)),
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "summary": "",
            "events": [],
        }
        with self._lock:
            self._operations[operation_id] = operation
            self._active_id = operation_id
            self._trim()
        return operation_id

    def configure(self, operation_id, *, title=None, total=None, article_id=None):
        with self._lock:
            operation = self._operations.get(operation_id)
            if not operation:
                return
            if title is not None:
                operation["title"] = str(title)
            if total is not None:
                operation["total"] = max(0, int(total))
            if article_id is not None:
                operation["article_id"] = article_id
            operation["updated_at"] = _now()

    def event(
        self,
        operation_id,
        message,
        *,
        level="info",
        stage="",
        article_id=None,
        article_title="",
        platform="",
        advance=0,
    ):
        with self._lock:
            operation = self._operations.get(operation_id)
            if not operation:
                return
            now = _now()
            operation["events"].append(
                {
                    "id": uuid.uuid4().hex,
                    "time": now,
                    "level": level,
                    "stage": stage,
                    "message": str(message),
                    "article_id": article_id,
                    "article_title": str(article_title or ""),
                    "platform": str(platform or ""),
                }
            )
            operation["events"] = operation["events"][-MAX_EVENTS:]
            if advance:
                operation["current"] = min(
                    operation["total"] or operation["current"] + advance,
                    operation["current"] + advance,
                )
            operation["updated_at"] = now

    def finish(self, operation_id, status, summary=""):
        with self._lock:
            operation = self._operations.get(operation_id)
            if not operation:
                return
            now = _now()
            operation["status"] = status
            if operation["total"] and status == "completed":
                operation["current"] = operation["total"]
            operation["summary"] = str(summary or "")
            operation["updated_at"] = now
            operation["finished_at"] = now
            if self._active_id == operation_id:
                self._active_id = None

    def snapshot(self):
        with self._lock:
            if self._active_id in self._operations:
                operation = self._operations[self._active_id]
            elif self._operations:
                operation = next(reversed(self._operations.values()))
            else:
                return None
            return deepcopy(operation)

    def clear(self):
        with self._lock:
            self._operations.clear()
            self._active_id = None

    def _trim(self):
        while len(self._operations) > MAX_OPERATIONS:
            self._operations.popitem(last=False)


def _now():
    return datetime.now(timezone.utc).isoformat()


publish_progress = PublishProgressStore()
