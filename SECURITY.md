# 安全策略（Security）

## 支持的版本

| 版本 | 支持状态 |
|------|---------|
| 1.0.0（master） | ✅ 支持 |

## 报告漏洞

发现安全漏洞请**不要**公开提交 Issue，请通过以下方式私下报告：

- **GitHub Security Advisory**：仓库 → Security → Report a vulnerability
- 或邮件联系维护者（见仓库 About 页面）

## 报告内容

请包含：
1. 漏洞类型与影响范围
2. 复现步骤（尽量精简）
3. 受影响的版本
4. 可能的修复建议（可选）

## 已知注意事项

- 本项目为本地运行的开源工具，**API Key 仅存储在你本机的 `config.json`**，请勿分享该文件
- 对话与记忆数据均保存在本地（`memory.json` / `chat_memory_*.json`），公开分享时注意清理隐私内容
- 本项目与 DeepSeek（深度求索）公司无任何关联，仅使用其公开 API
