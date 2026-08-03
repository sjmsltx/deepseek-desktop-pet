# -*- coding: utf-8 -*-
"""冒烟测试：验证核心模块可导入、核心函数可用（无 GUI 弹窗，offscreen 模式）。"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(scope='module')
def pet():
    import desktop_pet
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    w = desktop_pet.PetWidget()
    yield w
    w.close()


def test_import_module():
    """模块可正常导入"""
    import desktop_pet
    assert hasattr(desktop_pet, 'PetWidget')


def test_widget_construct(pet):
    """主控件可构造"""
    assert pet is not None


def test_todo_crud(pet):
    """待办增删改查核心逻辑"""
    r = pet._manage_todo('add', '冒烟测试项')
    assert '加入' in r or 'added' in r.lower()
    assert len(pet.todos) >= 1
    tid = pet.todos[-1]['id']
    pet._manage_todo('done', tid=tid)
    assert pet.todos[-1]['done'] is True
    r = pet._manage_todo('remove', tid=tid)
    assert '删除' in r or 'removed' in r.lower()


def test_bilingual_dict(pet):
    """双语字典存在且可取用"""
    zh = pet._t('reminder_menu')
    assert zh
    pet.language = 'en'
    en = pet._t('reminder_menu')
    assert en and en != zh
    pet.language = 'zh'


def test_smart_find_app(pet):
    """语义搜索能命中本地应用"""
    found = pet._smart_find_app('记事本')
    assert found is not None
    target, _name = found
    assert target and ('notepad' in target.lower() or os.path.exists(target))


def test_guess_status(pet):
    """AI 状态预判基础规则"""
    status, _lang = pet._guess_status('今天天气怎么样')
    assert '天气' in status or 'weather' in status.lower()
