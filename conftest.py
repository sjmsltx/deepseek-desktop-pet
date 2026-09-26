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


# ── D1（2026-09-26）：闸门卡状态件全局隔离 ──────────────────────────────
# 背景：缺陷 `WX-桌宠-20260926-28`（闸门卡反复刷聊天列表 ✗）根因 = `_gate_card_day`
# 为**纯内存态** ✗ → 重启/多实例清零 ✗ → 修法：**落盘**（`logs/gate_card_state.json` ✓）。
# ⚠️ 副作用：凡“建真 `PetWidget` 并触发成本闸门”的用例 ✗，会写到**真实**状态件 ✅
# → 同一测试进程内第二次触发（或第二次跑）就被判为“当天已有卡”✗ → 误红 ✗。
# → 故在 conftest 层**自动隔离**：所有用例一律把状态件指向各自 tmp ✓（真件不受污染 ✓）
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _isolate_gate_card_state(tmp_path, monkeypatch):
    """⭐ D1：所有用例的闸门卡状态件一律落 tmp ✓（真 `logs/gate_card_state.json` 不受影响 ✓）"""
    try:
        import desktop_pet
        monkeypatch.setattr(desktop_pet, 'GATE_CARD_STATE_PATH',
                            str(tmp_path / 'gate_card_state.json'))
    except Exception:
        pass
