from notion2md.exporter.block import MarkdownExporter

# 你的页面 ID（带或不带连字符均可）
page_id = "1f5a1feec2928060b52fe0bdc542b427"

# 导出到指定目录
exporter = MarkdownExporter(block_id=page_id, output_path="./md_output",token='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')
exporter.export()
print("导出完成：./md_output")
