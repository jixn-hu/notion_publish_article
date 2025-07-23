import re

import markdown
import requests
import json
import time
import os
import mimetypes
import logging
import config
from urllib.parse import urljoin
from typing import List, Dict, Union, Tuple
from md_to_html import md_to_wechat_html
from bs4 import BeautifulSoup
"""
微信公众号发布器
支持 发布文章和（图文）类型
"""

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('WechatPublisher')


class WechatOfficialAccountPublisher:
    def __init__(self, app_id: str, app_secret: str, max_retries: int = 3):
        self.app_id = app_id
        self.app_secret = app_secret
        self.access_token = None
        self.token_expire_time = 0
        self.base_api = "https://api.weixin.qq.com/cgi-bin/"
        self.max_retries = max_retries
        self.session = requests.Session()

        # 预定义图片类型限制
        self.image_types = {
            'cover': {'max_size': 2 * 1024 * 1024, 'min_dim': (900, 500)},
            'content': {'max_size': 10 * 1024 * 1024},
            'newspic': {'max_size': 10 * 1024 * 1024}  # 图片消息类型
        }

    def _build_url(self, endpoint: str) -> str:
        """构建完整的API URL"""
        return urljoin(self.base_api, endpoint)

    def _request_with_retry(self, method: str, endpoint: str, **kwargs) -> dict:
        """带重试机制的请求方法"""
        url = self._build_url(endpoint)
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"请求: {method} {url}")
                response = self.session.request(method, url, **kwargs)
                logger.debug(f"响应状态码: {response.status_code}")

                # 处理非200响应
                if response.status_code != 200:
                    error_msg = f"HTTP错误 {response.status_code}: {response.text[:200]}"
                    logger.error(error_msg)
                    raise Exception(error_msg)

                data = response.json()

                # 处理微信API错误码
                if 'errcode' in data and data['errcode'] != 0:
                    error_msg = f"微信API错误: {data['errmsg']} (代码: {data['errcode']})"
                    logger.error(error_msg)

                    # Token过期处理
                    if data['errcode'] in [40001, 42001]:
                        logger.warning("Token过期，尝试刷新...")
                        self.access_token = None
                        return self._request_with_retry(method, endpoint, **kwargs)

                    raise Exception(error_msg)

                return data
            except requests.exceptions.RequestException as e:
                logger.error(f"请求失败: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise
                wait_time = 2 ** attempt
                logger.info(f"等待 {wait_time}秒后重试...")
                time.sleep(wait_time)
        return {}

    def _get_access_token(self) -> str:
        """获取或刷新access_token"""
        if self.access_token and time.time() < self.token_expire_time:
            return self.access_token

        logger.info("获取新的access_token...")
        endpoint = "token?grant_type=client_credential"
        params = {
            "appid": self.app_id,
            "secret": self.app_secret
        }
        data = self._request_with_retry('GET', endpoint, params=params)

        if not data or 'access_token' not in data:
            raise Exception("获取access_token失败")

        self.access_token = data['access_token']
        self.token_expire_time = time.time() + data['expires_in'] - 300
        logger.info(f"获取access_token成功，有效期至 {time.ctime(self.token_expire_time)}")
        return self.access_token

    def upload_permanent_image(self, image_path: str, image_type: str = 'content') -> dict:
        """
        上传永久图片素材
        :param image_path: 图片本地路径或URL
        :param image_type: 'cover'、'content' 或 'newspic'
        :return: {'media_id': media_id, 'url': image_url}
        """
        # 验证图片类型
        if image_type not in self.image_types:
            raise ValueError(f"image_type 必须是 {', '.join(self.image_types.keys())}")

        # 如果是URL，先下载图片到临时文件，再上传
        is_remote = False
        temp_file_path = None
        if image_path.startswith(('http://', 'https://')):
            import tempfile
            import requests
            logger.info(f"下载远程图片: {image_path}")
            resp = requests.get(image_path, stream=True)
            if resp.status_code != 200:
                raise Exception(f"下载远程图片失败: {image_path}")
            suffix = os.path.splitext(image_path)[-1]
            if suffix == '':
                suffix = '.jpg'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                for chunk in resp.iter_content(1024 * 1024):
                    tmp.write(chunk)
                temp_file_path = tmp.name
            image_path = temp_file_path
            is_remote = True

        # 检查文件大小
        file_size = os.path.getsize(image_path)
        max_size = self.image_types[image_type]['max_size']

        if file_size > max_size:
            if is_remote and temp_file_path:
                os.remove(temp_file_path)
            raise Exception(
                f"{image_type}图片大小超过限制（最大{max_size / 1024 / 1024:.1f}MB），当前为{file_size / 1024 / 1024:.2f}MB")

        token = self._get_access_token()
        endpoint = f"material/add_material?access_token={token}&type=image"

        # 自动检测MIME类型
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith('image'):
            mime_type = 'image/jpeg'  # 默认类型

        logger.info(f"上传{image_type}图片: {image_path} ({mime_type})")
        with open(image_path, 'rb') as f:
            files = {'media': (os.path.basename(image_path), f, mime_type)}
            data = self._request_with_retry('POST', endpoint, files=files)

        # 上传后删除临时文件
        if is_remote and temp_file_path:
            try:
                os.remove(temp_file_path)
            except Exception as e:
                logger.warning(f"删除临时文件失败: {temp_file_path}, {str(e)}")

        if not data or 'media_id' not in data:
            raise Exception(f"图片上传失败: {data}")

        logger.info(f"图片上传成功, media_id: {data['media_id']}, url: {data.get('url', '')}")
        return {
            'media_id': data['media_id'],
            'url': data.get('url', ''),
            'is_remote': is_remote
        }

class MarkdownProcessor:
    """Markdown处理工具类"""

    @staticmethod
    def convert_to_html(md_content: str) -> str:
        """
        将Markdown转换为美观的HTML
        :param md_content: Markdown内容
        :return: 格式化后的HTML内容
        """
        # 将Markdown转换为HTML
        # html_content = markdown.markdown(md_content, extensions=['extra', 'tables'])
        html_content = md_to_wechat_html(md_content)
        return html_content

    @staticmethod
    def convert_to_html1(md_content: str) -> str:
        """
        将Markdown转换为美观的HTML
        :param md_content: Markdown内容
        :return: 格式化后的HTML内容
        """
        # 将Markdown转换为HTML
        html_content = markdown.markdown(md_content, extensions=['extra', 'tables'])
        # html_content = md_to_wechat_html(md_content)
        return html_content

    @staticmethod
    def extract_images(html_content: str) -> List[str]:
        """
        从HTML中提取所有图片路径
        :param html_content: HTML内容
        :return: 图片路径列表
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        images = []

        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                images.append(src)

        return images

    @staticmethod
    def replace_image_sources(html_content: str, image_map: Dict[str, str]) -> str:
        """
        替换HTML中的图片路径
        :param html_content: HTML内容
        :param image_map: 图片路径映射 (原始路径 -> 新路径)
        :return: 更新后的HTML内容
        """
        soup = BeautifulSoup(html_content, 'html.parser')

        for img in soup.find_all('img'):
            src = img.get('src')
            if src and src in image_map:
                img['src'] = image_map[src]

        return str(soup)


class WechatArticlePublisher:
    """微信公众号文章发布器"""

    def __init__(self, client: WechatOfficialAccountPublisher):
        self.client = client

    def process_article_images(self, html_content: str) -> Tuple[str, Dict[str, dict]]:
        """
        处理文章中的图片（全部上传，无论本地还是远程）
        :param html_content: HTML内容
        :param image_folder: 图片所在目录（已废弃，不再使用）
        :return: (处理后的HTML, 图片信息映射)
        """
        image_info = {}

        # 提取所有图片路径
        image_paths = MarkdownProcessor.extract_images(html_content)

        for img_path in image_paths:
            try:
                # 直接上传，无论本地还是远程
                result = self.client.upload_permanent_image(img_path, image_type='content')
                image_info[img_path] = result
            except Exception as e:
                logger.error(f"图片上传失败: {img_path}, 错误: {str(e)}")
                # 上传失败时保留原路径
                image_info[img_path] = {'url': img_path, 'is_remote': img_path.startswith(('http://', 'https://'))}

        # 创建图片路径映射
        image_map = {old: info['url'] for old, info in image_info.items()}

        # 替换HTML中的图片路径
        updated_html = MarkdownProcessor.replace_image_sources(html_content, image_map)

        return updated_html, image_info

    def extract_and_remove_images(self, html_content: str) -> Tuple[str, list]:
        """
        提取html_content中的所有图片，删除图片标签，返回处理后的html和图片列表
        :param html_content: HTML内容
        :return: (去除图片后的HTML, 图片src列表)
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        img_list = []
        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                img_list.append(src)
            img.decompose()  # 删除图片标签
        html = self.wechat_content_cleaner(str(soup))
        return html, img_list

    def wechat_content_cleaner(self,html_content):
        """
        处理微信公众号HTML内容使其合规
        功能：
        1. 移除外链的http/https前缀
        2. 移除非必要的<br/>和空段落
        3. 移除可能违规的样式标签
        """
        # 使用BeautifulSoup解析HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        # 去掉所有的a标签
        for a_tag in soup.find_all('a'):
            a_tag.decompose()
        # 1. 处理外链 - 移除外链协议头
        for a_tag in soup.find_all('a', href=True):
            original_url = a_tag['href']
            # 移除非微信白名单域名的http/https
            if not any(domain in original_url for domain in ['qq.com', 'weixin.qq.com']):
                cleaned_url = re.sub(r'^https?://', '', original_url)
                a_tag['href'] = cleaned_url
                # a标题也不要http/https
                if a_tag.string:
                    a_tag.string = re.sub(r'^https?://', '', a_tag.string)

        # 2. 清理不必要的换行和空段落
        for br in soup.find_all('br'):
            br.decompose()

        for p in soup.find_all('p'):
            if not p.get_text(strip=True):  # 如果是空段落
                p.decompose()

        # 3. 移除可能违规的样式标签（保留内容）
        for tag in soup.find_all(['strong', 'b', 'em', 'i', 'u']):
            tag.unwrap()  # 移除标签但保留内容

        # 返回处理后的HTML字符串
        return str(soup)

    def publish_markdown_article(
            self,
            md_content: str,
            title: str,
            author: str,
            content_source_url: str,
            cover_image_path: str,
    ) -> str:
        """
        发布Markdown格式的文章
        :param md_content: Markdown内容
        :param title: 文章标题
        :param author: 作者
        :param digest: 摘要
        :param content_source_url: 原文链接
        :param cover_image_path: 封面图路径（本地或URL）
        :param image_folder: 内容图片所在目录（用于本地图片）
        :param article_type: 文章类型 (news 或 newspic)
        :return: 发布ID
        """
        try:
            # 1. 转换Markdown为HTML
            logger.info("转换Markdown为HTML...")
            html_content = MarkdownProcessor.convert_to_html(md_content)

            # 2. 处理内容图片
            logger.info("处理内容图片...")
            processed_content, img_info = self.process_article_images(html_content)
            logger.info(f"处理了 {len(img_info)} 张内容图片")

            # 3. 上传封面图
            logger.info("上传封面图...")
            cover_result = self.client.upload_permanent_image(cover_image_path, image_type='cover')

            # 4. 创建草稿
            logger.info("创建草稿...")
            article_data = {
                "title": title,
                "author": author,
                "content": processed_content,
                "content_source_url": content_source_url,
                "need_open_comment": 1,
                "thumb_media_id": cover_result['media_id'],
            }
            # article_data = {
            #     "title": title,
            #     "author": author,
            #     "content": processed_html,
            #     "content_source_url": content_source_url,
            #     "digest": digest,
            #     "thumb_media_id": cover_result['media_id']
            # }
            # 5. 发布文章
            logger.info("发布文章...")
            return self.publish_article(article_data)

        except Exception as e:
            logger.error(f"文章发布失败: {str(e)}")
            raise

    def publish_image_message(
            self,
            title: str = "",
            md_content: str = ""
    ) -> str:
        """
        发布图片消息 (newspic)
        :param image_path: 图片路径（本地或URL）
        :param title: 图片标题
        :param description: 图片描述
        :return: 发布ID
        """
        try:
            # 1. 上传图片
            image_list = []
            logger.info("转换Markdown为HTML...")
            html_content = MarkdownProcessor.convert_to_html1(md_content)
            logger.info("提取图片...")
            html_content1, image_paths = self.extract_and_remove_images(html_content)
            logger.info("上传图片...")
            for image_path in image_paths:
                image_result = self.client.upload_permanent_image(image_path, image_type='newspic')
                image_list.append({
                    "image_media_id" : image_result['media_id']
                })

            # 2. 构建图片消息
            logger.info("构建图片消息...")
            article_data = {
                "article_type": "newspic",  # 指定为图片消息
                "title": title,
                "author": "小胡哥",
                "content": f"{html_content1}",
                "need_open_comment": 1,
                "image_info": {
                    "image_list": image_list
                }
            }

            # 3. 发布图片消息
            logger.info("发布图片消息...")
            return self.publish_article(article_data)

        except Exception as e:
            logger.error(f"图片消息发布失败: {str(e)}")
            raise

    def publish_article(self, article_data: dict) -> str:
        """
        发布单篇文章
        :param article_data: 文章数据
        :return: 发布ID
        """
        token = self.client._get_access_token()
        endpoint = f"draft/add?access_token={token}"

        payload = {"articles": [article_data]}
        headers = {'Content-Type': 'application/json'}

        logger.info("创建草稿...")
        data = self.client._request_with_retry(
            'POST', endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers=headers
        )

        if not data or 'media_id' not in data:
            raise Exception(f"创建草稿失败: {data}")

        draft_id = data['media_id']
        logger.info(f"草稿创建成功, media_id: {draft_id}")

        # 发布草稿
        return self.publish_draft(draft_id)

    def publish_draft(self, media_id: str) -> str:
        """
        发布草稿
        :param media_id: 草稿的media_id
        :return: 发布任务ID
        """
        token = self.client._get_access_token()
        endpoint = f"freepublish/submit?access_token={token}"

        payload = {"media_id": media_id}
        headers = {'Content-Type': 'application/json'}

        logger.info(f"发布草稿: {media_id}")
        data = self.client._request_with_retry('POST', endpoint, json=payload, headers=headers)

        if not data or 'publish_id' not in data:
            raise Exception(f"发布失败: {data}")

        publish_id = data['publish_id']
        logger.info(f"发布成功, publish_id: {publish_id}")
        return publish_id


# 使用示例1
if __name__ == "__main__":
    # 1. 初始化API客户端
    api_client = WechatOfficialAccountPublisher(
        app_id=config.gzh_app_id,
        app_secret=config.gzh_app_secret
    )

    # 2. 初始化文章发布器
    publisher = WechatArticlePublisher(api_client)

    # 示例1: 发布Markdown格式的图文文章
    markdown_content = """
# 这是文章标题

![封面图](cover.jpg)

这是一段**加粗**的正文内容...

- 列表项1
- 列表项2

![内容图片1](https://hqx.oss-cn-beijing.aliyuncs.com/1751442517910.png?x-oss-process=style/jixn)

更多内容...

[查看原文](https://hqx.oss-cn-beijing.aliyuncs.com/1751442524879.png?x-oss-process=style/jixn)
```
print("Hello, World!")
```
    """
#     markdown_content = """
# # 微信公众号Markdown发布测试
#
# 这是一个使用Markdown格式发布的文章示例，支持**粗体**、*斜体*等格式。
#
# ## 图片示例
#
# ### 本地图片
# ![本地图片](C:\\Users\\huqx2\\Downloads\\Image.png)
#
# ### 网络图片
# ![网络图片](https://hqx.oss-cn-beijing.aliyuncs.com/1750840964021.jpg?x-oss-process=style/jixn)
#
# ## 表格示例
#
# | 功能 | 支持情况 |
# |------|----------|
# | Markdown | ✓ |
# | 本地图片 | ✓ |
# | 网络图片 | ✓ |
# | 表格 | ✓ |
#             """

    try:
        publish_id = publisher.publish_markdown_article(
            md_content=markdown_content, # Markdown内容   最前面一定不能有空格
            title="测试文章标题",
            author="作者名称",
            digest="文章摘要文本",
            content_source_url="https://hqx.oss-cn-beijing.aliyuncs.com/1751442517910.png?x-oss-process=style/jixn",
            cover_image_path="https://hqx.oss-cn-beijing.aliyuncs.com/1751442517910.png?x-oss-process=style/jixn",  # 可以是本地路径或URL
            image_folder=".",  # 图片所在目录
            # article_type="news"  # 图文消息
        )
        print(f"图文文章发布成功! 发布ID: {publish_id}")
    except Exception as e:
        print(f"图文文章发布失败: {str(e)}")

    # 示例2: 发布图片消息 (newspic)
    # try:
    #     image_paths = [
    #         r"C:\Users\huqx2\AppData\Local\Temp\jixn_OSboStW2-W.jpg",
    #         r"https://hqx.oss-cn-beijing.aliyuncs.com/1751442524879.png?x-oss-process=style/jixn",
    #         r"https://hqx.oss-cn-beijing.aliyuncs.com/1751442517910.png?x-oss-process=style/jixn",
    #         r"https://hqx.oss-cn-beijing.aliyuncs.com/1750840964021.jpg?x-oss-process=style/jixn"]
    #     publish_id = publisher.publish_image_message(
    #         image_paths=image_paths,  # 可以是本地路径或URL
    #         title="精美图片",
    #         content=markdown_content
    #     )
    #     print(f"图片消息发布成功! 发布ID: {publish_id}")
    # except Exception as e:
    #     print(f"图片消息发布失败: {str(e)}")