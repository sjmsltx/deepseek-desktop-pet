# -*- coding: utf-8 -*-
"""AI 可调用气泡 say_bubble（v3.6，2026-10-24 Owner 需求 5）

Owner 原话：「气泡太呆板了。能不能把这个气泡做成能被 ai 调用的？
            我随便跟他说句话他回复之后也能用气泡显示简单的一句话」

根因：此前 33-1=32 个工具里**没有一个是说话类**，气泡只能从预设台词库随机取
⇒ 与本轮回复无关 ⇒ 「呆板」。本文件锁住新工具与它的三道闸。

三道闸（缺一道就变成刷屏源）：
1. 长度闸 ≤ ai_bubble_max_chars（默认 40）→ 截断，不拒绝
2. 频次闸 同一轮最多 1 次（按 _cur_gen）
3. 开关闸 config `ai_bubble`（默认 True）

运行：python -m pytest tests/test_say_bubble.py -q
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
    p.balance_watch = False
    p.ai_bubble = True
    p._speak_busy = False
    p._speak_queue = []
    p._cur_gen = 1
    p._bubble_said_gen = None
    return p


def _say(p, text, **kw):
    """清掉「正在说」再调 —— 否则新文本进队列，读到的是上一条"""
    p._speak_busy = False
    p._speak_queue = []
    return p._execute_tool('say_bubble', dict(text=text, **kw))


# ---------- 1. 工具注册 ----------

def test_tool_registered():
    import tools_registry as tr
    names = [t['function']['name'] for t in tr.AI_TOOLS]
    assert 'say_bubble' in names, 'say_bubble 没进 AI_TOOLS'
    assert len(names) == 33, '工具总数应为 33（v3.6 新增 say_bubble），实际 %d' % len(names)
    assert 'say_bubble' in tr.CORE_TOOLS, '说话是自己的事，应在 core 里'
    assert 'say_bubble' in tr.TOOL_STATUS, '缺状态文案'


def test_handler_registered():
    import desktop_pet as dp
    assert dp.PetWidget._TOOL_HANDLERS.get('say_bubble') == '_tool_say_bubble'
    assert hasattr(dp.PetWidget, '_tool_say_bubble')


def test_schema_has_required_text():
    import tools_registry as tr
    spec = next(t['function'] for t in tr.AI_TOOLS if t['function']['name'] == 'say_bubble')
    assert spec['parameters']['required'] == ['text']
    assert 'seconds' in spec['parameters']['properties']


# ---------- 2. 基本行为 ----------

def test_says_into_bubble():
    p = _pet()
    r = _say(p, '主人，我在这儿呢')
    assert p.bubble.text() == '主人，我在这儿呢', '气泡没显示该文本'
    assert '已在气泡里说了' in r
    assert not p.bubble.isHidden()


def test_does_not_pollute_chat_panel():
    """铁律：气泡不进聊天面板"""
    p = _pet()
    n0 = len(p.display_msgs)
    _say(p, '这句话只该在气泡里')
    assert len(p.display_msgs) == n0, '气泡被写进了聊天面板'


def test_empty_text_rejected():
    p = _pet()
    r = _say(p, '   ')
    assert '没有说' in r, '空文本应拒绝：%r' % r


# ---------- 3. 三道闸 ----------

def test_length_gate_truncates():
    """超长截断到上限（不拒绝 —— 拒绝会让 AI 白调一次）"""
    p = _pet()
    p.ai_bubble_max_chars = 40
    long_txt = '这是一句特别长的话' * 6      # 60 字
    _say(p, long_txt)
    assert p.bubble.text() == long_txt[:40], '应截断到 40 字，实际 %d' % len(p.bubble.text())


def test_length_gate_respects_custom_max():
    p = _pet()
    p.ai_bubble_max_chars = 12
    _say(p, '一二三四五六七八九十十一十二十三')
    assert len(p.bubble.text()) == 12, '应按自定义上限 12 截断'


def test_frequency_gate_same_round():
    """同一轮第二次调用被忽略，且气泡内容不变"""
    p = _pet()
    _say(p, '第一次')
    first = p.bubble.text()
    r2 = _say(p, '第二次应该被拦')
    assert '已用过一次' in r2, '频次闸没生效：%r' % r2
    assert p.bubble.text() == first, '被拦时不该改气泡'


def test_frequency_gate_resets_next_round():
    """换一轮（_cur_gen 变）后又能说一次"""
    p = _pet()
    _say(p, '第一轮')
    p._cur_gen = 2
    r = _say(p, '第二轮可以说')
    assert '已在气泡里说了' in r, '新一轮应允许再说：%r' % r
    assert p.bubble.text() == '第二轮可以说'


def test_switch_gate_off():
    """开关关掉 → 不弹气泡，返回说明（便于 AI 改用正文）"""
    p = _pet()
    before = p.bubble.text()
    p.ai_bubble = False
    r = _say(p, '关掉后不该出现')
    assert '已在设置里关闭' in r, '开关闸没生效：%r' % r
    assert p.bubble.text() == before, '关掉后不该改气泡'


# ---------- 4. seconds 参数 ----------

def test_seconds_sets_hold():
    p = _pet()
    _say(p, '定时三秒', seconds=3)
    assert p.bubble_hide_timer.interval() == 3000, \
        'seconds=3 应停留 3000ms，实际 %d' % p.bubble_hide_timer.interval()


def test_seconds_clamped():
    """seconds 过大要夹住（防「让它读 1 小时」把气泡钉在屏幕上）"""
    p = _pet()
    _say(p, '超长停留', seconds=99999)
    assert p.bubble_hide_timer.interval() <= 30000, '应夹到 30 秒内'


# ---------- 5. 源码护栏 ----------

def test_source_guard_three_gates_present():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    i = src.index('def _tool_say_bubble')
    body = src[i:i + 3000]
    assert 'ai_bubble_max_chars' in body, '缺长度闸'
    assert '_bubble_said_gen' in body, '缺频次闸'
    assert 'ai_bubble' in body, '缺开关闸'
    assert 'say_plain' in body, '没真的调气泡'


def test_per_round_marker_reset_on_new_round():
    """每轮开始时频次标记必须重置，否则说完一次就永久失效"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert "self._bubble_said_gen = None" in src, \
        '缺少每轮重置（AI 说完一次后整场对话都不能再说）'

