# -*- coding: utf-8 -*-
"""
chat_cards.py — 聊天渲染·卡片组件层（P2 模块化拆分）
=====================================================
从 desktop_pet.py 拆出的消息卡片组件（无 PetWidget 依赖）：
- CodeCard：代码卡片（标题栏 + 复制按钮 + 只读等宽文本 + 高度自适应）
- TableCard：表格卡片（标题栏 + 复制 markdown 原文 + 只读 HTML 表格）

模块化说明：QFrame 子类，只依赖 Qt，可独立复用/单测。
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QTextEdit


from pet_theme import color as T  # v6.58 主题化：取当前生效色（唯一源）


def code_card_qss():
    """代码卡片样式（v6.58：颜色全部取自主题 token）"""
    return ("""
            QFrame#codeCard { background:%s; border-radius:8px; }
            QLabel { color:%s; font-size:10px; background:transparent; }
            QPushButton { background:%s; color:%s; border:none; border-radius:4px;
                          padding:2px 8px; font-size:10px; }
            QPushButton:hover { background:%s; }
            QTextEdit { background:%s; color:%s; border:none; font-size:11px;
                        padding:4px; selection-background-color:%s;
                        font-family:'Consolas','Courier New',monospace; }
            QScrollArea { background:transparent; border:none; }
        """ % (T('ui_bg'), T('ui_text_dim'), T('ui_code_btn'), T('ui_text_soft'),
               T('ui_code_btn_hover'), T('ui_code_bg'), T('ui_code_text'), T('ui_code_sel')))


def table_card_qss():
    """表格卡片样式（v6.58：颜色全部取自主题 token）"""
    return ("""
            QFrame#tableCard { background:%s; border-radius:8px; }
            QLabel { color:%s; font-size:10px; background:transparent; }
            QPushButton { background:%s; color:%s; border:none; border-radius:4px;
                          padding:2px 8px; font-size:10px; }
            QPushButton:hover { background:%s; }
            QTextEdit { background:%s; color:%s; border:none; font-size:11px;
                        padding:4px; }
            QScrollArea { background:transparent; border:none; }
        """ % (T('ui_bg'), T('ui_text_dim'), T('ui_code_btn'), T('ui_text_soft'),
               T('ui_code_btn_hover'), T('ui_code_bg'), T('ui_code_text')))


class CodeCard(QFrame):
    """代码卡片：标题栏（title + 复制按钮）+ 长行自动换行 + 只读等宽文本（v6.17，v6.58 改换行）"""

    def __init__(self, code, title='代码', parent=None):
        super().__init__(parent)
        self._code = code
        self.setStyleSheet(code_card_qss())                 # v6.58 主题化
        self.apply_theme = lambda: self.setStyleSheet(code_card_qss())   # 切主题时重刷
        self.setObjectName('codeCard')
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 6)
        v.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(QLabel(title))
        bar.addStretch(1)
        self.copy_btn = QPushButton('复制')
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy)
        bar.addWidget(self.copy_btn)
        v.addLayout(bar)
        self.editor = QTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setPlainText(code)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)  # v6.58：长行换行，不再被卡片右缘裁掉
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        v.addWidget(self.editor)
        # 高度智能自适应：内容短完整显示(无滑块)，超过阈值才封顶内部滚动
        QTimer.singleShot(0, self._fit_height)

    def _fit_height(self):
        doc = self.editor.document()
        w = self.editor.viewport().width()
        doc.setTextWidth(w if w > 50 else 360)  # 未布局时用兜底宽度
        h = int(doc.size().height()) + 8
        self.editor.setFixedHeight(max(28, min(260, h)))

    def _copy(self):
        """多格式智能复制：纯文本 + 等宽 HTML，粘贴 Word 保留代码样式（v6.17）"""
        from PySide6.QtCore import QMimeData
        mime = QMimeData()
        mime.setText(self._code)  # text/plain：原始代码（markdown/记事本）
        escaped = self._code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        mime.setHtml(f'<pre style="font-family:Consolas,monospace;white-space:pre-wrap">{escaped}</pre>')
        QApplication.clipboard().setMimeData(mime)
        self.copy_btn.setText('已复制 ✓')
        QTimer.singleShot(1200, lambda: self.copy_btn.setText('复制'))


class TableCard(QFrame):
    """表格卡片：标题栏（表格 + 复制 markdown 原文）+ 只读 HTML 表格（v6.17）"""

    def __init__(self, md_text, html, parent=None):
        super().__init__(parent)
        self._md = md_text
        self.setStyleSheet(table_card_qss())                # v6.58 主题化
        self.apply_theme = lambda: self.setStyleSheet(table_card_qss())  # 切主题时重刷
        self.setObjectName('tableCard')
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 6)
        v.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(QLabel('表格'))
        bar.addStretch(1)
        self.copy_btn = QPushButton('复制')
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy)
        bar.addWidget(self.copy_btn)
        v.addLayout(bar)
        self.editor = QTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setHtml(html)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        v.addWidget(self.editor)
        # 高度智能自适应：内容短完整显示(无滑块)，超过阈值才封顶内部滚动
        QTimer.singleShot(0, self._fit_height)

    def _fit_height(self):
        doc = self.editor.document()
        w = self.editor.viewport().width()
        doc.setTextWidth(w if w > 50 else 360)  # 未布局时用兜底宽度
        h = int(doc.size().height()) + 8
        self.editor.setFixedHeight(max(28, min(220, h)))

    def _copy(self):
        """多格式智能复制：markdown 原文 + HTML 表格 + 纯文本，粘贴时目标程序自动适配（v6.17）"""
        from PySide6.QtCore import QMimeData
        mime = QMimeData()
        mime.setText(self._md)  # text/plain：markdown 原文（记事本/一般编辑器）
        mime.setData('text/markdown', self._md.encode('utf-8'))  # 显式 markdown（Typora/Obsidian 等）
        mime.setHtml(self.editor.toHtml())  # text/html：Word 粘贴自动成真表格
        QApplication.clipboard().setMimeData(mime)
        self.copy_btn.setText('已复制 ✓')
        QTimer.singleShot(1200, lambda: self.copy_btn.setText('复制'))
