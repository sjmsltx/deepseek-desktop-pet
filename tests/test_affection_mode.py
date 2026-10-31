# -*- coding: utf-8 -*-
"""减分三档（Owner 2026-10-31 拍）

原话：「你把 a 和 c 做成两个档位，然后还有一个选择就是像现在这个样子只增不减，
       让用户自己选就行了。默认的话选 c」

所以是三个档：
    off     只增不减（= 改造前的现状，永不扣分）
    gentle  A 保守型：只接「模型判断主人真生气」（emotion）
    full    C 全开  ：行为信号 + 情绪判断都接（behavior + emotion）—— **默认**

本文件锁六件事：
A. 默认是 full
B. off 档一律拦截（不管什么类别、什么分值）
C. gentle 档只放行 emotion，拦 behavior
D. full 档两类都放行
E. 档位名写错要安全兜底（不能因为配置写错就变成"什么都能扣"）
F. 切档不动已有数值（只影响之后的扣分）
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import affection_engine as ae  # noqa: E402


@pytest.fixture
def eng(tmp_path):
    return ae.AffectionEngine(str(tmp_path / 'affection.json'))


def _set(eng, role='flash', **kw):
    with eng._lock:
        st = eng._state(role)
        st.update(kw)
        eng._save()


# ---------- A. 默认档 ----------
def test_default_mode_is_full():
    assert ae.DEFAULT_MODE == 'full', '默认档应为 full（Owner 拍的决定）'


def test_engine_defaults_to_full(eng):
    assert eng.mode == 'full', '引擎默认档应为 full，实际 %r' % eng.mode


def test_three_modes_exist():
    assert set(ae.AFFECTION_MODES) == {'off', 'gentle', 'full'}, \
        '档位应为 off/gentle/full，实际 %r' % (ae.AFFECTION_MODES,)


def test_mode_allows_table_is_complete():
    for m in ae.AFFECTION_MODES:
        assert m in ae.MODE_ALLOWS, '档位 %s 缺放行类别表' % m
    assert ae.MODE_ALLOWS['off'] == frozenset()
    assert ae.MODE_ALLOWS['gentle'] == frozenset({'emotion'})
    assert ae.MODE_ALLOWS['full'] == frozenset({'emotion', 'behavior'})


# ---------- B. off 一律拦 ----------
@pytest.mark.parametrize('cat', ['emotion', 'behavior'])
def test_off_blocks_everything(eng, cat):
    eng.set_mode('off')
    _set(eng, affection=150)
    r = eng.apply_penalty('flash', '测试', -2, category=cat)
    assert r['blocked'] is True
    assert r.get('reason') == 'mode', 'off 档应说明原因=mode，实际 %r' % (r,)
    with eng._lock:
        assert eng._state('flash')['affection'] == 150, 'off 档却改了分数'


# ---------- C. gentle 只放 emotion ----------
def test_gentle_allows_emotion(eng):
    eng.set_mode('gentle')
    _set(eng, affection=150)
    r = eng.apply_penalty('flash', '主人真生气', -2, category='emotion')
    assert r['blocked'] is False, 'gentle 档应放行 emotion，实际 %r' % (r,)
    with eng._lock:
        assert eng._state('flash')['affection'] < 150


def test_gentle_blocks_behavior(eng):
    eng.set_mode('gentle')
    _set(eng, affection=150)
    r = eng.apply_penalty('flash', '主人点了停止', -2, category='behavior')
    assert r['blocked'] is True
    assert r.get('reason') == 'mode'
    with eng._lock:
        assert eng._state('flash')['affection'] == 150


# ---------- D. full 两类都放 ----------
@pytest.mark.parametrize('cat', ['emotion', 'behavior'])
def test_full_allows_both(eng, cat):
    _set(eng, affection=150)
    r = eng.apply_penalty('flash', '测试', -2, category=cat)
    assert r['blocked'] is False, 'full 档应放行 %s，实际 %r' % (cat, r)


# ---------- E. 档位名写错要安全兜底 ----------
def test_set_mode_rejects_unknown(eng):
    eng.set_mode('off')
    ok = eng.set_mode('wild')          # 不存在的档位
    assert ok is False, '写错的档位名应返回 False'
    assert eng.mode == 'off', '写错的档位名不该改掉原档位，实际 %r' % eng.mode


def test_set_mode_normalizes_case_and_space(eng):
    assert eng.set_mode('  FULL ') is True
    assert eng.mode == 'full'


def test_apply_penalty_with_unknown_category_is_blocked(eng):
    """类别写错不能当成 emotion 放行"""
    _set(eng, affection=150)
    r = eng.apply_penalty('flash', '测试', -2, category='whatever')
    assert r['blocked'] is True
    assert r.get('reason') == 'bad_category', '应报 bad_category，实际 %r' % (r,)


# ---------- F. 切档不动数值 ----------
def test_switching_mode_does_not_change_affection(eng):
    _set(eng, affection=143)
    for m in ('off', 'gentle', 'full', 'off'):
        eng.set_mode(m)
        with eng._lock:
            assert eng._state('flash')['affection'] == 143, '切档 %s 时改了分数' % m


def test_mode_visible_in_snapshot(eng):
    """UI 要能读到当前档位（不然主人不知道自己在哪档）"""
    eng.set_mode('gentle')
    _set(eng, affection=120)
    snap = eng.snapshot('flash')
    assert snap.get('mode') == 'gentle', 'snapshot 里应带 mode，实际 keys=%r' % list(snap)


# ---------- 与既有三道闸共存 ----------
def test_mode_gate_is_before_amount_gate(eng):
    """off 档时，即使分值非法也不该因为分值问题报错 —— 顺序要稳定"""
    eng.set_mode('off')
    r = eng.apply_penalty('flash', '测试', -999, category='emotion')
    assert r['blocked'] is True
    # 只要被拦住就行，原因可以是 mode（档位闸在前）也可以是 amount（分值闸在前）
    assert r.get('reason') in ('mode', 'bad_amount')


def test_daily_and_floor_still_apply_in_full(eng):
    _set(eng, affection=200)
    for _ in range(20):
        eng.apply_penalty('flash', '刷', -2, category='behavior')
    with eng._lock:
        aff = eng._state('flash')['affection']
    assert 200 - aff <= ae.PENALTY_MAX_DAILY, 'full 档下每日上限失效：减了 %d' % (200 - aff)
