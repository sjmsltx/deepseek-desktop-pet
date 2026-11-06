# -*- coding: utf-8 -*-
"""流式正文渲染不得重复/漏块（2026-11-06）

## 为什么有这份测试

Owner 报：「有的时候 AI 回复的内容还是会渲染不完全到真正的回复框中，反而到思考过程里去了。」

实测根因（两条叠加）：
  1. `_maybe_incremental_render` 里 `_rerender_rich(text)` 传**全文**，富文本块已画过前几块
  2. 紧接着 `_on_stream` 又 `setText(self._stream_text)` 把**全文**塞进流式 label
⇒ 同一段内容在气泡里出现两次（实测「第一段话」出现 2 次）。

## 口径（本文件锁住）

· 富文本块只画**已完成块**（最后一个块可能还没写完）
· 流式 label 只显示**还没画到的那一段原文**
· 两者严格互补，不重叠、不漏
· 流结束时 `_display_ai_reply` 会全量重渲染，最终布局必须与原文顺序一致
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication, QLabel   # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp    # noqa: E402


def _pet():
    """用产品真实入口造实例；只打桩落盘/网络等副作用"""
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._save_chat_memory = lambda *a, **k: True
    p._speak_reply = lambda *a, **k: None
    p._apply_emotion = lambda *a, **k: None
    p._record_api_usage = lambda *a, **k: None
    p.show()
    _app.processEvents()
    # 走产品自己的重置口径（与 ask_ai 里那段一致）
    p._thinking_label = None
    p._stream_active = False
    p._stream_rendered = False
    p._stream_text = ''
    p._stream_pending = ''
    p._thinking_pending = ''
    p._stream_render_len = 0
    p._stream_done_blocks = 0
    p._stream_last_render = 0.0
    return p


def _feed(p, body, chunk=7):
    """按 chunk 喂流式正文"""
    for i in range(0, len(body), chunk):
        p._on_stream(body[i:i + chunk])
        _app.processEvents()


def _body_items(p):
    """正文区里所有控件显示的文字（排除思考区）"""
    content = p._chat_type_content
    out = []
    for i in range(content.count()):
        item = content.itemAt(i)
        w = item.widget()
        if w is None or w is p._thinking_label:
            continue
        if isinstance(w, QLabel):
            out.append(('label', w.text()))
        else:
            out.append(('card', ' '.join(lb.text() for lb in w.findChildren(QLabel))))
    return out


def _joined(items):
    return '\n'.join(t for _k, t in items)


# ---------- A. 流式过程中：label 不得重复已完成块 ----------
def test_streaming_label_has_no_overlap_with_rendered_blocks():
    """边流边渲染时，label 的内容不能和富文本块重叠"""
    p = _pet()
    body = '第一段话。\n\n```python\nprint(1)\n```\n\n最后一句。'
    _feed(p, body)

    items = _body_items(p)
    joined = _joined(items)
    assert joined.count('第一段话') == 1, (
        '「第一段话」出现 %d 次 —— 富文本块与流式 label 重复了' % joined.count('第一段话'))
    p.close()


def test_streaming_cursor_advances_monotonically():
    """_stream_render_len 只增不减，且不超过已收到的正文长度"""
    p = _pet()
    body = '开头。\n\n```py\nx=1\n```\n\n结尾。'
    prev = -1
    for i in range(0, len(body), 5):
        p._on_stream(body[i:i + 5])
        _app.processEvents()
        cur = p._stream_render_len
        assert cur >= prev, '_stream_render_len 回退了（%d → %d）' % (prev, cur)
        assert cur <= len(p._stream_text) + 1, (
            '游标 %d 超过已收到正文 %d' % (cur, len(p._stream_text)))
        prev = cur
    p.close()


# ---------- B. 收尾后：布局与原文一致 ----------
CASES = [
    ('纯文本', '今天天气不错。\n\n要不要出去走走？', []),
    ('含代码块', '第一段话。\n\n```python\nprint(1)\n```\n\n最后一句。', ['第一段话', '最后一句']),
    ('含表格', '看表：\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n完事。', ['看表', '完事']),
    ('两段代码', '一：\n```\nx=1\n```\n中间说明。\n```\ny=2\n```\n结束。', ['一：', '中间说明', '结束']),
]


@pytest.mark.parametrize('name,body,frags', CASES)
def test_final_layout_matches_source(name, body, frags):
    """流结束 + 全量重渲染后：每段内容只出现原文那么多次，且不留围栏"""
    p = _pet()
    _feed(p, body)
    p._on_stream_done()
    _app.processEvents()
    p._display_ai_reply(body)      # 产品收尾路径（含全量重渲染）
    _app.processEvents()

    items = _body_items(p)
    joined = _joined(items)
    for frag in frags:
        want, got = body.count(frag), joined.count(frag)
        assert got == want, (
            '[%s] 「%s」原文 %d 次，显示 %d 次' % (name, frag, want, got))
    assert '```' not in joined, '[%s] 正文里残留代码围栏' % name
    p.close()


def test_code_block_renders_as_card_not_raw_text():
    """含代码块时，必须出现代码卡（而不是把 ``` 当普通文本显示）"""
    p = _pet()
    body = '看这段：\n\n```python\nprint("hi")\n```\n\n就这样。'
    _feed(p, body)
    p._on_stream_done()
    _app.processEvents()
    p._display_ai_reply(body)
    _app.processEvents()

    items = _body_items(p)
    kinds = [k for k, _t in items]
    assert 'card' in kinds, '没有渲染出任何卡片（代码块没被识别）'
    assert '```' not in _joined(items), '代码围栏漏进正文'
    p.close()


# ---------- C. 源码护栏 ----------
def test_stream_label_never_gets_full_text():
    """`_stream_label.setText` 不得再直接吃 `_stream_text` 全文

    这是 bug 3 的回潮护栏：两处（_on_stream / _on_stream_done）都必须是切片。
    """
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    bad = [ln for ln in src.split('\n')
           if 'setText(self._stream_text)' in ln and not ln.lstrip().startswith('#')]
    assert not bad, (
        '发现 %d 处 setText(self._stream_text) 全文刷新：\n%s'
        % (len(bad), '\n'.join(b.strip() for b in bad)))