# ---------- 6. 设置页 GUI 入口（Owner 2026-08-02「懒得改配置文件」）----------

def test_settings_has_switch():
    """设置页必须有 AI 气泡复选框（不能只让用户改 config.json）"""
    src = open(os.path.join(BASE, 'settings_ui.py'), encoding='utf-8').read()
    assert 'ck_bubble' in src, '设置页缺 AI 气泡复选框'
    # ⚠ 只查「方法存在」不够（证伪 #5 实测证明了）：
    #   方法定义还在、只是 connect 被删 → 原断言照样绿。
    #   必须查**真的接上了**。这与 WX-109 §4.1 是同一类错。
    assert 'self.ck_bubble.toggled.connect(self._toggle_ai_bubble)' in src, \
        '复选框没接到回调（勾了不生效）'
    assert "getattr(h, 'ai_bubble', True)" in src, '_refresh 没回填当前值（开关状态显示错）'


def test_host_has_setter():
    """宿主要有 set_ai_bubble（落盘 + 提示）"""
    import desktop_pet as dp
    assert hasattr(dp.PetWidget, 'set_ai_bubble')
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    i = src.index('def set_ai_bubble')
    body = src[i:i + 700]
    assert "_save_cfg_value('ai_bubble'" in body, '开关没落盘（重启就丢）'


def test_setter_toggles_and_persists():
    p = _pet()
    saved = []
    p._save_cfg_value = lambda k, v: saved.append((k, v)) or True
    p.set_ai_bubble(False)
    assert p.ai_bubble is False
    assert ('ai_bubble', False) in saved, '没写进 config'
    p.set_ai_bubble(True)
    assert p.ai_bubble is True
    assert ('ai_bubble', True) in saved
