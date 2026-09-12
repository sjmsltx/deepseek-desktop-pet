# -*- coding: utf-8 -*-
"""tests/test_tool_registry.py — 工具注册表契约测试
=====================================================
背景（2026-09-12 重构）：_execute_tool 原先是一个 169 行、29 个 if/elif 分支的大方法，
加一个工具要读懂整条链子。现改为「_TOOL_HANDLERS 注册表 + 每个工具一个 _tool_xxx 小方法」。

本测试把重构后的契约固定下来：
1. tools_registry.AI_TOOLS 里声明的每个工具都必须有对应处理函数（否则 AI 调用后只得到"未知工具"）；
2. 注册表里每个处理函数都必须真实存在（防改名后变成运行时 AttributeError）；
3. 注册表里不能有 AI_TOOLS 未声明的孤儿处理函数（防删工具后留死代码）。

运行：python tests/test_tool_registry.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from desktop_pet import PetWidget  # noqa: E402
from tools_registry import AI_TOOLS  # noqa: E402

declared = [t['function']['name'] for t in AI_TOOLS]
handlers = dict(PetWidget._TOOL_HANDLERS)

fails = []

missing = [n for n in declared if n not in handlers]
if missing:
    fails.append('AI_TOOLS 声明了但注册表没有处理函数：%s' % missing)

ghost = [h for h in handlers.values() if not callable(getattr(PetWidget, h, None))]
if ghost:
    fails.append('注册表指向不存在的方法：%s' % ghost)

orphan = [n for n in handlers if n not in declared and not n.startswith('mcp_')]
if orphan:
    fails.append('注册表有 AI_TOOLS 未声明的孤儿条目：%s' % orphan)

dup = len(handlers) != len(set(handlers.values()))
if dup:
    fails.append('多个工具名指向同一个处理函数（可能是复制粘贴错误）')

print('注册表契约测试：AI_TOOLS %d 个工具 / 注册表 %d 条' % (len(declared), len(handlers)))
if fails:
    for f in fails:
        print('  ❌ ' + f)
    sys.exit(1)
print('  结果：全部通过 ✅')
