# -*- coding: utf-8 -*-
"""朗读内容策略：「要求背/念原文」时不许被摘要压掉，也不许念出开场寒暄。

⛔ 这组存在的理由（Owner 2026-10-31 实测）：
   他让桌宠背一首 1360 字的诗，日志显示：
     AI 气泡：深呼吸，我开始背啦
     _speak_reply.policy | 用 AI 摘要
     朗读实况：原 1360 字 → 实际念 60 字
   ⇒ 只念了摘要，等于没背。

   根因三重：
     ① `set_voice_summary` 的工具描述没有「背原文时别调」的例外
     ② 回灌提示把「给摘要」当成「背诵没念完」的补救方案
     ③ `choose_speech_text` 只要 summary 非空就无脑用，没有内容判据兜底

   ①② 靠模型听话，③ 才是兜底。本文件钉住 ③。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import voice_io as vio  # noqa: E402

POEM = """深呼吸，我开始背啦
静夜思
床前明月光，疑是地上霜。
举头望明月，低头思故乡。
登鹳雀楼
白日依山尽，黄河入海流。
欲穷千里目，更上一层楼。
春晓
春眠不觉晓，处处闻啼鸟。
夜来风雨声，花落知多少。
相思
红豆生南国，春来发几枝。
愿君多采撷，此物最相思。"""

ESSAY = """关于这个问题的分析，我分成几个方面来说。

第一，从需求层面看，用户真正想要的是能够被耳朵完整接收的内容，而不是被压缩过的要点。
这一点在很多场景下都会出现，尤其是当内容本身具有文学性或者需要逐字记忆的时候。

第二，从实现层面看，摘要策略的初衷是降低听觉负担，避免用户被迫听完一大段与技术细节
无关的内容。这个初衷是合理的，但它的适用边界被忽略了。

第三，从体验层面看，判断标准不应该是字数，而应该是内容的性质。"""


def test_poem_with_summary_reads_full_text_not_summary():
    """⭐ 背诗 + AI 给了摘要 ⇒ 必须念全文，不能念摘要"""
    picked, note = vio.choose_speech_text(POEM, 'summary', summary='我读了第一句，其余略。')
    assert '韵文' in note, '没走韵文判据（备注：%r）' % (note,)
    assert len(picked) > 100, '只念了 %d 字，等于没背' % len(picked)
    assert '床前明月光' in picked and '此物最相思' in picked, '诗的内容缺失'
    assert '我读了第一句' not in picked, '居然念的是摘要'


def test_poem_strips_opening_preamble():
    """⭐ 开场寒暄「深呼吸，我开始背啦」不许被念出来"""
    picked, _ = vio.choose_speech_text(POEM, 'summary', summary='略。')
    assert '深呼吸' not in picked, '开场寒暄被念出来了'
    first = picked.splitlines()[0] if picked.splitlines() else ''
    assert ('静夜思' in first) or ('床前明月光' in first), \
        '剥寒暄剥过头了：%r' % (picked[:40],)


def test_prose_still_uses_summary():
    """普通散文长回复仍然用摘要（不能为了修诗词把摘要功能弄坏）"""
    picked, note = vio.choose_speech_text(ESSAY, 'summary', summary='讲了需求、实现、体验三方面。')
    assert note == '用 AI 摘要', '散文被误判成韵文（备注：%r）' % (note,)
    assert picked == '讲了需求、实现、体验三方面。'


def test_full_mode_also_strips_preamble():
    """mode=full 也要剥开场寒暄（Owner：「全读会读出问候语」）"""
    picked, note = vio.choose_speech_text(POEM, 'full')
    assert '深呼吸' not in picked, 'full 模式仍念出寒暄'
    assert '床前明月光' in picked and '此物最相思' in picked, 'full 模式丢内容'
    assert '剥开场寒暄' in note


def test_short_reply_not_emptied_by_preamble_strip():
    """极短回复（整句就是一句寒暄）不许被剥成空"""
    for s in ('好的，已经帮你看过了。', '嗯。', '好'):
        picked, _ = vio.choose_speech_text(s, 'full')
        assert picked, '被剥成空了：%r' % (s,)


def test_verse_detector_does_not_fire_on_prose():
    """判据本身：散文不该被判成韵文"""
    assert vio._looks_like_verse(ESSAY) is False
    assert vio._looks_like_verse(POEM) is True


def test_preamble_strip_only_touches_leading_lines():
    """剥寒暄只动开头，不动正文中间的句子"""
    text = '好的\n静夜思\n床前明月光，疑是地上霜。\n举头望明月，低头思故乡。\n'
    out = vio._strip_preamble(text)
    assert '好的' not in out
    assert '静夜思' in out and '低头思故乡' in out
