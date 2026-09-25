# -*- coding: utf-8 -*-
"""pytest 收集配置。

regression_test.py 是**手动回归器脚本**（其 `def test(name, fn)` 需要外部传入 name），
不是 pytest 测试模块；被收集会报 "fixture 'name' not found"，
导致用例其实全绿、但全量退出码为 1（任何按退出码判成败的 CI 都会误判）。
这里显式不收集它。
"""
collect_ignore = [
    'regression_test.py',
    # ── R1（2026-09-25）：脚本式检查模块 ──────────────────────────────
    # 这些文件是**脚本**（模块级代码 + sys.exit()），不是 pytest 用例 ✗。
    # 被收集时：它们只在 import 期跑一次，一旦断言失败（例如碰到仓库正在提交的瞬态）
    # 会令**整套 pytest** 报 INTERNALERROR —— 外部看成“测试挂了” ✗（微信侧 2026-09-25 实际撞到）
    # → 移出收集，改由 `tools/verify.py` **单独调用** ✓（覆盖不丢 ✓）
    'tests/test_command_gate.py',
    'tests/test_tool_registry.py',
    'tests/test_pet_selfcode.py',
    'tests/test_pet_sysutils.py',
    'tests/test_pet_docs.py',
    'tests/golden_ui.py',
]
