import json
import re

import requests


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

    def chat_with_tools(self, messages, tools):
        self.validate()
        response = self.session.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.model,
                "temperature": 0.2,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
            },
            timeout=180,
        )
        self._raise(response)
        payload = response.json()
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("AI 响应缺少 choices[0].message") from exc
        if not isinstance(message, dict):
            raise RuntimeError("AI 助手响应格式无效")
        content = message.get("content")
        if isinstance(content, list):
            message["content"] = "\n".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
        elif content is not None and not isinstance(content, str):
            message["content"] = str(content)
        return message

    def enrich(self, article):
        self.validate()
        prompt = f"""
你是一名严谨的中文内容编辑。请审阅下面的主稿，但不得改写正文，也不得
虚构事实、数据、经历或引用。

任务：
1. 提取 1-5 个准确、简洁的标签，标签不能为空；
2. 推荐一个可选标题，用户会自行决定是否采用；
3. 写一段不超过 120 字的摘要；
4. 给编辑留下需要人工确认的事项；
5. 提炼一个公众号封面视觉方案：只描述一个具体主体、一个场景和一个关键动作，必须直接对应文章核心观点，不使用空泛科技意象；
6. 提炼一个 6-14 个汉字的封面短标题，保留文章核心信息，不使用标点、引号或营销套话。

{self.custom_prompt}

仅返回一个 JSON 对象，不要 Markdown 代码围栏：
{{
  "recommended_title": "推荐标题",
  "tags": ["标签"],
  "summary": "摘要",
  "editor_notes": "人工确认事项，没有则为空字符串",
  "cover_brief": "单一、具体、与文章核心观点直接相关的封面主体和场景",
  "cover_title": "6-14 个汉字的封面短标题"
}}

主稿标题：{article["title"]}
作者：{article.get("author", "")}
主稿 Markdown：
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
                        "content": (
                            "你只输出合法 JSON，是一名不虚构事实的内容编辑。"
                        ),
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
        return self._validate_result(result)

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
        cover_guidance = (
            """
文章封面规则：
- image_plan 第 1 项必须专门设计为微信公众号文章封面，position 为 cover，purpose 为“公众号文章封面”。
- 封面 prompt 只选择一个与文章核心论点直接相关的具体主体、场景和关键动作；不要随机组合通用图标、动物、钱币、沙漏或科技光效。
- 顶层 cover_title 必须是 6-14 个汉字的封面短标题，准确概括文章核心，不使用标点、引号或营销套话。
- 封面按 2.35:1 横向头图思考：短标题位于左侧并控制在两行以内，主体位于中间偏右且仍在中央正方形安全区。
- 图片中只允许准确出现 cover_title，不得增加副标题、英文、数字、Logo 或装饰性文字。
- 电脑屏幕、手机、纸张、书页、书封、招牌和背景标识不得承载可读文字；如场景需要这些物体，只能显示空白界面或不可读的抽象线框。
- 正文中不要为封面放置占位符；其余正文配图从 <!-- image:2 --> 开始对应。
""".strip()
            if article_type == "article" and image_count
            else "图文内容的第 1 张图仍是整套竖版卡片的封面页，不套用公众号横向封面规则；每一页都在正文保留对应的 image:n 占位符。"
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
6. 图片占位符必须遵循下方的文章封面规则或图文规则，不得把公众号封面重复插入正文。
7. image_plan 必须为每张图给出 position、alt、prompt、purpose。
   prompt 应描述主体、场景、构图、光线与视觉风格，避免要求模型生成文字。

{cover_guidance}

{self.custom_prompt}

只返回合法 JSON 对象，不要代码围栏或解释：
{{
  "title": "标题",
  "cover_title": "6-14 个汉字的封面短标题",
  "summary": "120 字以内摘要",
  "content_md": "Markdown 正文",
  "tags": ["3-8 个标签"],
  "image_plan": [
    {{
      "position": "cover 或 image:n",
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

    def generate_assistant_item(self, target, instruction, source_url=""):
        self.validate()
        target_guidance = {
            "note": (
                "生成一张原子化 Markdown 卡片笔记。整张卡片只介绍一个概念、"
                "一个事实、一个结论或一个操作点；标题必须直接命名这个小点。"
                "如果用户输入包含多个主题，只选择最核心的一个，不罗列其余主题。"
                "正文控制在 150-500 字，最多三个短段落，不扩写行业背景、相关概念、"
                "延伸阅读或泛化总结；标签 1-5 个。"
            ),
            "news": (
                "整理为资讯资料卡。只使用用户提供的信息，不补造新闻事实、"
                "数据、时间或引语；信息不足时明确写出待核实项。"
            ),
            "image": (
                "设计一张可进入素材库的图片。image_prompt 要具体描述主体、"
                "场景、构图、光线和风格，且要求画面中不要生成文字或水印。"
            ),
        }
        if target not in target_guidance:
            raise ValueError("助手目标类型无效")
        prompt = f"""
