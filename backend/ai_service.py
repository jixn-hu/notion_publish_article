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

    def generate_article(self, specification):
        self.validate()
        article_type = specification["article_type"]
        image_count = int(specification.get("image_count") or 0)
        if article_type == "image":
            type_guidance = (
                "生成适合图文平台的内容：开头有明确钩子，主体使用 3-6 个短段落"
                "或清单，表达自然，结尾有互动；不要写成冗长论文。"
            )
        else:
            type_guidance = (
                "生成结构完整的中文文章：论点清晰，段落连贯，有二级标题，"
                "适合公众号或知识平台阅读。"
            )
        prompt = f"""
请围绕给定主题创作一篇可直接进入人工编辑流程的中文稿件。

主题：{specification["topic"]}
内容类型：{"图文" if article_type == "image" else "文章"}
目标读者：{specification.get("audience") or "由你根据主题判断"}
表达风格：{specification.get("style") or "自然、具体、克制"}
目标字数：{specification["word_count"]} 字左右
补充要求：{specification.get("requirements") or "无"}
用户选定的自有素材：
{specification.get("materials") or "未选择参考素材"}
外部参考资讯：
{specification.get("news") or "未选择参考资讯"}
配图数量：{image_count}

写作要求：
1. {type_guidance}
2. 自有素材用于创作方向与视觉参考；外部资讯用于事实参考，保留其来源和时间语境。
3. 不虚构具体数据、案例、经历或引用；资讯存在冲突或无法确认时，使用审慎表述。
4. 避免模板化开头、空泛总结和连续堆砌形容词。
5. Markdown 正文不要重复一级标题。
6. 需要配图时，在正文合适位置放置 <!-- image:1 --> 形式的占位符，
   数量与配图数量一致。
7. image_plan 必须为每张图给出 position、alt、prompt、purpose。
   prompt 应描述主体、场景、构图、光线与视觉风格，避免要求模型生成文字。

{self.custom_prompt}

只返回合法 JSON 对象，不要代码围栏或解释：
{{
  "title": "标题",
  "summary": "120 字以内摘要",
  "content_md": "Markdown 正文",
  "tags": ["3-8 个标签"],
  "image_plan": [
    {{
      "position": "image:1",
      "alt": "图片说明",
      "prompt": "图片生成提示词",
      "purpose": "图片在文章中的作用"
    }}
  ]
}}
""".strip()
        response = self.session.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.model,
                "temperature": 0.65,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是中文内容主编，只输出合法 JSON。"
                            "内容具体但不编造不可验证的事实。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=240,
        )
        self._raise(response)
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("AI 响应缺少 choices[0].message.content") from exc
        return self._validate_generated_article(
            self._parse_json(content),
            image_count,
        )

    def generate_image_storyboard(self, specification):
        self.validate()
        page_count = int(specification.get("image_count") or 5)
        prompt = f"""
请为中文图文帖子设计可直接出图的分镜脚本。

主题：{specification["topic"]}
目标读者：{specification.get("audience") or "由你根据主题判断"}
表达风格：{specification.get("style") or "自然、具体、有审美"}
页数：严格输出 {page_count} 页（包含封面）
补充要求：{specification.get("requirements") or "无"}
用户选定的自有素材：
{specification.get("materials") or "未选择参考素材"}
外部参考资讯：
{specification.get("news") or "未选择参考资讯"}

要求：
1. 第 1 页必须是 cover，标题短而有记忆点；其余页面为 content，最后一页可为 ending。
2. 每页只讲一个重点，headline 适合大字展示，body 要短、具体、可读。
3. visual 描述主体、场景和关键视觉元素，layout 描述标题、正文、留白和视觉焦点的位置。
4. visual_style 是所有页面共享的设计系统，具体描述色板、字体气质、图形语言和版式规则。
5. caption_md 是图片之外的发布文案，不重复逐页文案，结尾可自然引导互动。
6. 不虚构数据、案例、经历或引用；避免平台 Logo、用户 ID、水印、手机边框和无关文字。

只返回合法 JSON，不要代码围栏或解释：
{{
  "title": "帖子标题",
  "summary": "120 字以内摘要",
  "caption_md": "发布文案",
  "tags": ["3-8 个标签"],
  "visual_style": {{
    "direction": "整体视觉方向",
    "palette": ["#颜色1", "#颜色2", "#颜色3"],
    "typography": "中文字体气质与字号层级",
    "graphics": "插画、摄影、图标或纹理规则",
    "composition": "统一版式和留白规则"
  }},
  "pages": [{{
    "role": "cover",
    "headline": "页面主标题",
    "body": "页面正文，可为空",
    "visual": "主体、场景与视觉元素",
    "layout": "构图与文字位置"
  }}]
}}
""".strip()
        response = self.session.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.model,
                "temperature": 0.75,
                "messages": [
                    {"role": "system", "content": "你是中文图文内容总监，只输出合法 JSON。"},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=240,
        )
        self._raise(response)
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("AI 响应缺少 choices[0].message.content") from exc
        return self.validate_image_storyboard(
            self._parse_json(content),
            expected_pages=page_count,
        )

    @staticmethod
    def validate_image_storyboard(result, expected_pages=None):
        if not isinstance(result, dict):
            raise ValueError("图文分镜必须是 JSON 对象")

        def clean(value, limit):
            return str(value or "").strip()[:limit]

        title = clean(result.get("title"), 120)
        caption_md = clean(result.get("caption_md"), 5000)
        if not title or not caption_md:
            raise ValueError("图文分镜缺少标题或发布文案")

        raw_pages = result.get("pages")
        if not isinstance(raw_pages, list) or not raw_pages:
            raise ValueError("图文分镜至少需要 1 页")
        if expected_pages is not None and len(raw_pages) != int(expected_pages):
            raise ValueError(f"图文分镜必须包含 {int(expected_pages)} 页")
        if len(raw_pages) > 9:
            raise ValueError("图文分镜不能超过 9 页")

        pages = []
        for index, raw_page in enumerate(raw_pages):
            if not isinstance(raw_page, dict):
                raise ValueError(f"第 {index + 1} 页分镜格式无效")
            headline = clean(raw_page.get("headline"), 120)
            visual = clean(raw_page.get("visual"), 800)
            if not headline or not visual:
                raise ValueError(f"第 {index + 1} 页缺少标题或视觉描述")
            role = clean(raw_page.get("role"), 20).lower()
            if index == 0:
                role = "cover"
            elif role not in {"content", "ending"}:
                role = "content"
            pages.append(
                {
                    "index": index,
                    "role": role,
                    "headline": headline,
                    "body": clean(raw_page.get("body"), 1200),
                    "visual": visual,
                    "layout": clean(raw_page.get("layout"), 500),
                }
            )

        raw_style = result.get("visual_style")
        raw_style = raw_style if isinstance(raw_style, dict) else {}
        palette = raw_style.get("palette")
        palette = palette if isinstance(palette, list) else []
        visual_style = {
            "direction": clean(raw_style.get("direction"), 300),
            "palette": [clean(color, 30) for color in palette if clean(color, 30)][:6],
            "typography": clean(raw_style.get("typography"), 300),
            "graphics": clean(raw_style.get("graphics"), 500),
            "composition": clean(raw_style.get("composition"), 500),
        }
        tags = result.get("tags")
        tags = tags if isinstance(tags, list) else []
        return {
            "title": title,
            "summary": clean(result.get("summary"), 240),
            "caption_md": caption_md,
            "tags": [clean(tag, 30) for tag in tags if clean(tag, 30)][:8],
            "visual_style": visual_style,
            "pages": pages,
        }

    @staticmethod
    def image_plan_from_storyboard(storyboard, specification):
        storyboard = AIContentService.validate_image_storyboard(storyboard)
        style = storyboard["visual_style"]
        palette = "、".join(style["palette"]) or "根据主题选择协调且有对比度的色板"
        outline = "\n".join(
            f"P{page['index'] + 1} {page['role']}：{page['headline']}；{page['body']}"
            for page in storyboard["pages"]
        )
        plans = []
        for page in storyboard["pages"]:
            role_guidance = {
                "cover": "封面：主标题占据视觉主位，瞬间传达主题，背景可以更有冲击力。",
                "content": "内容页：信息层级清楚，正文适合手机阅读，重点有明确视觉强调。",
                "ending": "收尾页：总结或行动引导突出，画面有完整、收束的感觉。",
            }[page["role"]]
            prompt = f"""
生成一张高质量中文图文页面，竖版 3:4，画面铺满，不要白边和手机边框。

当前页面：P{page['index'] + 1} / {len(storyboard['pages'])}，{page['role']}
必须准确呈现的中文主标题：{page['headline']}
必须准确呈现的中文正文：{page['body'] or '无正文，不要自行添加文字'}
视觉内容：{page['visual']}
构图要求：{page['layout'] or '保证文字清晰、视觉焦点明确、留白合理'}
页面规则：{role_guidance}

全套统一视觉规范：
- 方向：{style['direction'] or specification.get('style') or '精致的编辑设计感'}
- 色板：{palette}
- 字体气质：{style['typography'] or '清晰的中文字体，标题与正文层级分明'}
- 图形语言：{style['graphics'] or '视觉元素服务于信息，不堆砌装饰'}
- 版式规则：{style['composition'] or '统一边距、网格、圆角和留白节奏'}

主题：{specification.get('topic') or storyboard['title']}
读者：{specification.get('audience') or '中文移动端读者'}
参考素材：{specification.get('materials') or '未选择参考素材'}
参考资讯：{specification.get('news') or '未选择参考资讯'}
完整分镜：
{outline}

所有页面必须像同一位设计师完成的同一套作品。中文必须清晰、完整、方向正确，除指定标题和正文外不要生成其他文字。不要平台 Logo、用户 ID、水印、二维码或签名。
""".strip()
            plans.append(
                {
                    "position": f"image:{page['index'] + 1}",
                    "alt": page["headline"],
                    "purpose": page["role"],
                    "prompt": prompt,
                }
            )
        return plans
    @staticmethod
    def _validate_generated_article(result, image_count):
        if not isinstance(result, dict):
            raise RuntimeError("AI 生成结果必须是 JSON 对象")
        title = str(result.get("title") or "").strip()
        content_md = str(result.get("content_md") or "").strip()
        if not title or not content_md:
            raise RuntimeError("AI 生成结果缺少标题或正文")

        tags = result.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        raw_plan = result.get("image_plan") or []
        if not isinstance(raw_plan, list):
            raw_plan = []
        image_plan = []
        for item in raw_plan[:image_count]:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt") or "").strip()
            if not prompt:
                continue
            image_plan.append(
                {
                    "position": f"image:{len(image_plan) + 1}",
                    "alt": str(item.get("alt") or "文章配图").strip(),
                    "prompt": prompt,
                    "purpose": str(item.get("purpose") or "").strip(),
                }
            )
        while len(image_plan) < image_count:
            index = len(image_plan) + 1
            image_plan.append(
                {
                    "position": f"image:{index}",
                    "alt": f"{title}配图 {index}",
                    "prompt": (
                        f"为中文文章《{title}》创作第 {index} 张配图，"
                        "主体明确，场景真实，构图简洁，光线自然，"
                        "高质量编辑摄影风格，画面中不要出现文字和水印"
                    ),
                    "purpose": "补充文章视觉信息",
                }
            )
        summary = str(result.get("summary") or "").strip()
        if not summary:
            summary = re.sub(r"[#*_>\\[\\]()!-]", "", content_md)[:120].strip()
        return {
            "title": title,
            "summary": summary,
            "content_md": content_md,
            "tags": [str(tag).strip() for tag in tags if str(tag).strip()][:8],
            "image_plan": image_plan,
        }

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

