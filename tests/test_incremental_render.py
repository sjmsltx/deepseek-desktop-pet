# -*- coding: utf-8 -*-
"""增量 markdown 渲染（v6.76）

使用者反馈：“文本是全部输出之后才统一渲染的，为什么不改成边输出边渲染”。
实测原行为：流式期间正文一直是纯文本（Qt.PlainText），只有流式结束才富文本化。

本测试锁定新机制：**块级增量渲染** —— 中途就有富文本控件出现，且不抛异常。
"""
import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

REPLY = """## 结论

这是**加粗**的关键点。

- 要点一
- 要点二

```python
print('hi')
```

收尾一段。
"""


@pytest.fixture(scope='module')
def pet():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    return p


def _widget_types(pet):
    content = getattr(pet, '_chat_type_content', None)
    out = []
    if content is not None:
        for j in range(content.count()):
            w = content.itemAt(j).widget()
            if w is not None:
                out.append(type(w).__name__)
    return out


def test_incremental_render_builds_rich_blocks_midstream(pet, monkeypatch):
    """流式期间就该出现富文本控件

    ⚠ 必须固定时间源：本功能有 200ms 节流（`_maybe_incremental_render`），
    靠 `time.sleep(0.07)` 撞窗口的结果随机器快慢变化 ——
    实测同一份代码，4 片喂完时「片 4 与片 2 的间隔」恰好压在 0.2s 临界，
    处理耗时稍快就被节流拦住、代码块永远没渲染成卡片（2026-11-06）。
    这里让 `monotonic` 每次调用推进 0.5s，与真实耗时解耦。
    """
    import time as _time_mod
    clock = [1000.0]

    def _fake_monotonic():
        clock[0] += 0.5
        return clock[0]

    monkeypatch.setattr(_time_mod, 'monotonic', _fake_monotonic)

    pet._chat_type_stream_begin()
    pet._stream_active = True
    pet._stream_rendered = False
    pet._stream_text = ''
    for i in range(0, len(REPLY), 20):
        pet._on_stream(REPLY[i:i + 20])
    assert pet._stream_done_blocks > 0, '流式期间没有提交任何已完成块 → 增量渲染没生效'
    types = _widget_types(pet)
    assert types, '气泡里没有正文控件'
    assert 'CodeCard' in types, '代码块应已渲染成卡片（而不是纯文本）：%s' % types


def test_plain_text_stream_not_rerendered(pet):
    """纯文本流式不该触发重渲染（快路径不能被破坏）"""
    pet._chat_type_stream_begin()
    pet._stream_active = True
    pet._stream_rendered = False
    pet._stream_text = ''
    for i in range(0, len('这是一段没有 markdown 的普通回复内容。' * 4), 10):
        pet._on_stream(('这是一段没有 markdown 的普通回复内容。' * 4)[i:i + 10])
        time.sleep(0.06)
    assert pet._stream_done_blocks == 0


def test_stream_new_label_creates_plain_label(pet):
    pet._chat_type_stream_begin()
    lb = pet._stream_new_label()
    assert lb is not None
