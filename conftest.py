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


# ── ⭐ 模块级全局 `ACTIONS_ALLOWED` 的隔离护栏（2026-10-05，⭐ 采纳微信侧 `WX-…-62` §2.2 ✓）──
# ⭐ ⭐ 背景：⭐ `relay_server.create_server()` **会写模块级全局** ✗（⭐ 对面实测确认 ✓）
#   ⇒ ⭐ ⭐ **模块级可变全局 ＝ 跨用例／跨模块污染的**结构性根源** ✗** ✓
# ⭐ 本条护栏 = ⭐ **每个用例跑完，断言全局回到初始值 `False`** ✗：
#   · ⭐ 有测试漏还原 ⇒ ⭐ ⭐ **当场红** ✓（⛔ 不再靠"下次偶发"✗ 才发现 ✓）
#   · ⭐ 与 EXP.0104「⭐ **mock 必须可自动恢复**」✗ 同族 ✓
# ⭐ 注：⭐ 治本之策是"⭐ **把开关做进 server 实例**"✗（⭐ 对面建议 1 ✓ ⇒ ⭐ 从根上不可能污染 ✓）
#   —— ⭐ 那属**较大改动** ✗ ⇒ ⭐ 我方列为下一批 ✓；⭐ 本护栏是**当下就该有**的探针 ✓。
@_pytest.fixture(autouse=True)
def _guard_actions_allowed_global(request):
    """⭐ 用例跑完，`relay_server.ACTIONS_ALLOWED` 必须回到初始值 ✗（⭐ 否则当场红 ✓）。"""
    yield
    try:
        import relay_server
    except Exception:
        return
    try:
        cur = getattr(relay_server, 'ACTIONS_ALLOWED', False)
    except Exception:
        return
    if cur is not False:
        # ⭐ 先**恢复**再报红 ✓（⭐ 免得污染后续用例 ✓ —— ⭐ 与"mock 必须可自动恢复"同族 ✓）
        # ⚠️ ⭐ 自纠（⭐ 本脚本首版在这里写了 `except Exception: pass` ✗ ⇒ ⭐ 被对方
        #   `test_silent_guard::test_no_new_silent_spots` **当场判红** ✗ ✓ —— ⭐ 那是本项目
        #   明令禁止的"新增静默失败点"✗ ✓（⛔ 不许靠 `--freeze` 绕过 ✗））
        #   ⇒ ⭐ 改为**不静默**：⭐ 直接赋值 ✓（⭐ 模块属性赋值不会失败 ✓）＋ ⭐ 失败就**抛** ✗ ✓
        relay_server.ACTIONS_ALLOWED = False
        raise AssertionError(
            '⛔ 用例 %s 跑完把模块级全局 ACTIONS_ALLOWED 留在 %r ✗（⭐ 应为 False ✓）'
            '⇒ ⭐ 这是跨用例／跨模块污染的根源 ✓ ⇒ 请改用 monkeypatch.setattr ✓'
            % (request.node.name, cur))
