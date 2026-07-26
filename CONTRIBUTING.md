# 参与贡献

感谢你愿意改进墨舟内容发布台。提交代码前，请先搜索现有 Issue，较大的功能建议先用 Issue 说明使用场景、预期行为和可能影响的平台。

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

cd frontend
npm ci
npm run build
cd ..
```

## 提交要求

- 保持改动聚焦，不要在功能提交中混入无关重构或格式化。
- 新增或修改后端行为时补充 `test_backend.py` 测试。
- 修改前端后至少执行一次生产构建；交互改动应在桌面和移动宽度下检查。
- 平台自动化必须等待明确的页面状态，不要用固定短延时冒充成功检测。
- 不要绕过验证码、扫码确认、内容审核或频率限制。
- 不要提交 `data/`、浏览器资料、截图、日志、Cookie、Token、API Key 或账号信息。
- 用户可见文字优先使用中文，代码标识和错误边界保持现有风格。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_backend.py test_notion_utool.py
cd frontend
npm run build
cd ..
git diff --check
```

涉及真实平台的改动还应使用专门的测试账号手动验证。请在 Pull Request 中说明测试平台、草稿或直发动作，以及没有覆盖的风险；不要附带包含个人账号资料的截图。

## Pull Request

标题应简洁描述结果，例如 `fix: 等待 CSDN 图片上传完成`。正文请说明：

- 问题和用户影响
- 解决方式与关键取舍
- 自动化测试和手动验证结果
- 平台页面变化、兼容性或安全风险

提交贡献即表示你同意按项目的 Apache License 2.0 许可你的改动。
