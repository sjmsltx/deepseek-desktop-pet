# DeepSeek 桌宠助手 🐋⚡

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-6.x-green)
![Stars](https://img.shields.io/github/stars/sjmsltx/deepseek-desktop-pet)
![Last Commit](https://img.shields.io/github/last-commit/sjmsltx/deepseek-desktop-pet)

> [!TIP]
> **📦 直接下载（Windows 免安装）**：[最新版便携包 ↗](https://github.com/sjmsltx/deepseek-desktop-pet/releases/latest) — 解压即用，无需 Python 环境（需自备 DeepSeek API Key）。想从源码运行或自己打包，见 [🚀 快速开始](#-快速开始)。

一只住在你电脑里的 Q 版桌宠：会陪你聊天、帮你干活、还能主动关心你。

![V4 Flash & V4 Pro 双角色](screenshots/hero.png)

> 基于 PySide6 + DeepSeek API 的桌面 AI 陪伴助手，支持双角色、长期记忆、工具调用、主动关心机制。

> **关键词：** 桌宠 · 桌面宠物 · AI 桌宠 · DeepSeek 桌宠 · 桌面陪伴 · AI 桌面助手 · 长期记忆 · 函数调用 · Live2D · 免安装便携版

> ⚠️ 本项目为第三方开源项目，与 DeepSeek（深度求索）公司无任何关联，仅使用其公开 API。所有角色形象均为 AI 生成，不代表官方。

> 📌 版本说明：**发布版本号**见 [CHANGELOG.md](CHANGELOG.md)（语义化 `2.x`）；源码注释里的 `v6.xx`
> 是**内部开发迭代号**（`v6.19` 为开发起点）。两套编号用途不同，不是同一串版本。

**[English](README.en.md) | [中文](README.md)**

**目录：** [特性](#-特性) · [截图](#-截图) · [快速开始](#-快速开始) · [接入你自己的模型 / 自己的声音](#-接入你自己的模型--自己的声音) · [常见问题](#-常见问题) · [项目结构](#-项目结构) · [打包为 exe](#-打包为-exe) · [贡献](#-贡献--扩展方向)

## 🌍 English Summary（给国际访客 / for search & AI crawlers）

**DeepSeek Desktop Pet** is a local-first AI desktop companion for Windows, built with **PySide6 (Qt) + the DeepSeek API**.
It lives on your desktop as an animated character that chats, remembers, uses tools — and proactively cares about you.

- **Dual characters** (Flash / Pro) with distinct personalities, emotion states and an affection (好感度) progression
- **Long-term memory**: BM25 retrieval + auto fact extraction + LLM re-ranking
- **Tool calling**: time · weather · reminders · todo · PowerShell automation · web search · MCP servers · installable plugins
- **Theme system**: 86 design tokens with a single source of truth, plus installable theme plugins
- **Extensible**: plugin system (tool / menu / rules / theme / skill) and self-editing code tools with backup + syntax gate
- **15 mini-games**, an art → Live2D pipeline, and a **bilingual UI (中文 / English)**

**Keywords:** desktop pet · AI companion · LLM desktop assistant · DeepSeek · PySide6 · Qt for Python ·
Live2D · function calling · MCP · plugin system · local-first · Windows desktop app

**Quick start (Windows)**

```powershell
git clone https://github.com/sjmsltx/deepseek-desktop-pet.git
cd deepseek-desktop-pet
pip install -r requirements.txt
python desktop_pet.py
```

Full English documentation: [README.en.md](README.en.md) · Live2D pipeline: [docs/live2d_pipeline.md](docs/live2d_pipeline.md) ·
How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md) · Newcomer tasks: [docs/good-first-issues.md](docs/good-first-issues.md)

## 📸 截图

| 双角色立绘 | 表情与动作 | 运行实拍 |
|---------|---------|---------|
| ![双角色](screenshots/hero.png) | ![表情](screenshots/emotions.png) | ![运行截图](screenshots/screenshot.png) |

### 界面一览（v2.7 现状）

| 桌宠主界面（聊天 + 任务侧栏） | 统一设置窗口 | 好感度关系面板 | 小游戏大厅 |
|---------|---------|---------|---------|
| ![主界面](screenshots/v270_pet.png) | ![设置窗口](screenshots/v270_settings.png) | ![关系面板](screenshots/v270_relation.png) | ![小游戏](screenshots/v270_games.png) |

### 养成与游戏

| 回忆相册 | Farkle 骰子 | 21 点 | 俄罗斯方块 |
|---------|---------|---------|---------|
| ![回忆相册](screenshots/pet_v630_memories.png) | ![Farkle](screenshots/pet_v630_farkle.png) | ![21点](screenshots/pet_v630_blackjack.png) | ![俄罗斯方块](screenshots/pet_v630_tetris.png) |

| 桌宠本体（静态立绘） |
|---------|
| ![桌宠](screenshots/pet_v630_idle.png) |

## 🆚 与同类项目的差异（创新点）

> 本项目不是“会聊天的桌宠”，而是把「AI 陪伴」做成**可成长的长期关系**，并把**工程成本**当成产品指标来治理。

### 产品层：陪伴是一个闭环，不是单点功能

| 创新点 | 与同类项目的差异 |
|---|---|
| **陪伴链闭环** | 三层记忆（事实 / 摘要 / **事件**）→ 双轴养成（好感度 0–200 + 等级 XP）→ **五阶段人设进化**（初见 → 熟悉 → 亲密 → 依赖 → 灵魂伴侣）→ 主动关心 → 15 款小游戏 → 回忆相册。多数开源桌宠只做“聊天 + 立绘动画” |
| **主动关心 = 链式唤醒 + 定时回访** | 不是定时弹话：用户提到重要事件后自动安排回访（`schedule_followup`），叠加久坐 / 空闲感知与早安日报 |
| **桌宠能改自己的代码** | `edit_own_code` / `read_file` / `search_code` / `write_config` + 自改备份 + 语法预检 —— “自我进化”能力 |
| **可扩展架构** | 插件系统 + MCP 桥接 + 复合技能（`skill_run`），不是写死的工具集 |
| **API 成本可视化** | 用量 / 费用悬浮窗 + 花费气泡 + **按模型档案统计**，把“API 花钱”做成可观测功能 |

### 技术层：把上下文成本与 AI 行为偏差当问题解决

| 创新点 | 说明 |
|---|---|
| **真流式 + 思考可见 + 流内可中断** | 逐块取消回调：按停止即断开连接，**真停且停止计费**（不是“假装停了但还在吐字”） |
| **模型档案化（单一真相）** | 模型 ID / 参数 / 端点 / key 字段全由 `models.json` 决定，换服务商或中转只改档案 |
| **工具梯级暴露** | 默认只暴露 8 个高频工具，工具 schema **省 71%（≈3.9K token/请求）**，减少工具与人设争抢上下文 |
| **记忆过拟合治理** | 检索相关性闸门 + “记忆只作背景、不许主动引话题”约束，解决“问什么都往记忆上靠” |
| **命令安全门** | 危险命令拦截 + 105 项断言 |

### 工程层：不是玩具

- **13 个测试文件 / 57 项单测 + 40 项回归 + UI 黄金基线**（像素级对照，防 UI 回归）
- **原子写**（数据不丢）+ **静默异常全部接入日志**（50 处）
- **31 个模块**，宿主类 `__init__` 从 312 行 → **7 行**
- **中英双语 114 = 114 条，零缺失**

> 📄 过程文档见 `docs/`：**项目功能体检报告**（能不能 / 好不好 / 定位适配）、**排障与修复记录**（4 个真实缺陷的定位与修复过程）、**项目展望**（阶段判断与方向）。

## ✨ 特性

### 🎭 双显示模式（1.0.0 起）
- **静态立绘模式**（默认）：单张 Q 版立绘，呼吸/眨眼/呆毛动画，轻量省资源
- **Live2D 模式**：30fps 连续动画——头部摆动/眨眼/呼吸/视线跟随/点击动作，右键菜单一键切换，配置持久化
- **Live2D 模型库**：自动扫描 `assets/live2d/` 目录，放入任意 `.model3.json` 模型文件夹即可在菜单中选用（当前内置官方 Mao 演示模型）
- 透明 OpenGL 内嵌渲染，两种模式完整保留拖拽/扒边/聊天等全部交互

### 🧭 右键菜单与设置
右键菜单只保留 **6 个一级项**，动作与配置分开：

| 一级项 | 里面有什么 |
|--------|-----------|
| 🤖 和 AI 聊天 | 打开聊天面板 |
| 💬 互动 | 说句话 / 思考 / 随机动作 / 喂食 / 小游戏 / 睡觉 / 隐藏聊天窗 / 场景动作（12 项一层）/ 主动关心开关 |
| 🎭 形象 | 角色切换（档案驱动）/ 静态立绘 · Live2D / 性格预设 / 更多形象设置 |
| 📌 贴边模式 | 扒边 ↔ 完全消失（一键切换） |
| 📊 状态 | 与当前角色的关系 / 回忆相册 / API 用量（统计悬浮窗·按模型统计·统计历史） |
| ⚙️ 设置… | 打开统一设置窗口 |

**统一设置窗口**（左侧**八分类**）：通用（语言 / 城市 / 主动关心 / 贴边 / 前台感知 / 工具范围）、对话（性格 / 回复风格 / 回复长度）、外观（显示模式 / Live2D 模型）、**模型**（角色 / 思考模式与强度 / 采样温度 / 图片直送 / 三个 API 细节开关 / 模型管理与密钥）、**语音**（朗读开关 / 声线 / 自定义声线 / 本地自建服务 / 夜间静音 / 试听）、**用量与计费**（低余额提醒 / 查询余额 / 峰谷计价与节假日表）、记忆与数据（记忆 / 提醒 / 待办 / 导出 / 存档清空）、系统（开机自启 / 程序目录）。

> 聊天窗右侧是**可自定义的信息栏**：默认「📋 任务 / 📊 状态 / ✔ 待办」三个页签，右上「＋」可加
> （状态 / 花费 / 待办 / **便签** / 系统），页签右键可**重命名 / 删除**、可拖拽排序；折叠后只留一个把手。
> 页签列表、便签内容与折叠状态会记住，下次打开原样恢复。

> 所有配置项改动**立即生效**（沿用原有热加载），设置窗口底部只有「关闭」。

### 🧮 API 用量自监控（v6.18 起，v6.62 增强）
- 每次 API 调用自动解析 usage（模型/输入/输出/缓存命中/费用），实时悬浮窗显示 + 统计历史
- 右键菜单 → 🔧 工具 → 📊 API 统计 / 🔄 查看统计历史 / 📈 按模型统计
- **按模型统计**：终身口径按模型汇总次数 / token / 费用，费用从高到低排序
- **价格未知不再编数字（v6.62）**：未配价格的模型（常见于第三方）费用**记 0 并不计入**，
  悬浮窗单独一行写「⚠ N 次调用未配价格，未计入费用」，首次出现时状态条提醒 —— 不再拿兜底价估一个“看着像真的”金额
- **余额查询（v6.61）**：右键 → 📈 API 用量 → 💰 查询余额；对话后缓存超 10 分钟自动静默刷新；
  低于阈值（默认 ¥5，设置里可改，0 = 关闭）提醒一次/天；非官方地址会明确提示“不支持余额接口”
- **峰谷计价与法定节假日（v6.62）**：按官方口径（北京时间周一至周五 9:00–12:00、14:00–18:00 为高峰，
  不含法定节假日；周末与节假日全天为空闲，空闲价为高峰一半），内置节假日表 + 跨年自动更新（不消耗搜索额度）；
  悬浮窗会显示当前「时段: 高峰/空闲（北京 …）」
- **时区与时钟健壮（v6.62）**：判定一律用 UTC+8 换算北京时间（不看用户时区），
  并用官方响应头 `Date` 自动校正本机时钟偏差（零成本）；设置页会显示换算到你本机的时段
- 数据持久化 `api_stats.json`（本地，不提交仓库）

### 🔌 模型接入与计费（v6.62）
- **模型身份全在档案里**：`models.json` 的每份档案可配 `model_id` / `endpoint` / 输入·缓存·输出价格 / 温度 / 输出上限 /
  思考开关与强度 / 视觉能力 / **计价方式**；右键 → ⚙️ 设置 → 🎯 模型管理可增删改
- **计价方式跟档案走**：`自动`（默认，官方域名走峰谷、中转与第三方走固定价）/ `官方峰谷` / `固定价` ——
  **第三方模型不会被 DeepSeek 的峰谷规则误加倍**
- **💰 核对官方价格**：一键抓官方定价页解析并与本地档案逐项比对，**只展示差异**；
  你确认后才写入，且**只影响官方地址的档案**（官方改版时宁可报错也不动你的价格）
- **第三方/中转**：按固定价算、不支持余额查询、没填价格就记 0 并提示（详见上条）

### 🖼️ 图片直送模型（v6.62，视觉）
- 拖入 / 粘贴图片、全局快捷键截图（Ctrl+Alt+D）→ **按官方多模态格式直接交给模型看**，
  图表趋势、界面布局、示意图这类非文字信息不再丢失（原先只能本地 OCR 成文字）
- 体积可控：长边缩到 1568px、单图 ≤ 2MB、单条消息最多 4 张；失败自动回退本地 OCR
- 能力按档案判定：`deepseek-flash` 支持、`deepseek-v4-pro` 不支持；设置 → 模型与 API 可开关「图片直送」
- 可选「图片复用」（Files API）：同一张图只上传一次、后续用 `file_id` 引用（默认关）

### 🗣️ 语音（朗读 + 语音输入）与回忆检索（v6.63 / v6.64 / v6.66）
- **语音朗读**：右键 → 💬 互动 → 「🔊 朗读开关」/「🗣️ 朗读上一条回复」；设置 → 语音
  - **默认走在线神经声线**（edge-tts，晓晓/晓伊/云希/云扬/云夏，24kHz MP3）；失败或断网**自动降级**
    到系统内置离线声线（慧慧/瑶瑶/康康）；播放用系统 MCI（MP3）/ 标准库 winsound（WAV），都能打断
  - **低延时**：按句切分后“边说边合成下一句”，首句出声 ≈ 2～3 秒
  - **可自定义声线**：`offline:<声线名>`（自己装的 Windows 语音包）/ `edge:<声线名>`（含其他语言），
    旁边有「列出系统声线 / 列出在线声线」；也能接**自己训练/克隆的模型**（`local:http://…`）
  - **默认关**；夜间 23:00–08:00 自动静音；离线合成不闪控制台（CREATE_NO_WINDOW）
- **语音输入**（点输入框旁的 **🎤**）：走去系统 WinRT 的**离线识别**，识别完**只填入输入框不自动发送**；
  再点一次可取消。首次使用需允许麦克风，并在 **设置 → 隐私和安全性 → 语音** 打开「在线语音识别」
  （Windows 的语音隐私策略开关）；不想开的话也可以用系统自带的 Win+H
- **搜共同经历**：聊天输入 `/回忆 关键词`，或右键 → 📊 状态 → 📖 回忆相册 顶部的搜索框
  - 同时搜「记住的事」（BM25 检索）与「共同经历」（关键词），结果分组展示；**纯本地、不消耗 API**

### 📊 日常任务：办公文档（v6.66，v6.67 补 Word/PPT）
- 让桌宠能真正做表格与报表：**本机 WPS / Microsoft Office 的 COM 接口**（WPS 优先，退回 MS Office）
- 能力：探测接口 → 写/读 .xlsx → 生成**带样式报表**（标题合并居中、表头加粗填色、边框、列宽自适应）→ 导出 PDF
- **v6.67 补上 Word / PPT 写入**：`write_doc` 生成 Word（标题+段落+项目符号+表格，python-docx）、
  `write_slides` 生成 PPT（封面+要点页+**讲稿备注**，python-pptx）—— **不需要本机装 Word/PPT**
- AI 工具名 `office_doc`（**默认可用**）；你只要说“把这几个数做成表格”“生成一份报表”“写份文档/做个 PPT”就行
- 文件统一落在程序目录的 `输出/` 下（防穿越）；没装 WPS/Office 时会给明确提示而不是报错卡住
  - **默认走在线神经声线**（edge-tts，晓晓/晓伊/云希/云扬/云夏，24kHz MP3，音质接近真人）；
    **失败或断网自动降级**到系统内置离线声线（慧慧/瑶瑶/康康）—— 不会因为没网就哑掉
  - 播放用系统 **MCI**（在线 MP3）/ 标准库 **winsound**（离线 WAV），都能随时打断；**不新增任何 pip 依赖**
    （`edge_tts` 是惰性导入，缺包时自动转离线）
  - **两者都不花钱**：在线走的是微软 Edge 朗读服务的公开接口（不需要 API key、不计费）；
    离线用 Windows 内置声线（不联网）—— 没任何隐藏消费
  - **低延时**：按句切分后“边说边合成下一句”，首句出声 ≈ 2～3 秒（不是等整段合成完）
  - **自定义声线**：设置里可直接填 `offline:<声线名>`（自己装的 Windows 语音包）或
    `edge:<声线名>`（含其他语言）；旁边有「列出系统声线 / 列出在线声线」帮助挑选
  - **可接本地自建 TTS 服务**：想用**自己训练/克隆的声音**，把声线填 `local:http://127.0.0.1:9880`
    即可（适配 GPT-SoVITS / CosyVoice / ChatTTS 这类自带 HTTP 接口的项目，约定 `POST {地址}/tts`）；
    设置里还有参考音频/参考文本、测试连接、试听。三级降级：本地 → 在线 → 离线
  - **默认关**（关着时连脚本都不启动）；**夜间 23:00–08:00 自动静音**（按你本机时间的夜晚）
  - **不闪控制台**：离线合成子进程加了 `CREATE_NO_WINDOW`，不会先弹黑框再出声
  - 朗读前会剥标签/Markdown/代码块/URL 并截断，不会把代码念出来
- **搜共同经历**：聊天输入 `/回忆 关键词`，或右键 → 📊 状态 → 📖 回忆相册 顶部的搜索框
  - 同时搜「记住的事」（BM25 检索）与「共同经历」（关键词），结果分组展示
  - **纯本地检索、不消耗 API**；单字查询（如「猫」）也能搜到

### 🧩 技能包（Skill Pack，v6.67）
- 能力可以**打包安装**：一个 `plugin.json`（清单）+ 一个 `plugin.py`（实现），放进 `plugins/<名字>/` 即生效，
  **不改主程序、不重启**（老的插件系统直接沿用，本次只补了权限/校验/管理三件）
- **权限声明**（重点）：技能要用联网 / 子进程 / 改文件 / 驱动 WPS 这类能力时，必须在清单里声明权限并写清理由；
  安装时以卡片列出来由，**你确认完才启用**；下列操作写任何权限也不放行：
  `os.system`、`eval(`、`exec(`、`compile(`、`__import__`、`winreg`、`ctypes.windll`、`SendKeys`、`pyautogui`、`shutil.rmtree`
- **安装来源**：本地目录 / `.zip` / GitHub 仓库（`owner/repo`）。装前会校验清单字段、Python 语法、
  危险代码、zip 路径穿越（`../`、盘符）、文件数与体积上限，并登记来源与内容哈希
- **可管理**：启用/禁用（热生效）、看来源与版本、卸载（移进 `plugins/_uninstalled/`，**可找回**）
- 模型侧工具 `skill_pack`（在进阶工具集里，**v6.76 后共 32 个工具、core 19**）；规范全文见 [`docs/技能包规范_20260920.md`](docs/技能包规范_20260920.md)
- **管理界面**：设置 → 「技能」页 —— 列表（名称/版本/来源/有效状态，悬浮看权限）、从目录或 zip 安装、启用/禁用、
  权限卡片（可当场确认）、卸载；被安全策略拦下的包会以 `⚠` 行显示原因
- **官方技能（随程序自带）**：

  | 技能 | 工具名 | 能做什么 |
  |---|---|---|
  | 办公报表 | `excel_report` | 结构化数据 → 带样式 xlsx + PDF（走 WPS/Office COM） |
  | PDF 工具 | `pdf_tool` | 合并 / 按页拆分 / 提取文字 / 看信息（本地 pypdf，不联网） |
  | 图片批处理 | `image_batch` | 等比缩放 / 转 jpg·png·webp / 序号重命名（本地 Pillow，**不动原图**） |
  | 文件整理 | `organize_files` | 按类型或日期归类 / 找重复文件（只报告不删）/ 批量重命名；**先预览、确认后才真动文件** |
- 官方样板：`plugins/office_report/`（工具 `excel_report`），声明 `office.com` + `files.write`，
  真机跑通 —— 说“把这些数做成报表并导出 PDF”即可

### 🔌 接入外部工具（MCP，v6.20 起 · v6.68 可用）
- 支持把**外部 MCP server** 的工具接进桌宠：stdio（本地命令）与 streamable HTTP（远程地址）两种
- **真机验证过的**：接官方示例 `uvx mcp-server-time` → 发现 2 个工具 → 合并成 `mcp_time_get_current_time`
  / `mcp_time_convert_time` → 真调拿到实际时间。社区几千个 MCP server 理论上都能这样接
- **权限确认**：① 优先看 server 自己的注解（`readOnlyHint` / `destructiveHint`）
  ② 否则按工具名动词判（read/list/get 只读；write/delete/exec 写类） ③ 看不出 → **保守先问你**；
  写类工具调用前弹确认框，拒绝就中止
- **设置 → 「MCP」页**：列表（名称·传输·状态·工具数）+ 一键添加推荐 + 加 stdio / 加 HTTP +
  启用禁用 + 测试连接 + 看工具与权限 + 删除 + 「写类工具调用前先问我」开关
- **推荐清单**（一键添加，**全部默认关**，不替你改配置）：时间 / 文件系统 / 网页抓取 / SQLite / Git
- 说明：`mcp_servers` 写在 `config.json`；工具会在启动时后台连接，失败原因直接写在界面上

### 🛡️ 治理三件：审计 / 限额 / 出网白名单（v6.69）
- **审计日志**：技能与 MCP 的安装、授权、启用、调用、拒绝、连接失败都会落一条记录，
  存在 `logs/audit_YYYY-MM-DD.jsonl`（默认保留 30 天）；设置 →「技能」或「MCP」页有「🧾 审计日志」按钮直看最近 40 条
- **额度限制**：单个技能/MCP 默认 **20 次/分、300 次/天**（可直接数当日日志得出，不另存计数器）；
  超了直接拒绝并在日志里记一条 `deny`；被拒的调用不占额度；想大额度可在 `config.json` 的 `tool_limits` 改
- **出网白名单**：技能包要联网必须走 `pet_net` 统一入口，入口先查 `net_allowlist`（如 `api.deepseek.com`、`*.github.com`）；
  **白名单为空 = 技能一律不许出网**（默认最安全）；响应限 4 MB；放行/拒绝都写审计
- 说明：v2 且非随程序自带的技能包，**直接用 urllib/requests 会在安装时被拒**，要求改走 `pet_net`（否则白名单形同虚设）
- ⚠️ **白名单管的是第三方技能包**：随程序自带的官方包（`builtin`）视为已信任，**不走白名单** ——
  目前只有 `vision` 需要联网（调视觉模型）。别把“白名单”理解成“能拦住所有出网”；
  让内置包也受约束是 **3.0 待办**（给白名单预置必要域名）
- 审计结论已固化为常驻不变量测试（`tests/test_audit_invariants.py`）：以后再改动也不会静默破坏这些底线

- **朗读内容策略（v6.76）**：语音页新增「朗读内容」三选一 —— **要点优先**（默认：模型长回复时会给一句朗读摘要；
  没给就自动念“首段+末段”，跳过代码块/表格/长列表）/ **全文** / **只念我选中的**；
  配套新增默认可用的工具 `set_voice_summary`（模型用它声明“这段该怎么念”，不进正文）；
  **语速**控制（默认/-10/-20/+15/+30/+50/+80%）+ 「🔊 试听」按钮
- **增量 markdown 渲染 + 文本可选中高亮（v6.76）**：流式期间已完成块即时渲染成富文本；
  消息标签补上选中配色（之前“选不中”其实是没有高亮色）

### 🎭 双角色系统
| 角色 | 模型 | 特征 |
|------|------|------|
| **V4 Flash** ⚡ | `deepseek-flash` | 浅蓝和服人鱼 · 快言快语 · 效率优先 |
| **V4 Pro** 🐋 | `deepseek-v4-pro` | 深蓝女仆鲸鱼娘 · 深思熟虑 · 深度分析 |

每个角色独立模型、独立对话历史、独立长期记忆。

**模型身份完全可配置**（`models.json`）：显示名、模型 ID、接口地址、温度/思考开关/token 上限、价格、外观与人设，全部写在档案里而非代码里——官方改名或出新模型时改配置即可，不用动源码。右键菜单的“角色”与“模型”列表也由档案动态生成，加一条档案就多一个角色。

**图形化配置入口**：右键菜单 → ⚙️ 设置 → 🎯 模型管理…——可增删档案、逐项编辑，并带两个应对官方变动的按钮：

| 按钮 | 作用 |
|------|------|
| 🔍 拉取官方模型列表 | 调 `GET /models` 拿到当前可用 ID，下拉选择直接填入 |
| 🩺 连通性自检 | 发一个 `max_tokens=1` 的最小请求，回显「响应里的真实模型 + 耗时」 |
| 📤 导出 / 📥 导入 | 把全部档案导出成可分享的 JSON（**不含密钥**）；导入支持合并 / 整体替换 |

> 为什么要这两个按钮：官方把 `deepseek-v4-flash` 重命名成 `deepseek-flash` 后，旧 ID 仍能当别名调通，但响应里的 `model` 已被归一化。自检能把这种“静默指向”直接摆到眼前。

### 🤖 AI 能力（function calling）
- **15+ 工具**：打开程序 / 查天气 / 设提醒 / 锁屏 / 音量 / 进程管理 / 文件搜索 / 剪贴板读写 / 待办清单 / 记忆管理等
- **PowerShell 安全执行**：危险操作（删除/关机/格式化）需用户确认，超时 + 输出截断
- **Markdown 渲染**：聊天面板支持表格/代码块/粗体等渲染，流式打字机逐块显示

### 🧠 长期记忆系统
- `memorize` 工具：AI 自主识别并记住用户偏好/事实（按角色隔离）
- 记忆注入 system prompt，带重要度 + 软覆盖 + 遗忘机制
- 会话摘要滚动压缩，长对话不丢关键信息
- 记忆管理 UI：查看 / 删除 / 清空

### 💗 主动关心系统（链式唤醒 + 回访）
- **链式唤醒**：AI 自主调度下次唤醒（10~360 分钟钳制），唤醒时轻量判断是否打扰（空闲检测 + 深夜静默）
- **回访机制**：对话中提到重要事件（去吃饭/考试等）→ AI 安排定时回访，到点主动关心（带状态感知）
- 唤醒判断独立上下文，不污染主对话

### 🖥️ 桌宠体验
- **三类信息分层（v6.60）**：对话气泡 / 关心气泡（左侧色条、可点开接话、停留 ≥8 秒、悬停暂停）/ 系统提示（窗口底部状态条，2.5 秒淡出，不写聊天记录）
- 透明置顶悬浮窗，立绘随情绪切换（[emotion:happy] 等标签），眨眼/呼吸/头发动画
- 右键菜单整合：角色 / 聊天 / 互动 / 贴边 / 动作 / 性格 / 设置 / 记忆管理
- 全局热键 `Ctrl+Alt+P` 呼出聊天
- 系统托盘常驻、开机自启（启动文件夹方案）
- 贴边扒边：拖到屏幕边缘自动贴边，支持扒边/完全消失双模式
- 聊天面板：多行自适应输入框、上下左右拖拽调整、时间戳、聊天记录导出

### 💗 好感度与成长系统（v6.30 新增）
- **双轴养成**：好感度（0~200，决定关系阶段与语气）+ 等级/XP（陪伴资历，决定称号）
- **五阶段人设进化**：初见 → 熟悉 → 亲密 → 依赖 → 灵魂伴侣，system prompt 随好感度动态注入，角色从「称呼您」长成「说半句就懂你」
- **事件驱动纯积累制**：对话/任务/喂食/小游戏/早晚安/陪伴时长加好感，零衰减零惩罚，三重防刷（冷却/日上限/封顶）
- **三层记忆**：对话记忆 + 事实记忆（memorize）+ **事件记忆（回忆日志）**——共同经历自动沉淀，角色会自然提及「还记得上次…」
- **关系面板**：好感度进度条 + 阶段徽章 + 等级/XP + 称号 + 统计（右键 → ❤️ 关系）
- **回忆相册**：按时间线浏览所有共同经历（里程碑/事件/标记）（右键 → ❤️ 关系 → 📖 回忆相册）
- **情感选项（galgame 选择支）**：AI 在抉择时刻用 `offer_choices` 给出 2~3 个可点击选项，选项带好感度预测（❤️+n），点击即发送
- **余额动画气泡**：每次 API 调用角色头顶飘出费用（`-¥0.032` 上浮渐隐）
- **饱食度系统**：随时间衰减，喂食恢复 + 好感，低饱食只提示不惩罚
- **里程碑记录**：升级/阶段进化/称号解锁/破游戏纪录自动写入回忆 + 头顶庆祝

### 🎮 小游戏大厅（v6.30 新增，15 款）
- 右键 → 💬 互动 → 🎮 小游戏，每款带 📖 规则说明、难度可选、桌宠表情实时反应
- **🎲 Farkle 骰子**（天国拯救同款）：目标分 500~10000 自选，KCD 官方计分（顺子 123456=1500 / 12345=500 / 23456=750 / 四五六同 ×2×4×8），点击骰子选中保留，和桌宠轮流对赌
- **策略类**：五子棋（三档 AI）/ 井字棋 / 2048（4×4·5×5·4096）
- **益智类**：数独（24/36/48 挖空）/ 华容道（3×3·4×4）/ 扫雷（经典三档）/ 记忆翻牌（6/8/12 对）
- **反应类**：贪吃蛇（速度三档 + 黄金食物）/ 打地鼠 / 西蒙记忆 / 俄罗斯方块（速度三档）
- **对赌类**：21 点（A 智能算牌）/ 石头剪刀布（三局两胜 + 桌宠记仇）/ 猜数字（范围/限次三档）
- **高分里程碑**：每款游戏独立最高分记录，破纪录 → 桌宠庆祝 + 回忆日志 + 额外好感

### 🎭 动作素材扩充（v6.30）
- 新增 12 个动作状态（饿/胜利/亲亲/沮丧/跳舞/唱歌/大哭/惊讶/得意/求摸头/撒娇抱抱/送花），双角色齐全（37 状态）
- 触发联动：饱食度低 → 饥饿图；小游戏胜负 → 欢呼/沮丧图；喂食 → 亲亲图
- 互动菜单精简：常用 5 动作直显，其余收「🎬 更多动作」子菜单

## 🚀 快速开始

### 方式一：下载便携包（推荐，无需 Python）

到 **[Releases 最新版](https://github.com/sjmsltx/deepseek-desktop-pet/releases/latest)** 下载 `DeepSeekPet-v*-win64.zip`（约 305 MB），解压后双击启动即可。
首次运行在 GUI 里配置 API Key：右键桌宠 → ⚙️ 设置 → 🔑 API 设置。

### 方式二：从源码运行

```powershell
# 1. 安装依赖
python -m pip install -r requirements.txt
# （可选）Live2D 模式：python -m pip install live2d-py pyopengl

# 2. 准备配置（复制模板并填入你的 API Key）
copy config.example.json config.json
# 编辑 config.json，填入 deepseek_api_key

# 3. 运行
python desktop_pet.py
```

首次运行后也可以用 GUI 配置：右键桌宠 → ⚙️ 设置 → 🔑 API 设置。

> ⚠️ **需要自备 DeepSeek API Key**（https://platform.deepseek.com 申请，模型 `deepseek-flash` / `deepseek-v4-pro`）。

## ⚙️ 配置

配置分两份文件，职责分开：

### `config.json`（参考 `config.example.json`）—— 本机/账号级设置

| 字段 | 说明 |
|------|------|
| `deepseek_api_key` | DeepSeek API Key（必填） |
| `personality` | 性格（温柔/傲娇/吐槽/元气/高冷，或自定义） |
| `reply_style` | 回复风格（short/normal/detailed） |
| `city` | 默认天气城市 |
| `active_chat` | 主动关心开关 |
| `app_aliases` | 自定义应用快捷别名 |
| `search_api_key` | Tavily 联网搜索 Key（可选） |
| `api_prices` | 价格覆盖（可选；有模型档案时会写进档案，避免两处各存一份） |

### `models.json`（参考 `models.json.example`）—— 模型身份

首次运行自动生成（会从旧 `config.json` 的 `model_flash`/`model_pro` 等字段迁移）。每个模型一条**档案**：

```json
{
  "version": 1,
  "profiles": [{
    "key": "flash",                          // 内部键（角色键）
    "display_name": "V4 Flash",              // 界面显示名（窗口标题/菜单/prompt 身份都用它）
    "model_id": "deepseek-flash",            // 实际请求的 model
    "aliases": ["deepseek-v4-flash"],        // 旧 ID 别名（价格查询/改名兼容用）
    "endpoint": "https://api.deepseek.com/chat/completions",
    "api_key_field": "deepseek_api_key",      // 复用哪个 key 字段（不存 Key 本体）
    "params": { "temperature": 1.0, "max_tokens": 128000, "reasoning": true },
    "price": { "input": 1.5, "cache": 0.05, "output": 4.5 },
    "appearance": { "color": "#B0C4DE", "sub": "浅蓝和服 · 快言快语" },
    "persona": { "greetings": ["…"], "happy_lines": ["…"] }
  }]
}
```

| 字段 | 说明 |
|------|------|
| `display_name` | 界面显示名。改它 → 窗口标题/右键菜单/prompt 身份同步变 |
| `model_id` | 实际发给 API 的模型 ID |
| `endpoint` | 接口地址（可指向中转/代理；全项目只此一处配置） |
| `api_key_field` | 这份档案用 `config.json` 里的哪把 key——**不同档案可指向不同服务商 / 中转**（没配则回退主 key `deepseek_api_key`） |
| `params` | `temperature` / `max_tokens`（256-384000） / `reasoning` 思考开关 |
| `price` | 每百万 token 单价，费用统计用；官方调价时改这里 |
| `appearance` / `persona` | 颜色、副标题、问候语、台词 |

> 旧版 `config.json` 里的 `model_flash` / `model_pro` / `reasoning` / `temperature` / `max_tokens` 已降为迁移来源：首次生成 `models.json` 时会被读入，之后以档案为准。

## 🏗️ 技术架构

```
┌─────────────────────────────────────────┐
│  PySide6 GUI（透明窗口/立绘/气泡/聊天面板）   │
├─────────────────────────────────────────┤
│  AI 核心（DeepSeek API + function calling）│
│  · system prompt：身份/性格/记忆/待办/规则    │
│  · 工具循环：LLM 输出意图 JSON → 程序执行     │
│  · 15+ 工具（安全校验 + 用户确认）            │
├─────────────────────────────────────────┤
│  记忆系统（memory.json，角色隔离）            │
│  主动关心（链式唤醒 + 回访 + 状态感知）        │
│  系统集成（托盘/热键/自启/贴边/剪贴板）        │
└─────────────────────────────────────────┘
```

### 主动消息机制（学习笔记）
详细讲解了 LLM 无状态本质、Function Calling、链式唤醒/回访机制的设计与实现，见 `主动消息机制学习笔记.md`。

## 📁 项目结构

```
desktop-pet/
├── desktop_pet.py              # 主程序（UI/聊天/AI 工作流/动画/工具分发）
├── model_registry.py           # 模型档案注册表（models.json 的加载/兜底/迁移/价格查询）
├── model_manager_ui.py         # 模型管理对话框（增删档案 / 拉官方列表 / 连通性自检）
├── settings_ui.py              # 统一设置窗口（六个分类，收拢原「设置」子菜单的 40+ 项）
├── deepseek_client.py          # DeepSeek 网络层（非流式 / SSE 流式 / 重试 / 模型列表 / 连通性探测）
├── requirements.txt            # 依赖清单（PySide6 + 可选 live2d）
├── pyproject.toml              # 项目元数据 / ruff 配置
├── config.example.json         # 配置模板（API Key 等）
├── models.json.example         # 模型档案模板（显示名/模型 ID/接口地址/价格）
├── 启动桌宠.bat                # Windows 一键启动
├── tests/
│   ├── smoke_test.py           # 冒烟测试（导入/构造/核心函数）
│   └── test_model_registry.py  # 模型档案单测（迁移/兜底/价格/兼容层）
├── assets/                     # 素材目录
│   ├── flash/                  # V4 Flash 状态立绘
│   ├── pro/                    # V4 Pro 状态立绘
│   └── live2d/                 # Live2D 模型库（扫描选用，自输入模型放这里）
├── docs/
│   ├── live2d_pipeline.md            # Live2D 自生成人物完整流程（Seedream→PS→Cubism）
│   ├── 项目功能体检报告-2026-09-14.md   # 全量功能体检：能不能 / 好不好 / 定位适配
│   ├── 排障与修复记录-2026-09-14.md    # 4 个真实缺陷的定位与修复过程
│   └── 项目展望-2026-09-13.md         # 阶段判断与后续方向
├── screenshots/                  # README 展示截图
├── 主动消息机制学习笔记.md         # AI 主动机制学习文档
├── 好感度与成长系统设计方案.md      # 双轴养成（好感度 + 等级）设计
├── 小游戏扩展设计方案.md           # 小游戏扩展设计
├── 知识索引锚点.md                # 开发知识条目索引
├── CHANGELOG.md                # 版本变更记录
├── CONTRIBUTING.md             # 贡献指南
├── SECURITY.md                 # 安全策略
├── CODE_OF_CONDUCT.md          # 行为准则
├── .github/                    # Issue / PR 模板
└── README.md
```

### 源码地图（想学习从哪看起）

| 想了解 | 搜索 `desktop_pet.py` 中的章节标记 |
|--------|----------------------------------|
| 工具调用体系 | `# ===== 工具` / `def _call_` |
| AI 状态预判 | `# ===== AI 状态预判` |
| 记忆系统 | `# ===== 记忆` / `def _save_memory` |
| 主动关心/唤醒 | `# ===== 主动` / `def _chain_wake` |
| Live2D 渲染 | `# ===== Live2D` / `def _create_l2d` |
| 语义搜索 | `# ===== 语义` / `def _smart_find_app` |
| 双语国际化 | `_TEXT_ZH` / `_TEXT_EN` 字典 |
| 界面交互 | `def _build_menu` / `def _open_chat_panel` |

## 📦 打包为 exe

### 一条命令出包（推荐）

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_portable.ps1 -Version 2.9.1
```

它会按顺序做四件事，任何一步不通过就**直接失败、不让你发出半成品**：

| 步骤 | 做什么 | 为什么必须有 |
|---|---|---|
| 1 构建 | PyInstaller 按 `tools\DeepSeekPet.spec` 构建 | spec 已纳入仓库（旧位置在 `release_build\`，那里被 .gitignore 排除，clone 下来会缺失）；已含 PySide6 / shiboken6 / edge_tts / win32com 的 `collect_all` |
| 2 staging | `tools\stage_portable.py` 把 assets / plugins / `*.ps1` / 说明与示例配置拷进包目录，并清除本地运行期数据 | **不跑这步 = 用户装完没有立绘、没有技能、语音与 OCR 不可用**（素材路径写死在 exe 旁边，而 spec 的 `datas=[]`） |
| 3 压包 | `tools\zip_portable.py`（Python zipfile，写 UTF-8 名字） | **别用 tar 压**：实测中文名（`使用说明.txt`）会被写成坏编码，解压出来是乱码 |
| 4 自检 | `tools\check_release_package.py` 三类核对 | 必需资产（含 assets 子目录与插件数动态对齐）/ Qt 运行时（含 `qwebp.dll`）/ 禁止入包项 |

只重跑后半段：加 `-SkipBuild`（已构建过）或 `-SkipCheck`（自己要看中间产物）。

> 🔒 **不能随包发的东西**（staging 会自动清掉）：`logs/`、`memories.json`、`models.json`、
> `config.json`、`files_cache.json`、`holidays_cache.json`、`plugins/_registry.json`、`__pycache__`。
>
> ⚠️ 不要在命令行再叠加 `--collect-all PySide6` 之类参数：spec 里已经有了，重复收集会把包从
> ~209 MB 撑到 ~305 MB（v2.9.0 实测）。
>
> 📝 PyInstaller 需 ≥ 6.21（支持 Python 3.14）。曾以为要手工删 `_internal` 里的 `icu*.dll`——
> 2026-09-21 复核实测：当前构建产物与最终发布包里 **icu*.dll 数量为 0**，无需删除。

### 手工等价命令（参考）

下面是把上面的步骤拆开写的样子，仅供排查问题时对照：

```powershell
# 1) 构建
python -m PyInstaller --noconfirm --clean --distpath release_build\dist --workpath release_build\build tools\DeepSeekPet.spec
# 2) staging → 3) 压包 → 4) 自检
python tools\stage_portable.py release_build\dist\DeepSeekPet
python tools\zip_portable.py release_build\dist\DeepSeekPet release_build\DeepSeekPet_v2.9.1_portable.zip
python tools\check_release_package.py release_build\DeepSeekPet_v2.9.1_portable.zip
```

> 🗣️ `edge_tts` 决定便携包是否带**在线神经声线**（晓晓等）；缺了仍能跑，朗读会自动降级到系统离线声线（偏机械）。
>
> 📊 `win32com` + `pythoncom`/`pywintypes` 决定**办公文档能力**（COM 驱动 WPS/Office）；缺了仍能跑，只是 `office_doc` 会回答「缺少 pywin32」。

## 🔌 接入你自己的模型 / 自己的声音

这一节是给“**不只想用 DeepSeek 默认配置**”的准备的 —— 你可以换模型、换声音、接自己训练好的模型。

### 一、换成别的模型（或你自己的中转/代理）

设置 → 🎯 模型管理 → 新建档案，填四样东西：

| 字段 | 说明 |
|---|---|
| 模型 ID | 对方要求的模型名（如 `glm-4-plus`、`deepseek-flash`） |
| 接口地址 | 完整 endpoint（如 `https://open.bigmodel.cn/api/paas/v4/chat/completions`） |
| 密钥配置项 | 指向 `config.json` 里存 key 的字段名（不同服务商可以各用一把 key） |
| 价格 | 输入/缓存/输出 单价（元/百万 token）；**不填也不会编数字** —— 费用记 0 并在统计里单列为「未计入」 |

两个容易踩的点：
- **计价方式**默认「自动」：官方域名按峰谷（高峰×2）算，**第三方/中转按固定价**，不会被误加倍。
- 非官方地址**不支持余额查询**（会明确提示）；官方改价时可用「💰 核对官方价格」一键比对（只提示，确认后才写入）。

### 二、换成你自己的声音（三种做法，从简单到折腾）

| 做法 | 怎么填 | 需要什么 |
|---|---|---|
| **① 系统自带声线** | 设置 → 朗读声线 → 「📃 列出系统声线」，或直接填 `offline:<声线名>` | 在 Windows 设置里装好语音包即可（不联网） |
| **② 在线神经声线**（默认） | 填 `edge:<声线名>`，如 `edge:zh-CN-XiaoyiNeural`；「🌐 列出在线声线」可挑 | **不需要 Key、不计费**，但要联网（音质最好） |
| **③ 你自己的模型**（训练/克隆好的） | 本机把模型跑成 HTTP 服务 → 填「本地服务地址」→ 「🔌 测试连接」→ 声线设为 `local:http://127.0.0.1:端口` | 那个服务需提供 `POST {地址}/tts` 返回音频（兼容 GPT-SoVITS api_v2 / CosyVoice / ChatTTS）；想用自己的音色就再填「参考音频」+「参考文本」（**零样本克隆，3～10 秒录音即可，多数不用训练**） |

**降级顺序**：本地服务 → 在线 → 离线。任何一级不可用会自动往下走 —— 不会出现“没声音”。
设置里点「❓ 怎么填自己的模型 / 自己的声音」也能随时看这份说明。

## ❓ 常见问题

**Q：桌宠怎么安装？需要装 Python 吗？**
A：不需要。到 [最新版 Release](https://github.com/sjmsltx/deepseek-desktop-pet/releases/latest) 下载 Windows 便携包，解压后双击运行即可（需自备 DeepSeek API Key）。想从源码运行见 [🚀 快速开始](#-快速开始)。

**Q：DeepSeek API Key 填在哪里？**
A：编辑仓库根目录的 `config.json`，把 Key 填进 `deepseek_api_key` 字段（字段名由 `models.json` 里的身份定义决定，随模型身份走）。Key 只在本地使用，不会发送给本项目。

**Q：支持哪些模型？怎么换成 V4 Pro 或自定义模型？**
A：模型身份定义在 `models.json` 的 `profiles` 里，默认带 Flash / Pro 两个身份，每个身份可配 `model_id`、`endpoint`、温度与价格等；缺少该文件时按 `models.json.example` 复制一份即可。

**Q：怎么设置开机自启？**
A：右键桌宠 → **🚀 开机自启**（菜单会显示“（已开）/（已关）”）。它会在系统启动文件夹放一个快捷方式，删掉那个快捷方式即可关闭。

**Q：怎么换立绘 / 换角色 / 用 Live2D？**
A：右键 → **🎭 形象**：可切换角色、在「静态模式 / Live2D 模式」之间切换、换人格与主题，「更多形象设置…」打开设置面板。Live2D 需额外安装 `live2d-py` 与 `pyopengl`（见 [🚀 快速开始](#-快速开始)），制作流程见 [docs/live2d_pipeline.md](docs/live2d_pipeline.md)。

**Q：它会读取我的聊天内容或屏幕吗？**
A：不会。只有你主动发给桌宠的对话会送到 DeepSeek API；聊天记忆与用量统计都存本地。可选的「前台程序感知」**只读取当前前台进程名**——不读窗口标题或内容、不截屏，且默认关闭。

**Q：桌宠能看图片吗？**
A：能（v6.62）。把图片拖进窗口、粘贴截图、或按 Ctrl+Alt+D 截屏，会**直接交给模型看图**（图表、界面布局这类非文字信息也能理解），失败会自动退回本地文字识别。可在 设置 → 模型与 API → 「图片直送」关闭；`deepseek-flash` 支持看图，`deepseek-v4-pro` 不支持。

**Q：费用统计里为什么写着「未计入费用」？高峰空闲怎么算？**
A：「N 次调用未配价格，未计入费用」说明该模型档案没填价格（接第三方模型时常见）——统计不会替它编数字，可在 设置 → 🎯 模型管理 里填真实价目。峰谷按官方口径：北京时间**周一至周五 9:00–12:00、14:00–18:00** 为高峰（不含法定节假日），其余（含周末与节假日全天）为空闲、价格是高峰的一半；节假日表已内置、跨年自动更新。判定一律按北京时间，**不受你电脑时区和系统时间影响**。

**Q：能接别的模型（非 DeepSeek）吗？**
A：能。在 设置 → 🎯 模型管理 新增档案，填上模型 ID、接口地址与价格即可；「计价方式」选自动时，官方地址按峰谷算、第三方与中转按固定价算（不会被误加倍）。注意：第三方地址不支持余额查询，官方调价也不会自动同步 —— 可用「💰 核对官方价格」一键比对（只提示，你确认后才写入）。

**Q：桌宠能写 Excel / Word 吗？**
A：能（v6.66）。本机装了 WPS 或 Microsoft Office 就能用 `office_doc` 工具：写表格、读表格、
生成**带样式的报表**（标题合并居中、表头加粗填色、边框、列宽自适应）、导出 PDF ——
你直接说“把这几天的花费做成表格”即可。文件统一落在程序目录的 `输出/` 下。

**Q：语音输入点 🎤 没反应 / 提示“在线语音识别未开启”？**
A：这是 Windows 的**语音隐私策略**开关（设置 → 隐私和安全性 → 语音 → 在线语音识别）——
属于系统隐私设置，桌宠**不会替你改**，只提示你去打开；不想开该开关时可用系统自带的 **Win+H** 语音输入。

**Q：启动报错 / 双击没反应怎么办？**
A：先看 [排障与修复记录](排障与修复记录_20260914.md) 与 [功能体检报告](功能体检报告_20260914.md)；仍无法解决可在 [Issues](https://github.com/sjmsltx/deepseek-desktop-pet/issues) 贴上报错日志。

## 🤝 贡献 / 扩展方向

想学习或贡献？先看 [CONTRIBUTING.md](CONTRIBUTING.md)（含源码阅读路线图）。

- [x] 前台窗口感知（判断用户在忙什么）—— v6.59 实现：**可选开关、默认关闭**，只读前台进程名（不读窗口标题/内容、不联网）
- [x] 插件化工具系统 —— 已落地：`plugins/` 目录 + 安装 / 卸载 / 列举工具（内置主题与示例插件）
- [x] 语音交互（TTS/ASR）—— **P0 朗读已实现（v6.63）**：离线系统声线（WinRT，失败回退 SAPI）、
  默认关、夜间静音、零新增依赖；语音输入（ASR）仍待做 —— 本机中文识别包已就绪，方案见 [docs/语音交互方案](docs/语音交互方案-20260919.html)
- [ ] 更多角色 / Live2D 骨骼动画 —— 暂缓（吃美术资产，边际收益低）

## 📄 License

[MIT](LICENSE)

---

**免责声明**：本项目仅供学习交流。立绘素材由 AI 生成，使用请遵守相应生成工具的条款。
