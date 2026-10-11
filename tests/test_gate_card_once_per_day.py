# -*- coding: utf-8 -*-
"""D1 + D11-2 护栏：闸门/额度卡片「同 category 同一天**聊天列表最多一张**」

现象（Owner 20:50 截图 ✓）：19:47–19:49 两分钟内 **4 张**同类卡片 ✗（余额不足 / 达到上限 交替 ✓）

── D1（2026-09-26，原修）──────────────────────────────────
根因：`_gate_card_day` 原为**纯内存态** ✗ → 重启/多实例即清零 ✗ → 同日同类再出卡 ✗
修法：① `_gate_card_day` **落盘** ✓（`logs/gate_card_state.json` ✓ 不写 config ✗）
      ② 判定 = **内存态 ＋ 落盘态合并** ✓ → 跨重启/多实例亦只一张 ✓
      ③ 兜底 emit **纳入同一守卫** ✓

── ⭐ D11-2（2026-10-11，本次修）────────────────────────────
真因（微信侧 `WX-71` 独立定位 ✓ ＋ 我方 `PC-193` 核证 ✓）：
  ⭐ 那道门**只挂在 `_notify_cost_blocked` 内部** ✗，而 `_notify_failure_card` 有**三条** caller：
     `:1246`（内部）／ `:1302`（`source='cost_gate'` ← **只有这条带门** ✓）／
     `:3331`（`source='_post_stream'` ← ⭐ **不带门** ✗，只剩同代次去重，而每次重试都是新代次 ✗）
  ⭐ 硬证据：`logs/gate_card_state.json` **从未生成** ✓（git 全历史亦无 ✓）⇒ 带门那条路几乎没走到 ✓
  ⭐ 而用户遇到的多是**上游失败**（402 / quota）→ 全走 `_post_stream` ⇒ **反复弹** ✗
修法：**门收到唯一出口** ✓（⛔ 不是给 `_post_stream` 单独补 ✗ —— 那会两处逻辑、下次还漏第三处 ✗）
  ① 出口内加**第二道门**（当天同因只一张），与**同代次门并存** ✓ 非替代 ✗
  ② 只对 `GATE_CARD_KINDS = ('本地闸门', '额度')` 生效 ✓ —— 别的卡照旧即时出 ✓
  ③ 归类**先按 Diag.cause 细分** ✓ 再 kind 兜底 ✓（`本地闸门` 一个 kind 装了两件事 ✗）
  ④ ⭐ **本轮新增用例 ⑧：从 `_post_stream` 触发** ✓（⛔ 只看本文件旧用例全绿 ＝ 没验到用户走的路 ✗）

═══ 本文件用例与要验的"那条路" ═══
  ①~⑤ 走 `_notify_cost_blocked`（闸门路）  ⑥⑦ 源码护栏  ⑧ **走 `_post_stream`（用户走的路）** ✓
"""
from __future__ import annotations

import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'desktop_pet.py'


def _src():
    return io.open(APP, encoding='utf-8').read()


class _W:
    """最小替身：只带 `_notify_cost_blocked` / `_notify_failure_card` 所需属性 ✓（不打真 GUI ✓）

    ⭐ D11-2 关键改动：`_notify_failure_card` **不再原地造假** ✗
      —— 改为**转发给真出口** ✓，让"当天同因只一张"那道门**真的被执行** ✓
      （原版替身直接 append 并返回 'emitted' ⇒ 门被架空 ⇒ 修完也不会红 ⇒ 形同没测 ✓）
    """

    def __init__(self, state_path, key_day_seed=None):
        self._cards = []
        self._fallbacks = []
        self._notifies = []
        self._suspended = []
        self.COST_BLOCKED_NOTIFY_COOLDOWN = 3600
        self.COST_NOTIFY_MS = 1000
        self.ai_reply_signal = self  # emit → self.emit
        self._state_path = str(state_path)
        self._gen = 1
        self.UPSTREAM_LAYERS = ()            # 本替身不测上游公告 ✓

    # 使落盘/读盘指向临时文件 ✓（不污染真 logs ✓）
    def _gate_card_state_path(self):
        return self._state_path

    def _card_gen(self):
        """⭐ 供真出口取代次 ✓

        ⚠️ **每次调用自增** ✓ —— 这是**关键的真实性**：
          真实里每次用户请求是一个**新任务 = 新代次** ✓；
          若恒返回同一个值 ⇒ 同代次门会把后续全部挡住 ✗
          ⇒ 测到的是「同代次门」而不是「日门」✗（旧版替身直接造假，连门都没跑 ✗）
        """
        _g = self._gen
        self._gen += 1
        return _g

    def emit(self, txt):
        """⭐ 分流 ✓：四段卡片 vs 兜底行 —— 断言强度不变 ✓（仍然分别计数 ✓）"""
        if '（已暂停本次调用' in txt:
            self._fallbacks.append(txt)
        else:
            self._cards.append(txt)

    def _notify(self, txt, ms=None):
        self._notifies.append(txt)

    def _suspend_active_care(self, reason=''):
        self._suspended.append(reason)

    def _atomic_write_json(self, path, obj):
        with io.open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f)

    # ⭐ 转发真出口 ✓（不再造假 ✗）
    def _notify_failure_card(self, diag, gen=None, source=''):
        import desktop_pet
        return desktop_pet.PetWidget._notify_failure_card(self, diag, gen=gen, source=source)


