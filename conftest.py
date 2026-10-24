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
# -- 聊天历史隔离护栏（2026-10-23 实测发现的真缺陷） ------------------
# 实测：跑全量后 Owner 的 chat_memory_flash.json 从 60 条变 62 条（多 2 条闸门卡）✗
#   原因：_chat_memory_path() 用 BASE_DIR（真仓库根），
#         而 7 个用例会真建 PetWidget 并触发 _save_chat_memory() ✗
#   修法：与 D1「闸门卡状态件一律落 tmp」同一口径，历史文件也一律落 tmp ✓
@_pytest.fixture(autouse=True)
def _isolate_chat_memory(tmp_path, monkeypatch):
    """所有用例的聊天历史一律落 tmp（真 chat_memory_*.json 不受影响）"""
    # 窄异常 + 不静默：导入不到就带原因跳过（不吞错，也不刷屏）
    try:
        import desktop_pet as _dp
    except ImportError as _exc:
        _pytest.skip('desktop_pet 不可导入，跳过聊天历史隔离：%s' % _exc)
    monkeypatch.setattr(_dp.PetWidget, '_chat_memory_path',
                        lambda self: str(tmp_path / ('chat_memory_%s.json'
                                                   % getattr(self, 'current', 'flash'))))

# -- 日志文件隔离护栏（2026-10-24 实测发现的第二个隔离缺口） --------------
# 实测：logs/pet.log 里有 20 条「余额盯梢：别处花费约 ¥0.4200」，
#   而 ¥0.4200 正是 tests/test_balance_watch.py 的夹具数据（13.90 → 13.48）
#   ⇒ 测试构造真 PetWidget → _report_other_spend → log.info 写进**真日志文件**
#
# ⚠ 为什么必须 function 级（第一版写 session 级无效，实测被撤销）：
#   `test_pet_log_injection.test_set_log_file_redirects_writes` 在 finally 里调
#   `pet_log.reset()`，而**无参 reset 回到默认路径** → session 注入被悄悄撤销
#   → 之后每个用例又开始写真 logs/pet.log（18:20:38~18:21:13 那段即此）
#
# ⚠ 为什么 test_pet_log_injection 必须豁免：
#   该模块断言 `pet_log.LOG_FILE == DEFAULT_LOG_FILE`（验证默认路径一字不变）。
#   隔离了它，就把「默认路径不变」这个护栏的前提打破 → 等于让护栏失效。
_LOG_ISOLATION_EXEMPT = ('test_pet_log_injection',)


@_pytest.fixture(scope='session')
def _petlog_dir(tmp_path_factory):
    """日志专用目录：**独立于任何用例的 tmp_path** ✓

    ⚠ 第一版把 pet.log 放在用例自己的 `tmp_path` 下 → 被
    `test_output_prefix_guard` / `test_collab_init_channel` / `test_remote_wiring`
    这些**扫描目录内文件命名**的用例当成「多出来的文件」→ 7 个用例误红（实测）。
    改用 pytest 会话根下的独立子目录，不在任何用例 tmp_path 里。
    """
    return tmp_path_factory.mktemp('_petlog')


@_pytest.fixture(autouse=True)
def _isolate_log_file(request, _petlog_dir):
    """所有用例的日志一律落 tmp（真 logs/pet.log 不受影响）

    例外：`test_pet_log_injection` 专测日志路径本身 → 不隔离（见上方注释）。
    """
    _mod = getattr(getattr(request.node, 'module', None), '__name__', '') or ''
    if _mod in _LOG_ISOLATION_EXEMPT:
        yield
        return
    try:
        import pet_log
    except ImportError as _exc:
        _pytest.skip('pet_log 不可导入，跳过日志隔离：%s' % _exc)
    pet_log.set_log_file(str(_petlog_dir / 'pet.log'))
    yield
    pet_log.reset()


# -- 用量统计隔离护栏（2026-10-24 实测发现的真缺陷） --------------------
# 实测：跑全量时真 api_stats.json 的余额缓存被改写（mtime 18:03:11），
#   日志出现「余额查询成功」—— 测试进程构造了真 PetWidget，
#   而 PetWidget 用 os.path.join(BASE_DIR, 'api_stats.json') 这个**真路径**。
# 口径与 _isolate_chat_memory 一致：统计文件一律落 tmp ✓
@_pytest.fixture(autouse=True)
def _isolate_api_stats(tmp_path, monkeypatch):
    """所有用例的用量统计一律落 tmp（真 api_stats.json 不受影响）"""
    try:
        import desktop_pet as _dp
    except ImportError as _exc:
        _pytest.skip('desktop_pet 不可导入，跳过用量统计隔离：%s' % _exc)
    _real = _dp.ApiStats
    _seq = [0]

    class _TmpStats(_real):
        def __init__(self, path=None, *args, **kwargs):
            _seq[0] += 1
            super().__init__(str(tmp_path / ('api_stats_%d.json' % _seq[0])),
                             *args, **kwargs)

    monkeypatch.setattr(_dp, 'ApiStats', _TmpStats)


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