用户希望通过内容助手创建一项资料。

目标：{target}
用户要求：
{instruction}
来源链接：{source_url or "未提供"}

任务要求：
{target_guidance[target]}
标题简洁明确；摘要/说明保持简短；标签数量服从对应目标要求。
Markdown 正文使用清晰的小标题和列表，不要重复一级标题。
{self.custom_prompt}

只返回合法 JSON 对象，不要代码围栏或解释：
{{
  "title": "标题",
  "summary": "摘要或素材说明",
  "content_md": "Markdown 正文；图片目标可为空",
  "tags": ["标签"],
  "source_name": "资讯来源名称；非资讯留空",
  "image_prompt": "图片生成提示词；非图片留空"
}}
""".strip()
        response = self.session.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.model,
                "temperature": 0.55,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是墨流内容助手，只输出合法 JSON，"
                            "不虚构用户未提供的事实。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=180,
        )
        self._raise(response)
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("AI 响应缺少 choices[0].message.content") from exc
        return self.validate_assistant_item(
            target,
            self._parse_json(content),
        )

    @staticmethod
    def validate_assistant_item(target, result):
        if target not in {"note", "news", "image"}:
            raise ValueError("助手目标类型无效")
        if not isinstance(result, dict):
            raise RuntimeError("AI 助手结果必须是 JSON 对象")

        def clean(value, limit):
            return str(value or "").strip()[:limit]

        title = clean(result.get("title"), 200 if target == "news" else 120)
        if not title:
            raise RuntimeError("AI 助手结果缺少标题")
        content_limit = {"news": 50000, "note": 1000}.get(target, 20000)
        content_md = clean(result.get("content_md"), content_limit)
        image_prompt = clean(result.get("image_prompt"), 3000)
        if target in {"note", "news"} and not content_md:
            raise RuntimeError("AI 助手结果缺少正文")
        if target == "image" and not image_prompt:
            raise RuntimeError("AI 助手结果缺少图片提示词")
        tags = result.get("tags")
        tags = tags if isinstance(tags, list) else []
        return {
            "title": title,
            "summary": clean(result.get("summary"), 120 if target == "note" else 1000),
            "content_md": content_md,
            "tags": [
                clean(tag, 30) for tag in tags if clean(tag, 30)
            ][: 5 if target == "note" else 12],
            "source_name": clean(result.get("source_name"), 120),
            "image_prompt": image_prompt,
        }
    def generate_image_storyboard(self, specification):
        self.validate()
        page_count = int(specification.get("image_count") or 5)
        prompt = f"""
请为中文图文帖子设计可直接出图、可脱离发布文案独立阅读的分镜脚本。

