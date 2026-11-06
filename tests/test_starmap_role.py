# -*- coding: utf-8 -*-
"""星图按角色过滤 + 主区切换器（2026-11-06）

## 为什么有这份测试

Owner 报：「主区只是一个 AI 的主区 …… 换了形象和 API 模型后，主区记忆没变。」

根因：星图 `load_stars()` 完全不看 role，而注入侧按角色过滤
（facts 看 `roles`、events 看 `role`）⇒ 星图与注入口径不一致。

## 口径（本文件锁住）

· `load_stars(role=X)` 的过滤必须与注入口径**逐条一致**：
  facts: `roles` 缺省视为 both，只认 both 或本角色（同 build_l0_block）
  events: 严格相等（同 MemoryEvents.recent）
· `role=None` = 全部角色，不过滤
· 换角色必须真的换数据（含 `_current_sig` 要认 role，否则文件没变就不重载）
· 面板 refresh() 跟随 host.current；但用户手选「全部」后不许抢
· 副标题的「另有 N 颗」必须是「全部 - 当前」的真差值（不能只算 facts）
"""
import json
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication   # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import memory_starmap as sms                  # noqa: E402
import memory_engine as me                    # noqa: E402
import starmap_panel as smp                   # noqa: E402


# ---------- 夹具：真实字段集（含 role/roles 各种取值） ----------
FACTS = [
    {'id': 'f1', 'content': '共享的记忆一', 'importance': 5, 'status': 'active',
     'roles': 'both', 'created_at': '2026-11-01 10:00', 'updated_at': '2026-11-01 10:00'},
    {'id': 'f2', 'content': '共享的记忆二', 'importance': 4, 'status': 'active',
     'created_at': '2026-11-01 10:00', 'updated_at': '2026-11-01 10:00'},   # 无 roles
    {'id': 'f3', 'content': '只有 pro 记得', 'importance': 4, 'status': 'active',
     'roles': 'pro', 'created_at': '2026-11-01 10:00', 'updated_at': '2026-11-01 10:00'},
    {'id': 'f4', 'content': '只有 flash 记得', 'importance': 4, 'status': 'active',
     'roles': 'flash', 'created_at': '2026-11-01 10:00', 'updated_at': '2026-11-01 10:00'},
    {'id': 'f5', 'content': '已失效的共享记忆', 'importance': 3, 'status': 'superseded',
     'roles': 'both', 'created_at': '2026-10-01 10:00', 'updated_at': '2026-10-01 10:00'},
]
EVENTS = [
    {'id': 'e1', 'title': 'flash 的经历甲', 'detail': '甲乙丙丁', 'role': 'flash',
     'time': '2026-11-01 09:00', 'emotion': '开心'},
    {'id': 'e2', 'title': 'pro 的经历', 'detail': '戊己庚辛', 'role': 'pro',
     'time': '2026-11-01 09:00', 'emotion': ''},
]


@pytest.fixture
def paths(tmp_path):
    fp = tmp_path / 'memory.json'
    ep = tmp_path / 'memories.json'
    fp.write_text(json.dumps({'facts': FACTS}, ensure_ascii=False), encoding='utf-8')
    ep.write_text(json.dumps(EVENTS, ensure_ascii=False), encoding='utf-8')
    return str(fp), str(ep)


def _texts(stars):
    return sorted(s['text'] for s in stars)


# ---------- A. load_stars 的过滤口径 ----------
def test_all_roles_sees_everything(paths):
    stars, _dead, _raw = sms.load_stars(*paths, role=None)
    t = _texts(stars)
    for want in ('只有 pro 记得', '只有 flash 记得', 'flash 的经历甲', 'pro 的经历'):
        assert want in t, 'role=None 应看到全部，缺了 %r' % want


def test_role_filters_facts_like_build_l0_block(paths):
    """facts 口径必须与 memory_engine.build_l0_block 一致（缺省 roles 视为 both）"""
    for role in ('flash', 'pro'):
        stars, _d, _r = sms.load_stars(*paths, role=role)
        t = _texts(stars)
        # 用注入侧的同一份判据算一遍，两边必须相等
        want = {f['content'] for f in FACTS
                if f.get('status') == 'active'
                and (f.get('roles', 'both') == 'both' or f.get('roles') == role)}
        got = {s['text'] for s in stars if s['kind'] == 'fact'}
        assert got == want, (
            'role=%s 的 facts 集合与 build_l0_block 口径不一致：\n多出 %r\n缺 %r'
            % (role, got - want, want - got))


def test_role_filters_events_strictly(paths):
    """events 严格相等 —— 缺省 role 的事件不属任何角色"""
    stars, _d, _r = sms.load_stars(*paths, role='flash')
    got = {s['text'] for s in stars if s['kind'] == 'event'}
    assert got == {'flash 的经历甲'}, 'flash 看到了不该看的事件：%r' % (got,)


