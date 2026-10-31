# -*- coding: utf-8 -*-
"""好感度减分（机制层）

口径来源（均已落文件，非我臆想）：
    PC-桌宠-20261031-296 §7.4   Owner 拍：地板设「熟悉」
    PC-桌宠-20261031-298 §4.6   必须有一处**显式引用 STAGE_FLOOR**，
                                不能靠「碰巧 80 恰好是熟悉的下限」
    PC-桌宠-20261031-298 §4.7   Owner 拍：**不做开关**（否则体会不到真实效果）
                                速率限制：单次 ≤ −2、每日累计 ≤ −10、
                                保留 history_max、每次减分写 before/after

本文件锁机制层；**触发事件（什么时候真减分）不在本文件**，属业务决策。

A. 单次上限、每日上限、地板 三道闸都真的拦
B. 地板是从 STAGE_FLOOR **反查**来的 —— 改 STAGE_FLOOR 地板跟着变
   （这是 298 号件点名的「证行为不证常量」）
C. history_max 保留历史最高，减分不抹掉
D. 每次减分写 before/after 审计
E. 误用防护：正数/零/None 被拒绝，不偷偷当"加 0 分"
F. 减分不影响原有涨分路径
"""
import json
import os
import sys
import tempfile

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import affection_engine as ae  # noqa: E402


@pytest.fixture
def eng(tmp_path):
    return ae.AffectionEngine(str(tmp_path / 'affection.json'))


def _set(eng, role='flash', **kw):
    """直接改状态（测试夹具）"""
    with eng._lock:
        st = eng._state(role)
        st.update(kw)
        eng._save()


# ---------- A. 三道闸 ----------
def test_single_penalty_capped(eng):
    _set(eng, affection=150)
    r = eng.apply_penalty('flash', 'test', -9)      # 想减 9
    assert r['blocked'] is False
    assert r['affection_after'] >= 150 - ae.PENALTY_MAX_SINGLE, \
        '单次减了 %d 分，超过上限 %d' % (150 - r['affection_after'], ae.PENALTY_MAX_SINGLE)


def test_daily_total_capped(eng):
    _set(eng, affection=180)
    for _ in range(20):
        eng.apply_penalty('flash', 'test', -2)
    with eng._lock:
        st = eng._state('flash')
        aff = st['affection']
    assert 180 - aff <= ae.PENALTY_MAX_DAILY, \
        '一天减了 %d 分，超过每日上限 %d' % (180 - aff, ae.PENALTY_MAX_DAILY)


def test_cannot_go_below_floor(eng):
    _set(eng, affection=ae.stage_floor_value() + 1)
    for _ in range(200):        # 狂减
        eng.apply_penalty('flash', 'test', -2)
    with eng._lock:
        aff = eng._state('flash')['affection']
    assert aff >= ae.stage_floor_value(), '好感度跌破了地板：%d < %d' % (
        aff, ae.stage_floor_value())


def test_floor_blocks_with_reason(eng):
    _set(eng, affection=ae.stage_floor_value())
    r = eng.apply_penalty('flash', 'test', -2)
    assert r['blocked'] is True
    assert r.get('reason') == 'floor', '地板拦截应说明原因，实际：%r' % (r,)


# ---------- B. 地板必须真的读 STAGE_FLOOR ----------
def test_floor_is_derived_from_stage_floor_constant(monkeypatch):
    """298 号件点名要求：不能靠「碰巧 80 是熟悉的下限」

    判据：改 STAGE_FLOOR 的值，stage_floor_value() 必须跟着变。
    如果实现里写死 80，这条会红。
    """
    assert ae.stage_floor_value() == 80, '「熟悉」的下限应为 80'
    monkeypatch.setattr(ae, 'STAGE_FLOOR', '亲密')
    assert ae.stage_floor_value() == 110, \
        '改了 STAGE_FLOOR 地板没跟着变 ⇒ 实现是硬编码的，没真读常量'
    monkeypatch.setattr(ae, 'STAGE_FLOOR', '初见')
    assert ae.stage_floor_value() == 0


