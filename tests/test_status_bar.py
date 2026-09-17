# -*- coding: utf-8 -*-
"""系统状态条护栏（v6.60 批 2）

锁住「污染会话」的根治点：系统通知不再以「桌宠」身份写进聊天列表。
一旦有人把系统话术改回 _append_chat，这里会红灯。

运行：python -m pytest tests/test_status_bar.py -q
"""
import os
import re
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
    assert p.status_bar.text() == '💾 记忆已备份：E:\\备份'
    assert not p.status_bar.isHidden(), '状态条应显示出来'


def test_append_chat_still_records_conversation():
    """对照：对话内容仍要进聊天列表"""
    p = _pet()
    n0 = len(p.display_msgs)
    p._append_chat('桌宠', '这是一条真正的对话内容')
    assert len(p.display_msgs) == n0 + 1, '对话内容必须仍进聊天列表'


def test_status_bar_auto_hide_timer():
    p = _pet()
    p._notify('会自动消失')
    assert p.status_hide_timer.isActive(), '状态条应启动自动隐藏计时'
    assert p.status_hide_timer.interval() == p.STATUS_MS


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
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    calls = re.findall(r"_append_chat\('桌宠',[^\n]*", src)
    bad_words = ['已备份', '已导出', '已导入', '存档并清空', '已切换 Live2D', '开机自启',
                 '配置保存失败', '回复风格', '默认城市', '采样温度', '贴边模式切换',
                 '主动关心已', '前台程序感知：已', '已设置提醒', '没有可导出的聊天记录',
                 '截图失败', '图片处理失败', '正在识别图片文字']
    offenders = sorted({w for c in calls for w in bad_words if w in c})
    assert not offenders, '以下系统话术又写回聊天列表了：%s' % offenders


def test_source_guard_notify_widely_used():
    """迁移不能被悄悄回退：_notify 调用点应保持在一个下限之上"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    n = src.count('self._notify(')
    assert n >= 55, '_notify 调用点从 64 掉到 %d，疑似被回退' % n
