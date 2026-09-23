# ENTRY.md —— 从哪开始读 / 从哪开始跑（桌宠项目入口页）

> **状态截至：2026-09-23**（⚠️ 本文是入口指针，**功能状态一律以代码与测试为准** ✗ 不以文档为准）
> 用途：新会话/新人接手时，**只读这一页**就能把"跑起来 / 测一遍 / 改哪里"接上 ✓

---

## 1. 三十秒跑起来

```powershell
cd 'E:\ai工作站\desktop-pet'
& "C:\Users\lby13\AppData\Local\Python\pythoncore-3.14-64\python.exe" desktop_pet.py
```
- ★ **必须用上面这个独立 python** ✗ —— 用 AutoClaw 捆绑的 python 会出"白框事故"（Qt 定制环境）✓
- 需要在界面里填 **自己的 DeepSeek API Key**（不进仓库 ✗）

## 2. 三十秒测一遍

```powershell
cd 'E:\ai工作站\desktop-pet'
& "C:\Users\lby13\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m pytest tests -q
# 期望：762 passed / 8 skipped / 退出码 0（★ 退出码必须是 0 ✗ 人眼看绿不算）
# 762 = 739（旧基线）+ 10（A 类维护护栏）+ 13（B 类：回收/落点护栏 11 条 + 成本冷却 2 条）
```

> ✅ **已重采（2026-09-23，Owner 批准）**：`markdown.sample_01` 差异已消除 —— **重采前红 ✗ / 重采后「黄金对照：完全一致 ✅（7 个分区）」✓**
> 根因（供以后复盘）：`chat_render.py` 在 **`07bfe78`（v2.9.1 渲染修复）** 改过 ✓，但基线停在 **`d45f351`（v2.9.0）** ✗ → 发版时漏了重采 ✗
> → 教训：**改了渲染/主题就要重采基线**；该检查已纳入发版前清单 ✓
一键版（本 A 类新增 ✓）：
```powershell
& "C:\Users\lby13\AppData\Local\Python\pythoncore-3.14-64\python.exe" tools\verify.py            # 全量
& "C:\Users\lby13\AppData\Local\Python\pythoncore-3.14-64\python.exe" tools\verify.py --quick    # 快速
& "C:\Users\lby13\AppData\Local\Python\pythoncore-3.14-64\python.exe" tools\verify.py --with-ui  # 追加 UI 黄金基线
```
另有两件**不属 pytest**（手工 / 较慢 ✗）：
- 手工回归器：`regression_test.py`（**故意不进 pytest 收集** ✓ 见 `conftest.py`）
- UI 黄金基线：`tests\golden_ui.py check`
- 真机冒烟 4 步：① 双击启动 ② **看立绘（空白 = 回归，立即回退）** ③ 发一句话有回复 ④ 右键干净退出

## 3. 改代码前先知道的五条

| # | 约定 | 谁在守 |
|---|---|---|
| 1 | **平台能力一律走 `platform_layer`**，调用方不得直连平台实现 | `tests/test_platform_boundaries.py` |
| 2 | **技能包权限分级 + 永禁 14 项**，`open()` 也按 AST 判读写 | `tests/test_file_api_permissions.py` |
| 3 | **前台程序感知只读进程名**，不读标题/内容、不联网、默认关 | `tests/test_foreground_privacy.py` |
| 4 | **UI 颜色只走 `pet_theme` 的 token**（哨兵色 `#ff00ff` 例外） | `tests/test_source_conventions.py`（本 A 类新增 ✓） |
| 5 | **协作台 `data-*` 契约（9 个属性）** 与"同一 `data-seq` 只渲染一次" | `docs/3.0-M2-UI导出契约-冻结v1.md` + 复核脚本 |

## 4. 关键入口（读代码从这里切）

| 想干什么 | 从哪读 |
|---|---|
| 程序怎么起来、窗口怎么搭 | `desktop_pet.py`（⚠️ 8,204 行 / 非空 7,632 行 / **`PetWidget` 一个类 7,928 行** ✗ 按需跳读 ✓） |
| 消息内核（3.0·M1） | `relay_log.py`（536 行 ✓ `append/view/replay/inbox` ✓） |
| 协作台（3.0·M2） | `collab/relay_server.py`（只读导出面 ✓）+ `collab/index.html`（渲染面 ✓） |
| 工具与治理 | `tools_registry.py`（schema ✓）、`tools_executor.py`（执行 ✓）、`governance.py`（审计/限额/白名单 ✓） |
| 发布工程 | `tools/build_portable.ps1`（一条命令出包 ✓）+ `tools/check_release_package.py`（三类机器校验 ✓） |
| 测试口径 | `pytest.ini`（收集范围 ✓）+ `conftest.py`（排除手工回归器 ✓） |

## 5. 两套版本号（别混 ✗）

- **发布版**：语义化 `2.x`（最新 **v2.9.1** ✓）
- **源码注释里的 `v6.xx`**：内部开发迭代号 ✓（起点 v6.19 ✓）

## 6. 文档可信度（**重要** ✗）

- **"某功能做没做"一律问测试/代码** ✓ **不问文档** ✗（文档只作线索 ✓）
- 过期文档清单见 `docs/DOC-STATUS.md` ✓（本 A 类新增 ✓）
- 引用行号时**给出取法边界** ✓（"读了前 N 行"不等于读全 ✓）

---

*本页由桌宠线维护；改动本页只需改"状态截至"日期与差异 ✓ 不需要重写全页 ✓*
