# -*- coding: utf-8 -*-
"""完整执行 v3：模块地图 + 能力段注入 + 第5条；第7条已改则跳过"""
import io

PB = r'E:\ai工作站\desktop-pet\prompt_builder.py'
src = io.open(PB, 'r', encoding='utf-8').read()
changed = []

# 1. 模块地图常量
old_anchor = "def build_system_prompt(char_name, current, cur_model, personality, style_hint, lang_hint,"
if 'MODULE_MAP = (' not in src:
    assert old_anchor in src, '锚点未找到'
    MODULE_MAP = '''MODULE_MAP = (
    '【项目结构（模块化，改代码流程：search_code 定位 → read_file 读行号 → edit_own_code 指定 file 修改）】\\n'
    'desktop_pet.py — 主程序：UI/聊天面板/AI工作流(_ai_worker)/动画/工具分发(_execute_tool)\\n'
    'deepseek_client.py — DeepSeek API 网络层（非流式/SSE 流式/重试）\\n'
    'tools_registry.py — 28 个 AI 工具 schema 定义（AI_TOOLS/TOOL_STATUS）\\n'
    'tools_executor.py — 纯逻辑工具实现（时间/计算/锁屏/天气/选项解析）\\n'
    'prompt_builder.py — system prompt 构建（build_system_prompt）\\n'
    'memory_engine.py — 记忆检索引擎（BM25/自动抽取/LLM重排）\\n'
    'memory_store.py — 记忆数据层（load/save/remember_fact）\\n'
    'chat_render.py — Markdown 解析（split_rich_blocks/md_to_html）\\n'
    'chat_cards.py — 代码/表格卡片组件（CodeCard/TableCard）\\n'
    'api_stats.py — API 用量统计；care_engine.py — 主动关心网络层\\n'
    'code_checker.py — Python 语法检查；pet_sysutils.py — 剪贴板/PowerShell/音量/热键\\n'
    'pet_storage.py — JSON 原子持久化；affection_engine.py — 好感度引擎\\n'
    'memory_events.py — 回忆日志；affection_ui.py — 关系面板/回忆相册\\n'
    'pet_minigames.py — 15 款小游戏；plugin_manager.py — 插件系统；mcp_bridge.py — MCP 桥接\\n'
)


'''
    src = src.replace(old_anchor, MODULE_MAP + old_anchor, 1)
    changed.append('模块地图常量')

# 2. 能力段前注入
old2 = "        + '\\n\\n【桌宠自身能力（重要，不要改源码）】桌宠有完整的插件系统/主题系统/MCP 扩展能力：\\n'"
if "MODULE_MAP\n" not in src.split(old2)[0][-50:] if old2 in src else True:
    pass
if old2 in src and "+ '\\n\\n' + MODULE_MAP" not in src:
    new2 = "        + '\\n\\n' + MODULE_MAP\n        + '\\n\\n【桌宠自身能力（重要，不要改源码）】桌宠有完整的插件系统/主题系统/MCP 扩展能力：\\n'"
    src = src.replace(old2, new2, 1)
    changed.append('能力段注入')

# 3. 第 5 条
old5 = "        + '5. read_file 的 path 是相对桌宠项目目录（desktop-pet-dev）的相对路径，不是当前工作目录。\\n'"
if old5 in src:
    new5 = ("        + '5. read_file 的 path 是相对桌宠项目目录的路径（项目已模块化，共 14+ 个 .py 文件，见上方【项目结构】），"
            "不是当前工作目录；不确定文件时用 search_code 搜关键词定位。\\n'")
    src = src.replace(old5, new5, 1)
    changed.append('第5条')

# 4. 第 7 条（若还是旧版则更新）
old7 = ("+ '7. 若确需用 edit_own_code 改代码：先用 read_file 带 start_line/end_line 精确读目标行（输出带行号），'\n"
        "        '再用 start_line/end_line + new_text 按行替换，不要凭记忆写 old_text。\\n'")
if old7 in src:
    new7 = ("+ '7. 若确需用 edit_own_code 改代码：先用 search_code 定位关键词所在文件与行号，再 read_file 带 start_line/end_line '\n"
            "        '精确读目标行（输出带行号），最后 edit_own_code 指定 file（目标模块名，默认 desktop_pet.py）+ start_line/end_line + new_text 按行替换。\\n'")
    src = src.replace(old7, new7, 1)
    changed.append('第7条')

io.open(PB, 'w', encoding='utf-8').write(src)
print('✅ 更新:', changed or '（均已在位）')

import ast
ast.parse(src)
print('✅ 语法通过')
