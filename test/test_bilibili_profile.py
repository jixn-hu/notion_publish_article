import unittest

import backend.accounts
from backend.platforms.bilibili import (
    _bilibili_api_profile,
    _bilibili_text_profile,
)


class BilibiliProfileTests(unittest.TestCase):
    def test_api_profile_extracts_identity_and_metrics(self):
        profile = _bilibili_api_profile(
            {
                "code": 0,
                "data": {
                    "isLogin": True,
                    "mid": 123456,
                    "uname": "小胡",
                    "face": "https://example.com/avatar.jpg",
                    "level_info": {"current_level": 6},
                },
            },
            {
                "code": 0,
                "data": {
                    "following": 120,
                    "follower": 3456,
                },
            },
            {
                "code": 0,
                "data": {
                    "video": 78,
                },
            },
        )

        self.assertEqual(profile["display_name"], "小胡")
        self.assertEqual(profile["platform_user_id"], "123456")
        self.assertEqual(profile["avatar_url"], "https://example.com/avatar.jpg")
        self.assertEqual(profile["following_count"], 120)
        self.assertEqual(profile["followers_count"], 3456)
        self.assertEqual(profile["works_count"], 78)
        self.assertEqual(profile["level"], 6)

    def test_text_profile_is_used_as_api_fallback(self):
        profile = _bilibili_text_profile(
            "UID: 123456\n关注 12\n粉丝 1.2万\n视频 35"
        )

        self.assertEqual(profile["platform_user_id"], "123456")
        self.assertEqual(profile["following_count"], 12)
        self.assertEqual(profile["followers_count"], 12000)
        self.assertEqual(profile["works_count"], 35)

    def test_profile_handler_is_registered(self):
        self.assertEqual(
            backend.accounts.ACCOUNT_PROFILE_HANDLERS["bilibili"],
            (
                "backend.platforms.bilibili",
                "fetch_bilibili_profile",
            ),
        )


if __name__ == "__main__":
    unittest.main()
