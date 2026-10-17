# -*- coding: utf-8 -*-
"""任务面板：数据定位必须按条目 id，不能按表格行号

背景（PC-207 / PC-208 实证）：
    对话框版用 `self.todos[row]` 从不出错，因为「打开—刷新—销毁」闭环里行号恒同步；
    但常驻面板存在「外部改动窗口」——AI 在别处改 todos 而面板没收到通知，
    表格没重建 ⇒ 行号与索引错位 ⇒ 用户点 A 实际改中 X，且静默无报错。
"""
import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QApplication.instance() or QApplication(sys.argv)

from todo_panel import TodoPanel  # noqa: E402


class _Recorder:
    """记录保存回调被调用次数"""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


@pytest.fixture
def mk():
    created = []

    def _make(todos):
        rec = _Recorder()
        p = TodoPanel(todos, rec)
        created.append(p)
        return p, rec

    yield _make
    for p in created:
        p.deleteLater()


# ============ 核心：错位场景（这条如果红，说明改造失败） ============

def test_toggle_uses_id_not_row_after_external_insert(mk):
    """面板开着 → 外部在最前面插一条（面板未刷新）→ 点第 0 行

    屏幕上第 0 行写着「A 写周报」，所以必须勾中 A；
    绝不能勾中外部新插入的「X 老板临时加的」。
    """
    todos = [
        {'id': 'a1', 'text': 'A 写周报', 'done': False, 'created': '10-17 10:00'},
        {'id': 'b2', 'text': 'B 交作业', 'done': False, 'created': '10-17 10:01'},
    ]
    panel, _ = mk(todos)
    assert panel.table.item(0, 1).text() == 'A 写周报'

    # 模拟 AI 通过 _manage_todo('add') 在别处插入，插在最前；面板不刷新
    todos.insert(0, {'id': 'x9', 'text': 'X 老板临时加的',
                     'done': False, 'created': '10-17 10:02'})
    assert panel.table.item(0, 1).text() == 'A 写周报', '表格应仍是旧内容（未刷新）'

    # 用户双击屏幕上第 0 行
    panel._on_toggle(0)

    done = {t['text']: t['done'] for t in todos}
    assert done['A 写周报'] is True, '应勾中屏幕上显示的那一条'
    assert done['X 老板临时加的'] is False, '不得勾中外部新插入的那一条'


def test_delete_selected_by_id_not_row(mk):
    """删除同理：选屏幕上第 1 行（B），外部插过一条未刷新，也应删掉 B"""
    todos = [
        {'id': 'a', 'text': 'A', 'done': False},
        {'id': 'b', 'text': 'B', 'done': False},
    ]
    panel, _ = mk(todos)
    todos.insert(0, {'id': 'x', 'text': 'X', 'done': False})

    panel.table.selectRow(1)          # 屏幕上第 1 行 = B
    panel._on_del_selected()

    assert [t['text'] for t in todos] == ['X', 'A'], '应删掉 B'


def test_done_selected_by_id(mk):
    todos = [
        {'id': 'a', 'text': 'A', 'done': False},
        {'id': 'b', 'text': 'B', 'done': False},
    ]
    panel, _ = mk(todos)
    todos.insert(0, {'id': 'x', 'text': 'X', 'done': False})

    panel.table.selectRow(0)          # 屏幕上第 0 行 = A
    panel._on_done_selected()

    done = {t['text']: t['done'] for t in todos}
    assert done['A'] is True
    assert done['X'] is False


# ============ 找不到 id 时：重建，绝不乱改 ============

def test_unknown_id_refreshes_instead_of_mutating(mk):
    """外部已删光、面板未刷新时再点：应重建表格，不凭空改数据"""
    todos = [{'id': 'a', 'text': 'A', 'done': False}]
    panel, _ = mk(todos)

    todos.clear()                     # 外部删光，面板不知道
    panel._on_toggle(0)

    assert todos == [], '不得凭空造出数据'
    assert panel.table.rowCount() == 0, '应重建表格'


# ============ 基本功能 ============

def test_add_then_toggle_twice(mk):
    todos = []
    panel, rec = mk(todos)

    assert panel.add_text('买牛奶') is True
    assert len(todos) == 1
    assert todos[0]['text'] == '买牛奶'
    assert todos[0].get('id'), '新增条目必须带 id'
    assert todos[0]['done'] is False
    assert rec.calls >= 1, '新增后应触发保存'

    panel._on_toggle(0)
    assert todos[0]['done'] is True

    panel._on_toggle(0)
    assert todos[0]['done'] is False


def test_add_empty_rejected(mk):
    todos = []
    panel, _ = mk(todos)
    assert panel.add_text('   ') is False
    assert todos == []


def test_legacy_item_without_id_gets_one(mk):
    """早期数据没有 id：进面板时自动补上"""
    todos = [{'text': '老条目', 'done': False, 'created': ''}]
    panel, _ = mk(todos)
    assert todos[0].get('id'), '无 id 的旧条目应自动补 id'
    assert panel.table.rowCount() == 1


def test_clear_done_keeps_list_identity(mk):
    """清空已完成必须用切片赋值，不能替换列表对象（外部持有同一引用）"""
    todos = [
        {'id': 'a', 'text': 'A', 'done': True},
        {'id': 'b', 'text': 'B', 'done': False},
    ]
    ref = todos
    panel, _ = mk(todos)

    panel._on_clear_done()

    assert todos is ref, '不得替换列表对象'
    assert [t['text'] for t in todos] == ['B']


def test_refresh_picks_up_external_changes(mk):
    """外部改完 todos 后调 refresh() 应看到新数据（常驻面板的刷新契约）"""
    todos = [{'id': 'a', 'text': 'A', 'done': False}]
    panel, _ = mk(todos)

    todos.insert(0, {'id': 'n', 'text': '新来的', 'done': False})
    panel.refresh()

    assert panel.table.rowCount() == 2
    assert panel.table.item(0, 1).text() == '新来的'
