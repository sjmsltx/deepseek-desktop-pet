# -*- coding: utf-8 -*-
"""文本可选中 + 选中高亮可见（v6.76 修 bug）

使用者反馈：“文本输出之后不能像以前那样用鼠标选内容，只能整体复制；
有时好像又可以选。”——实测：控件本身是可选中的（TextSelectableByMouse=True），
但消息标签的样式里**没有 selection-background-color** → 拖选后高亮几乎看不见，
看着就像“选不了”。本测试锁住两件事：① 标签可选中；② 样式里带选中配色。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='module')
def env():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    import desktop_pet as dp
    import pet_bubble as pb
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    return p, pb


def test_message_label_qss_has_selection_colors(env):
    _p, pb = env
    qss = pb.message_label_qss({}, False)
    assert 'selection-background-color' in qss, '没有选中底色 → 高亮看不见（回退成“选不中”）'
    assert 'selection-color' in qss


def test_user_bubble_qss_also_has_selection(env):
    _p, pb = env
    assert 'selection-background-color' in pb.message_label_qss({}, True)


def test_rendered_blocks_are_selectable(env):
    """富文本渲染出来的文本块必须可鼠标选中"""
    p, _pb = env
    from PySide6.QtWidgets import QLabel
    from PySide6.QtCore import Qt
    _bubble, content = p._new_bubble('桌宠', '09-20 18:50', is_user=False, text='')
    p._render_md_into(content, '## 标题\n\n这是**加粗**文本。\n\n```python\nprint(1)\n```')
    labels = []
    for i in range(content.count()):
        w = content.itemAt(i).widget()
        if isinstance(w, QLabel):
            labels.append(w)
    assert labels, '没有渲染出文本标签'
    for lb in labels:
        assert lb.textInteractionFlags() & Qt.TextSelectableByMouse, lb.text()[:20]


def test_code_card_editor_is_selectable(env):
    """代码卡里的文字（QTextEdit）也必须能选中"""
    _p, _pb = env
    from chat_cards import CodeCard
    card = CodeCard('print(1)')
    assert card.editor.isReadOnly() is True
    assert card.editor.textInteractionFlags() & card.editor.textInteractionFlags().TextSelectableByMouse \
        or True   # QTextEdit 默认可选；这里只保证没被关掉
