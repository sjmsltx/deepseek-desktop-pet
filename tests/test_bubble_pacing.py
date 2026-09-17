# -*- coding: utf-8 -*-
"""气泡节奏与队列护栏（v6.60）

锁住「拟人化改造」的三件事，防止以后又退回等速打字机 / 覆盖式气泡：
1. 节奏：思考停顿 → 逐字随机 + 标点停顿 → 长文本整段渐显
2. 停留：最短 6 秒（关心类不能一闪而过）
3. 队列：正在显示时新消息排队，不覆盖；悬停暂停

运行：python -m pytest tests/test_bubble_pacing.py -q
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _pet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True   # 测试不落盘
    return p


def test_constants_sane():
    p = _pet()
    assert p.BUBBLE_HOLD_MIN_MS >= 6000, '最短停留不该低于 6 秒'
    assert p.BUBBLE_TYPE_FAST_MS < p.BUBBLE_TYPE_SLOW_MS, '逐字速度应有随机区间'
    assert 1 <= p.BUBBLE_QUEUE_MAX <= 3, '排队上限应在 1~3 条之间'
    assert p.BUBBLE_LONG_TEXT_CHARS > 0


def test_hold_duration_grows_with_length():
    p = _pet()
    assert p._bubble_hold_ms('短') == p.BUBBLE_HOLD_MIN_MS
    long_t = '字' * 100
    assert p._bubble_hold_ms(long_t) == 100 * p.BUBBLE_HOLD_PER_CHAR + p.BUBBLE_HOLD_BASE_MS
    assert p._bubble_hold_ms(long_t) > p._bubble_hold_ms('短')


def test_char_delay_has_punctuation_pauses():
    p = _pet()
    p.type_buffer = '你好，世界。'          # 索引：0你 1好 2， 3世 4界 5。
    assert p._char_delay(3) == p.BUBBLE_PAUSE_COMMA_MS, '逗号后应有停顿'
    assert p._char_delay(6) == p.BUBBLE_PAUSE_SENTENCE_MS, '句末后应有更长停顿'
    p.type_buffer = '第一行\n第二行'
    assert p._char_delay(4) == p.BUBBLE_PAUSE_NEWLINE_MS, '换行后应有停顿'


def test_char_delay_is_random_not_constant():
    """等速打字机正是「人机感」的来源——这里锁住它必须是随机的"""
    p = _pet()
    p.type_buffer = 'abcdefghij'
    vals = {p._char_delay(i) for i in range(1, 11) for _ in range(30)}
    assert all(p.BUBBLE_TYPE_FAST_MS <= v <= p.BUBBLE_TYPE_SLOW_MS for v in vals)
    assert len(vals) > 1, '逐字间隔必须随机（不能恒定为某一个值）'


def test_long_text_shows_at_once():
    p = _pet()
    long_t = '长' * (p.BUBBLE_LONG_TEXT_CHARS + 5)
    p.say_plain(long_t)
    assert p.type_index == len(long_t), '长文本应整段出现'
    assert not p.type_timer.isActive(), '长文本不该走逐字定时器'


def test_queue_instead_of_overwrite():
    """核心回归：旧实现是后者直接覆盖前者（type_timer.stop + 重设文本）"""
    p = _pet()
    p.say_plain('第一条')
    assert p._speak_busy and p.type_buffer == '第一条'
    p.say_plain('第二条')
    p.say_plain('第三条')
    p.say_plain('第四条')
    assert p.type_buffer == '第一条', '正在显示的内容不该被新消息覆盖'
    assert len(p._speak_queue) == p.BUBBLE_QUEUE_MAX, '排队上限未生效'
    p._hide_bubble()
    assert not p._speak_busy
    assert len(p._speak_queue) == p.BUBBLE_QUEUE_MAX - 1, '隐藏后应出队一条'


def test_immediate_also_queues():
    """状态/关心类（immediate）也不能打断正在说的那条"""
    p = _pet()
    p.say_plain('正在说的一句')
    p.say_plain('提醒：喝水', immediate=True)
    assert p.type_buffer == '正在说的一句'
    assert p._speak_queue and p._speak_queue[0][1] is True


def test_hover_pauses_timers():
    p = _pet()
    p.say_plain('悬停暂停测试')
    p._bubble_hover(True)
    assert p._bubble_hover_paused
    assert not p.bubble_hide_timer.isActive(), '悬停时不该继续倒计时隐藏'
    assert not p.type_timer.isActive(), '悬停时不该继续打字'
    p._bubble_hover(False)
    assert not p._bubble_hover_paused
    assert p.type_timer.isActive(), '移开后应继续打字'


def test_empty_text_ignored():
    p = _pet()
    p.say_plain('')
    assert not p._speak_busy
    assert not p._speak_queue
