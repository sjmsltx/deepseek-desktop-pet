# -*- coding: utf-8 -*-
"""朗读内容策略（v6.76）

使用者反馈：“现在会直接念完整个输出文本” → 新增策略：
  full（全文，旧行为）/ summary（要点优先，默认）/ manual（只念我选中的）
summary 优先用 AI 通过工具 `set_voice_summary` 给的摘要；没给就**兜底**取“首段 + 末段”，
跳过代码块 / 表格 / 长列表。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import voice_io as vio                                           # noqa: E402

LONG = """## 结论

这次改动共三处，主要是权限闸门补了文件 API。

- 要点一：权限声明
- 要点二：AST 判据
- 要点三：测试覆盖
- 要点四：文档同步

```python
print('code should not be read')
```

| 列A | 列B |
|---|---|
| 1 | 2 |

最后一段是收尾，说明下一步会做什么。
"""


def test_manual_mode_speaks_nothing():
    txt, note = vio.choose_speech_text(LONG, 'manual')
    assert txt == '' and 'manual' in note


def test_full_mode_returns_full_text():
    txt, _note = vio.choose_speech_text(LONG, 'full')
    assert txt == LONG


def test_summary_mode_prefers_ai_summary():
    txt, note = vio.choose_speech_text(LONG, 'summary', summary='一句话摘要')
    assert txt == '一句话摘要' and '摘要' in note


def test_summary_mode_falls_back_to_first_and_last():
    txt, note = vio.choose_speech_text(LONG, 'summary')
    assert '结论' in txt, txt[:40]
    assert '收尾' in txt, txt[:60]
    assert 'print(' not in txt, '代码块不该被念'
    assert '列A' not in txt, '表格不该被念'
    assert '要点四' not in txt, '长列表不该被念'
    assert '兜底' in note


def test_summary_short_text_keeps_all():
    txt, _ = vio.choose_speech_text('就一句话。', 'summary')
    assert txt == '就一句话。'


def test_summary_empty_text():
    assert vio.choose_speech_text('', 'summary')[0] == ''
    assert vio.choose_speech_text('   ', 'summary')[0] == ''


def test_summary_only_code_falls_back_to_full():
    txt, note = vio.choose_speech_text('```\nprint(1)\n```', 'summary')
    assert 'print' in txt and '全文' in note


@pytest.mark.parametrize('mode', ['SUMMARY', 'Full', 'manual', 'nonsense'])
def test_mode_is_case_insensitive_and_safe(mode):
    txt, _note = vio.choose_speech_text('一段话。', mode)
    assert isinstance(txt, str)
