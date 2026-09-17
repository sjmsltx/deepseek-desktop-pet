# -*- coding: utf-8 -*-
"""v6.58：代码卡片长行必须换行（此前 NoWrap，长行超出卡片宽度被右缘截掉）

使用者实测：桌宠回复里的 JSON 代码块右侧约 1/4 看不到，必须横向拖动。
定位：代码块走 `pet_bubble.render_md_into` → `CodeCard`，而其内部是
`QTextEdit.setLineWrapMode(NoWrap)`。复现时该块文档宽 558px、卡片可视宽 408px
→ 约 27% 内容落在卡片右侧之外。改为 WidgetWidth（按宽度换行）后不再有"看不见的字"。

运行：python -m pytest tests/test_code_card_wrap.py -q
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

LONG = '{"very_long_key_name_here": "a_very_long_value_that_would_never_fit_in_a_narrow_chat_panel_1234567890"}'


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def test_code_card_uses_widget_width_wrap():
    from PySide6.QtWidgets import QTextEdit
    from chat_cards import CodeCard
    _app()
    card = CodeCard(LONG)
    assert card.editor.lineWrapMode() == QTextEdit.LineWrapMode.WidgetWidth, \
        'CodeCard 又回到 NoWrap 了（长行会被卡片右缘截掉）'


def test_code_card_does_not_overflow_container():
    """放进 360px 宽的容器里，文档不得比可视区宽（即不会需要横向滚动）"""
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from chat_cards import CodeCard
    app = _app()
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(6, 6, 6, 6)
    card = CodeCard(LONG)
    lay.addWidget(card)
    box.resize(360, 400)
    box.show()
    for _ in range(5):
        app.processEvents()
    vw = card.editor.viewport().width()
    dw = int(card.editor.document().size().width())
    assert vw > 50, '视口宽度异常：%d' % vw
    assert dw <= vw + 4, '文档宽 %d 超过可视宽 %d（长行仍会溢出）' % (dw, vw)
    # 卡片自身也不得把容器顶宽（最小宽度应受限）
    assert card.minimumSizeHint().width() <= 360, '卡片最小宽度把容器顶宽了'
