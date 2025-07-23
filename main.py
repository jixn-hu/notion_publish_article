from pprint import pprint

from publish_gzh import *
from notion_utool import database_get_fb_info, database_update_fb_info,page_get_info
"""
1. 获取notion中需要发送的图文或者文章 
2. 把文章内容转换成markdown格式 
3. 判断文章类型，如果是图文消息，则调用publish_markdown_article方法，如果是图片消息，则调用publish_image_message方法 
4. 确定发布后，更新noton中的文章状态为已发布 
"""

def run():
    try:
        fb_infos = database_get_fb_info()  # 获取数据库中公众号信息
    except Exception as e:
        print(e)
        return
    pprint(fb_infos)
    # 1. 初始化API客户端
    api_client = WechatOfficialAccountPublisher(
        app_id=config.gzh_app_id,
        app_secret=config.gzh_app_secret
    )
    # # 2. 初始化文章发布器
    publisher = WechatArticlePublisher(api_client)
    if not fb_infos:
        print("没有需要发布的文章!!!")
    for fb_info in fb_infos:
        notion_url = fb_info['notion_url']
        page_id = fb_info['page_id'].replace('-', '')
        markdown_content = page_get_info(page_id)
        if fb_info['文章类型'] == '图片' or fb_info['文章类型'] == 'all':
            time.sleep(60 * 60)
            # 3. 发布文章
            try:
                publish_id = publisher.publish_image_message(
                    title=fb_info['标题'],
                    md_content=markdown_content
                )
                print(f"图片消息发布成功! 发布ID: {publish_id}")

            except Exception as e:
                print(f"图片消息发布失败: {str(e)}")

        if fb_info['文章类型'] == '图文' or fb_info['文章类型'] == 'all':
            time.sleep(60 * 60)
            try:
                publish_id = publisher.publish_markdown_article(
                    md_content=markdown_content,  # Markdown内容   最前面一定不能有空格
                    title=fb_info['标题'],
                    author=fb_info['作者'],
                    content_source_url=fb_info['阅读原文'],
                    cover_image_path=fb_info['封面图片'],
                )
                print(f"图文文章发布成功! 发布ID: {publish_id}")

            except Exception as e:
                print(f"图文文章发布失败: {str(e)}")
        # 4. 更新notion中文章状态为已发布
        data = database_update_fb_info(page_id)
        # pprint(data)


if __name__ == '__main__':
    while True:
        run()
        time.sleep(60*5)