def _bind(w):
    """把类里的方法绑到替身上 ✓（状态件读写已模块级 ✓ → 替身无需感知 ✓）"""
    import types

    import desktop_pet
    for name in ('_cost_gate_key', '_notify_cost_blocked'):
        setattr(w, name, types.MethodType(getattr(desktop_pet.PetWidget, name), w))


def _diag_for_quota():
    """⭐ 造一张"账户余额不足"的诊断 ✓（⭐ 与 `_post_stream` 那条路同源 ✓）

    路径与真实一致：`pet_diagnosis.explain_error(exc, status=402, ...)`
      → 命中 `n == 402 or 关键词` ⇒ `Diag('额度', …)` ✓
    """
    import pet_diagnosis as _d
    return _d.explain_error(Exception('Payment Required'), status=402, context='对话')


# ── ① 同 category 同一天 → 只渲染一次 ✓ ─────────────────────────────
def test_same_category_same_day_only_one_card(tmp_path, monkeypatch):
    import desktop_pet

    state = tmp_path / 'gate_card_state.json'
    w = _W(str(state))
    _bind(w)
    monkeypatch.setattr(desktop_pet, 'GATE_CARD_STATE_PATH', str(state))

    w._notify_cost_blocked('今日模型调用已花 ¥3.00，余额不足 ¥1.00')
    w._notify_cost_blocked('今日模型调用已花 ¥3.00，余额不足 ¥1.00')
    w._notify_cost_blocked('今日模型调用已花 ¥25.00，余额不足 ¥1.00')      # 金额变 ✓ 同类 ✓
    assert len(w._cards) == 1, w._cards
    assert w._fallbacks == [], '⭐ 当天已有卡 → 不得再 emit 兜底行 ✗'


# ── ② 重启后（新实例读同一状态件）→ 不再出第二张 ✓ ───────────────────
def test_restart_does_not_emit_second_card(tmp_path, monkeypatch):
    import desktop_pet

    state = tmp_path / 'gate_card_state.json'
    monkeypatch.setattr(desktop_pet, 'GATE_CARD_STATE_PATH', str(state))
    for _ in range(3):                       # 模拟 3 次“重启”（各自新实例 ✓）
        w = _W(str(state))
        _bind(w)
        w._notify_cost_blocked('今日模型调用已花 ¥3.00，余额不足 ¥1.00')
        if _ == 0:
            assert len(w._cards) == 1
        else:
            assert w._cards == [], '⭐ 重启后不得再出第二张 ✗'


# ── ③ 两个实例共用状态 → 合计一张 ✓ ─────────────────────────────────
def test_two_instances_share_one_card(tmp_path, monkeypatch):
    import desktop_pet

    state = tmp_path / 'gate_card_state.json'
    monkeypatch.setattr(desktop_pet, 'GATE_CARD_STATE_PATH', str(state))
    ws = []
    for _ in range(2):
        w = _W(str(state))
        _bind(w)
        ws.append(w)
    ws[0]._notify_cost_blocked('余额不足 ¥1.00')
    ws[1]._notify_cost_blocked('余额不足 ¥1.00')
    assert [len(x._cards) for x in ws] == [1, 0], '⭐ 两实例合计一张 ✓'


