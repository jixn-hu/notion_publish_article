import base64
import binascii
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlparse
from uuid import uuid4

import requests

import backend.media as media


MAX_IMAGE_BYTES = 25 * 1024 * 1024


class AIImageService:
    def __init__(self, settings):
        self.base_url = (
            settings.get("ai_image_base_url") or settings.get("ai_base_url") or ""
        ).rstrip("/")
        self.api_key = (
            settings.get("ai_image_api_key") or settings.get("ai_api_key") or ""
        )
        self.model = str(settings.get("ai_image_model") or "").strip()
        self.size = str(settings.get("ai_image_size") or "1024x1024").strip()
        self.image_post_size = str(
            settings.get("ai_image_post_size") or "1024x1536"
        ).strip()
        self.session = requests.Session()
        self.session.trust_env = False
        proxy_url = str(settings.get("ai_proxy_url") or "").strip()
        if proxy_url:
            self.session.proxies.update({"http": proxy_url, "https": proxy_url})

    def validate(self):
        if not self.base_url:
            raise ValueError("请配置图片 API Base URL，或复用 AI API Base URL")
        if not self.api_key:
            raise ValueError("请配置图片 API Key，或复用 AI API Key")
        if not self.model:
            raise ValueError("请配置图片生成模型")

    def generate_images(self, image_plan):
        plans = list(image_plan or [])
        if not plans:
            return []
        self.validate()
        generated = []
        try:
            for item in plans:
                generated.append(self._generate_one(item))
        except Exception:
            for item in generated:
                Path(item["path"]).unlink(missing_ok=True)
            raise
        return generated

    def _generate_one(self, plan):
        size = (
            self.image_post_size
            if plan.get("content_kind") == "image_post"
            else self.size
        )
        response = self.session.post(
            f"{self.base_url}/images/generations",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "prompt": plan["prompt"],
                "size": size,
                "n": 1,
                "response_format": "b64_json",
            },
            timeout=300,
        )
        self._raise(response)
        payload = response.json()
        image_bytes = self._image_bytes(payload)
        extension = self._image_extension(image_bytes)
        directory = media.MEDIA_DIR / "ai"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{uuid4().hex}{extension}"
        target.write_bytes(image_bytes)
        return {
            "position": plan.get("position") or "",
            "alt": plan.get("alt") or "文章配图",
            "purpose": plan.get("purpose") or "",
            "prompt": plan["prompt"],
            "path": str(target.resolve()),
        }

    def _image_bytes(self, payload):
        items = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(items, dict):
            image_urls = items.get("image_urls")
            if isinstance(image_urls, list) and image_urls:
                return self._download(image_urls[0])
        if not isinstance(items, list) or not items:
            raise RuntimeError("图片生成响应缺少 data")
        item = items[0]
        if not isinstance(item, dict):
            raise RuntimeError("图片生成响应格式无效")
        if item.get("b64_json"):
            try:
                data = base64.b64decode(item["b64_json"], validate=True)
            except (ValueError, binascii.Error) as exc:
                raise RuntimeError("图片生成响应包含无效 Base64") from exc
            return self._validated_bytes(data)
        if item.get("url"):
            return self._download(item["url"])
        image_urls = item.get("image_urls")
        if isinstance(image_urls, list) and image_urls:
            source = image_urls[0]
            if isinstance(source, dict):
                source = source.get("url")
            return self._download(source)
        raise RuntimeError("图片生成响应缺少 b64_json 或 url")

    def _download(self, source):
        source = str(source or "").strip()
        if source.startswith("data:"):
            try:
                metadata, encoded = source.split(",", 1)
                data = (
                    base64.b64decode(encoded, validate=True)
                    if ";base64" in metadata
                    else unquote_to_bytes(encoded)
                )
            except (ValueError, binascii.Error) as exc:
                raise RuntimeError("图片生成响应包含无效 Data URL") from exc
            return self._validated_bytes(data)
        if urlparse(source).scheme not in {"http", "https"}:
            raise RuntimeError("图片生成响应包含无效图片地址")
        response = self.session.get(source, timeout=120, stream=True)
        self._raise(response)
        chunks = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise RuntimeError("生成图片超过 25MB 限制")
            chunks.append(chunk)
        return self._validated_bytes(b"".join(chunks))

    @staticmethod
    def _validated_bytes(data):
        if not data:
            raise RuntimeError("生成图片内容为空")
        if len(data) > MAX_IMAGE_BYTES:
            raise RuntimeError("生成图片超过 25MB 限制")
        AIImageService._image_extension(data)
        return data

    @staticmethod
    def _image_extension(data):
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if data.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return ".gif"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return ".webp"
        raise RuntimeError("图片生成接口返回的不是受支持的图片")

    @staticmethod
    def _raise(response):
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = ""
            try:
                payload = response.json()
                detail = payload.get("error", {}).get("message") or payload.get("message")
            except (ValueError, AttributeError):
                detail = response.text[:300]
            raise RuntimeError(
                f"图片生成接口请求失败：{detail or response.status_code}"
            ) from exc
