# -*- coding: utf-8 -*-
"""D11-3 / D11-4 回归

D11-3（金额不一致）：
    · 卡上写「达到你设的日上限 ¥20.00」，但 config 里从来没有这个键 —— 20 是代码默认值
    · 当日花费持续增长、卡上又不写截数时间 ⇒ 三个数看着像统计出错
    修法：governance.cost_state() 单一取数 + 文案区分默认/你设的 + 带「截至 HH:MM」

D11-4（余额 ≠ 后台）：
    · _query_balance_async 原来用当前档案的 key/endpoint，切到中转就查到中转站的余额
    · 余额是 DeepSeek 账户的属性，与当前模型无关 ⇒ 固定查 DeepSeek
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import governance as gov  # noqa: E402


# ==================== D11-3：cost_state 是单一来源 ====================

def test_cost_state_reports_default_limit_honestly():
    """没设过上限时必须标 is_default=True（否则卡上会谎称「你设的」）"""
    st = gov.cost_state()
    assert 'enabled' in st and 'limit' in st and 'used' in st
    assert isinstance(st['is_default'], bool)
    # 本机 config 里没有 cost_limit_daily 这个键 → 必须是默认值
    assert st['is_default'] is True, 'config 里没有 cost_limit_daily，应判为默认值'
    assert st['limit'] == gov.COST_LIMIT_DEFAULT


def test_cost_state_has_timestamp():
    """必须带取数时刻，否则两次提示的三个数无法区分先后"""
    st = gov.cost_state()
    assert st.get('at') and len(st['at']) == 5 and ':' in st['at']


def test_cost_limit_text_distinguishes_default_and_user_set():
    d = {'limit': 20.0, 'is_default': True, 'unlimited': False}
    u = {'limit': 35.5, 'is_default': False, 'unlimited': False}
    off = {'limit': 20.0, 'is_default': True, 'unlimited': True}
    assert '默认上限' in gov.cost_limit_text(d)
    assert '你设的' in gov.cost_limit_text(u)
    assert '未设上限' in gov.cost_limit_text(off)
    # brief 模式不带「可在设置里改」，免得上卡重复两遍引导语
    assert '可在设置里改' not in gov.cost_limit_text(d, brief=True)


def test_check_cost_message_says_default_not_yours():
    """这条是 D11-3 的核心：超限文案不许再谎称「你设的」"""
    real = gov.cost_state
    try:
        gov.cost_state = lambda path=None: {
            'enabled': True, 'limit': 20.0, 'is_default': True,
            'used': 25.3, 'calls': 7, 'at': '22:25', 'unlimited': False}
        ok, why, used = gov.check_cost()
    finally:
        gov.cost_state = real
    assert ok is False
    assert '默认上限' in why, why
    assert '你设的' not in why, why
    assert '22:25' in why, '必须带截数时间，否则三个数无法区分先后'
    assert '7 次' in why, '必须带当日调用次数'


def test_check_cost_message_when_user_really_set_it():
    real = gov.cost_state
    try:
        gov.cost_state = lambda path=None: {
            'enabled': True, 'limit': 20.0, 'is_default': False,
            'used': 21.0, 'calls': 3, 'at': '18:02', 'unlimited': False}
        ok, why, used = gov.check_cost()
    finally:
        gov.cost_state = real
    assert ok is False
    assert '你设的上限' in why, why


def test_check_cost_passes_when_unlimited():
    real = gov.cost_state
    try:
        gov.cost_state = lambda path=None: {
            'enabled': False, 'limit': 20.0, 'is_default': True,
            'used': 999.0, 'calls': 100, 'at': '10:00', 'unlimited': True}
        ok, why, used = gov.check_cost()
    finally:
        gov.cost_state = real
    assert ok is True and why == ''


def test_check_cost_no_duplicate_guidance():
    """文案里「设置 → 用量与计费」只该出现一次"""
    real = gov.cost_state
    try:
        gov.cost_state = lambda path=None: {
            'enabled': True, 'limit': 20.0, 'is_default': True,
            'used': 30.0, 'calls': 2, 'at': '09:00', 'unlimited': False}
        _, why, _ = gov.check_cost()
    finally:
        gov.cost_state = real
    assert why.count('用量与计费') == 1, why


# ==================== D11-4：余额固定查 DeepSeek 账户 ====================

def _make_pet(monkeypatch, endpoint, key='sk-deepseek-test', cfg=None):
    """造一个只带余额相关方法的桩（不构造整个 PetWidget，界面起不来）"""
    import desktop_pet as dp
    holder = {'endpoint': endpoint, 'cfg': cfg or {}}

    class Stub:
        # ⚠ 关键：ai_key 与 _current_api_key() 故意都是**别家**的 key。
        #   原版把 ai_key 设成期望值，于是"代码误调 _current_api_key 并被 except 兜到
        #   ai_key"这条路会静默通过 —— 正是 WX-097 §三 指出的没牙之处。
        ai_key = 'sk-relay-wrong'
        _cfg = property(lambda self: holder['cfg'])

        def _current_endpoint(self):
            return holder['endpoint']

        def _current_api_key(self):
            # 真实宿主里这个方法按当前档案取 key；桩里模拟"当前档案是别家"
            return 'sk-relay-wrong'

        def _api_key_for_field(self, field):
            if field == 'deepseek_api_key':
                return key
            return str((holder['cfg'] or {}).get(field) or '') or key

    s = Stub()
    s._balance_target = dp.PetWidget._balance_target.__get__(s, Stub)
    s.BALANCE_BASE = dp.PetWidget.BALANCE_BASE
    return s, holder


def test_balance_target_fixed_to_deepseek_when_on_deepseek(monkeypatch):
    s, _ = _make_pet(monkeypatch, 'https://api.deepseek.com/chat/completions')
    key, base, note = s._balance_target()
    assert base == 'https://api.deepseek.com'
    assert key
    assert note == '', '本来就是 DeepSeek，不该有额外说明'


def test_balance_target_still_deepseek_when_on_relay(monkeypatch):
    """这是 D11-4 的核心断言：切到中转，余额仍必须查 DeepSeek"""
    s, _ = _make_pet(monkeypatch, 'https://relay.example.com/v1/chat/completions')
    key, base, note = s._balance_target()
    assert base == 'https://api.deepseek.com', '余额不该跟着中转走'
    assert 'relay.example.com' in note, '必须说明当前模型走中转，余额查的是 DeepSeek'


def test_balance_target_key_is_deepseek_field(monkeypatch):
    """即使当前档案指向别家，取 key 也必须取 deepseek_api_key"""
    s, holder = _make_pet(monkeypatch, 'https://api.moonshot.cn/v1/chat/completions',
                          cfg={'kimi_api_key': 'sk-kimi'})
    key, _, _ = s._balance_target()
    assert key == 'sk-deepseek-test', '取错 key 就会查到别家账户'


def test_balance_target_key_never_follows_profile(monkeypatch):
    """key 必须始终取 deepseek_api_key，即使宿主能提供别的 key

    ⛔ 这条是为「没牙」专门补的（WX-097 §三）：
       桩里 `ai_key` 与 `_current_api_key()` 都返回别家 key，
       一旦代码误调它们、又被 except 兜底，拿到就是 'sk-relay-wrong' ⇒ 必红。
    """
    s, _ = _make_pet(monkeypatch, 'https://relay.example.com/v1/chat/completions')
    key, _, _ = s._balance_target()
    assert key == 'sk-deepseek-test', '取到了别家的 key：%r' % key
    assert key != 'sk-relay-wrong'


def test_balance_base_url_override(monkeypatch):
    """中转用户可显式指定余额地址"""
    s, _ = _make_pet(monkeypatch, 'https://api.deepseek.com/chat/completions',
                     cfg={'balance_base_url': 'https://api.deepseek.com'})
    _, base, _ = s._balance_target()
    assert base == 'https://api.deepseek.com'


def test_query_balance_async_uses_target(monkeypatch):
    """端到端：_query_balance_async 传给 query_balance 的必须是 target 的值"""
    import desktop_pet as dp
    import api_stats as api_stats_mod

    captured = {}

    class FakeApi:
        @staticmethod
        def query_balance(key, base, timeout=None):
            captured['key'] = key
            captured['base'] = base
            return {'ok': False, 'error': 'stub'}

    monkeypatch.setattr(api_stats_mod.ApiStats, 'query_balance',
                        staticmethod(FakeApi.query_balance))

    s, _ = _make_pet(monkeypatch, 'https://relay.example.com/v1/chat/completions')
    s._balance_busy = False

    class Sig:
        def emit(self, *a, **k):
            pass

    s.balance_signal = Sig()
    s._query_balance_async = dp.PetWidget._query_balance_async.__get__(s, type(s))
    s._balance_target = dp.PetWidget._balance_target.__get__(s, type(s))

    s._query_balance_async(manual=False)
    # 线程是 daemon，等它跑完
    import time as _t
    for _ in range(50):
        if captured:
            break
        _t.sleep(0.02)
    assert captured.get('base') == 'https://api.deepseek.com', captured
    assert captured.get('key') == 'sk-deepseek-test', captured

# ── 成本闸门：读不到当日花费时必须拦（WX-098 §三，2026-10-22）──────────────
# ⚠ 这 3 条钉的是 `check_cost` 里 `if st.get('used_unknown')` 那一支。
#   补之前实测：把该行改成 `if False:`，本文件 13 条**全绿** —— 最核心的修复
#   反而没有测试钉住（提交主题正是"补护栏的洞"，新修复自己漏在护栏外面）。
#   ⇒ 现在改成 `if False:` 必红。

def test_check_cost_blocks_when_used_unreadable(monkeypatch):
    """读不到当日花费 ⇒ 必须拦住并说清（不能当 0 放行，否则数据源坏掉时闸门隐身）"""
    monkeypatch.setattr(gov, '_cfg',
                        lambda: {'cost_limit_enabled': True, 'cost_limit_daily': 20})
    monkeypatch.setattr(gov, 'today_cost_ex',
                        lambda path=None: (0.0, False, 'FileNotFoundError: api_stats.json'))
    st = gov.cost_state()
    assert st['used_unknown'] is True, '读不出必须标记 used_unknown，不能悄悄当 0'
    ok, why, used = gov.check_cost()
    assert ok is False, '读不出时放行 = 无上限花钱'
    assert '读不到' in why, '文案要说清是读不到，不是花了多少：%r' % why
    assert '用量与计费' in why, '要给去处，不能无声卡死：%r' % why


def test_check_cost_passes_when_truly_zero(monkeypatch):
    """真 0 与读不出必须分开：真没花钱要放行（否则读不到一次就永久卡住）"""
    monkeypatch.setattr(gov, '_cfg',
                        lambda: {'cost_limit_enabled': True, 'cost_limit_daily': 20})
    monkeypatch.setattr(gov, 'today_cost_ex', lambda path=None: (0.0, True, ''))
    st = gov.cost_state()
    assert st['used_unknown'] is False, '真 0 不许被当成读不出'
    ok, why, _used = gov.check_cost()
    assert ok is True and why == ''


def test_check_cost_unlimited_wins_over_used_unknown(monkeypatch):
    """上限关掉时，读不到花费也放行 —— 钉住判断顺序（不设限就没有要守的线）"""
    monkeypatch.setattr(gov, '_cfg',
                        lambda: {'cost_limit_enabled': False, 'cost_limit_daily': 20})
    monkeypatch.setattr(gov, 'today_cost_ex',
                        lambda path=None: (0.0, False, 'boom'))
    assert gov.cost_state()['used_unknown'] is True
    assert gov.check_cost()[0] is True, '不设上限时不该因为读不出而拦住'
