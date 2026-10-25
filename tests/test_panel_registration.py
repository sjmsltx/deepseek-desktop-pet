# -*- coding: utf-8 -*-
"""面板注册的结构性护栏（从 test_status_panel.py 迁来）

2026-10-25：`status_panel.py` 已删除（它和侧栏「◎ 状态」页是同一份信息，
留着只会变成"两个副本各自为政"）。但原文件里有三条护栏**与状态面板本身无关**，
删文件前先迁到这里，不能跟着一起丢：

  1 判据 3：`_register_builtin_panels` 里只许有注册语句，不许出现面板装配/布局代码
  2 容器能同时切到多个面板
  3 两个面板的注册必须各用各的 try（共用会把失败记到错的模块上）

⛔ 「删东西之前先想清楚会丢什么」——这一轮被 Owner 指出过：
   改一处漏三处。所以这里先迁移、再删除，删完还要跑一遍确认没丢判据。
"""
import ast
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

QApplication.instance() or QApplication(sys.argv)

import panel_registry as pr          # noqa: E402
from panel_shell import PanelShell   # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 注册函数里允许出现的面板名字（因为 register_panel 调用本身要提到它们）
PANEL_NAMES = ('todo_panel', 'TodoPanel', 'note_panel', 'NotePanel',
               'status_panel', 'StatusPanel')


@pytest.fixture(autouse=True)
def clean_registry():
    pr.clear_panels()
    yield
    pr.clear_panels()


def test_registration_function_has_no_assembly_code():
    """判据 3：注册函数体里，除了 register_panel 调用行，不得出现面板装配代码

    这条防的是「加面板时顺手在主窗口里写布局」——一旦那样，
    加第 3 个面板就要动主窗口，注册机制就等于没了。
    """
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
        if 'register_panel' in s or 'import ' in s:
            allowed_hits.append(s)
            continue
        for bad in PANEL_NAMES:
            assert bad not in s, '注册函数里出现了面板装配代码：%r' % s
    assert allowed_hits, '没找到注册语句，判据失效'


def test_shell_shows_multiple_panels():
    """容器能连续切到多个面板（懒建，切过的才建）"""
    pr.register_panel('a', 'A', lambda h: QLabel('a'), order=1)
    pr.register_panel('b', 'B', lambda h: QLabel('b'), order=2)
    shell = PanelShell(host=object())
    try:
        assert shell.show_panel('a') is True
        assert shell.show_panel('b') is True
        assert shell.built_keys() == ['a', 'b']
    finally:
        shell.deleteLater()


def test_two_panels_have_separate_try_blocks():
    """todo 与 note 两个面板的注册必须各用各的 try（共用会把失败记到错的模块上）

    做法：ast 找 _register_builtin_panels 里所有 Try 节点，看
      · 含 TodoPanel 的那个 Try 里不许出现便签注册
      · 含便签注册的那个 Try 里不许出现 TodoPanel
      · 两个 handler 的日志标签必须各指各的（:todo / :note）
    ⛔ 不用字符串 grep：注释里写着这些名字会误命中。
    """
    src = io.open(os.path.join(REPO, 'desktop_pet.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '_register_builtin_panels':
            fn = node
            break
    assert fn is not None, '找不到 _register_builtin_panels'

    seg = lambda n: ast.get_source_segment(src, n) or ''
    todo_try = note_try = None
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        s = seg(node)
        code = '\n'.join(l for l in s.splitlines() if not l.strip().startswith('#'))
        if 'TodoPanel' in code:
            todo_try = code
        if "register_panel('note'" in code:
            note_try = code

    assert todo_try is not None, '找不到待办面板的 try'
    assert note_try is not None, '找不到便签面板的 try'
    assert "register_panel('note'" not in todo_try, '待办 try 里不该有便签注册（共用会连坐）'
    assert 'TodoPanel' not in note_try, '便签 try 里不该有待办面板'
    assert ':todo' in todo_try, '待办 try 的日志标签丢了'
    assert ':note' in note_try, '便签 try 的日志标签必须指自己的模块，不能写死 :todo'


def test_no_status_panel_module_left():
    """status_panel.py 已删（2026-10-25 Owner 决定）—— 不许有代码再指它

    它和侧栏「◎ 状态」页是同一份信息；留着就是两个副本。
    真要恢复：加回文件 + 重新注册 + 删掉这条测试，并说明理由。
    """
    assert not os.path.exists(os.path.join(REPO, 'status_panel.py')), \
        'status_panel.py 又出现了：请确认是否真的要恢复这个重复面板'
    src = io.open(os.path.join(REPO, 'desktop_pet.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    for n in ast.walk(tree):
        mods = []
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods = [n.module or '']
        assert not any('status_panel' in m for m in mods), \
            'desktop_pet.py 还在 import status_panel（文件已删）'
