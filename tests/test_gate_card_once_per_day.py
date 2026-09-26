# -*- coding: utf-8 -*-
"""D1 护栏：闸门卡片「同 category 同一天**聊天列表最多一张**」（缺陷 `WX-桌宠-20260926-28`）

现象（Owner 20:50 截图 ✓）：19:47–19:49 两分钟内 **4 张**同类卡片 ✗（余额不足 / 达到上限 交替 ✓）
根因（我方读码定位 ✓ 与微信侧两条线索都不同 ✗）：
  · `_gate_card_day` 原为**纯内存态** ✗ → **重启/多实例即清零** ✗ → 同日同类再出卡 ✗
  · `:1187` 传 `gen=None` ✗ → 闸门卡**刻意绕过同代次去重** ✓ → **全部防护只剩这一个内存标志** ✗
修法：① `_gate_card_day` **落盘** ✓（新状态件 `logs/gate_card_state.json` ✓ 不写 config ✗）
      ② 判定 = **内存态 ＋ 落盘态合并** ✓ → 跨重启/多实例亦只一张 ✓
      ③ 兜底 emit **纳入同一守卫** ✓（当天已有卡 → 不再 emit 兜底行 ✗）
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
    """最小替身：只带 `_notify_cost_blocked` 所需属性 ✓（不打真 GUI ✓）"""

    def __init__(self, state_path, key_day_seed=None):
        self._cards = []
        self._fallbacks = []
        self._notifies = []
        self._suspended = []
        self.COST_BLOCKED_NOTIFY_COOLDOWN = 3600
        self.COST_NOTIFY_MS = 1000
        self.ai_reply_signal = self  # emit → self.emit
        self._state_path = str(state_path)

    # 使落盘/读盘指向临时文件 ✓（不污染真 logs ✓）
    def _gate_card_state_path(self):
        return self._state_path

    def emit(self, txt):
        self._fallbacks.append(txt)

    def _notify(self, txt, ms=None):
        self._notifies.append(txt)

    def _suspend_active_care(self, reason=''):
        self._suspended.append(reason)

    def _atomic_write_json(self, path, obj):
        with io.open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f)

    def _notify_failure_card(self, diag, gen=None, source=''):
        self._cards.append({'diag': diag, 'gen': gen, 'source': source})
        return 'emitted'


def _bind(w):
    """把类里那两个方法绑到替身上 ✓（状态件读写已模块级 ✓ → 替身无需感知 ✓）"""
    import types

    import desktop_pet
    for name in ('_cost_gate_key', '_notify_cost_blocked'):
        setattr(w, name, types.MethodType(getattr(desktop_pet.PetWidget, name), w))


# ── ① 同 category 同一天 → 只渲染一次 ✓ ─────────────────────────────
def test_same_category_same_day_only_one_card(tmp_path, monkeypatch):
    import desktop_pet

    state = tmp_path / 'gate_card_state.json'
    w = _W(str(state))
    _bind(w)
    # 把模块级状态件路径改到 tmp ✓
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
    assert 'disk = _gate_card_day_load()' in s, '⭐ 判定必须合并落盘态 ✗'
    assert 'self._gate_card_day_load' not in s, '⭐ 不得再依赖实例方法 ✗（会让批 A 替身失效 ✗）'


def test_state_file_not_config():
    """⭐ 落盘件**不得**是 `config.json` ✗（守 09-25「挂起不落盘」口径 ✓）"""
    s = _src()
    idx = s.index('GATE_CARD_STATE_PATH =')
    line = s[idx:idx + 200].split('\n')[0]
    assert 'logs' in line and 'config.json' not in line, line
