# -*- coding: utf-8 -*-
"""系统状态条护栏（v6.60 批 2）

锁住「污染会话」的根治点：系统通知不再以「桌宠」身份写进聊天列表。
一旦有人把系统话术改回 _append_chat，这里会红灯。

运行：python -m pytest tests/test_status_bar.py -q
"""
import os
import re
import sys
from pathlib import Path

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


def test_status_bar_hidden_by_default():
    p = _pet()
    assert getattr(p, 'status_bar', None) is not None, '缺少 status_bar 控件'
    assert p.status_bar.isHidden(), '状态条默认必须是隐藏的'


def test_notify_does_not_pollute_chat_list():
    """核心：状态提示绝不写进聊天列表（display_msgs）"""
    p = _pet()
    n0 = len(p.display_msgs)
    p._notify('💾 记忆已备份：E:\\备份')
    assert len(p.display_msgs) == n0, '状态提示被写进了聊天列表（污染回归）'
    # v3.3（Owner 2026-10-24「统一走人物弹出气泡」）：短提示改显现在人物气泡，
    #   不再显示底部状态条。断言随之改「气泡里能看到」——
    #   ⛔ 上面的污染断言一字未动（这是本条的核心，不许因换地方而放松）。
    assert p.status_bar.text() == '💾 记忆已备份：E:\\备份', '文本仍要写进状态条（兜底）'
    assert p.bubble.text() == '💾 记忆已备份：E:\\备份', '短提示应显现在人物气泡'
    assert not p.bubble.isHidden(), '气泡应显示出来'
    assert p.status_bar.isHidden(), '走了气泡就不该同时留底部条（同一句话不出现两遍）'


def test_append_chat_still_records_conversation():
    """对照：对话内容仍要进聊天列表

    ⚠️ 2026-09-26（D1 批次附带发现 ✓）：原断言 `len == n0 + 1` 在 `display_msgs` **已满 300** 时必红 ✗
    —— `_append_chat` 追加后**裁到 300** ✓（`:5733-5734` ✓ 设计如此 ✓），故满表时 len 不变 ✗。
    ⭐ 且当 Owner 真实聊天档已被**闸门刷屏**写满 300 条 ✗（本次缺陷的数据后果 ✓）时必红 ✗。
    → 改断言**内容落入** ✓（不放松 ✓：反而更直接证明“进聊天列表”✓，且不受满表影响 ✓）
    """
    p = _pet()
    n0 = len(p.display_msgs)
    p._append_chat('桌宠', '这是一条真正的对话内容')
    assert p.display_msgs[-1]['text'] == '这是一条真正的对话内容', '对话内容必须仍进聊天列表'
    assert len(p.display_msgs) in (n0 + 1, 300), '满表时列表长度保持 300 ✓'


def test_status_bar_auto_hide_timer():
    """短提示走气泡后，自动隐藏由气泡的计时器负责（v3.3）"""
    p = _pet()
    p._notify('会自动消失')
    assert p.bubble_hide_timer.isActive(), '气泡应启动自动隐藏计时'
    assert p.bubble_hide_timer.interval() >= p.BUBBLE_HOLD_MIN_MS, \
        '气泡停留不应短于下限 %d ms' % p.BUBBLE_HOLD_MIN_MS


def test_long_notify_still_uses_status_bar():
    """长文本/多行仍走底部状态条（气泡装不下会把窗口撑爆）"""
    p = _pet()
    long_txt = '很长的诊断信息' * 8          # 56 字 > NOTIFY_BUBBLE_MAX_CHARS(40)
    p._notify(long_txt)
    assert p.status_bar.text() == long_txt
    assert not p.status_bar.isHidden(), '长文本应仍显示底部状态条'
    assert p.status_bar.isHidden() is False


def test_notify_ms_passed_to_bubble_hold():
    """调用方明确要的停留时长要传递到气泡（否则 8 秒提示被缩短成 6 秒）"""
    p = _pet()
    p._notify('余额 ¥70.68', ms=8000)
    assert p.bubble_hide_timer.interval() == 8000, \
        'ms=8000 没传到气泡停留，实际 %d' % p.bubble_hide_timer.interval()


def test_notify_ignores_empty():
    p = _pet()
    p._notify('   ')
    assert p.status_bar.text() in ('', '💾 记忆已备份：E:\\备份')  # 未被空串覆盖成空文本也可接受


def test_status_bar_uses_theme_tokens():
    """配色必须来自主题（不得写死颜色）"""
    p = _pet()
    qss = p.status_bar.styleSheet()
    t = p.theme or {}
    vals = [t.get('say_bg'), t.get('panel_bg'), t.get('hint_text'), t.get('text')]
    assert 'background' in qss and 'color' in qss, '状态条样式未生效'
    assert any(v and v in qss for v in vals), '状态条配色未取自主题 token'


def test_source_guard_system_notices_moved_out():
    """ratchet：系统类话术不得再出现在 _append_chat('桌宠', …) 里"""
    src = Path(os.path.join(BASE, 'desktop_pet.py')).read_text(encoding='utf-8')
    calls = re.findall(r"_append_chat\('桌宠',[^\n]*", src)
    bad_words = ['已备份', '已导出', '已导入', '存档并清空', '已切换 Live2D', '开机自启',
                 '配置保存失败', '回复风格', '默认城市', '采样温度', '贴边模式切换',
                 '主动关心已', '前台程序感知：已', '已设置提醒', '没有可导出的聊天记录',
                 '截图失败', '图片处理失败', '正在识别图片文字']
    offenders = sorted({w for c in calls for w in bad_words if w in c})
    assert not offenders, '以下系统话术又写回聊天列表了：%s' % offenders


def test_source_guard_notify_widely_used():
    """迁移不能被悄悄回退：_notify 调用点应保持在一个下限之上"""
    src = Path(os.path.join(BASE, 'desktop_pet.py')).read_text(encoding='utf-8')
    n = src.count('self._notify(')
    assert n >= 55, '_notify 调用点从 64 掉到 %d，疑似被回退' % n

def test_queue_full_falls_back_to_status_bar():
    """气泡队列满时回落底部状态条 —— **信息不能丢**（v3.3 设计要点）

    背景：`say_plain` 在 `_speak_busy` 且队列已满（BUBBLE_QUEUE_MAX=2）时
    **静默丢弃**新文本。状态提示（"已保存""查询失败"）比闲聊重要，
    宁可回落底部条，也不能让它消失。
    """
    p = _pet()
    p._speak_busy = True
    p._speak_queue = [('占位1', True), ('占位2', True)]     # 队列已满
    try:
        p._notify('保存失败：磁盘已满')
        assert p._speak_queue and len(p._speak_queue) == p.BUBBLE_QUEUE_MAX, \
            '队列不该被再塞进第 3 条（应为回落而不是硬塞）'
        assert p.status_bar.text() == '保存失败：磁盘已满', '队列满时应回落状态条'
        assert not p.status_bar.isHidden(), '回落时必须真的显示出来（否则信息丢了）'
    finally:
        p._speak_busy = False
        p._speak_queue = []


def test_bubble_not_ready_falls_back_to_status_bar():
    """气泡控件还没建好（启动早期）时回落状态条"""
    p = _pet()
    p.bubble = None
    try:
        p._notify('启动早期提示')
        assert p.status_bar.text() == '启动早期提示'
        assert not p.status_bar.isHidden()
    finally:
        pass
