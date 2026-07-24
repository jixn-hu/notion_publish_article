import json
import re

import requests


PLATFORM_GUIDANCE = {
    "wechat": "微信公众号：结构完整、标题克制、段落清晰，适合深度阅读。",
    "xiaohongshu": "小红书：标题有吸引力，正文短段落、重点前置，可给出话题标签。",
    "csdn": "CSDN：技术表达准确，保留代码和步骤，标题便于搜索。",
}


class AIContentService:
    def __init__(self, settings):
        self.base_url = settings["ai_base_url"].rstrip("/")
        self.api_key = settings["ai_api_key"]
        self.model = settings["ai_model"]
        self.custom_prompt = settings["ai_custom_prompt"].strip()
        self.session = requests.Session()
        self.session.trust_env = False
        proxy_url = settings["ai_proxy_url"].strip()
        if proxy_url:
            self.session.proxies.update({"http": proxy_url, "https": proxy_url})

    def validate(self):
        if not self.base_url:
            raise ValueError("请配置 AI API Base URL")
        if not self.api_key:
            raise ValueError("请配置 AI API Key")
        if not self.model:
            raise ValueError("请配置 AI 模型")

    def test_connection(self):
        self.validate()
        response = self.session.get(
            f"{self.base_url}/models",
            headers=self._headers(),
            timeout=30,
        )
        self._raise(response)
        return {"message": "AI 接口连接成功"}

    def enrich(self, article):
        self.validate()
        targets = article.get("target_platforms") or ["wechat"]
        guidance = "\n".join(
            PLATFORM_GUIDANCE[key]
            for key in targets
            if key in PLATFORM_GUIDANCE
        )
        prompt = f"""
你是一名严谨的中文内容编辑。请加工下面的原稿，但不得虚构事实、数据、
经历或引用。信息不足时保留原意，不自行补造。

任务：
1. 提取 3-8 个准确标签；
2. 写一段不超过 120 字的摘要；
3. 给编辑留下需要人工确认的事项；
4. 针对目标平台分别生成标题和 Markdown 正文。可以优化结构、语气、
   开头和小标题，但必须保留原稿事实。

平台要求：
{guidance}

{self.custom_prompt}

仅返回一个 JSON 对象，不要 Markdown 代码围栏：
{{
  "tags": ["标签"],
  "summary": "摘要",
  "editor_notes": "人工确认事项，没有则为空字符串",
  "platforms": {{
    "wechat": {{
      "title": "平台标题",
      "content_md": "平台 Markdown 正文",
      "tags": ["平台标签"]
    }}
  }}
}}

原稿标题：{article["title"]}
作者：{article.get("author", "")}
目标平台：{", ".join(targets)}
原稿 Markdown：
{article["content_md"]}
""".strip()

        response = self.session.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.model,
                "temperature": 0.3,
                "messages": [
                    {
                        "role": "system",
                        "content": "你只输出合法 JSON，是一名不虚构事实的内容编辑。",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=180,
        )
        self._raise(response)
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("AI 响应缺少 choices[0].message.content") from exc
        result = self._parse_json(content)
        return self._validate_result(result, targets)

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _raise(response):
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            try:
                data = response.json()
                message = data.get("error", {}).get("message") or response.text
            except ValueError:
                message = response.text
            raise RuntimeError(f"AI API 请求失败: {message}") from exc

    @staticmethod
    def _parse_json(content):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError("AI 没有返回合法 JSON，请重试或调整模型") from exc

    @staticmethod
    def _validate_result(result, targets):
        if not isinstance(result, dict):
            raise RuntimeError("AI 结果必须是 JSON 对象")
        tags = result.get("tags", [])
        platforms = result.get("platforms", {})
        if not isinstance(tags, list) or not isinstance(platforms, dict):
            raise RuntimeError("AI 结果中的 tags 或 platforms 格式不正确")
        clean_platforms = {}
        for key in targets:
            value = platforms.get(key)
            if not isinstance(value, dict):
                continue
            clean_platforms[key] = {
                "title": str(value.get("title", "")).strip(),
                "content_md": str(value.get("content_md", "")).strip(),
                "tags": [
                    str(tag).strip()
                    for tag in value.get("tags", [])
                    if str(tag).strip()
                ],
            }
        return {
            "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
            "summary": str(result.get("summary", "")).strip(),
            "editor_notes": str(result.get("editor_notes", "")).strip(),
            "platforms": clean_platforms,
        }

