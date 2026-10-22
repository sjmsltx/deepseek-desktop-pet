# -*- coding: utf-8 -*-
"""P2 回归：AI 在别处改了待办，常驻面板必须同步（不许"改了看不到"）

背景：
    2026-10-20 微信侧复核件（WX-90）指出——任务面板的点错已修（按 id 定位），
    但 `_manage_todo` 的 add / done / remove 三条路只存盘、不刷新面板，
    所以面板开着时用户看到的是旧列表（数据对、显示过期）。
    2026-10-21 Owner 批「你开始修吧」，修法：在唯一存盘出口 `_save_todos()` 加同步。

本文件只测**产品真实路径**，不重写一份实现：
    直接拿 `PetWidget._save_todos` / `_manage_todo` / `_find_todo` 绑到一个桩对象上，
    面板用真的 `TodoPanel`。
"""
import io
import json
import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp  # noqa: E402
from todo_panel import TodoPanel  # noqa: E402


class _PetStub:
    """把产品类里的真方法绑上来，只替换掉写盘与提示这两个副作用。"""

    # 实例方法照原样绑（会正常带 self）；类里的 staticmethod 必须包一层
    # staticmethod，否则普通函数作为类属性会被再绑一次 self（踩过一次）。
    _save_todos = dp.PetWidget._save_todos
    _sync_todo_panel = dp.PetWidget._sync_todo_panel
    _manage_todo = dp.PetWidget._manage_todo
    _new_todo_id = staticmethod(dp.PetWidget._new_todo_id)
    _find_todo = staticmethod(dp.PetWidget._find_todo)

    def __init__(self, todos, panel=None):
        self.todos = todos
        self._todo_panel = panel
        self.saves = 0
        self.notices = []

    def _atomic_write_json(self, path, obj):
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def _notify(self, msg):
        self.notices.append(msg)


@pytest.fixture
def tmp_todo_path(tmp_path, monkeypatch):
    p = str(tmp_path / "todos.json")
    monkeypatch.setattr(dp, "TODO_PATH", p)
    return p


@pytest.fixture
def mk(tmp_todo_path):
    created = []

    def _make(todos):
        panel = TodoPanel(todos, lambda: None)
        created.append(panel)
        pet = _PetStub(todos, panel)
        return pet, panel

    yield _make
    for p in created:
        p.deleteLater()


# ==================== P2 本体 ====================

def test_save_todos_refreshes_open_panel(mk):
    """存盘出口必须把面板拉回最新（P2 核心断言）"""
    todos = [{'id': 'a', 'text': 'A 写周报', 'done': False, 'created': '10-21 10:00'}]
    pet, panel = mk(todos)
    assert panel.table.rowCount() == 1

    # 模拟 AI 在别处改数据（绕开面板），然后走产品自己的存盘出口
    todos.append({'id': 'b', 'text': '明天交实验报告', 'done': False, 'created': '10-21 18:40'})
    pet._save_todos()

    assert panel.table.rowCount() == 2, '面板没跟着刷新 ⇒ 用户看到的是旧列表'
    assert panel.table.item(1, 1).text() == '明天交实验报告'


def test_manage_todo_add_shows_up_on_panel(mk):
    """走真实工具入口 add：面板当场就能看到（端到端数据路径）"""
    todos = []
    pet, panel = mk(todos)
    assert panel.table.rowCount() == 0

    pet._manage_todo('add', '买牛奶')

    assert len(todos) == 1
    assert panel.table.rowCount() == 1, 'add 之后面板必须立刻显示'
    assert panel.table.item(0, 1).text() == '买牛奶'


def test_manage_todo_done_reflects_on_panel(mk):
    todos = [{'id': 'a', 'text': 'A 写周报', 'done': False, 'created': '10-21 10:00'}]
    pet, panel = mk(todos)

    pet._manage_todo('done', tid='a')

    assert todos[0]['done'] is True
    assert panel.table.item(0, 0).text() == '✅', '勾选状态没反映到面板'


def test_manage_todo_remove_reflects_on_panel(mk):
    todos = [{'id': 'a', 'text': 'A', 'done': False},
             {'id': 'b', 'text': 'B', 'done': False}]
    pet, panel = mk(todos)

    pet._manage_todo('remove', tid='a')

    assert [t['text'] for t in todos] == ['B']
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 1).text() == 'B'


def test_sync_does_not_recurse(mk):
    """面板块补 id 时会回调存盘 ⇒ 必须有闸，不许无限递归"""
    legacy = [{'text': '老条目没有 id', 'done': False}]
    pet, panel = mk(legacy)

    calls = {'n': 0}
    real = pet._atomic_write_json

    def counting(path, obj):
        calls['n'] += 1
        assert calls['n'] < 10, '存盘次数爆炸 ⇒ 防重入闸失效'
        return real(path, obj)

    pet._atomic_write_json = counting
    pet._save_todos()

    assert legacy[0].get('id'), '老条目应补上 id'
    assert panel.table.rowCount() == 1
    assert calls['n'] <= 2, '最多两次（原存盘 + 补 id 后回写），实际 %d' % calls['n']


def test_no_panel_does_not_crash(mk, tmp_todo_path):
    """面板没开时存盘照常，不得因为取不到面板报错"""
    todos = [{'id': 'a', 'text': 'A', 'done': False}]
    pet = _PetStub(todos, None)
    pet._manage_todo('add', 'B')
    assert len(todos) == 2
    assert pet.notices == []


def test_destroyed_panel_does_not_crash(mk):
    """面板对象已销毁（对话框关了）时存盘不得炸"""
    todos = [{'id': 'a', 'text': 'A', 'done': False}]
    pet, panel = mk(todos)
    panel.deleteLater()
    QApplication.processEvents()
    pet._manage_todo('add', 'B')     # 不抛即通过


# ==================== 同族小风险 1：id 撞号 ====================

def test_new_todo_id_unique_in_same_millisecond():
    ids = [dp.PetWidget._new_todo_id() for _ in range(50)]
    assert len(set(ids)) == 50, '同一毫秒内 id 撞号 ⇒ 按 id 定位会命中错条目'


def test_panel_add_ids_unique_in_same_millisecond(mk):
    todos = []
    pet, panel = mk(todos)
    for i in range(50):
        assert panel.add_text('第 %d 条' % i) is True
    assert len({t['id'] for t in todos}) == 50


# ==================== 同族小风险 2：文字定位精确优先 ====================

def test_find_todo_prefers_exact_over_substring():
    todos = [{'id': '1', 'text': '写日报'},
             {'id': '2', 'text': '写周报'}]
    assert dp.PetWidget._find_todo(todos, '', '写周报')['id'] == '2', '完整相等应优先'
    assert dp.PetWidget._find_todo(todos, '', '写')['id'] == '1', '只有子串命中时取第一条'
    assert dp.PetWidget._find_todo(todos, '', '不存在') is None
    assert dp.PetWidget._find_todo(todos, 'zzz', '') is None


def test_manage_todo_done_by_exact_text_not_first_substring(mk):
    """传完整文字时必须命中那一条，而不是"第一条含它的" """
    todos = [{'id': '1', 'text': '写报告初稿', 'done': False},
             {'id': '2', 'text': '写报告', 'done': False}]
    pet, panel = mk(todos)

    pet._manage_todo('done', text='写报告')

    by_id = {t['id']: t['done'] for t in todos}
    assert by_id['2'] is True, '应命中完整相等的那条'
    assert by_id['1'] is False, '不得误改含该文字的第一条'
