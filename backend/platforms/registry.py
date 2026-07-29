from backend.platforms.bilibili import BilibiliPublisher
from backend.platforms.channels import ChannelsPublisher
from backend.platforms.csdn import CsdnPublisher
from backend.platforms.douyin import DouyinPublisher
from backend.platforms.wechat import WechatPublisher
from backend.platforms.xiaohongshu import XiaohongshuPublisher


PLATFORM_CLASSES = {
    "wechat": WechatPublisher,
    "xiaohongshu": XiaohongshuPublisher,
    "douyin": DouyinPublisher,
    "channels": ChannelsPublisher,
    "bilibili": BilibiliPublisher,
    "csdn": CsdnPublisher,
}


def get_platforms(settings):
    return {
        key: publisher_class(settings)
        for key, publisher_class in PLATFORM_CLASSES.items()
    }
