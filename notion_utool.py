from pprint import pprint
from notion2md.exporter.block import StringExporter
import requests
import  config
token = config.notion_token
def database_get_fb_info():

    databases_id = config.databases_id
    cookies = {
        '__cf_bm': 'kFiekh6V1KROUrLT_ih3w7ZJ6SyToQfWf5QM1.EyMd4-1751512522-1.0.1.1-1KXAhIIHAtZkNtnYibqid5eJN_VdYym5X_rdKqNTC0nVfzv_OYoMfbIot7NOD9RJlFAH3wT6YvvLxLXe734vnBUVJozbK.hRikj53_6IROo',
        '_cfuvid': 'mPmdMMGsVrIDkdPwcG5m8HvNggYg7WcSDnTqTAQcdDg-1751512522220-0.0.1.1-604800000',
    }

    headers = {
        'Accept': '*/*',
        # 'Accept-Encoding': 'gzip, deflate, br',
        'Authorization': f'Bearer {token}',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        # 'Content-Length': '146',
        'Content-Type': 'application/json',
        # 'Cookie': '__cf_bm=kFiekh6V1KROUrLT_ih3w7ZJ6SyToQfWf5QM1.EyMd4-1751512522-1.0.1.1-1KXAhIIHAtZkNtnYibqid5eJN_VdYym5X_rdKqNTC0nVfzv_OYoMfbIot7NOD9RJlFAH3wT6YvvLxLXe734vnBUVJozbK.hRikj53_6IROo;_cfuvid=mPmdMMGsVrIDkdPwcG5m8HvNggYg7WcSDnTqTAQcdDg-1751512522220-0.0.1.1-604800000',
        'Host': 'api.notion.com',
        'Notion-Version': '2022-06-28',
        'User-Agent': 'PostmanRuntime-ApipostRuntime/1.1.0',
    }

    json_data = {
        'filter': {
            'property': '状态',
            'status': {
                'equals': '待发布',
            },
        },
    }
    proxy = {
        'http': 'http://127.0.0.1:7890',
        'https': 'http://127.0.0.1:7890',
    }
    response = requests.post(
        f'https://api.notion.com/v1/databases/{databases_id}/query',
        cookies=cookies,
        headers=headers,
        json=json_data,proxies=proxy
    )
    response.raise_for_status()
    data = response.json()
    if 'results' not in data:
        return []
    results = data['results']
    fb_infos = []
    for result in results:
        fb_info = {}
        properties = result['properties']
        fb_info['标题'] = properties['标题']['title'][0]['plain_text']
        fb_info['封面图片'] = properties['封面图片']['url']
        fb_info['作者'] = properties['作者']['select']['name']
        fb_info['文章类型'] = properties['文章类型']['select']['name']
        fb_info['阅读原文'] = properties['阅读原文']['url'] if properties['阅读原文']['url'] else r'https://aiutools.fun/jixn/'
        fb_info['notion_url'] = result['url']
        fb_info['page_id'] = result['id']
        bqs = properties['标签']['multi_select']
        fb_info['标签'] = [bq['name'] for bq in bqs]
        fb_infos.append(fb_info)
    return fb_infos

def database_update_fb_info(page_id):
    for _ in range(3):
        try:
            headers = {
                'Accept': '*/*',
                # 'Accept-Encoding': 'gzip, deflate, br',
                'Authorization': f'Bearer {token}',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                # 'Content-Length': '109',
                'Content-Type': 'application/json',
                # 'Cookie': '_cfuvid=VZ7TQrkewf_Vvc04zj4pUbHm8EfNTppHQHATZPfw1So-1751519628963-0.0.1.1-604800000',
                'Host': 'api.notion.com',
                'Notion-Version': '2022-06-28',
                'User-Agent': 'PostmanRuntime-ApipostRuntime/1.1.0',
            }

            json_data = {
                'properties': {
                    '状态': {
                        'status': {
                            'name': '已发布',
                        }
                    },
                        "已发布平台": {
                            "type": "multi_select",
                            "multi_select": [
                                {
                                    "id": "tXRt",
                                    "name": "微信公众号",
                                    "color": "green"
                                }
                            ]
                        }
                },
            }
            proxy = {
                'http': 'http://127.0.0.1:7890',
                'https': 'http://127.0.0.1:7890',
            }
            response = requests.patch(
                f'https://api.notion.com/v1/pages/{page_id}',
                headers=headers,
                json=json_data,proxies=proxy
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"更新文章状态失败: {str(e)}")
        else:
            return data

def page_get_info(page_id):
    """
    获取文章具体内容
    """

    markdown_content = StringExporter(block_id=page_id, token=token).export()

    print("获取的 Markdown 内容:")
    print(markdown_content)
    return markdown_content



if __name__ == '__main__':
    fb_infos = database_get_fb_info()
    pprint(fb_infos)
    for fb_info in fb_infos:
        notion_url = fb_info['notion_url']
        data = database_update_fb_info(notion_url)
        pprint(data)
