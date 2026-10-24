# -*- coding: utf-8 -*-
"""随机问候不污染聊天面板 + 金额精度（v3.1，2026-10-24）

锁两件事：

1. **随机问候不再写聊天历史** —— Owner 原话（2026-10-24）：
   「固定刷的这玩意儿」「刷了一堆这个东西占着那个面板会看起来非常难受」
   根因：`pet_anim.say_random` 无条件 `_append_chat`，而 `greet_timer`
   每 20~40 分钟自动调一次（间隔 `random.randint` 一次定死 → 看着像「固定刷」）。

2. **金额按 4 位小数显示** —— 单次调用约 ¥0.0089，`%.2f` 会显示成 ¥0.01，
   看着像花了一分钱，实际不到一分。

运行：python -m pytest tests/test_greet_no_history.py -q
"""
import os
import sys
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


class _FakePet(object):
    """只实现 say_random 用到的三个接口（不建 Qt 窗口，跑得快）"""

    def __init__(self, sleeping=False):
        self.sleeping = sleeping
        self.said = []
        self.history = []

    def _char_lines(self, key):
        assert key == 'greetings', '随机问候应取 greetings 台词，实际取 %r' % key
        return ['测试台词']

    def say_plain(self, text, immediate=False):
        self.said.append(text)

    def _append_chat(self, who, text):
        self.history.append((who, text))


# ---------- 行为：气泡照说，历史不写 ----------

def test_auto_greet_shows_bubble_but_skips_history():
    """自动问候（定时器/双击/随机动作）→ 只出气泡，不进面板"""
    from pet_anim import say_random
    w = _FakePet()
    say_random(w)
    assert w.said == ['测试台词'], '自动问候必须照旧出气泡（信息不能丢）'
    assert w.history == [], '自动问候不得写进聊天历史（Owner 反馈「固定刷」）'


def test_explicit_say_still_records_one_line():
    """右键「说点什么」是玩家主动要的 → 保留一条历史"""
    from pet_anim import say_random
    w = _FakePet()
    say_random(w, into_history=True)
    assert w.said == ['测试台词'], '气泡照旧'
    assert w.history == [('桌宠', '测试台词')], '右键主动要的话应留一条'


def test_sleeping_returns_early():
    """睡觉时不说话（保持原行为）"""
    from pet_anim import say_random
    w = _FakePet(sleeping=True)
    say_random(w, into_history=True)
    assert w.said == [] and w.history == [], '睡觉时不得说话'


# ---------- 源码护栏：防止有人把自动路径改回写历史 ----------

def _src(name):
    return Path(os.path.join(BASE, name)).read_text(encoding='utf-8')


def test_only_right_click_menu_passes_into_history():
    """全仓只允许右键菜单一处传 into_history=True"""
    src = _src('desktop_pet.py')
    n = src.count('say_random(into_history=True)')
    assert n == 1, ('只允许「右键 → 说点什么」保留历史，现有 %d 处'
                    '（自动路径又被写回历史了）' % n)
    # 那一处必须就是右键菜单
    for line in src.splitlines():
        if 'say_random(into_history=True)' in line:
            assert "imenu.addAction(T('say'))" in line, 'into_history=True 出现在非右键菜单位置：%s' % line


def test_greet_timer_uses_default_no_history():
    """定时器直连 say_random（不传参 → 默认不进历史）"""
    src = _src('desktop_pet.py')
    assert 'self.greet_timer.timeout.connect(self.say_random)' in src, \
        'greet_timer 接线被改动，请确认自动问候仍走默认（不进历史）'


def test_say_random_wrapper_default_false():
    """PetWidget.say_random 的默认值必须是 False"""
    src = _src('desktop_pet.py')
    assert 'def say_random(self, into_history=False):' in src
    assert 'return anim.say_random(self, into_history=into_history)' in src


# ---------- 金额精度 ----------

def test_money_text_uses_4_decimals():
    """今日花费不再被 %.2f 四舍五入成 0.01"""
    dp = _src('desktop_pet.py')
    assert '今日 ¥%.2f / %d 次' not in dp, '状态条「今日」又被改回 2 位小数'
    assert '今日 ¥%.4f / %d 次' in dp, '状态条「今日」应为 4 位小数'

    gov = _src('governance.py')
    assert '已花 ¥%.2f' not in gov, '闸门卡金额又被改回 2 位小数'
    assert '已花 ¥%.4f' in gov, '闸门卡金额应为 4 位小数'

    st = _src('settings_ui.py')
    assert "lb_today_cost.setText('¥%.2f'" not in st, '设置页今日花费又被改回 2 位小数'
    assert "lb_today_cost.setText('¥%.4f'" in st, '设置页今日花费应为 4 位小数'


def test_00089_keeps_precision():
    """实际数值验证：¥0.0089 不显示成 ¥0.01"""
    assert ('%.4f' % 0.0089) == '0.0089'
    assert ('%.2f' % 0.0089) == '0.01', '2 位确实会显示成 0.01 —— 这就是当初的问题'
