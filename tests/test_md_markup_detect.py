# -*- coding: utf-8 -*-
"""流式回复的富文本渲染判定（v6.75 修 bug）

背景（使用者反馈“有时候渲染不生效，出选项那次显示原始 .md”）：
  旧条件只认 ``` 代码块与表格 → 标题 / 加粗 / 列表 / 引用 / 行内代码 / 链接
  在**流式路径**下永远停在纯文本 → 显示原始 markdown。
  所以“是否渲染”取决于内容里有没有代码块或表格 —— 表现就是“有时不渲染”。

本测试锁定新判定：有 markdown 迹象就该重渲染；纯文本仍走快路径。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='module')
def pet():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    return p


@pytest.mark.parametrize('text,expect', [
    ('**加粗**的结论', True),
    ('## 小标题\n下面是正文', True),
    ('- 要点一\n- 要点二', True),
    ('1. 第一步\n2. 第二步', True),
    ('> 引用一句', True),
    ('行内 `code` 测试', True),
    ('看这个 [链接](https://example.com/a)', True),
    ('```python\nprint(1)\n```', True),
    ('| 列A | 列B |\n|---|---|\n| 1 | 2 |', True),
    ('就是普通一句话，没有标记。', False),
    ('带数字 2026 年 9 月 20 日，仅此而已', False),
    ('', False),
    ('   \n  ', False),
])
def test_has_md_markup(pet, text, expect):
    assert pet._has_md_markup(text) is expect, text


def test_plain_with_dash_inside_not_list(pet):
    """行内破折号/负号不该被当成列表（避免纯文本被误判重渲染）"""
    assert pet._has_md_markup('温度 -5 度，参数 a-b 关系') is False


def test_table_helper_still_used(pet):
    """表格仍要走富文本（旧行为不能丢）"""
    assert pet._has_md_markup('| a | b |\n| --- | --- |\n| 1 | 2 |') is True
