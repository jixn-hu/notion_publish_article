import unittest
from unittest.mock import patch

from backend.platforms import csdn


class _Locator:
    def __init__(self, visible=False, text="", on_click=None):
        self.visible = visible
        self.text = text
        self.on_click = on_click
        self.clicks = 0

    @property
    def first(self):
        return self

    def count(self):
        return int(self.visible)

    def is_visible(self):
        return self.visible

    def inner_text(self):
        return self.text

    def wait_for(self, **_kwargs):
        return None

    def click(self):
        self.clicks += 1
        if self.on_click:
            self.on_click()


class _PublishPage:
    def __init__(self):
        self.url = csdn.EDITOR_URL
        self.submit = _Locator(visible=True)
        self.saving = _Locator(visible=True, text="文章正在保存，请耐心等待")
        self.success = _Locator()
        self.waits = []

    def get_by_role(self, _role, **_kwargs):
        return self.submit

    def get_by_text(self, _pattern, **_kwargs):
        return self.success

    def locator(self, _selector):
        return self.saving

    def wait_for_timeout(self, timeout):
        self.waits.append(timeout)
        self.saving.visible = False
        self.url = "https://mp.csdn.net/mp_blog/manage/article"


class CsdnPublishTests(unittest.TestCase):
    def test_publish_waits_for_saving_without_clicking_twice(self):
        page = _PublishPage()

        with patch("backend.platforms.csdn._wait_for_editor_ready"):
            result = csdn._publish_blog(page)

        self.assertEqual(result, page.url)
        self.assertEqual(page.submit.clicks, 1)
        self.assertEqual(page.waits, [500])
