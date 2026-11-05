# -*- coding: utf-8 -*-
"""修复：唤醒路径从不产 emotion（评审-158 §1.3 追到底）

158 观察到「emotion 修了但库里还是 0」。我 304 只修了「解析出 emotion 却只传 display」，
但**解析结果本身一直是 None** —— 因为主唤醒路径 care_engine.judge_wakeup 的 prompt
从来没要求模型输出 emotion（只有回访路径 followup_message 说「可带[emotion:xxx]」）。

实证：库里那条「主动关心：记得站起来活动一下」，
    · 文本不在兜底台词池里（兜底是「要不要站起来走走？我等你回来。」）⇒ 是模型生成的
    · 走的是 _display_wakeup → 已传 emotion_hint
    · 但仍为空 ⇒ 模型没吐标签
    ⇒ 根因在 prompt 契约，不在落盘、也不在解析。

修法（最小改动、复用现成解析）：
    1. judge_wakeup 的 JSON 契约里加 "emotion"，取值限定为 EMOTION_STATE_MAP 的键
    2. _wakeup_worker emit 时若带 emotion，拼成 `[emotion:xxx] ` 前缀 ——
       _display_wakeup 本来就会把标签剥掉并解析，不用改信号签名
    3. 白名单校验：模型给了非法词一律丢弃（不能把垃圾写进回忆）

本文件锁五件事：
A. prompt 里真的要求了 emotion
B. 合法 emotion 能被带到 display
C. 非法 emotion 被丢弃，不污染
D. 没给 emotion 时行为不变（向后兼容）
E. 端到端：judge 返回带 emotion → 真实写到 memories 的 emotion 非空
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import care_engine as ce  # noqa: E402


# ---------- A. prompt 契约 ----------
def test_judge_prompt_asks_for_emotion():
    """judge_wakeup 的 prompt 源码里必须有 emotion 字段要求"""
    src = open(os.path.join(BASE, 'care_engine.py'), encoding='utf-8').read()
    i = src.find('def judge_wakeup')
    j = src.find('def ', i + 10)
    body = src[i:j]
    assert '"emotion"' in body or "'emotion'" in body, \
        'judge_wakeup 的 JSON 契约里没有 emotion —— 模型永远不会给'
    assert 'act' in body and 'message' in body, '原有字段被动了'


def test_prompt_lists_valid_emotion_words():
    """取值必须被约束，否则模型会造词"""
    src = open(os.path.join(BASE, 'care_engine.py'), encoding='utf-8').read()
    i = src.find('def judge_wakeup')
    body = src[i:src.find('def ', i + 10)]
    # 至少要出现几个合法词，说明做了枚举而不是放任
    hits = [w for w in ('happy', 'calm', 'tired', 'thinking', 'shy') if w in body]
    assert len(hits) >= 3, 'prompt 里没枚举合法情绪词：%r' % hits


# ---------- B/C/D. 组装与校验 ----------
def test_emotion_prefix_attached_when_valid():
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    out = p._wrap_wakeup_with_emotion('记得站起来活动一下', 'happy')
    assert out == '[emotion:happy] 记得站起来活动一下', repr(out)
    # 且能被现有解析器还原
    display, emo = p._strip_emotion_tag(out)
    assert display == '记得站起来活动一下'
    assert emo == 'happy'


@pytest.mark.parametrize('bad', ['', None, 'joyful', '开心的', 'happy;rm', 'happ'])
def test_invalid_emotion_dropped(bad):
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    out = p._wrap_wakeup_with_emotion('该休息了', bad)
    assert out == '该休息了', '非法情绪 %r 应被丢弃，实际 %r' % (bad, out)


def test_no_emotion_keeps_message_unchanged():
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    assert p._wrap_wakeup_with_emotion('喝口水吧', '') == '喝口水吧'


def test_all_legal_emotions_accepted():
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    for emo in p.EMOTION_STATE_MAP.keys():
        out = p._wrap_wakeup_with_emotion('x', emo)
        assert out == '[emotion:%s] x' % emo, '合法情绪 %s 被拒了' % emo


# ---------- E. 端到端 ----------
def test_end_to_end_emotion_reaches_memory(tmp_path):
    """judge 返回带 emotion → 走真实 say_care → 写到 memories 的 emotion 非空"""
    import desktop_pet as dp
    import memory_events as me

    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.memories = me.MemoryEvents(str(tmp_path / 'm.json'))

    wrapped = p._wrap_wakeup_with_emotion('记得站起来活动一下', 'calm')
    p._display_wakeup(wrapped)

    items = p.memories.all(p.current)
    assert items, '没写进回忆'
    assert items[-1].get('emotion') == 'calm', \
        'End-to-end 链断了：emotion=%r' % (items[-1].get('emotion'),)


def test_end_to_end_without_emotion_still_works(tmp_path):
    import desktop_pet as dp
    import memory_events as me

    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.memories = me.MemoryEvents(str(tmp_path / 'm.json'))

    p._display_wakeup('记得喝水')
    items = p.memories.all(p.current)
    assert items, '无 emotion 时没写进回忆（回归）'
