# -*- coding: utf-8 -*-
"""复制带图（v6.76）

使用者反馈：“能不能保证复制之后那个图片也是完整的粘贴过去？”
实测：① 消息的复制只写纯文本 → 图丢；② `md_to_html` 根本没处理 `![](路径)` 语法
→ 连聊天里都不显示图片。

本测试锁定：图片语法要转 <img>；富复制要写 text/plain + text/html 且本地图内联为 data URI；
文件不存在时不崩、不丢原文。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

IMG = 'assets/pro/pro_idle.png'


@pytest.fixture(scope='module')
def env():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QGuiApplication
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.say_plain = lambda *a, **k: None          # 静音提示
    return p, QGuiApplication.clipboard()


def test_md_image_syntax_becomes_img_tag():
    import pet_bubble as pb
    html = pb.to_html('看这张 ![](%s) 图' % IMG)
    assert '<img' in html and IMG in html


def test_md_link_still_works():
    import pet_bubble as pb
    html = pb.to_html('看 [链接](https://example.com/a)')
    assert '<a href="https://example.com/a">链接</a>' in html


def test_image_rule_beats_link_rule():
    """图片语法不能被当成普通链接处理"""
    import pet_bubble as pb
    html = pb.to_html('![](x.png)')
    assert '<img' in html and '<a href' not in html


def test_rich_copy_has_both_formats_and_inlines_image(env):
    p, cb = env
    assert os.path.isfile(os.path.join(BASE, IMG)), '测试图缺失'
    ok = p._copy_rich_text('## 标题\n\n![](assets/pro/pro_idle.png)\n\n收尾。')
    assert ok is True
    md = cb.mimeData()
    assert md.hasText() and md.hasHtml()
    html = md.html()
    assert 'data:image' in html, '本地图片没有被内联 → 粘到别处还是会丢图'
    assert '收尾' in md.text()


def test_rich_copy_plain_message_no_image(env):
    p, cb = env
    p._copy_rich_text('就是一句普通回复。')
    md = cb.mimeData()
    assert md.hasText() and md.hasHtml()
    assert 'data:image' not in md.html()


def test_rich_copy_missing_file_does_not_break(env):
    p, cb = env
    ok = p._copy_rich_text('![](not/exists/xx.png) 文字还在')
    assert ok is True
    assert '文字还在' in cb.mimeData().text()