这里的“图文”不是文章配图：读者主要通过逐页图片获取内容，图片必须承担完整的信息表达。

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
1. 第 1 页必须是 cover，标题短而有记忆点，并在 body 中给出一句副标题；其余页面为 content，最后一页可为 ending。
2. 每页只讲一个重点，但必须讲完整。headline 适合大字展示；body 是必须原样放进图片的可见正文，内容页建议 40-140 个中文字符，可使用 2-5 条短列表、步骤、对比或结论，不能只写一句空泛口号。
3. 相邻页面要形成清楚的阅读顺序，避免重复观点。仅看所有图片、不看 caption_md，读者也应能理解主题并获得完整信息。
4. visual 只描述辅助信息理解的主体、场景、图标、图表或关键视觉元素，不要用视觉装饰替代正文内容。
5. layout 必须明确本页的信息结构，例如“标题 + 三条要点 + 底部结论”“左右对比”“三步流程”，并确保信息区是页面主体、视觉元素是辅助。
6. visual_style 是所有页面共享的设计系统，具体描述色板、字体气质、图形语言和版式规则。
7. caption_md 是图片之外的发布文案，不重复逐页文案，结尾可自然引导互动。
8. 不虚构数据、案例、经历或引用；避免平台 Logo、用户 ID、水印、手机边框和无关文字。

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
                "cover": "封面页：准确呈现主标题和副标题，标题占据视觉主位，瞬间传达主题；视觉负责吸引，但不能遮挡文字。",
                "content": "内容页：这是知识信息卡，不是插画。文字信息区应占主要版面，完整呈现本页观点、步骤或列表；视觉元素只用于解释和强调。",
                "ending": "收尾页：完整呈现总结、清单或行动建议，信息仍然可独立阅读，画面有明确的收束感。",
            }[page["role"]]
            prompt = f"""
生成一张高质量中文信息卡片页面，竖版 3:4，画面铺满，不要白边和手机边框。

这是一组以图片为主要阅读载体的图文内容，不是给文章配一张装饰插图。页面必须先把信息讲清楚，再考虑视觉美感。

当前页面：P{page['index'] + 1} / {len(storyboard['pages'])}，{page['role']}
必须逐字、完整、清晰呈现的中文主标题：{page['headline']}
必须逐字、完整、清晰呈现的中文正文（保留换行和列表层级）：
---
{page['body'] or '无正文，不要自行添加文字'}
---
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

硬性排版要求：
- 信息表达优先，内容页的标题和正文区域合计占页面视觉权重的 60%-80%，插画、摄影或装饰不得喧宾夺主。
- 标题、正文、列表必须有明确字号层级和足够对比度，适合手机直接阅读；正文不能缩成小字，也不能被裁切、遮挡或改写。
- 可以使用分区、序号、项目符号、流程线、对比栏和小图标组织内容，不要生成只有一句标题的大幅氛围图。

所有页面必须像同一位设计师完成的同一套作品。中文必须清晰、完整、方向正确，除指定标题和正文外不要生成其他文字。不要平台 Logo、用户 ID、水印、二维码或签名。
""".strip()
            plans.append(
                {
                    "position": f"image:{page['index'] + 1}",
                    "alt": page["headline"],
                    "purpose": page["role"],
                    "prompt": prompt,
                    "content_kind": "image_post",
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
        cover_title = re.sub(
            r"[\s“”\"'《》【】\[\]]+",
            "",
            str(result.get("cover_title") or ""),
        ).strip()[:18] or title[:18]

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
            "cover_title": cover_title,
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
    def _validate_result(result):
        if not isinstance(result, dict):
            raise RuntimeError("AI 结果必须是 JSON 对象")
        tags = result.get("tags", [])
        if not isinstance(tags, list):
            raise RuntimeError("AI 结果中的 tags 格式不正确")
        clean_tags = list(
            dict.fromkeys(
                str(tag).strip()
                for tag in tags
                if str(tag).strip()
            )
        )[:5]
        if not clean_tags:
            raise RuntimeError("AI 未生成有效标签，请重试或调整模型")
        return {
            "recommended_title": str(
                result.get("recommended_title", "")
            ).strip(),
            "tags": clean_tags,
            "summary": str(result.get("summary", "")).strip(),
            "editor_notes": str(result.get("editor_notes", "")).strip(),
            "cover_brief": str(result.get("cover_brief", "")).strip()[:800],
            "cover_title": re.sub(
                r"[\s“”\"'《》【】\[\]]+",
                "",
                str(result.get("cover_title") or ""),
            ).strip()[:18],
        }
