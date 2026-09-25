# -*- coding: utf-8 -*-
"""缺陷 2 护栏：本地闸门**不刷屏**（Owner 2026-09-25 冒烟反馈 ✓）

三条要盯死：
  ① **冷却前不得写提示** ✗（原实现把 `_notify(...)` 写在冷却判断之前 → 每次被拦都写 ✗）
  ② **卡片当天同因只出一张** ✓（原按 reason 原文算 key ✗ + 闸门例外绕过同代次去重 ✗ → 反复出）
  ③ **触顶即挂起主动关心；次日自动恢复** ✓（触发源 = 主动关心定时唤醒 ✓）
另：**审计不限频** 保留 ✓（调用方每次都记 deny ✗）
"""
from __future__ import annotations

import io
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class _Sig:
    def __init__(self):
        self.msgs = []

    def emit(self, t):
        self.msgs.append(t)


class _FakePet:
    """只带 _notify_cost_blocked 所需的最小状态（不实例化整个 GUI ✓）"""
    COST_NOTIFY_MS = 4000
    COST_BLOCKED_NOTIFY_COOLDOWN = 3600
    FAIL_CARD_TAG_KINDS = ()
    UPSTREAM_LAYERS = ()

    def __init__(self, care_on=True):
        self.ai_reply_signal = _Sig()
        self.notes = []
        self.saved = []
        self.active_chat_enabled = care_on
        # 绑定真实方法（不复制逻辑 ✓ 只借宿主方法在替身上跑 ✓）
        from desktop_pet import PetWidget
        self._cost_gate_key = lambda why: PetWidget._cost_gate_key(self, why)
        self._suspend_active_care = lambda reason='': PetWidget._suspend_active_care(self, reason)
        self._resume_active_care_if_new_day = lambda: PetWidget._resume_active_care_if_new_day(self)

    # —— 宿主方法的最小替身 ——
    def _notify(self, text, ms=None):
        self.notes.append(text)

    def _save_cfg_value(self, k, v):
        self.saved.append((k, v))

    def _notify_failure_card(self, diag, *, gen=None, source=''):
        self.ai_reply_signal.emit(diag.cause)
        return 'emitted'

    def _card_gen(self):
        return None


def _call(pet, why):
    from desktop_pet import PetWidget
    PetWidget._notify_cost_blocked(pet, why)


def test_notify_gated_by_cooldown():
    """① 连续 5 次同因超限 → **状态条提示 ≤1 条** ✓（原为 5 条 ✗）"""
    p = _FakePet()
    for _ in range(5):
        _call(p, '今日已花 ¥25.00，达到上限 ¥20.00')
    assert len(p.notes) <= 1, f'状态条刷屏 ✗ 实际 {len(p.notes)} 条：{p.notes}'


def test_card_once_per_day_same_reason():
    """② 同因同天 → **卡片 ≤1 张** ✓（金额/措辞变化也算同因 ✓）"""
    p = _FakePet()
    _call(p, '今日已花 ¥25.00，达到上限 ¥20.00')
    _call(p, '今日已花 ¥21.00，达到上限 ¥20.00')     # 金额不同 → 仍同类 ✓
    _call(p, '今日已花 ¥30.00，达到上限 ¥20.00')
    assert len(p.ai_reply_signal.msgs) == 1, f'同因同天出了 {len(p.ai_reply_signal.msgs)} 张卡 ✗'


def test_two_reason_kinds_two_cards():
    """② 附：**不同类**（日上限 / 余额）各出 1 张 ✓（同日合计 2 张 ✓）"""
    p = _FakePet()
    _call(p, '今日已花 ¥25.00，达到上限 ¥20.00')
    _call(p, '账户余额不足 ¥1.00')
    assert len(p.ai_reply_signal.msgs) == 2, p.ai_reply_signal.msgs


def test_gate_key_is_categorical():
    """② key 按**类**算 ✓（不按原文 ✗）"""
    from desktop_pet import PetWidget
    assert PetWidget._cost_gate_key(_FakePet(), '今日已花 ¥25.00，达到上限 ¥20.00') == 'daily_cost'
    assert PetWidget._cost_gate_key(_FakePet(), '账户余额不足 ¥1.00') == 'balance'
    assert PetWidget._cost_gate_key(_FakePet(), '别的什么') == 'other'


def test_suspend_active_care_on_gate():
    """③ 触顶 → 主动关心**被挂起** ✓（**只改内存、不写 config** ✓ 闸门判定零副作用 ✗）"""
    p = _FakePet(care_on=True)
    _call(p, '今日已花 ¥25.00，达到上限 ¥20.00')
    assert p.active_chat_enabled is False, '触顶后未挂起主动关心 ✗'
    assert p.saved == [], f'闸门判定不得写 config ✗ 实际写了 {p.saved}'
    assert getattr(p, '_care_suspended_date', '') == time.strftime('%Y-%m-%d')


def test_auto_resume_next_day():
    """③ 次日自动恢复 ✓（只恢复被我们挂起的 ✓ 仍不写 config ✓）"""
    from desktop_pet import PetWidget
    p = _FakePet(care_on=False)
    p._care_suspended_date = '2026-01-01'          # 昨天的挂起标记 ✓
    assert PetWidget._resume_active_care_if_new_day(p) is True
    assert p.active_chat_enabled is True, '跨天未恢复主动关心 ✗'
    assert p.saved == [], f'恢复同样不得写 config ✗ 实际 {p.saved}'
    assert p._care_suspended_date == '', '恢复后应清空标记 ✓'


def test_no_resume_same_day():
    """③ 当天不恢复 ✓（否则等于没挂起 ✗）"""
    from desktop_pet import PetWidget
    p = _FakePet(care_on=False)
    p._care_suspended_date = time.strftime('%Y-%m-%d')
    assert PetWidget._resume_active_care_if_new_day(p) is False
    assert p.active_chat_enabled is False


def test_user_off_is_not_auto_resumed():
    """③ 用户自己关的**不被自动开回** ✗（没有挂起标记 → 不动 ✓）"""
    from desktop_pet import PetWidget
    p = _FakePet(care_on=False)
    assert PetWidget._resume_active_care_if_new_day(p) is False
    assert p.active_chat_enabled is False


def test_audit_still_unthrottled_and_notify_after_cooldown_in_source():
    """① 源码护栏：`_notify` 必须在冷却**之后**；审计不限频保留 ✓"""
    src = io.open(ROOT / 'desktop_pet.py', encoding='utf-8').read()
    i_fn = src.index('def _notify_cost_blocked')
    body = src[i_fn:i_fn + 2600]
    i_cooldown = body.index('COST_BLOCKED_NOTIFY_COOLDOWN')
    i_notify = body.index("self._notify('（成本闸门")
    assert i_cooldown < i_notify, '状态条提示仍在冷却之前 ✗（缺陷 2 主因复发）'
    # 审计不限频：调用方每次都记 deny ✓
    assert "_gov_c.log_event('deny', 'ai.calls', '模型调用'" in src, '审计拒绝记录被去掉 ✗'