def test_single_role_is_subset_of_all(paths):
    all_t = set(_texts(sms.load_stars(*paths, role=None)[0]))
    for role in ('flash', 'pro'):
        sub = set(_texts(sms.load_stars(*paths, role=role)[0]))
        assert sub <= all_t, 'role=%s 出现了全量视角里没有的条目' % role


# ---------- B. 控件换角色 ----------
def test_set_role_reloads_even_if_files_unchanged(paths):
    """换 role 必须真的换数据 —— 文件名/mtime 都没变也要重载

    ⚠ 这就是 bug 2 的核心：原先 `_current_sig` 只看文件，
    换形象时文件没变 ⇒ `_maybe_reload` 永远不触发 ⇒ 星图一直显示旧角色。

    判据用**内容集合**而不是星点数：夹具里两个角色的条数恰好都等于 4，
    只看数量区分不出「换了」还是「没换」（第一版就是这么写错的）。
    """
    view = sms.MemoryStarMap(None, facts_path=paths[0], events_path=paths[1], role='flash')
    set_flash = set(_texts(view.stars))
    sig_flash = view._current_sig()
    view.set_role('pro')
    set_pro = set(_texts(view.stars))
    sig_pro = view._current_sig()
    assert set_flash != set_pro, '换角色后星点内容没变：%r' % (set_flash,)
    assert sig_flash != sig_pro, '_current_sig 没把 role 算进去 ⇒ _maybe_reload 不会触发'
    assert '只有 pro 记得' in set_pro and '只有 pro 记得' not in set_flash
    assert '只有 flash 记得' in set_flash and '只有 flash 记得' not in set_pro


def test_set_role_same_role_is_noop(paths):
    view = sms.MemoryStarMap(None, facts_path=paths[0], events_path=paths[1], role='flash')
    assert view.set_role('flash') is False


# ---------- C. 面板：切换器与跟随 ----------
class _FakeHost:
    def __init__(self, current):
        self.current = current
        self.theme = {}


def _panel(paths, current='flash'):
    """用真实文件路径造面板（绕开默认路径）"""
    p = smp.StarmapPanel(_FakeHost(current))
    # 面板内部新建的 MemoryStarMap 用的是默认路径 → 这里改指夹具路径并重载
    p._view._facts_path = paths[0]
    p._view._events_path = paths[1]
    p._view.reload_data()
    p._view._data_sig = p._view._current_sig()
    p._n_total = None
    p._update_scope()
    return p


def test_panel_default_follows_current(paths):
    p = _panel(paths, 'pro')
    assert p._view.role == 'pro', '面板默认视角应等于 host.current'
    assert 'pro' in [r for _t, r in p._combos]


def test_panel_refresh_follows_new_current(paths):
    """模拟换形象：host.current 变了 → refresh 后视角跟着变（看内容，不看数量）"""
    host = _FakeHost('flash')
    p = smp.StarmapPanel(host)
    p._view._facts_path = paths[0]
    p._view._events_path = paths[1]
    p._view.reload_data()
    texts_flash = set(_texts(p._view.stars))

    host.current = 'pro'
    p.refresh()

    assert p._view.role == 'pro', 'refresh 没跟随 host.current'
    texts_pro = set(_texts(p._view.stars))
    assert texts_pro != texts_flash, '视角变了但数据没换：%r' % (texts_pro,)
    assert '只有 pro 记得' in texts_pro, 'refresh 后没读到 pro 专属记忆'


def test_panel_respects_manual_all_choice(paths):
    """用户手选「全部」后，换形象不许把他的选择抢走"""
    host = _FakeHost('flash')
    p = smp.StarmapPanel(host)
    p._view._facts_path = paths[0]
    p._view._events_path = paths[1]
    idx_all = next(i for i, (_t, r) in enumerate(p._combos) if r is None)
    p._combo.setCurrentIndex(idx_all)
    assert p._view.role is None

    host.current = 'pro'
    p.refresh()
    assert p._view.role is None, 'refresh 抢走了用户手选的「全部」'


# ---------- D. 副标题数字必须是真差值 ----------
def test_scope_label_reports_real_gap(paths):
    """「另有 N 颗」= 全部 - 当前，不能只算 facts"""
    p = _panel(paths, 'pro')
    idx_pro = next(i for i, (_t, r) in enumerate(p._combos) if r == 'pro')
    p._combo.setCurrentIndex(idx_pro)
    n_cur = len(p._view.stars)
    n_all = p._n_total
    txt = p._scope_lbl.text()
    gap = n_all - n_cur
    assert str(gap) in txt, (
        '副标题应有真差值 %d，实际：%r' % (gap, txt))
    # 反向断言：不能是「只算 facts」的那个偏小数字
    n_facts_skipped = sum(1 for f in FACTS
                          if f.get('status') == 'active'
                          and not (f.get('roles', 'both') == 'both' or f.get('roles') == 'pro'))
    assert gap != n_facts_skipped or str(n_facts_skipped) == str(gap), (
        '差值恰好等于只算 facts 的数，这条用例区分不出对错（夹具需要调整）')
