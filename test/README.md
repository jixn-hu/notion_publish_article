# 测试目录

本目录集中存放项目测试脚本：

- `test_backend.py`：后端 API、服务和发布流程单元测试。
- `test_notion_utool.py`：Notion 兼容工具测试。
- `test_e2e.py`：需要先启动应用的浏览器端到端测试。

在项目根目录运行单元测试：

```powershell
.\.venv\Scripts\python.exe -m unittest -v test.test_backend test.test_notion_utool
```

启动应用后运行端到端测试：

```powershell
.\.venv\Scripts\python.exe -m test.test_e2e
```