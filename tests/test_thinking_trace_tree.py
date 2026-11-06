# -*- coding: utf-8 -*-
"""思考过程树形折叠（2026-11-06）

## 为什么有这份测试

Owner 要求：「思考过程能不能像你这样自动折叠，分为父子过程，还可以继续下分，
一个父过程完了，其下的子过程自动收起。」

`reasoning_content` 是一整段无结构文本，模型不给层级 ⇒ 用 agent 循环的**轮次**
做父过程、**工具调用**做子过程（`round_begin_signal` / `tool_trace_signal`）。

## 口径（本文件锁住）

· 每轮推理落在自己的节点（旧实现把两轮粘成一段：「轮1思考：…轮2思考：…」）
· 工具调用挂在**当轮**下，可继续下分
· 流式中：根展开、当前轮展开（要能看到实时推理）
· 该轮完成 → 该轮收起；整轮对话完成 → 根收起（子节点随之不可见）
· 收起后 `full_text()` 仍能读到全部思考（信息不丢，只是折叠）
· `ui_probe()['thinking_text']` 仍可读（兼容既有探针）
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication, QLabel   # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp     # noqa: E402
import chat_trace as ct      # noqa: E402


# ---------- A. chat_trace 单元 ----------
def _tree():
    t = ct.TraceTree()
    t.show()
    _app.processEvents()
    return t


def test_root_expanded_by_default():
    t = _tree()
    assert t.expanded is True, '根节点默认应展开（否则流式中看不到推理）'


def test_active_round_expanded_finished_round_collapsed():
    """进行中的轮展开（看得到实时推理），完成后收起"""
    t = _tree()
    r = t.begin_round(1)
    assert r.expanded is True, '刚开始的轮应展开'
    r.append_text('推理中')
    assert r.text() == '推理中'
    t.end_round(1, seconds=1.2)
    assert r.expanded is False, '轮完成后应收起'
    assert '1.2s' in r.summary


def test_parent_collapsed_hides_children():
    """父收起 → 子不可见（这就是「其下子过程自动收起」）"""
    t = _tree()
    r = t.begin_round(1)
    tool = r.add_child('调用 t1')
    tool.set_text('结果')
    _app.processEvents()
    assert tool.isVisible() is True, '父展开时子应可见'
    t.set_expanded(False)
    _app.processEvents()
    assert r.isVisible() is False, '根收起后轮节点应不可见'
    assert tool.isVisible() is False, '根收起后子节点应不可见'


def test_can_nest_deeper():
    """可以继续下分（三层以上）"""
    t = _tree()
    r = t.begin_round(1)
    a = r.add_child('调用 t1')
    b = a.add_child('结果详情')
    b.set_text('temperature=24')
    chain = [b, a, r]
    assert [n.title for n in chain] == ['结果详情', '调用 t1', '第 1 轮推理']
    assert sum(1 for _ in t.root.iter_children()) == 4


def test_finish_collapses_root_and_keeps_full_text():
    t = _tree()
    r1 = t.begin_round(1)
    r1.append_text('轮1推理')
    t.end_round(1)
    r2 = t.begin_round(2)
    r2.append_text('轮2推理')
    t.end_round(2)
    t.finish()
    _app.processEvents()
    assert t.expanded is False, 'finish 后根应收起'
    assert '2 轮' in t.root.summary
    full = t.full_text()
    assert '轮1推理' in full and '轮2推理' in full, '收起后全文仍应可读'
    assert t.visible_text() == '', '根收起时可见文本应为空'


def test_two_trees_independent():
    a, b = _tree(), _tree()
    a.begin_round(1).append_text('A')
    b.begin_round(1).append_text('B')
    a.finish()
    assert a.expanded is False and b.expanded is True


# ---------- B. 端到端：真实 _ai_worker 两轮工具调用 ----------
class _FakeStream:
    def __init__(self):
        self.round = 0

    def __call__(self, key, data, **kw):
        self.round += 1
        if self.round == 1:
            yield ('reasoning', '轮1思考')
            yield ('content', '轮1正文')
            yield ('done', {'content': '轮1正文',
                            'tool_calls': [{'id': 'c1', 'type': 'function',
                                            'function': {'name': 'query_weather',
                                                         'arguments': '{}'}}],
                            'reasoning_content': '轮1思考'})
            return
        yield ('reasoning', '轮2思考')
        yield ('content', '轮2正文')
        yield ('done', {'content': '轮2正文', 'tool_calls': None,
                        'reasoning_content': '轮2思考'})


def _pet():
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._save_chat_memory = lambda *a, **k: True
    p._summarize_old = lambda *a, **k: None
    p._load_ai_config = lambda *a, **k: None
    p._current_api_key = lambda: 'sk-test'
    p._request_endpoint = lambda: 'http://127.0.0.1:1/chat'
    p._execute_tool = lambda name, args: '工具结果'
    p._maybe_extract_memory = lambda: None
    p._speak_reply = lambda *a, **k: None
    p._record_api_usage = lambda *a, **k: None
    p._handle_affection = lambda *a, **k: None
    p._apply_emotion = lambda *a, **k: None
    p.ai_enabled = True
    p.chat_history_msgs = []
    p.show()
    _app.processEvents()
    return p


@pytest.fixture
def two_round_pet(monkeypatch):
    p = _pet()
    monkeypatch.setattr(dp, 'stream_chat_completions', _FakeStream())
    p._ai_worker('查天气')
    _app.processEvents()
    return p


def test_tree_has_one_node_per_round(two_round_pet):
    t = two_round_pet._trace_tree
    assert t is not None, '没有建出思考树'
    assert len(t.rounds()) == 2, '应为 2 轮，实际 %d' % len(t.rounds())


def test_each_round_reasoning_separate(two_round_pet):
    """两轮推理必须分开 —— 旧实现粘成「轮1思考：…轮2思考：…」"""
    t = two_round_pet._trace_tree
    r1, r2 = t.rounds()
    assert '轮1思考' in r1.text() and '轮2思考' not in r1.text()
    assert '轮2思考' in r2.text() and '轮1思考' not in r2.text()


def test_tool_hangs_under_its_round(two_round_pet):
    t = two_round_pet._trace_tree
    r1, r2 = t.rounds()
    assert r1.child_count() == 1, '第 1 轮下应有 1 个工具子节点'
    assert r2.child_count() == 0, '第 2 轮没有工具'
    child = r1.children[0]
    assert 'query_weather' in child.title
    assert '工具结果' in child.text()


def test_auto_collapsed_after_finish(two_round_pet):
    p = two_round_pet
    t = p._trace_tree
    assert t.expanded is False, '整轮对话结束后根应收起'
    for i, r in enumerate(t.rounds(), 1):
        assert r.isVisible() is False, '第 %d 轮应不可见' % i
    # 外部按钮文字要同步（否则显示 ▼ 但实际收起）
    assert p._thinking_toggle.text().endswith('▶'), (
        '按钮文字 %r 与实际收起状态不一致' % p._thinking_toggle.text())
    # 收起后要能看到摘要（「2 轮 · 1 次工具」）—— 截图实测这一条曾缺失
    assert '2 轮' in p._think_summary_lbl.text(), (
        '收起后摘要没显示（%r）' % p._think_summary_lbl.text())


def test_toggle_button_syncs_both_ways(two_round_pet):
    """点折叠按钮：树状态、按钮箭头、摘要三边必须一致

    截图实测过两种不一致：
      收起后按钮还显示 ▼（点一下反而更收起）、摘要不显示
    """
    p = two_round_pet
    t = p._trace_tree
    btn = p._thinking_toggle

    # 收起态 → 点一下展开
    assert t.expanded is False
    btn.click()
    _app.processEvents()
    assert t.expanded is True, '点了按钮但树没展开'
    assert btn.text().endswith('▼'), '按钮箭头没跟着变（%r）' % btn.text()
    assert p._think_summary_lbl.text() == '', '展开时摘要应隐藏'

    # 再点一下收起
    btn.click()
    _app.processEvents()
    assert t.expanded is False
    assert btn.text().endswith('▶')
    assert '2 轮' in p._think_summary_lbl.text()


def test_full_text_still_readable(two_round_pet):
    full = two_round_pet._trace_tree.full_text()
    for frag in ('轮1思考', '轮2思考', '工具结果'):
        assert frag in full, '收起后全文应仍含 %r' % frag


def test_ui_probe_still_readable(two_round_pet):
    """既有探针兼容：thinking_text 可读、thinking_hidden 为 False"""
    probe = two_round_pet.ui_probe()
    assert probe['thinking_text'], 'thinking_text 不应为空'
    assert probe['thinking_hidden'] is False


def test_two_bubbles_toggle_independently(two_round_pet):
    """旧气泡的按钮只改旧气泡（不能串到新气泡）

    回潮翼障：回调若取 `self._thinking_toggle`（全局最新），
    点旧气泡会改到新气泡的按钮（regression_test B3 就是这么红的）。

    ⚠ 判据必须是「新气泡按钮文字 ↔ 新气泡树状态」是否一致。
      只断言「文字没变」区分不了 —— 两个气泡都展开时文字恰好都是 ▼，
      被误写成 ▼ 也是「没变」（第一版就是这么写错的，真锁验证造假绿）。
    """
    p = two_round_pet
    old_tree, old_btn = p._trace_tree, p._thinking_toggle

    # 用产品入口开第二个气泡
    p._chat_type_stream_begin()
    p._on_reasoning('第二段思考')
    _app.processEvents()
    new_tree, new_btn = p._trace_tree, p._thinking_toggle
    assert new_tree is not old_tree, '第二个气泡没有新建树'

    # 把新气泡收起来 → 若回调串味，会把它的按钮错写成 ▼
    new_btn.click()
    _app.processEvents()
    assert new_tree.expanded is False, '新气泡没被收起来（前置条件不成立）'
    assert new_btn.text().endswith('▶')

    # 点旧气泡（从收起 → 展开）
    old_btn.click()
    _app.processEvents()
    assert old_tree.expanded is True

    # 唯一能区分的判据：新气泡的按钮必须仍然与它自己的树一致
    assert new_tree.expanded is False, '旧气泡的操作把新气泡展开了'
    assert new_btn.text().endswith('▶'), (
        '新气泡按钮被写成 %r，但它自己的树是收起的 —— 回调串到别的气泡了'
        % new_btn.text())


# ---------- C. 多轮正文不重复（同族 bug） ----------
def test_multi_round_body_not_duplicated(two_round_pet):
    """多轮工具调用时，正文区不该出现重复内容或空 label

    实测根因（trace_multiround.py）：
      P1 `_on_stream_done` 丢弃 `_stream_label` 引用却不清布局 ⇒ 每轮多一个空 label
      P2 `_stream_text` 跨轮不累积重置 ⇒ 新 label 带着上一轮全文
    """
    p = two_round_pet
    content = p._chat_type_content
    texts, empties = [], 0
    for i in range(content.count()):
        w = content.itemAt(i).widget()
        if w is None or not isinstance(w, QLabel):
            continue
        t = w.text().strip()
        if not t:
            empties += 1
        else:
            texts.append(t)
    assert empties == 0, '正文区有 %d 个空 label（应 0）' % empties
    joined = '\n'.join(texts)
    assert joined.count('轮1正文') == 1, '轮1正文出现 %d 次' % joined.count('轮1正文')
    assert joined.count('轮2正文') == 1, '轮2正文出现 %d 次' % joined.count('轮2正文')
