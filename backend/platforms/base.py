from abc import ABC, abstractmethod


class PlatformPublisher(ABC):
    key = ""
    name = ""
    implemented = False
    content_types = ()

    def __init__(self, settings):
        self.settings = settings

    def status(self):
        return {
            "key": self.key,
            "name": self.name,
            "implemented": self.implemented,
            "enabled": self.is_enabled(),
            "configured": self.is_configured(),
            "content_types": list(self.content_types),
        }

    def supports_content_type(self, article_type):
        return article_type in self.content_types

    def is_enabled(self):
        return bool(self.settings.get(f"{self.key}_enabled", False))

    @abstractmethod
    def is_configured(self):
        raise NotImplementedError

    @abstractmethod
    def publish(self, article, action="publish"):
        raise NotImplementedError

    def test_connection(self):
        if not self.implemented:
            raise NotImplementedError(f"{self.name}发布能力尚未实现")
        raise NotImplementedError


class PlaceholderPublisher(PlatformPublisher):
    implemented = False

    def is_configured(self):
        return False

    def publish(self, article, action="publish"):
        raise NotImplementedError(f"{self.name}发布能力尚未实现")
