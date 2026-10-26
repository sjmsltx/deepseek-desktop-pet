# -*- coding: utf-8 -*-
"""用户消息的正文必须左对齐（2026-10-26，Owner 实测「我自己文本输出排版错误」）

## 缺陷

`pet_bubble.py:117` 原先：
    setAlignment((AlignRight | AlignVCenter) if is_user else (AlignLeft | AlignVCenter))
⇒ 用户消息的**正文**跟着右对齐。把一整段中文贴进输入框发出去，每行都顶到右边、
  换行后更乱，看着像排版坏了。

## 为什么能断定是「对齐」而不是「原文缩进」

Owner 真实存储（`chat_memory_flash.json` → `display[33].text`）里：
    第 3 行 `相关知识`：前导空白 = 0，长度 = 4 字
左对齐时这种零缩进短行只可能出现在**最左边**；而截图里它在**最右边**。

## 为什么不能靠「气泡靠右」来替代

`_new_bubble` 里只有「名字+时间」那行对用户用 `addStretch(1)` 靠右；
正文标签是直接塞进 QVBoxLayout 的，会撑满整行宽度。
⇒ 原先的「用户消息靠右」这个视觉，其实完全由正文那句 AlignRight 冒充。
  正文一右对齐，多行文本就不可读。

用户 / AI 仍有两处区分，不受影响：
  ① 名字+时间那行：用户靠右、AI 靠左
  ② 背景色：`message_label_qss` 用 `user_bubble` / `ai_bubble` 两个 token
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from PySide6.QtCore import Qt  # noqa: E402


def _pb():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import pet_bubble as pb
    return pb


THEME = {
    'user_bubble': '#123456', 'ai_bubble': '#654321', 'bubble_text': '#eeeeee',
    'accent': '#ff0000', 'panel_bg': '#000000',
}


def test_user_text_is_left_aligned():
    """用户消息正文必须左对齐（右对齐会让多行中文每行顶到右边）"""
    pb = _pb()
    lbl = pb.bubble_text_label('第一行<br>相关知识<br>第三行', THEME, is_user=True)
    al = lbl.alignment()
    assert al & Qt.AlignLeft, '用户正文必须是左对齐'
    assert not (al & Qt.AlignRight), (
        '用户正文不能是右对齐 —— 这正是「一整段中文贴进来像排版坏了」的根因'
        '（原文 `相关知识` 那行零缩进、仅 4 字，左对齐只可能在最左边）')


def test_ai_text_is_left_aligned():
    """AI 消息正文左对齐（保持原状，防止改反）"""
    pb = _pb()
    lbl = pb.bubble_text_label('普通回复', THEME, is_user=False)
    al = lbl.alignment()
    assert al & Qt.AlignLeft and not (al & Qt.AlignRight)


def test_user_and_ai_still_distinguishable_by_background():
    """左对齐之后，用户/AI 必须仍能靠背景色区分（别把区分一起改没了）"""
    pb = _pb()
    q_user = pb.message_label_qss(THEME, is_user=True)
    q_ai = pb.message_label_qss(THEME, is_user=False)
    assert q_user != q_ai, '用户与 AI 的气泡样式必须不同（否则改成左对齐后两条消息长得一样）'
    assert THEME['user_bubble'] in q_user
    assert THEME['ai_bubble'] in q_ai


def test_alignment_survives_theme_refresh():
    """切主题刷新（apply_message_label_theme）不得把对齐改回右对齐"""
    pb = _pb()
    lbl = pb.bubble_text_label('多行<br>内容', THEME, is_user=True)
    pb.apply_message_label_theme(lbl, THEME, is_user=True)
    al = lbl.alignment()
    assert al & Qt.AlignLeft and not (al & Qt.AlignRight), (
        '切主题刷新后若变成右对齐，用户会在"换主题之后"再次看到排版错乱')


def test_word_wrap_still_on():
    """必须仍然是自动换行（防止有人为了"左对齐好看"把它关掉导致横向溢出）"""
    pb = _pb()
    lbl = pb.bubble_text_label('很长的文本' * 50, THEME, is_user=True)
    assert lbl.wordWrap() is True
    assert lbl.textFormat() == Qt.TextFormat.RichText