# ── ④ 不同 category 各自一张 ✓ ─────────────────────────────────────
def test_different_category_each_one(tmp_path, monkeypatch):
    import desktop_pet

    state = tmp_path / 'gate_card_state.json'
    monkeypatch.setattr(desktop_pet, 'GATE_CARD_STATE_PATH', str(state))
    w = _W(str(state))
    _bind(w)
    w._notify_cost_blocked('余额不足 ¥1.00')          # balance
    w._notify_cost_blocked('已花 ¥25.00，达到上限 ¥20.00')   # daily_cost
    w._notify_cost_blocked('余额不足 ¥1.00')
    assert len(w._cards) == 2, w._cards


# ── ⑤ 跨天重置 ✓ ──────────────────────────────────────────────────
def test_cross_day_resets(tmp_path, monkeypatch):
    import desktop_pet

    state = tmp_path / 'gate_card_state.json'
    monkeypatch.setattr(desktop_pet, 'GATE_CARD_STATE_PATH', str(state))
    w = _W(str(state))
    _bind(w)
    w._notify_cost_blocked('余额不足 ¥1.00')
    assert len(w._cards) == 1
    # 手改落盘日期为“昨天” → 新的一天应可再出一张 ✓
    with io.open(state, encoding='utf-8') as f:
        d = json.load(f)
    d['day'] = '1970-01-01'
    with io.open(state, 'w', encoding='utf-8') as f:
        json.dump(d, f)
    w._gate_card_day = None
    w._notify_cost_blocked('余额不足 ¥1.00')
    assert len(w._cards) == 2, '⭐ 跨天应重置 ✓'


# ── ⑥ 源码护栏：落盘 + 合并判 + 不写 config ✓ ──────────────────────
def test_source_guards():
    s = _src()
    assert 'GATE_CARD_STATE_PATH' in s, '⭐ 缺少落盘状态件常量 ✗'
    assert 'gate_card_state.json' in s
    assert 'def _gate_card_day_load' in s and 'def _gate_card_day_mark' in s, '⭐ 须为模块级函数 ✗'
    assert '_gate_card_day_load()' in s, '⭐ 判定必须合并落盘态 ✗'
    assert 'self._gate_card_day_load' not in s, '⭐ 不得再依赖实例方法 ✗（会让批 A 替身失效 ✗）'


# ── ⑦ ⭐ D11-2 源码护栏：门必须收在**唯一出口**内 ✓ ─────────────────
def test_source_guard_gate_lifted_into_single_exit():
    """⭐ 本次修的核心：门不能再只住在 `_notify_cost_blocked` 里 ✗"""
    s = _src()
    # 出口体内必须有 GATE_CARD_KINDS 判定
    body = s.split('def _notify_failure_card(self, diag', 1)[1].split('\n    def ', 1)[0]
    assert 'GATE_CARD_KINDS' in body, '⭐ 日门必须在唯一出口内 ✗（否则 _post_stream 仍绕过 ✗）'
    assert '_gate_card_day_mark(' in body, '⭐ 出口内必须落盘 ✓ 防多实例抢 ✗'
    # ⛔ 旧位置不得再自行判日门（避免两处逻辑 ✗）
    cb = s.split('def _notify_cost_blocked(self, why):', 1)[1].split('\n    def ', 1)[0]
    assert '_gate_card_day_mark(' not in cb, \
        '⭐ 旧位置不得再落盘判门 ✗ —— 门应收在唯一出口 ✓（微信侧 `WX-73` §3 收严②③ ✓）'
    # 归类必须按 cause 细分 ✓ 不能只按 kind ✓
    assert 'def _gate_card_key_for' in s and "'余额' in _w" in s, \
        '⭐ 归类必须按 Diag.cause 细分 ✗（只按 kind 会把"上限"和"余额"压成一张 ✗）'


def test_state_file_not_config():
    """⭐ 落盘件**不得**是 `config.json` ✗（守 09-25「挂起不落盘」口径 ✓）"""
    s = _src()
    idx = s.index('GATE_CARD_STATE_PATH =')
    line = s[idx:idx + 200].split('\n')[0]
    assert 'logs' in line and 'config.json' not in line, line


