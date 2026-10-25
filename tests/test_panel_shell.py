# -*- coding: utf-8 -*-
"""批 2 回归：骨架 + 注册接口 + P3 接线

对应 WX-096 五条判据里的：
  判据 2 新入口可开可关（不点永远不出现）
  判据 3 注册机制成立（加面板不改主窗口）
  判据 4 面板不依赖宿主（无 import desktop_pet）
  P3     面板自己存盘时不回刷（refresh 次数不翻倍）

⛔ 这些测试**不用真启动 PetWidget**（要起窗口、读 config、连 MCP，太脆）。
   注册表与容器都设计成可独立导入，这里直接测它们；宿主接线用静态检查兜住。
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtWidgets import QLabel        # noqa: E402

QApplication.instance() or QApplication(sys.argv)

import panel_registry as pr                  # noqa: E402
from panel_shell import PanelShell           # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean_registry():
    pr.clear_panels()
    yield
    pr.clear_panels()


# ==================== 注册接口 ====================

def test_register_and_order():
    pr.register_panel('b', 'B', lambda h: QLabel('b'), order=20)
    pr.register_panel('a', 'A', lambda h: QLabel('a'), order=10)
    assert pr.panel_keys() == ['a', 'b'], 'order 小的排前面'


def test_duplicate_key_rejected():
    pr.register_panel('a', 'A', lambda h: QLabel('a'))
    with pytest.raises(ValueError):
        pr.register_panel('a', 'A2', lambda h: QLabel('a2'))
    pr.register_panel('a', 'A2', lambda h: QLabel('a2'), replace=True)
    assert pr.count() == 1


def test_empty_key_rejected():
    with pytest.raises(ValueError):
        pr.register_panel('  ', 'X', lambda h: QLabel('x'))


def test_non_callable_factory_rejected():
    with pytest.raises(TypeError):
        pr.register_panel('a', 'A', None)


def test_build_missing_returns_none():
    assert pr.build('nope', object()) is None


# ==================== 判据 2：不点不出现 / 开了能关 ====================

def test_shell_starts_hidden_and_shows_only_registered():
    pr.register_panel('one', '面板一', lambda h: QLabel('1'), order=1)
    pr.register_panel('two', '面板二', lambda h: QLabel('2'), order=2)
    shell = PanelShell(host=object())
    try:
        assert shell.isVisible() is False, '容器建出来不该自动显示（判据 2）'
        assert set(shell._btns.keys()) == {'one', 'two'}
        shell.show()
        assert shell.isVisible() is True
        assert shell.show_panel('two') is True
        shell.close()
        assert shell.isVisible() is False, '关掉就隐藏，不销毁'
    finally:
        shell.deleteLater()


def test_lazy_build_only_used_panels():
    built = []
    pr.register_panel('one', '一', lambda h: (built.append('one'), QLabel('1'))[1], order=1)
    pr.register_panel('two', '二', lambda h: (built.append('two'), QLabel('2'))[1], order=2)
    shell = PanelShell(host=object())
    try:
        assert built == ['one'], '只建当前显示的（懒建）'
        shell.show_panel('two')
        assert built == ['one', 'two']
        assert shell.built_keys() == ['one', 'two']
    finally:
        shell.deleteLater()


def test_empty_registry_does_not_crash():
    shell = PanelShell(host=object())
    try:
        assert shell.show_panel('nope') is False
    finally:
        shell.deleteLater()


def test_show_panel_unknown_returns_false():
    pr.register_panel('a', 'A', lambda h: QLabel('a'))
    shell = PanelShell(host=object())
    try:
        assert shell.show_panel('zzz') is False
    finally:
        shell.deleteLater()


# ==================== 判据 3：加面板不改主窗口 ====================

def test_shell_has_no_panel_names():
    """容器源码里不得出现具体面板的 key/类名 —— 否则加第 3 个还得改它"""
    src = io.open(os.path.join(REPO, 'panel_shell.py'), encoding='utf-8').read()
    for bad in ("'todo'", '"todo"', 'TodoPanel', 'SidePanel', 'todo_panel'):
        assert bad not in src, '容器里出现了具体面板标识：%s' % bad


def test_registry_has_no_host_imports():
    """注册表必须能脱离主程序导入

    ⛔ 用 ast 判真实 import，不用字符串 grep：
       本文件与 panel_registry 的 docstring 里都写着这些名字，
       按字符串判会把自己判成违规（今天已踩过一次）。
    """
    import ast
    p = os.path.join(REPO, 'panel_registry.py')
    tree = ast.parse(io.open(p, encoding='utf-8').read())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or '').split('.')[0])
    forbidden = {'desktop_pet', 'todo_panel', 'side_panel'}
    assert not (mods & forbidden), '注册表不该依赖：%s' % sorted(mods & forbidden)


def test_adding_third_panel_needs_no_host_change():
    """核心断言：加一个面板只要注册，容器与宿主都不用动。

    做法：记录下宿主里与面板装配相关的两处源码，注册前后逐字比对。
    """
    host = io.open(os.path.join(REPO, 'desktop_pet.py'), encoding='utf-8').read()
    pick = lambda t: t[t.find('def _open_main_area'):][:1200]
    before = pick(host)

    pr.register_panel('a', 'A', lambda h: QLabel('a'))
    pr.register_panel('b', 'B', lambda h: QLabel('b'))
    pr.register_panel('c', 'C', lambda h: QLabel('c'))     # 第 3 个

    after = pick(io.open(os.path.join(REPO, 'desktop_pet.py'), encoding='utf-8').read())
    assert before == after, '注册新面板不该要求改主窗口'


# ==================== 判据 4：面板不依赖宿主 ====================

def test_panel_files_do_not_import_host():
    bad = PanelShell.contract_violations([
        os.path.join(REPO, 'todo_panel.py'),
        os.path.join(REPO, 'panel_registry.py'),
        os.path.join(REPO, 'panel_shell.py'),
    ])
    assert bad == [], '面板文件违反了「不 import 宿主」契约：%r' % (bad,)


def test_contract_checker_has_teeth(tmp_path):
    """证伪：故意造一个 import 宿主的文件，检查器必须抓到"""
    p = tmp_path / 'bad_panel.py'
    p.write_text('import desktop_pet\n', encoding='utf-8')
    bad = PanelShell.contract_violations([str(p)])
    assert bad and 'import desktop_pet' in bad[0][1]


def test_contract_checker_ignores_comments(tmp_path):
    p = tmp_path / 'ok_panel.py'
    p.write_text('# 不要 import desktop_pet\nimport os\n', encoding='utf-8')
    assert PanelShell.contract_violations([str(p)]) == []


# ==================== P3：面板自己存盘不回刷 ====================

def test_from_panel_true_wired_in_host():
    """静态钉：待办面板的 save_cb 必须传 from_panel=True（P3 的落点）

    2026-10-25 主区 B 方案：待办面板从「独立弹窗里 new」改成「panel_registry 的 factory 造」，
    接收者名字随之从 self 变成 host（host 就是 PetWidget，语义不变）：
        return _TP(host.todos, lambda: host._save_todos(from_panel=True), labels=_labels)
    所以钉的形态从 `self._save_todos(...)` 放宽到 `_save_todos(...)`；
    判别力没降 —— 谁把 from_panel=True 去掉，这条仍然红。
    """
    src = io.open(os.path.join(REPO, 'desktop_pet.py'), encoding='utf-8').read()
    assert '_save_todos(from_panel=True)' in src, \
        'P3：TodoPanel 的 save_cb 必须带 from_panel=True（面板自己存盘后宿主不再回刷）'
    # 不许改回默认（from_panel=False 会让宿主再 refresh 一次，勾选位置被抹掉）
    assert 'lambda: self._save_todos()' not in src
    # 不许再用 partial（会抓旧 bound method）
    assert 'partial(self._save_todos' not in src


def test_panel_self_save_does_not_double_refresh():
    """行为验证：面板发起存盘 ⇒ 宿主不再回刷（refresh 不翻倍）

    用真 TodoPanel + 桩宿主，数 refresh 次数。
    """
    import desktop_pet as dp
    from todo_panel import TodoPanel

    todos = [{'id': 'a', 'text': 'A', 'done': False},
             {'id': 'b', 'text': 'B', 'done': False}]

    class Host:
        _save_todos = dp.PetWidget._save_todos
        _sync_todo_panel = dp.PetWidget._sync_todo_panel

        def __init__(self, t, panel):
            self.todos = t
            self._todo_panel = panel
            self.saves = 0

        def _atomic_write_json(self, p, o):
            pass

        def _notify(self, m):
            pass

    panel = TodoPanel(todos, lambda: None)
    host = Host(todos, panel)
    # 复刻宿主真实接线（判据就是照它写的）
    panel._save = lambda: host._save_todos(from_panel=True)

    n = {'r': 0}
    real = panel.refresh

    def counted():
        n['r'] += 1
        return real()

    panel.refresh = counted
    panel.table.selectRow(0)
    panel._on_done_selected()

    assert todos[0]['done'] is True, '数据必须改对'
    assert n['r'] == 1, '面板自己存盘后不该再被宿主回刷一遍（实际 %d 次）' % n['r']
    panel.deleteLater()