def test_floor_really_used_in_penalty(monkeypatch):
    """不只看函数返回，还要看 apply_penalty 真的用它"""
    eng = ae.AffectionEngine(os.path.join(tempfile.mkdtemp(), 'a.json'))
    monkeypatch.setattr(ae, 'STAGE_FLOOR', '亲密')      # 地板抬到 110
    _set(eng, affection=115)
    for _ in range(100):
        eng.apply_penalty('flash', 'test', -2)
    with eng._lock:
        aff = eng._state('flash')['affection']
    assert aff >= 110, '地板抬到 110 后仍跌到 %d ⇒ apply_penalty 没用新地板' % aff


# ---------- C. history_max ----------
def test_history_max_preserved(eng):
    _set(eng, affection=200)
    eng.apply_penalty('flash', 'test', -2)
    with eng._lock:
        st = eng._state('flash')
    assert st.get('history_max') == 200, 'history_max 没保住：%r' % (st.get('history_max'),)


def test_history_max_updates_on_gain(eng):
    _set(eng, affection=100, history_max=150)
    with eng._lock:
        st = eng._state('flash')
        st['affection'] = 180
        eng._save()
    eng.apply_penalty('flash', 'test', -2)     # 触发一次保存路径
    with eng._lock:
        st = eng._state('flash')
    assert st.get('history_max') >= 180, '涨过之后 history_max 应更新：%r' % (st.get('history_max'),)


# ---------- D. 审计 ----------
def test_penalty_writes_before_after(eng):
    _set(eng, affection=150)
    r = eng.apply_penalty('flash', '原因是测试', -2)
    assert 'affection_before' in r and 'affection_after' in r, '返回值缺 before/after：%r' % (r,)
    assert r['affection_before'] - r['affection_after'] > 0
    with eng._lock:
        st = eng._state('flash')
        log = st.get('penalty_log') or []
    assert log, '没写审计日志'
    last = log[-1]
    for f in ('at', 'reason', 'before', 'after'):
        assert f in last, '审计缺字段 %s：%r' % (f, last)


def test_penalty_log_is_capped(eng):
    """审计日志不能无限长（这库要长期跑）"""
    _set(eng, affection=200)
    for i in range(ae.PENALTY_LOG_KEEP + 30):
        eng.apply_penalty('flash', 'r%d' % i, -1)
        # 绕过每日上限，专测日志长度
        with eng._lock:
            st = eng._state('flash')
            st['penalty_daily'] = {}
            st['affection'] = 200
            eng._save()
    with eng._lock:
        log = eng._state('flash').get('penalty_log') or []
    assert len(log) <= ae.PENALTY_LOG_KEEP, '审计日志 %d 条，超过上限 %d' % (
        len(log), ae.PENALTY_LOG_KEEP)


# ---------- E. 误用防护 ----------
@pytest.mark.parametrize('bad', [0, 5, 2.5, None, 'abc'])
def test_rejects_non_negative_amount(eng, bad):
    _set(eng, affection=150)
    r = eng.apply_penalty('flash', 'test', bad)
    assert r['blocked'] is True, 'amount=%r 应被拒绝，实际 %r' % (bad, r)
    with eng._lock:
        assert _state_aff(eng) == 150, '被拒绝却改了分数'


def _state_aff(eng):
    return eng._state('flash')['affection']


# ---------- F. 不影响涨分 ----------
def test_gain_still_works(eng):
    _set(eng, affection=100)
    before = _state_aff(eng)
    r = eng.trigger('flash', 'task_done')
    assert r['blocked'] is False
    assert _state_aff(eng) > before


def test_penalty_and_gain_coexist(eng):
    _set(eng, affection=120)
    eng.apply_penalty('flash', 'test', -2)
    mid = _state_aff(eng)
    eng.trigger('flash', 'task_done')
    assert _state_aff(eng) > mid


# ---------- 真实数据只读检查（本轮不碰线上文件）----------
def test_does_not_touch_real_affection_file():
    """本测试文件用 tmp_path，断言没意外写到仓库里的 affection.json"""
    real = os.path.join(BASE, 'affection.json')
    if not os.path.exists(real):
        pytest.skip('无真实 affection.json')
    before = os.stat(real).st_mtime_ns
    eng = ae.AffectionEngine(os.path.join(tempfile.mkdtemp(), 'x.json'))
    eng.apply_penalty('flash', 'test', -2)
    assert os.stat(real).st_mtime_ns == before, '测试写到了真实 affection.json'