# ══════════════════════════════════════════════════════════════════
# ⑧ ⭐⭐ D11-2 核心新用例：**从 `_post_stream` 那条路触发** ✓
#    ⛔ 不是只看 ①~⑤ 变绿 ✗ —— 那五条走的是 `_notify_cost_blocked`，
#       而用户实际遇到的是**上游失败** ⇒ 走 `_post_stream`（`source='_post_stream'`，每次新代次）
# ══════════════════════════════════════════════════════════════════
def test_post_stream_path_same_day_only_one_card(tmp_path, monkeypatch):
    """⭐ 模拟上游失败（HTTP 402）连续触发 ⇒ 同一天同因**只出一张** ✓

    修前行为（可复现 ✗）：每次都是新代次 ⇒ 同代次门拦不住 ⇒ **弹 N 张** ✗
    修后行为：出口内第二道门（当天同因只一张）接住 ⇒ **只 1 张** ✓
    """
    import desktop_pet

    state = tmp_path / 'gate_card_state.json'
    monkeypatch.setattr(desktop_pet, 'GATE_CARD_STATE_PATH', str(state))
    w = _W(str(state))
    _bind(w)

    d = _diag_for_quota()
    assert getattr(d, 'layer', '') == '额度', \
        '⭐ 夹具必须真的造出"额度"层 ✗（否则测的不是那条路 ✗），实际=%r' % getattr(d, 'layer', None)

    for i in range(4):                       # ⭐ 连续 4 次，每次**新代次** ✓（模拟真实重试 ✓）
        w._gen = 100 + i
        _st = w._notify_failure_card(d, gen=w._card_gen(), source='_post_stream')

    assert len(w._cards) == 1, \
        '⭐ 上游失败路径（_post_stream）同一天同因必须只出一张 ✗ —— 实际 %d 张 ✗' % len(w._cards)
    assert _st == 'deduped', '⭐ 第 4 次应被日门判为 deduped ✓，实际=%r' % _st


def test_post_stream_path_cross_kind_still_emits(tmp_path, monkeypatch):
    """⭐ 反向护栏 ✓：**不同因**在该路径上仍应各出一张 ✓（防"一刀切把该出的压掉" ✗）"""
    import desktop_pet

    state = tmp_path / 'gate_card_state.json'
    monkeypatch.setattr(desktop_pet, 'GATE_CARD_STATE_PATH', str(state))
    w = _W(str(state))
    _bind(w)

    d_quota = _diag_for_quota()                                  # 额度 → balance
    import pet_diagnosis as _d
    d_gate = _d.gate_diag('今日模型调用已花 ¥25.00，达到你设的日上限 ¥20.00')   # 本地闸门 → daily_cost

    w._gen = 200
    w._notify_failure_card(d_quota, gen=w._card_gen(), source='_post_stream')
    w._gen = 201
    w._notify_failure_card(d_gate, gen=w._card_gen(), source='_post_stream')
    assert len(w._cards) == 2, \
        '⭐ 不同因（余额 / 上限）应各出一张 ✓，实际 %d 张 ✗' % len(w._cards)


def test_other_kinds_not_throttled(tmp_path, monkeypatch):
    """⭐ 收严① 的反向护栏 ✓：**非闸门/额度类**（如上游故障）**不受日门** ✗ —— 该即时出 ✓"""
    import desktop_pet

    state = tmp_path / 'gate_card_state.json'
    monkeypatch.setattr(desktop_pet, 'GATE_CARD_STATE_PATH', str(state))
    w = _W(str(state))
    _bind(w)

    import pet_diagnosis as _d
    d = _d.explain_error(Exception('Service Unavailable'), status=503, context='对话')   # → 上游故障
    assert getattr(d, 'layer', '') not in ('本地闸门', '额度'), getattr(d, 'layer', '')

    for i in range(3):
        w._gen = 300 + i
        w._notify_failure_card(d, gen=w._card_gen(), source='_post_stream')
    assert len(w._cards) == 3, \
        '⭐ 非闸门类不该被日门压掉 ✗（该即时出 ✓），实际 %d 张 ✗' % len(w._cards)
