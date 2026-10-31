# -*- coding: utf-8 -*-
"""P0 止血：余额播报不得进入 system prompt，也不得写入记忆库

背景（2026-10-31，WX-153 实测 + 我方复验）：
  · memories.json 200 条里 194 条是「主动关心：别处用了约 ¥…」，全部机械可重算
  · prompt_hint 取最近 3 条原样注入，提示词还写着「可以自然提及」
  · ⇒ 模型每轮都被喂三条过期账，且被鼓励说出口（说假话）
  · say_care 的 docstring 写着「不进模型上下文」，实现却在 L6190 写进 memories

Owner 第一原则：能自己查到的不许进记忆。余额 / 花费属于此列。
"""
import io
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from memory_events import MemoryEvents  # noqa: E402

BALANCE_TITLE = '主动关心：别处用了约 ¥0.1500（12:29 → 12:34）'
BALANCE_DETAIL = '别处用了约 ¥0.1500（12:29 → 12:34），余额 ¥29.62'
REAL_TITLE = '用户喜欢喝冰美式咖啡'
REAL_DETAIL = '早上聊到咖啡，他说只喝冰美式'


@pytest.fixture()
def ev(tmp_path):
    return MemoryEvents(str(tmp_path / 'memories.json'))


def _seed_balance(ev, n=3):
    """灌 n 条余额播报（形态与线上真实件一致）"""
    for i in range(n):
        ev.add('flash', 'event',
               '主动关心：别处用了约 ¥0.%d500' % (i + 1),
               '别处用了约 ¥0.%d500（12:%02d → 12:%02d），余额 ¥29.%d2'
               % (i + 1, 20 + i, 25 + i, 60 - i))


# ---------- 核心断言：注入路径必须排除余额播报 ----------
def test_prompt_hint_excludes_balance_report(ev):
    """余额播报不得出现在注入文本里 —— 这是「说假话」的直接来源"""
    _seed_balance(ev, 3)
    hint = ev.prompt_hint('flash')
    assert '别处用了' not in hint, (
        '余额播报被注入 system prompt 了：\n%s' % hint)
    assert '¥' not in hint, '注入文本里仍有金额：\n%s' % hint


def test_prompt_hint_still_returns_real_memories(ev):
    """过滤不能把真回忆一起滤掉 —— 期望值锚点，防「两边都空」假绿"""
    _seed_balance(ev, 3)
    ev.add('flash', 'event', REAL_TITLE, REAL_DETAIL)
    hint = ev.prompt_hint('flash')
    assert REAL_TITLE in hint, '真回忆被误滤了：\n%s' % hint
    assert '别处用了' not in hint, '余额播报仍被注入：\n%s' % hint


def test_prompt_hint_returns_empty_when_only_balance(ev):
    """只剩余额播报时应返回空串，不返回半截标题"""
    _seed_balance(ev, 3)
    assert ev.prompt_hint('flash') == '', '只有噪声时不该产出注入段'


def test_prompt_hint_fills_quota_from_real_memories(ev):
    """噪声占满最近 3 条时，应继续往前找真回忆，而不是返回空"""
    ev.add('flash', 'event', REAL_TITLE, REAL_DETAIL)
    _seed_balance(ev, 5)
    hint = ev.prompt_hint('flash')
    assert REAL_TITLE in hint, (
        '噪声挤占后没回退去取真回忆：\n%s' % hint)


def test_balance_report_not_written_to_memories(ev):
    """根因修复：余额播报根本不该进记忆库"""
    ev.add('flash', 'event', BALANCE_TITLE, BALANCE_DETAIL)
    assert ev.all('flash') == [], (
        '余额播报被写进记忆库了（应被拒绝）：%r' % (ev.all('flash'),))


def test_non_balance_money_memory_is_kept(ev):
    """含金额但不是机械播报的真事实要保留（防过滤过宽）"""
    ev.add('flash', 'event', '用户说他这个月生活费 1500 元', '聊到预算')
    items = ev.all('flash')
    assert len(items) == 1, '真事实被误拒：%r' % (items,)


def test_balance_marker_is_recomputable_classified():
    """余额播报必须被判为可重算类，供迁移分流复用"""
    from memory_events import is_recomputable_notice
    assert is_recomputable_notice(BALANCE_TITLE, BALANCE_DETAIL) is True
    assert is_recomputable_notice(REAL_TITLE, REAL_DETAIL) is False
    assert is_recomputable_notice('主动关心：别处用了约 ¥0.4200', '') is True
    # detail 空、只有 title 也得认出来
    assert is_recomputable_notice('别处用了约 ¥0.0500（12:29 → 12:34）', '') is True
    # 反向：普通问候不是可重算
    assert is_recomputable_notice('问候：早上好', '打了个招呼') is False


def test_recomputable_filter_survives_empty_fields():
    """字段缺失不应抛异常（真实库里 detail 可能为空）"""
    ev2 = MemoryEvents(os.path.join(os.path.dirname(__file__), '_tmp_empty.json'))
    try:
        ev2.add('flash', 'event', '', '')
        assert isinstance(ev2.prompt_hint('flash'), str)
    finally:
        p = os.path.join(os.path.dirname(__file__), '_tmp_empty.json')
        if os.path.exists(p):
            os.remove(p)


def test_real_file_still_readable():
    """线上真实件必须能正常加载，过滤不破坏读取"""
    real = os.path.join(REPO, 'memories.json')
    if not os.path.exists(real):
        pytest.skip('无线上 memories.json')
    n_before = len(io.open(real, encoding='utf-8').read())
    assert n_before > 0
    e = MemoryEvents(real)
    hint = e.prompt_hint('flash')
    assert '别处用了' not in hint, (
        '线上真实件注入文本里仍有余额播报（%d 条库存）：\n%s' % (len(e.all()), hint[:300]))
