import asyncio
import logging
from datetime import datetime, timedelta, timezone

from backend.services import run_auto_publish, sync_from_notion
from backend.settings import get_settings


logger = logging.getLogger("ContentScheduler")


class AutomationScheduler:
    def __init__(self):
        self.task = None
        self.last_sync_at = None
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
            "自动化检查 notion_enabled=%s publish_enabled=%s "
            "last_sync_at=%s last_publish_at=%s",
            settings["notion_sync_enabled"],
            settings["auto_publish_enabled"],
            self.last_sync_at,
            self.last_publish_at,
        )

        if settings["notion_sync_enabled"] and self._is_due(
            self.last_sync_at,
            settings["notion_sync_interval_minutes"],
            now,
        ):
            try:
                result = await asyncio.to_thread(sync_from_notion)
                self.last_sync_at = now
                logger.info("Notion 自动同步完成 result=%s", result)
            except RuntimeError as exc:
                logger.warning("Notion 自动同步跳过: %s", exc)

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

    def status(self):
        return {
            "running": self.task is not None and not self.task.done(),
            "last_sync_at": (
                self.last_sync_at.isoformat() if self.last_sync_at else None
            ),
            "last_publish_at": (
                self.last_publish_at.isoformat() if self.last_publish_at else None
            ),
        }
