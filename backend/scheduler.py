import asyncio
import logging
from datetime import datetime, timedelta, timezone

from backend.rss import scan_rss_feeds
from backend.services import run_auto_publish, sync_from_notion
from backend.settings import get_settings


logger = logging.getLogger("ContentScheduler")


class AutomationScheduler:
    def __init__(self):
        self.task = None
        self.last_sync_at = None
        self.last_sync_attempt_at = None
        self.last_sync_error = ""
        self.last_rss_scan_at = None
        self.last_publish_at = None

    def start(self):
        if not self.task:
            self.task = asyncio.create_task(self._loop())
            logger.info("自动化调度器已启动 tick_seconds=15")

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
            logger.info("自动化调度器已停止")

    async def _loop(self):
        while True:
            try:
                await self._tick()
            except Exception:
                logger.exception("自动化任务执行失败")
            await asyncio.sleep(15)

    async def _tick(self):
        settings = get_settings()
        now = datetime.now(timezone.utc)
        logger.debug(
            "自动化检查 notion_enabled=%s rss_enabled=%s publish_enabled=%s "
            "last_sync_at=%s last_sync_attempt_at=%s "
            "last_rss_scan_at=%s last_publish_at=%s",
            settings["notion_sync_enabled"],
            settings["rss_enabled"],
            settings["auto_publish_enabled"],
            self.last_sync_at,
            self.last_sync_attempt_at,
            self.last_rss_scan_at,
            self.last_publish_at,
        )

        if settings["notion_sync_enabled"] and self._is_due(
            self.last_sync_attempt_at,
            settings["notion_sync_interval_minutes"],
            now,
        ):
            self.last_sync_attempt_at = now
            try:
                result = await asyncio.to_thread(sync_from_notion)
                self.last_sync_at = now
                self.last_sync_error = ""
                logger.info("Notion 自动同步完成 result=%s", result)
            except RuntimeError as exc:
                self.last_sync_error = str(exc)
                logger.warning("Notion 自动同步跳过: %s", exc)

        if settings["rss_enabled"] and self._is_due(
            self.last_rss_scan_at,
            settings["rss_scan_interval_minutes"],
            now,
        ):
            result = await asyncio.to_thread(scan_rss_feeds)
            self.last_rss_scan_at = now
            logger.info("RSS 自动扫描完成 result=%s", result)

        if settings["auto_publish_enabled"] and self._is_due(
            self.last_publish_at,
            settings["auto_publish_interval_minutes"],
            now,
        ):
            try:
                result = await asyncio.to_thread(run_auto_publish)
                self.last_publish_at = now
                logger.info("自动发布检查完成 result=%s", result)
            except RuntimeError as exc:
                logger.warning("自动发布跳过: %s", exc)

    @staticmethod
    def _is_due(last_run, interval_minutes, now):
        if last_run is None:
            return True
        return now >= last_run + timedelta(minutes=interval_minutes)

    def mark_rss_scan(self):
        self.last_rss_scan_at = datetime.now(timezone.utc)

    def status(self):
        return {
            "running": self.task is not None and not self.task.done(),
            "last_sync_at": (
                self.last_sync_at.isoformat() if self.last_sync_at else None
            ),
            "last_sync_attempt_at": (
                self.last_sync_attempt_at.isoformat()
                if self.last_sync_attempt_at
                else None
            ),
            "last_sync_error": self.last_sync_error,
            "last_rss_scan_at": (
                self.last_rss_scan_at.isoformat()
                if self.last_rss_scan_at
                else None
            ),
            "last_publish_at": (
                self.last_publish_at.isoformat() if self.last_publish_at else None
            ),
        }