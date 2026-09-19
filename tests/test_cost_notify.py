# -*- coding: utf-8 -*-
"""费用/提示气泡：不重叠 + 看得清（v6.61）

使用者反馈（2026-09-19）：
1. API 计费气泡固定在窗口顶部 y=8，**与对话气泡重叠**；
2. 该气泡 1.4 秒全程渐隐，**根本看不清**。
现改为：费用提示走底部状态条（不冲突、停留 6 秒、带今日累计）；
好感/喂食类浮动气泡遇到说话气泡自动下移，并先静止再渐隐。

运行：python -m pytest tests/test_cost_notify.py -q
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
    p._save_cfg_value = lambda *a, **k: True
    return p


def test_cost_goes_to_status_bar_with_long_hold():
    """费用提示应落在底部状态条，且停留 ≥6 秒（原来 1.4 秒渐隐看不清）"""
    p = _pet()
    p._on_cost_bubble(0.0032)
    txt = p.status_bar.text()
    assert '本次' in txt and '今日' in txt, '状态条应显示本次+今日：%r' % txt
    assert '−¥0.0032' in txt or '-¥0.0032' in txt, '应含本次金额（4 位小数）：%r' % txt
    assert not p.status_bar.isHidden(), '状态条应显示出来'
    assert p.status_hide_timer.interval() >= 6000, \
        '费用提示停留应 ≥6 秒，实际 %d ms' % p.status_hide_timer.interval()


def test_cost_does_not_create_top_bubble():
    """费用提示不得再创建窗口顶部浮动气泡（那是与对话气泡重叠的根源）"""
    from affection_ui import CostBubble
    p = _pet()
    p._on_cost_bubble(0.01)
    tops = [b for b in p.findChildren(CostBubble) if b.y() <= 20]
    assert tops == [], '费用提示不应再出现顶部浮动气泡'


def test_pet_bubble_offsets_below_speech_bubble():
    """说话气泡正在显示时，好感/喂食类浮动气泡必须下移，不与它叠在一起"""
    from affection_ui import CostBubble
    p = _pet()
    p.say_plain('正在说话的一句话')
    assert getattr(p, '_speak_busy', False), '前置条件：说话气泡应处于显示中'
    p._show_pet_bubble('好吃！饱食度 100%')
    bs = [b for b in p.findChildren(CostBubble) if b.text() == '好吃！饱食度 100%']
    assert bs, '应创建浮动气泡'
    low = p.bubble.y() + p.bubble.height() + 6
    assert bs[-1].y() >= low - 1, \
        '浮动气泡应排在说话气泡下方（实际 y=%d，说话气泡底 %d）' % (bs[-1].y(), low)


def test_bubble_hold_before_fade():
    """hold_ms>0：先静止满不透明再渐隐；hold_ms=0：与旧行为一致（直接渐隐）"""
    p = _pet()
    from affection_ui import CostBubble
    b = CostBubble(p, '-¥0.003', '#888')
    b.show_bubble(10, 10, duration=1000, hold_ms=1500)
    assert getattr(b, '_group', None) is not None, '应使用「静止 + 渐隐」顺序动画'
    assert b._group.state() != b._group.State.Stopped, '动画应已启动'
    assert b._group.duration() >= 1500 + 1000 - 1, '总时长应≈hold+duration'

    b2 = CostBubble(p, '-¥0.003', '#888')
    b2.show_bubble(10, 10, duration=800)
    assert getattr(b2, '_group', None) is None, '不传 hold_ms 时应走旧的并行渐隐'
    assert b2._pos_anim.state() != b2._pos_anim.State.Stopped


def test_source_guard_cost_notify_wired():
    """源码护栏：费用提示走状态条通道，且不再有顶部 show_bubble"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert 'COST_NOTIFY_MS' in src, '缺少费用提示停留常量'
    body = src.split('def _on_cost_bubble(self, cost):', 1)[1].split('\n    def ', 1)[0]
    assert '_notify(' in body, '费用提示应走 _notify（底部状态条）'
    assert 'show_bubble' not in body, '费用提示不应再创建顶部浮动气泡'
    ui = open(os.path.join(BASE, 'affection_ui.py'), encoding='utf-8').read()
    assert 'hold_ms' in ui, 'CostBubble 应支持「先静止再渐隐」'
