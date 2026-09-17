# 贡献指南（Contributing）

欢迎对本项目提出 Issue、改进建议或代码贡献！无论你是来**学习借鉴**还是**贡献代码**，这份指南帮你快速上手。

## 想学习/借鉴？先看这些

| 目的 | 看什么 |
|------|--------|
| 快速了解功能 | `README.md`（特性表 + 截图） |
| 理解整体架构 | `README.md` → 「📁 项目结构」章节（模块地图） |
| 搞懂 Live2D 接入 | `docs/live2d_pipeline.md`（从生成立绘到 Cubism 绑定的完整流程） |
| 深入源码 | `desktop_pet.py`（单文件架构，按章节注释搜索，如 `# ============ AI 状态预判`） |
| 跑起来 | `pip install -r requirements.txt` 后运行 `python desktop_pet.py` |

## 想贡献代码？

### 环境准备
```bash
pip install -r requirements.txt
pip install pytest ruff   # 开发依赖
```

### 开发规范
1. **单文件架构**：本项目刻意保持 `desktop_pet.py` 单文件，新增功能请沿用现有代码风格（函数 + 章节注释）
2. **中英双语**：新增 UI 文案必须同时加入中英文字典（`_TEXT_ZH` / `_TEXT_EN`），通过 `self._t()` 取用
3. **配置持久化**：新增可配置项写入 `config.json`（参考 `config.example.json`）
4. **提交前自检**：`python -m py_compile desktop_pet.py` + `python -m pytest tests/`

### 提交流程
1. Fork 本仓库
2. 新建分支：`git checkout -b feature/你的功能`
3. 提交并推送，然后发起 Pull Request
4. 描述中说明：改了什么、为什么改、如何验证

## 🌱 新手任务（Good First Issues）

第一次参与开源、不知道从哪下手？看 **[docs/good-first-issues.md](docs/good-first-issues.md)** ——
里面是 5 条已拆好的任务，每条都标了**难度**、**涉及文件**和**验收标准**（改文案、小游戏记住设置、补测试、
扩写文档、打包自检）。满足验收标准就能提 PR，不需要先读懂整个项目。

## 报告 Bug

请用 Issue 模板提交，包含：
- 复现步骤
- 期望行为 vs 实际行为
- 环境信息（Windows 版本、Python 版本）
- 日志或截图（如有）

## 行为准则

参与本项目即表示你同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 相关文档

| 文档 | 用途 |
|------|------|
| [SECURITY.md](SECURITY.md) | 安全模型与漏洞报告流程（勿公开提 Issue） |
| [docs/good-first-issues.md](docs/good-first-issues.md) | 新手任务候选（含验收标准） |
| [CHANGELOG.md](CHANGELOG.md) | 发布版本变更记录 |
| [docs/live2d_pipeline.md](docs/live2d_pipeline.md) | Live2D 接入全流程 |
