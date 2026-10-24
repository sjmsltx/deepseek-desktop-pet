# -*- coding: utf-8 -*-
"""闸门卡「同因原地替换」验收（Owner 2026-10-23 选的方案 B）

Owner 报的现象：到上限后卡片把之前发的消息全都顶掉了。
实测：60 条历史里 43 条是同一张卡（14 个时间点 × 3 条）。

本文件钉住：
  ① 同因重复出卡 → display_msgs **长度不增**，只更新最后一条
  ② 不同因 → 各占一条
  ③ 非闸门卡（上游故障/工具失败）行为不变（照旧追加）
  ④ 真仓库里的历史污染基线：显示条数与卡片条数可复核
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ── 最小宿主：只带方案 B 需要的东西（不打真 GUI）──────────────────────
class _Host:
    _GATE_CARD_MARKS = ('出在哪：本地闸门', '出在哪：额度')

    def __init__(self):
        self.display_msgs = []
        self._rendered = []

    # 复用真实实现的三个方法（不造假）
    def _gate_card_key_of(self, text):
        import desktop_pet as dp
        return dp.PetWidget._gate_card_key_of(self, text)

    def _show_gate_card(self, key, text):
        import desktop_pet as dp
        return dp.PetWidget._show_gate_card(self, key, text)

    def _cost_gate_key(self, why):
        import desktop_pet as dp
        return dp.PetWidget._cost_gate_key(self, why)

    # 界面与落盘用替身（本测试只关心数据结构与是否新增）
    def _new_bubble(self, who, ts, is_user=False, text=''):
        class _W:
            _gate_key = ''
            _content_layout = object()
        class _C:
            def addWidget(self, w):
                pass
        self._rendered.append((who, ts, text))
        return _W(), _C()

    def _find_last_gate_bubble(self, key):
        return None          # 替身不打界面，走「只改数据」分支

    def _bubble_text_label(self, *a, **k):
        return object()

    def _save_chat_memory(self):
        pass

    def _chat_scroll_bottom(self):
        pass


def _card(reason_layer, detail):
    return ("❌ 这一轮没答上：" + detail + "\n"
            "　· 出在哪：" + reason_layer + "\n"
            "　· 影响：本次调用未发出\n"
            "　· 下一步：等到次日额度重置")


def test_same_reason_replaces_in_place():
    """同因重复 → 长度只增一次，后续是改写"""
    h = _Host()
    c1 = _card('本地闸门', '今日模型调用已花 ¥21.00（截至 23:21），已达默认上限 ¥20.00')
    c2 = _card('本地闸门', '今日模型调用已花 ¥25.30（截至 23:40），已达默认上限 ¥20.00')

    assert h._show_gate_card(h._gate_card_key_of(c1), c1) == 'appended'
    assert len(h.display_msgs) == 1

    assert h._show_gate_card(h._gate_card_key_of(c2), c2) == 'replaced'
    assert len(h.display_msgs) == 1, '同因第二次必须原地替换，不许追加'
    assert '¥25.30' in h.display_msgs[-1]['text'], '必须更新为新金额'
    assert h.display_msgs[-1]['gate_key'] == 'daily_cost'


def test_different_reason_appends():
    """不同因（余额 vs 日上限）各占一条"""
    h = _Host()
    a = _card('本地闸门', '今日模型调用已花 ¥21.00（截至 23:21），已达默认上限 ¥20.00')
    b = _card('额度', '今日模型调用已花 ¥3.00，余额不足 ¥1.00')

    h._show_gate_card(h._gate_card_key_of(a), a)
    h._show_gate_card(h._gate_card_key_of(b), b)
    assert len(h.display_msgs) == 2
    assert h.display_msgs[0]['gate_key'] == 'daily_cost'
    assert h.display_msgs[1]['gate_key'] == 'balance'


def test_repeat_many_times_stays_one():
    """连续被拦 10 次 → 仍然只有 1 条（这正是 Owner 报的场景）"""
    h = _Host()
    for i in range(10):
        c = _card('本地闸门', '今日模型调用已花 ¥2%d.00（截至 23:5%d），已达默认上限 ¥20.00' % (i, i))
        h._show_gate_card(h._gate_card_key_of(c), c)
    assert len(h.display_msgs) == 1, '被拦 10 次却留下 %d 条卡' % len(h.display_msgs)
    assert '¥29.00' in h.display_msgs[-1]['text'], '应是最后一次的金额'


def test_non_gate_card_not_treated_as_gate():
    """上游故障卡不是闸门卡 → _gate_card_key_of 必须返回空（行为不变）"""
    h = _Host()
    up = _card('上游故障', 'DeepSeek 服务返回 502')
    assert h._gate_card_key_of(up) == '', '上游故障卡不该被当闸门卡'


def test_plain_reply_not_gate_card():
    h = _Host()
    assert h._gate_card_key_of('这是一条普通 AI 回复') == ''
    assert h._gate_card_key_of('') == ''
    assert h._gate_card_key_of(None) == ''


def test_existing_history_is_polluted_baseline():
    """记录现状基线：真仓库历史里卡片占比（只读，不改）

    Owner 2026-10-23 报「消息被覆盖」时，实测 60 条里 43 条是卡。
    本用例只断言「读得到、能数」，不断言具体数字（历史会随使用变化）。
    """
    import io
    import json
    p = os.path.join(ROOT, 'chat_memory_flash.json')
    if not os.path.exists(p):
        pytest.skip('本机无 chat_memory_flash.json')
    d = json.load(io.open(p, encoding='utf-8'))
    disp = d.get('display') or []
    cards = [m for m in disp if isinstance(m, dict)
             and '这一轮没答上' in str(m.get('text', ''))]
    print('历史共 %d 条，其中失败卡 %d 条' % (len(disp), len(cards)))
    assert isinstance(disp, list)
