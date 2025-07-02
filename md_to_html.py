import markdown
import re
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter


def md_to_wechat_html(md_content):
    """
    将 Markdown 转换为微信公众号友好的 HTML（仅核心内容）

    参数:
    md_content (str): Markdown 格式的内容

    返回:
    str: 格式化后的 HTML 内容
    """
    # Markdown 扩展配置
    extensions = [
        'markdown.extensions.extra',
        'markdown.extensions.codehilite',
        'markdown.extensions.tables',
        'markdown.extensions.toc'
    ]

    # 转换 Markdown 为 HTML
    html_content = markdown.markdown(md_content, extensions=extensions)

    # 高亮代码块
    html_content = highlight_code_blocks(html_content)

    # 应用公众号专用样式
    html_content = f"""
    <style>
        /* 公众号专用样式 */
        .markdown-body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
            font-size: 16px;
            line-height: 1.7;
            color: #333;
            max-width: 680px;
            margin: 0 auto;
            padding: 20px;
            background-color: #fff;
        }}

        .markdown-body h1, 
        .markdown-body h2, 
        .markdown-body h3, 
        .markdown-body h4, 
        .markdown-body h5, 
        .markdown-body h6 {{
            margin: 24px 0 16px;
            font-weight: 600;
            line-height: 1.4;
            color: #1a1a1a;
        }}

        .markdown-body h1 {{
            font-size: 22px;
            border-left: 4px solid #4361ee;
            padding-left: 12px;
        }}

        .markdown-body h2 {{
            font-size: 20px;
            padding-bottom: 8px;
            border-bottom: 1px solid #f0f0f0;
        }}

        .markdown-body h3 {{
            font-size: 18px;
        }}

        .markdown-body h4 {{
            font-size: 17px;
        }}

        .markdown-body p {{
            margin: 0 0 18px 0;
            text-align: justify;
            word-break: break-word;
        }}

        .markdown-body a {{
            color: #4361ee;
            text-decoration: none;
            border-bottom: 1px solid rgba(67, 97, 238, 0.3);
        }}

        .markdown-body img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 20px auto;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        }}

        .markdown-body blockquote {{
            background-color: #f8f9ff;
            border-left: 4px solid #4361ee;
            padding: 15px 20px;
            margin: 20px 0;
            color: #555;
            border-radius: 0 8px 8px 0;
        }}

        .markdown-body ul, 
        .markdown-body ol {{
            padding-left: 25px;
            margin: 0 0 20px 0;
        }}

        .markdown-body li {{
            margin-bottom: 8px;
        }}

        .markdown-body code {{
            font-family: Consolas, Monaco, 'Andale Mono', monospace;
            background-color: #f5f7fa;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 15px;
        }}

        .markdown-body pre {{
            position: relative;
            margin: 25px 0;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
            background: #2d2d2d;
        }}

        .markdown-body pre code {{
            background: none;
            padding: 20px;
            display: block;
            overflow: auto;
            font-size: 14px;
            color: #f8f8f2;
            border-radius: 8px;
        }}

        .markdown-body table {{
            width: 100%;
            border-collapse: collapse;
            margin: 25px 0;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
            border-radius: 8px;
            overflow: hidden;
        }}

        .markdown-body th, 
        .markdown-body td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #f0f0f0;
        }}

        .markdown-body th {{
            background-color: #f8f9ff;
            font-weight: 600;
        }}

        .markdown-body tr:hover {{
            background-color: #fafafa;
        }}

        @media (max-width: 480px) {{
            .markdown-body {{
                padding: 15px;
            }}

            .markdown-body h1 {{
                font-size: 20px;
            }}

            .markdown-body h2 {{
                font-size: 19px;
            }}

            .markdown-body h3 {{
                font-size: 18px;
            }}

            .markdown-body p, 
            .markdown-body li {{
                font-size: 15px;
            }}

            .markdown-body pre code {{
                font-size: 13px;
                padding: 15px;
            }}
        }}
    </style>

    <div class="markdown-body">
        {html_content}
    </div>
    """

    return html_content


def highlight_code_blocks(html_content):
    """
    高亮处理代码块

    参数:
    html_content (str): 包含代码块的 HTML 内容

    返回:
    str: 高亮处理后的 HTML 内容
    """
    # 匹配代码块
    pattern = re.compile(r'<pre><code class="language-(.*?)">(.*?)</code></pre>', re.DOTALL)

    def replacer(match):
        language = match.group(1)
        code = match.group(2)

        try:
            # 获取对应的语法分析器
            lexer = get_lexer_by_name(language, stripall=True)
            # 使用 GitHub 风格的样式
            formatter = HtmlFormatter(style='github', cssclass="highlight", noclasses=True)
            # 高亮代码
            highlighted = highlight(code, lexer, formatter)
            return highlighted
        except:
            # 如果无法识别语言，返回原始代码块
            return f'<pre><code>{code}</code></pre>'

    return pattern.sub(replacer, html_content)


# 示例使用
if __name__ == "__main__":
    # Markdown 示例内容
    sample_md = """
## Python Markdown 转换器

这是一个简洁高效的 Markdown 转 HTML 工具，专为微信公众号设计。

### 核心特性

- **代码高亮**：支持多种编程语言
- **响应式设计**：完美适配移动设备
- **简洁美观**：无多余元素干扰
- **表格支持**：专业的数据展示

```
import markdown

def convert_md_to_html(md_text):
    \"\"\"
    将 Markdown 转换为 HTML
    \"\"\"
    return markdown.markdown(
        md_text,
        extensions=['extra', 'codehilite']
    )
```
    """
    # 转换 Markdown 为微信公众号友好的 HTML
    html_content = md_to_wechat_html(sample_md)
    # 输出结果
    print(html_content)