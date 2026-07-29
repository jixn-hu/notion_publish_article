import unittest

from backend.publish_progress import PublishProgressStore


class PublishProgressStoreTests(unittest.TestCase):
    def test_tracks_events_progress_and_completion(self):
        store = PublishProgressStore()
        operation_id = store.begin("manual", "测试稿件", total=2, article_id=7)

        store.event(operation_id, "CSDN：正在保存草稿", platform="csdn")
        store.event(
            operation_id,
            "CSDN：草稿已保存",
            level="success",
            platform="csdn",
            advance=1,
        )
        store.finish(operation_id, "completed", "发布任务已完成")

        result = store.snapshot()
        self.assertEqual(result["id"], operation_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["current"], 2)
        self.assertEqual(result["events"][1]["level"], "success")
        self.assertEqual(result["summary"], "发布任务已完成")

    def test_snapshot_is_detached_from_internal_state(self):
        store = PublishProgressStore()
        operation_id = store.begin("automatic", "自动发布")
        store.event(operation_id, "开始检查")

        result = store.snapshot()
        result["events"].append({"message": "外部修改"})

        self.assertEqual(len(store.snapshot()["events"]), 1)


if __name__ == "__main__":
    unittest.main()
