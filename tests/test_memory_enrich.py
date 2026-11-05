# -*- coding: utf-8 -*-
"""回忆补采集：emotion + affection_at + id 唯一

根因（2026-10-31 实测）：
  memories.json 200 条，emotion 与 affection_at **全 0 填充**
  · 字段在 entry 里定义了，但 4 个调用点里 2 个（say_care / _extract_worker）没传值
  · say_care 明明已经拿到情绪（_strip_emotion_tags 的第三个返回值是情绪列表），
    却在 L6168 只取 [0] 把情绪丢了
  · 另有 3 组 id 重复（[35]/[36]、[39]/[40]、[41]/[42]）：
    id = int(毫秒时间戳) % 1e7，同一次抽取写两条必然同毫秒 ⇒ 必撞

为什么这两项算「该写」而不是「可重算」：
  · 当时好感度 —— affection.json 只存当前值，历史一改即覆盖 ⇒ 已经丢了，不可重算
  · 当时情绪   —— 任何文件里都没有 ⇒ 不可重算
  符合「源数据会先于需求被裁掉 ⇒ 该写」。
"""
import os
import sys
import time

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import memory_events as me  # noqa: E402


@pytest.fixture()
def ev(tmp_path):
    return me.MemoryEvents(str(tmp_path / 'memories.json'))


# ---------- 1. 存取：字段要真的落下来 ----------
def test_add_persists_emotion_and_affection(ev):
    ev.add('flash', 'event', '早上说晚安，疑似熬了一夜',
           '对话发生在 08:49 的早上', emotion='心疼', affection_at=178)
    items = ev.all('flash')
    assert len(items) == 1, '没写进去'
    assert items[0]['emotion'] == '心疼', 'emotion 未持久化：%r' % items[0].get('emotion')
    assert items[0]['affection_at'] == 178, 'affection_at 未持久化：%r' % items[0].get('affection_at')


def test_emotion_survives_reload(tmp_path):
    """落盘后重新加载仍带值 —— 防「只在内存里有」"""
    p = str(tmp_path / 'memories.json')
    e1 = me.MemoryEvents(p)
    e1.add('flash', 'event', '一起玩了扫雷', '玩得很开心', emotion='开心', affection_at=120)
    e2 = me.MemoryEvents(p)
    it = e2.all('flash')[0]
    assert it['emotion'] == '开心' and it['affection_at'] == 120, '重新加载后丢了：%r' % it


# ---------- 2. id 唯一（当前会红：3 组存量重复就是证据） ----------
def test_add_ids_unique_under_burst(ev):
    for i in range(30):
        ev.add('flash', 'event', '事件 %d' % i, '细节 %d' % i)
    ids = [m['id'] for m in ev.all('flash')]
    assert len(ids) == 30
    assert len(set(ids)) == 30, 'id 撞号：%d 条只有 %d 个唯一 id' % (len(ids), len(set(ids)))


def test_add_ids_unique_on_same_millisecond(ev, monkeypatch):
    """同毫秒连续写入必须不撞 —— 原实现必撞"""
    monkeypatch.setattr(time, 'time', lambda: 1793010722.059)   # 固定毫秒
    for i in range(5):
        ev.add('flash', 'event', '并发事件 %d' % i, '')
    ids = [m['id'] for m in ev.all('flash')]
    assert len(set(ids)) == 5, '同毫秒撞号：%r' % (ids,)


def test_add_id_does_not_collide_with_existing(tmp_path, monkeypatch):
    """已存在同 id 时，新写入必须避开（原来算出 target 却没用，等于没测）"""
    p = str(tmp_path / 'memories.json')
    e1 = me.MemoryEvents(p)
    e1.add('flash', 'event', '占位', '')
    old_id = e1.all('flash')[0]['id']

    # 固定时间源，让 _next_id 的起算值**正好等于**已存在的那条
    monkeypatch.setattr(time, 'time', lambda: (old_id / 1000.0) if old_id else 0.0)
    e2 = me.MemoryEvents(p)
    e2.add('flash', 'event', '后来者', '')
    ids = [m['id'] for m in e2.all('flash')]
    assert len(set(ids)) == len(ids), '撞了已有 id：%r' % (ids,)
    assert old_id in ids and len(ids) == 2


# ---------- 3. say_care 要把情绪交上去（现成信号被丢弃） ----------
class _FakeMem:
    def __init__(self):
        self.calls = []

    def add(self, *a, **k):
        self.calls.append((a, k))
        return {}


def _pet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.memories = _FakeMem()
    return p


