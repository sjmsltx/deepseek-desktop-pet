# -*- coding: utf-8 -*-
"""关心气泡护栏（v6.60 批 3）

锁住三件事：
1. 关心内容不进聊天列表（`display_msgs`）—— 只进回忆日志；点开才展开成对话
2. 关心气泡外观与普通说话气泡不同（左侧 accent 色条）、停留 ≥8 秒
3. 扒边时不再静默放弃（v6.61：默认只冒气泡不弹人；开关开启则探头说完缩回）

运行：python -m pytest tests/test_care_bubble.py -q
"""
import os
import re
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


class _FakeMem:
    """替代真实的 MemoryEvents（避免测试写进用户真实回忆日志文件）"""

    def __init__(self):
        self.items = []

    def add(self, *a, **k):
        self.items.append((a, k))
        return {}


def _pet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.memories = _FakeMem()
    return p


def test_care_not_in_chat_list_but_in_memories():
    p = _pet()
    n0 = len(p.display_msgs)
    p.say_care('看你连着写了一个多小时了，先喝口水？')
    assert len(p.display_msgs) == n0, '关心内容不该写进聊天列表'
    assert len(p.memories.items) == 1, '关心内容应写入回忆日志'
    assert '喝口水' in str(p.memories.items[0]), '回忆日志内容不对'


def test_care_bubble_has_accent_bar():
    p = _pet()
    p.say_care('测试关心')
    qss = p.bubble.styleSheet()
    t = p.theme or {}
    assert 'border-left' in qss, '关心气泡缺少左侧色条'
    assert (t.get('accent') or '') and t.get('accent') in qss, '色条颜色未取自主题 accent'


def test_care_hold_longer_than_say():
    p = _pet()
    p.say_care('短句')
    care = p._bubble_hold_ms('短句')
    p._reset_bubble_mode()
    say = p._bubble_hold_ms('短句')
    assert care >= 8000, '关心气泡停留应 ≥8 秒'
    assert care > say, '关心气泡应比普通气泡停留更久'


def test_click_expands_to_chat():
    p = _pet()
    p.say_care('点我展开')
    n0 = len(p.display_msgs)
    p._bubble_clicked(None)
    assert len(p.display_msgs) == n0 + 1, '点击后应展开成一条对话'
    assert p._bubble_mode == 'say', '展开后应复位为普通模式'
    assert p._care_click_text == ''


def test_normal_bubble_click_does_nothing():
    p = _pet()
    p.say_plain('普通说话')
    n0 = len(p.display_msgs)
    p._bubble_clicked(None)
    assert len(p.display_msgs) == n0, '普通气泡点击不应写聊天列表'


def test_dock_probe_toggle_controls_popup():
    """回归（v6.60 批 3 → v6.61）：扒边时不再静默放弃关心；是否弹出整个人由开关决定

    - 开关关（默认）：只冒关心气泡，人保持扒边
    - 开关开：弹出来说，说完缩回扒边
    """
    p = _pet()
    p.ai_enabled = False                 # 走随机台词兜底，避免联网
    p.active_chat_enabled = True
    p._is_night = lambda *a, **k: False   # 锁掉深夜静默，免得晚上跑用例时莫名失败
    p.sleeping = False
    p._edge_side, p._edge_mode, p._edge_popped = 'left', 'peek', False
    p._active_chat_next = 0              # 已到点

    # ① 默认（开关关）：不弹人，但关心气泡照旧 —— 不得静默放弃
    p.dock_probe = False
    p._check_active_chat()
    assert p._edge_popped is False and p._dock_rehide is False, \
        '关闭开关时应保持扒边不动（只冒气泡）'
    assert p._bubble_mode == 'care', '仍然要冒关心气泡（不静默放弃）'

    # ② 开关开：弹出来说，说完缩回
    p.dock_probe = True
    p._care_last_at = 0                  # 清冷却（上一步刚 mark 过）
    p._active_chat_next = 0
    p._check_active_chat()
    assert p._dock_rehide is True, '开启开关时应探头，而不是静默放弃'
    assert p._edge_popped is True, '应已从扒边弹出'
    p._probe_timer.stop()
    p._hide_bubble()
    assert p._dock_rehide is False and p._edge_popped is False, '说完应缩回扒边'


def test_source_guard_no_duplicate_care_write():
    """ratchet：关心类不得再「气泡 + 聊天列表」各写一遍"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    calls = re.findall(r"_append_chat\('桌宠',[^\n]*", src)
    bad = ['早安回访', '补发提醒', '提醒：', '你已经连续坐', '早上好！今天是']
    offenders = sorted({w for c in calls for w in bad if w in c})
    assert not offenders, '关心类话术又写回聊天列表了：%s' % offenders


def test_source_guard_say_care_used():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert src.count('self.say_care(') >= 6, '关心通道的调用点被回退了'
