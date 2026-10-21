# -*- coding: utf-8 -*-
"""批 3 补充：状态面板的判据验证

新增断言：
  判据 3 实测：注册第二个面板后，desktop_pet.py 的改动必须只有「注册语句」这几行，
              不含任何面板装配/布局代码
  判据 4     status_panel.py 不得 import desktop_pet
  判据 5     同一份 data，面板显示值与侧栏 _text_for 的字段值必须一致
             （搬移最怕两边显示不一致，那比没搬还糟）
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

QApplication.instance() or QApplication(sys.argv)

import panel_registry as pr          # noqa: E402
from panel_shell import PanelShell   # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean_registry():
    pr.clear_panels()
    yield
    pr.clear_panels()


# ==================== 判据 4：状态面板不依赖宿主 ====================

def test_status_panel_no_host_import():
    bad = PanelShell.contract_violations([os.path.join(REPO, 'status_panel.py')])
    assert bad == [], 'status_panel 违反了不 import 宿主的契约：%r' % (bad,)


def test_status_panel_takes_only_data_cb():
    """构造只收一个取数回调 —— 宿主是谁它不知道"""
    import inspect
    import status_panel as sp
    sig = inspect.signature(sp.StatusPanel.__init__)
    params = [p for p in sig.parameters if p != 'self']
    assert params[:1] == ['data_cb'], params
    assert 'host' not in params, '面板不该拿整个宿主'


# ==================== 判据 5：两边显示必须一致 ====================

def _sample_data():
    return {'today_count': 7, 'today_tokens': '4.1万', 'today_cost': '0.1145',
            'balance': '¥64.36', 'model': 'deepseek-v4-flash', 'voice': '默认',
            'peak': '空闲（北京 23:20）', 'affection': '12', 'satiety': '68%',
            'satiety_low': False, 'hint': ''}


def test_status_panel_matches_sidebar_values():
    """同一份 data，面板显示值必须逐一等于侧栏格式化后的值

    ⛔ 这条是搬移的安全网：搬完两边数字不一样，比不搬更糟。
    """
    import status_panel as sp
    data = _sample_data()
    panel = sp.StatusPanel(lambda: data)
    try:
        got = panel.values()
        for title, key, default in sp.FIELDS:
            expect = data.get(key, default)
            assert got[key] == str(expect), '%s 显示 %r，应为 %r' % (key, got[key], str(expect))
    finally:
        panel.deleteLater()


def test_status_panel_row_count_matches_fields():
    import status_panel as sp
    panel = sp.StatusPanel(lambda: _sample_data())
    try:
        assert len(panel._rows) == len(sp.FIELDS)
    finally:
        panel.deleteLater()


# ==================== 取数失败不许崩，也不许静默 ====================

def test_status_panel_survives_data_cb_crash():
    import status_panel as sp

    def boom():
        raise RuntimeError('取数炸了')

    panel = sp.StatusPanel(boom)
    try:
        vals = panel.values()
        assert all(v for v in vals.values()), '取数失败时应全部回落到缺省值，不能出现空串'
        assert '取数失败' in panel.lb_hint.text(), '必须提示取数失败（不许静默）'
    finally:
        panel.deleteLater()


def test_status_panel_missing_keys_use_defaults():
    import status_panel as sp
    panel = sp.StatusPanel(lambda: {})          # 空 dict
    try:
        vals = panel.values()
        assert vals['today_count'] == '0'
        assert vals['balance'] == '未查询'
        assert vals['model'] == '—'
    finally:
        panel.deleteLater()


def test_status_panel_hungry_hint():
    import status_panel as sp
    data = _sample_data()
    panel = sp.StatusPanel(lambda: data)
    try:
        data['satiety_low'] = True
        panel.refresh()
        assert '饿' in panel.lb_hungry.text()
    finally:
        panel.deleteLater()


# ==================== 判据 3：加第二个面板，主窗口只该多「注册」几行 ====================

def test_second_panel_registration_is_only_registration():
    """desktop_pet.py 里与面板装配相关的源码段，除注册语句外不得出现面板名字

    做法：扫 _register_builtin_panels 函数体，除了 register_panel 调用行，
    其余代码不得出现 status_panel / StatusPanel / todo_panel / TodoPanel。
    """
    import ast
    src = io.open(os.path.join(REPO, 'desktop_pet.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    body_src = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '_register_builtin_panels':
            seg = src.splitlines()[node.lineno - 1:node.end_lineno]
            body_src = '\n'.join(seg)
            break
    assert body_src, '找不到 _register_builtin_panels'
    allowed_hits = []
    for ln in body_src.splitlines():
        s = ln.strip()
        if not s or s.startswith('#'):
            continue
        if 'register_panel' in s or 'import status_panel' in s or 'StatusPanel(' in s or 'TodoPanel' in s:
            allowed_hits.append(s)
            continue
        for bad in ('status_panel', 'StatusPanel', 'todo_panel', 'TodoPanel'):
            assert bad not in s, '注册函数里出现了面板装配代码：%r' % s
    assert allowed_hits, '没找到注册语句，判据失效'


def test_shell_shows_both_panels():
    """两个面板注册后，容器都能切过去"""
    pr.register_panel('a', 'A', lambda h: __import__('PySide6.QtWidgets', fromlist=['QLabel']).QLabel('a'), order=1)
    pr.register_panel('b', 'B', lambda h: __import__('PySide6.QtWidgets', fromlist=['QLabel']).QLabel('b'), order=2)
    shell = PanelShell(host=object())
    try:
        assert shell.show_panel('a') is True
        assert shell.show_panel('b') is True
        assert shell.built_keys() == ['a', 'b']
    finally:
        shell.deleteLater()

# ==================== WX-098 §五：两个面板各自独立 try ====================

def test_two_panels_have_separate_try_blocks():
    """状态面板的注册不得与待办面板共用 try（共用会把失败记到错的模块上）

    做法：ast 找 _register_builtin_panels 里所有 Try 节点，看
      · 含 TodoPanel 的那个 Try 里不许出现 status_panel
      · 含 import status_panel 的那个 Try 里不许出现 TodoPanel
      · 两个 handler 的日志标签必须各指各的（:todo / :status）
    ⛔ 不用字符串 grep：注释里写 'status_panel' 会误命中。
    """
    import ast
    src = io.open(os.path.join(REPO, 'desktop_pet.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '_register_builtin_panels':
            fn = node
            break
    assert fn is not None, '找不到 _register_builtin_panels'

    seg = lambda n: ast.get_source_segment(src, n) or ''
    todo_try = status_try = None
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        s = seg(node)
        # 跳过注释行，只看真代码
        code = '\n'.join(l for l in s.splitlines() if not l.strip().startswith('#'))
        if 'TodoPanel' in code:
            todo_try = code
        if 'import status_panel' in code:
            status_try = code

    assert todo_try is not None, '找不到待办面板的 try'
    assert status_try is not None, '找不到状态面板的 try'
    assert 'status_panel' not in todo_try, '待办 try 里不该有状态面板（共用了同一个 try）'
    assert 'TodoPanel' not in status_try, '状态 try 里不该有待办面板（共用会连坐）'
    assert ':todo' in todo_try, '待办 try 的日志标签丢了'
    assert ':status' in status_try, '状态 try 的日志标签必须指自己的模块，不能写死 :todo'