def test_say_care_passes_emotion_from_tag():
    p = _pet()
    p.say_care('[emotion:心疼]别熬了，早点睡', kind='care')
    assert p.memories.calls, 'say_care 没写回忆'
    kw = p.memories.calls[0][1]
    assert kw.get('emotion') == '心疼', (
        '情绪标签被丢了：emotion=%r（_strip_emotion_tags 已返回情绪列表）' % kw.get('emotion'))


def test_say_care_joins_multiple_emotions():
    p = _pet()
    p.say_care('[emotion:心疼][emotion:温柔]喝点水吧', kind='care')
    kw = p.memories.calls[0][1]
    assert kw.get('emotion') == '心疼,温柔', '多情绪未合并：%r' % kw.get('emotion')


def test_say_care_emotion_empty_without_tag():
    """没有标签就是空，不许编造"""
    p = _pet()
    p.say_care('记得站起来活动一下', kind='care')
    kw = p.memories.calls[0][1]
    assert kw.get('emotion') == '', '无标签却编了情绪：%r' % kw.get('emotion')


def test_say_care_passes_affection_snapshot():
    p = _pet()
    p.say_care('记得站起来活动一下', kind='care')
    kw = p.memories.calls[0][1]
    v = kw.get('affection_at')
    assert isinstance(v, int), 'affection_at 不是整数：%r' % (v,)


# ---------- 4. 抽取链路：prompt 要要这个字段，worker 要传下去 ----------
def test_extract_prompt_asks_for_emotion():
    """结构钉：不写进 schema，模型永远不会返回"""
    import memory_engine
    assert 'emotion' in memory_engine.EXTRACT_PROMPT, (
        'EXTRACT_PROMPT 里没有 emotion 字段，抽取结果必然空')


def test_extract_worker_passes_emotion(monkeypatch):
    p = _pet()
    monkeypatch.setattr(
        sys.modules['desktop_pet'], 'extract_memories',
        lambda *a, **k: {'facts': [], 'update_facts': [],
                         'events': [{'title': '一起看雪', 'detail': '很开心',
                                     'emotion': '开心'}]})
    p._extract_worker()
    kw = p.memories.calls[0][1]
    assert kw.get('emotion') == '开心', 'worker 没把 emotion 传下去：%r' % kw.get('emotion')


def test_extract_worker_passes_affection(monkeypatch):
    p = _pet()
    monkeypatch.setattr(
        sys.modules['desktop_pet'], 'extract_memories',
        lambda *a, **k: {'facts': [], 'update_facts': [],
                         'events': [{'title': '一起看雪', 'detail': ''}]})
    p._extract_worker()
    kw = p.memories.calls[0][1]
    assert isinstance(kw.get('affection_at'), int), (
        'worker 没传 affection_at：%r' % (kw.get('affection_at'),))


def test_extract_worker_emotion_bad_type_no_crash(monkeypatch):
    """模型返回非字符串情绪不能炸（防脏数据）"""
    p = _pet()
    monkeypatch.setattr(
        sys.modules['desktop_pet'], 'extract_memories',
        lambda *a, **k: {'facts': [], 'update_facts': [],
                         'events': [{'title': '脏数据', 'detail': '', 'emotion': {'x': 1}}]})
    p._extract_worker()          # 不抛异常即通过
    assert p.memories.calls


def test_say_care_emotion_hint_fallback():
    """④ 评审-155 真漏洞：所有 say_care 调用方都不带 [emotion:] 标签，
    导致真实库 200 条 event 的 emotion 全为空串。
    """
    p = _pet()
    p.say_care('记得站起来活动一下', kind='care', emotion_hint='关心')
    kw = p.memories.calls[0][1]
    assert kw.get('emotion') == '关心', 'emotion_hint 没被兜底：%r' % kw.get('emotion')


def test_say_care_tag_wins_over_hint():
    """文本里有标签时以标签为准，hint 不覆盖。"""
    p = _pet()
    p.say_care('[emotion:心疼]别熬了', kind='care', emotion_hint='关心')
    kw = p.memories.calls[0][1]
    assert kw.get('emotion') == '心疼', '标签优先级错了：%r' % kw.get('emotion')


def test_display_wakeup_passes_emotion_to_memory():
    """真实主路径：_display_wakeup 解析出的 emotion 必须落进回忆。"""
    p = _pet()
    p._display_wakeup('[emotion:心疼]看你写了一个多小时了，喝口水？')
    assert p.memories.calls, '_display_wakeup 没写回忆'
    kw = p.memories.calls[0][1]
    assert kw.get('emotion') == '心疼', (
        '_display_wakeup 解析出 emotion 却没传下去：%r' % kw.get('emotion'))
