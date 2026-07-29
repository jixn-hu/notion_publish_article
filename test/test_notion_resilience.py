import asyncio
import unittest
from unittest.mock import Mock, patch

import requests

from backend.notion_client import NotionClient
from backend.scheduler import AutomationScheduler


class NotionResilienceTests(unittest.TestCase):
    def test_transient_network_error_is_retried(self):
        client = NotionClient("token", "database", data_source_id="source")
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}

        with (
            patch.object(
                client.session,
                "request",
                side_effect=[
                    requests.exceptions.SSLError("unexpected EOF"),
                    response,
                ],
            ) as request,
            patch("backend.notion_client.time.sleep") as sleep,
        ):
            result = client._request("GET", "/data_sources/source")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_repeated_network_error_becomes_concise_runtime_error(self):
        client = NotionClient("token", "database", data_source_id="source")
        error = requests.exceptions.SSLError("unexpected EOF")

        with (
            patch.object(client.session, "request", side_effect=error) as request,
            patch("backend.notion_client.time.sleep") as sleep,
            self.assertRaisesRegex(RuntimeError, "Notion 网络连接失败"),
        ):
            client._request("GET", "/data_sources/source")

        self.assertEqual(request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_scheduler_waits_for_interval_after_sync_failure(self):
        scheduler = AutomationScheduler()
        settings = {
            "notion_sync_enabled": True,
            "notion_sync_interval_minutes": 5,
            "rss_enabled": False,
            "auto_publish_enabled": False,
        }

        with (
            patch("backend.scheduler.get_settings", return_value=settings),
            patch(
                "backend.scheduler.sync_from_notion",
                side_effect=RuntimeError("Notion 网络连接失败"),
            ) as sync,
        ):
            asyncio.run(scheduler._tick())
            asyncio.run(scheduler._tick())

        sync.assert_called_once_with()
        self.assertIsNone(scheduler.last_sync_at)
        self.assertIsNotNone(scheduler.last_sync_attempt_at)
        self.assertEqual(
            scheduler.status()["last_sync_error"],
            "Notion 网络连接失败",
        )


if __name__ == "__main__":
    unittest.main()
