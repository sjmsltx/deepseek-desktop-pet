# -*- coding: utf-8 -*-
"""v6.53 新增：陪伴核心最小回归 —— 好感度 / 回忆日志 / 气泡渲染 / 主动关心

背景：全面体检发现 13/31 模块零测试，且盲区恰好集中在"陪伴体验"核心。
本文件给其中 4 个模块补最小冒烟，防止后续改动把陪伴体验改坏。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tmp(name):
    p = os.path.join(tempfile.gettempdir(), name)
    if os.path.exists(p):
        os.remove(p)
    return p


# ---------------- 好感度引擎 ----------------

def test_affection_basics():
    from affection_engine import AffectionEngine, AFFECTION_MAX, AFFECTION_INIT
    p = _tmp('pet_aff_test.json')
    e = AffectionEngine(p)
    s0 = e.snapshot('flash')
    assert s0 and s0.get('affection') == AFFECTION_INIT, '初始好感度应为常量初值'
    r = e.trigger('flash', 'chat')
    assert set(('blocked', 'affection_delta', 'xp_delta')) <= set(r), 'trigger 返回结构变了：%s' % list(r)
    after = e.snapshot('flash').get('affection')
    assert after >= AFFECTION_INIT, '聊天后好感度不应下降（零负反馈原则）'
    assert after <= AFFECTION_MAX, '好感度不得超过上限'
    assert isinstance(e.stage_prompt('flash'), str) and e.stage_prompt('flash'), '阶段提示不应为空'


def test_affection_persists():
    from affection_engine import AffectionEngine
    p = _tmp('pet_aff_test2.json')
    e1 = AffectionEngine(p)
    e1.trigger('flash', 'chat')
    a1 = e1.snapshot('flash').get('affection')
    e2 = AffectionEngine(p)          # 重新加载
    assert e2.snapshot('flash').get('affection') == a1, '好感度未持久化'


def test_affection_no_farm_explosion():
    """防刷：同一事件连续触发不应无限涨（冷却/日上限/封顶三重）"""
    from affection_engine import AffectionEngine, AFFECTION_MAX, AFFECTION_INIT
    p = _tmp('pet_aff_test3.json')
    e = AffectionEngine(p)
    blocked_seen = False
    for _ in range(50):
        r = e.trigger('flash', 'chat')
        blocked_seen = blocked_seen or bool(r.get('blocked'))
    aff = e.snapshot('flash').get('affection', 0)
    assert aff <= AFFECTION_MAX, '防刷封顶失效'
    assert aff - AFFECTION_INIT <= 20, '连刷 50 次涨幅过大（%d）' % (aff - AFFECTION_INIT)
    assert blocked_seen, '冷却机制未触发（连刷 50 次都没有一次 blocked）'


def test_affection_satiety_and_best():
    from affection_engine import AffectionEngine, SATIETY_MAX
    p = _tmp('pet_aff_test4.json')
    e = AffectionEngine(p)
    s_before = e.satiety('flash')
    e.feed('flash')
    s_after = e.satiety('flash')
    assert s_after >= s_before, '喂食后饱食度不应下降'
    assert s_after <= SATIETY_MAX + 0.001, '饱食度超上限'
    e.record_best('flash', 'tetris', 100)
    r2 = e.record_best('flash', 'tetris', 50)
    best = ((e.snapshot('flash').get('stats') or {}).get('best') or {}).get('tetris')
    assert best == 100, '最高分应保留较大值，实际 %s' % best
    assert r2.get('is_record') is False, '低分不应判为新纪录'


def test_affection_helpers():
    from affection_engine import (level_from_xp, xp_for_level, stage_from_affection,
                                  check_titles, AFFECTION_MAX, AFFECTION_INIT)
    assert level_from_xp(0) >= 1
    assert xp_for_level(2) > 0
    s_lo, s_hi = stage_from_affection(AFFECTION_INIT), stage_from_affection(AFFECTION_MAX)
    assert s_lo != s_hi, '满好感与初始好感应处于不同阶段'
    assert s_lo[0] == '初见' and s_hi[0] == '灵魂伴侣', '阶段端点异常：%s / %s' % (s_lo[0], s_hi[0])
    assert isinstance(check_titles({'level': 1, 'affection': 0}), list)


# ---------------- 回忆日志（事件记忆） ----------------

def test_memory_events_roundtrip():
    from memory_events import MemoryEvents
    p = _tmp('pet_events_test.json')
    ev = MemoryEvents(p)
    ev.add('flash', 'milestone', '升级到 2 级', '经验和陪伴时长达标')
    ev.add('pro', 'event', '一起玩了扫雷')
    assert len(ev.all('flash')) == 1 and len(ev.all('pro')) == 1
    assert ev.recent('flash', n=3), 'recent 应有内容'
    assert isinstance(ev.prompt_hint('flash'), str)
    # 持久化
    ev2 = MemoryEvents(p)
    assert len(ev2.all('flash')) == 1, '事件未持久化'
    ev2.clear('flash')
    assert ev2.all('flash') == [], 'clear 未生效'


# ---------------- 气泡 / Markdown 渲染 ----------------

def test_bubble_emotion_strip():
    from pet_bubble import strip_emotion_tags, strip_emotion_tag
    assert '开心' in strip_emotion_tags('[emotion:happy] 开心')[0]
    assert '[emotion' not in strip_emotion_tags('[emotion:happy] 开心')[0]
    out = strip_emotion_tag('你好[emotion=sad]呀')
    assert '[emotion' not in (out[0] if isinstance(out, tuple) else out)


def test_bubble_typewriter_split():
    from pet_bubble import split_typewriter_blocks, split_blocks
    blocks = split_typewriter_blocks('第一段\n\n第二段')
    assert isinstance(blocks, list) and len(blocks) >= 1
    assert isinstance(split_blocks('a\n\nb'), list)


def test_bubble_html_escape():
    """表格渲染必须转义 HTML，且不得双重转义（v6.53 修的 bug）"""
    from chat_render import md_to_html, looks_like_table, _esc
    md = '| a | b |\n|---|---|\n| <img src=x onerror=alert(1)> | A & B |'
    html = md_to_html(md)
    assert '<table' in html, '表格未渲染成 HTML：%s' % html[:80]
    assert '<img src=x' not in html, '单元格未转义（可能被执行）'
    assert '&lt;img' in html, '应保留单层转义'
    assert '&amp;lt;' not in html, '出现双重转义（v6.53 前的 bug）'
    assert '&amp;' in html, '普通 & 应转义为 &amp;'
    assert looks_like_table('| a | b |\n|---|---|\n| 1 | 2 |') is True
    # 直接对原始文本调用的路径（pet_bubble.to_table_html）仍需转义
    import re as _re
    m = _re.search(r'((?:^\|.*\|\s*(?:\n|$))+)', md, _re.M)
    from pet_bubble import to_table_html
    raw_html = to_table_html(m)
    assert '&lt;img' in raw_html and '<img src=x' not in raw_html, '原始文本路径未转义'
    assert _esc('a<b') == 'a&lt;b'


# ---------------- 主动关心（只做接口冒烟，不发网络请求） ----------------

def test_care_engine_interface():
    import care_engine as ce
    assert callable(ce.judge_wakeup) and callable(ce.followup_message), '主动关心入口缺失'
    mins = ce.user_idle_minutes()
    assert isinstance(mins, (int, float)) and mins >= 0, '空闲时长应为非负数'


def test_source_guard_memory_rule():
    """护栏：记忆"只作背景"的约束句 + 闸门入口必须在源码里"""
    pet = open(os.path.join(ROOT, 'desktop_pet.py'), encoding='utf-8-sig').read()
    assert '记忆的使用方式' in pet and 'search_memory_for_injection(' in pet


if __name__ == '__main__':
    test_affection_basics()
    test_affection_persists()
    test_affection_no_farm_explosion()
    test_affection_satiety_and_best()
    test_affection_helpers()
    test_memory_events_roundtrip()
    test_bubble_emotion_strip()
    test_bubble_typewriter_split()
    test_bubble_html_escape()
    test_care_engine_interface()
    test_source_guard_memory_rule()
    print('✅ 陪伴核心 11 项断言通过')
