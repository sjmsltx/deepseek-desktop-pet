# -*- coding: utf-8 -*-
"""记忆写入边界：facts vs events（2026-11-06）

## 为什么有这份测试

Owner：「库里混了『脱离语境无意义』的条目，任何话题都能匹配到点什么 —— 调阈值治不好。」
真实库取证：21 条 active facts 里 3 条是一次性状态（在做…/正在…/满分）、
1 条混着助手主张（「适合分层治理而非单文件方案」）。

`memory_write_policy.classify()` 在**写入前**判层；本文件锁住判据与接线。

## 口径

· 一次性里程碑 / 进行中的任务 / 对系统的评测 → events（不是 facts）
· 助手主张：能剥就剥（保留同句里的用户属性），剥完没内容才丢
· 同时命中「稳定习惯词」时不因评测词误判（真实库实例：经常发截图…实测效果好…习惯用…）
· 已存在同样的记忆 → 只累加 evidence，不新增
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import memory_write_policy as wp    # noqa: E402


# ---------- A. 分类判据 ----------
def test_stable_attribute_is_fact():
    r = wp.classify('用户爱吃重庆合川桃片，偏好甜味、老工艺、现切的')
    assert r['target'] == wp.TARGET_FACT
    assert r['reason'] == 'fact'


def test_identity_is_fact():
    r = wp.classify('我的名字叫小蓝（V4 Flash 桌宠）')
    assert r['target'] == wp.TARGET_FACT


def test_milestone_goes_to_event():
    r = wp.classify('用户在 Python 基础关卡中 5 关全部满分（100/100，全部通过）')
    assert r['target'] == wp.TARGET_EVENT
    assert r['reason'] == 'milestone'
    assert '满分' in r['hits']


def test_ordinal_counted_as_milestone():
    r = wp.classify('用户第 7 次做坐标转换练习，全部通过')
    assert r['target'] == wp.TARGET_EVENT
    assert r['reason'] == 'milestone'


def test_session_goes_to_event():
    r = wp.classify('用户正在学习用 Python 的 matplotlib 绘图库，练习绘制抛体运动轨迹点')
    assert r['target'] == wp.TARGET_EVENT
    assert r['reason'] == 'session'


def test_long_term_learning_stays_fact():
    """「在学习/练习 Python」是长期技能，不是一次性会话

    ⚠ 第一版把「在学」放进会话词表，把这条判成 events —— 而它正是
      h05「我在练哪门编程」的唯一答案源。dry-run 实测抓出来的误判。
    """
    r = wp.classify('用户在学习/练习 Python，会把自己写的代码片段发给桌宠请求分析')
    assert r['target'] == wp.TARGET_FACT, '长期技能被误判成一次性会话'


def test_pure_advice_is_dropped():
    r = wp.classify('建议先把统计基础补齐，再考虑回测')
    assert r['target'] == wp.TARGET_DROP
    assert r['reason'] == 'advice'


def test_advice_clause_trimmed_but_user_fact_kept():
    """库内实例：前半是真属性，尾子句是助手主张 → 剥掉尾子句，保留前半"""
    text = ('用户是 AI Agent 治理体系的重度用户：用 agent-governance-template 分层体系'
            '（AutoClaw/龙虾搭建），属于"规则会翻十倍"的重度用户类型，适合分层治理而非单文件方案')
    r = wp.classify(text)
    assert r['target'] == wp.TARGET_FACT
    assert r['trimmed'], '没有剥掉助手主张子句'
    assert '适合分层治理而非单文件方案' not in r['text'], '助手主张仍在正文里'
    assert '重度用户' in r['text'], '把用户属性也剥掉了'


def test_system_eval_goes_to_event():
    r = wp.classify('实测视觉识别功能效果好，响应也快')
    assert r['target'] == wp.TARGET_EVENT
    assert r['reason'] == 'system_eval'


def test_habit_marker_beats_system_eval():
    """库内实例：「经常发截图…实测效果好…习惯用…」是习惯，不该被拓去 events"""
    r = wp.classify('用户经常发教材插图/截图让桌宠识别，实测视觉识别功能效果好，'
                    '习惯用"越具体越准"的提问方式')
    assert r['target'] == wp.TARGET_FACT


def test_contextless_fragment_dropped():
    r = wp.classify('那就用这个吧')
    assert r['target'] == wp.TARGET_DROP
    assert r['reason'] == 'contextless'


def test_pronoun_with_entity_is_kept():
    r = wp.classify('用户会用日语梗和桌宠开玩笑、逗它玩')
    assert r['target'] == wp.TARGET_FACT, '有具体内容（日语梗）不该因「它」被丢'


def test_empty_dropped():
    assert wp.classify('  ')['target'] == wp.TARGET_DROP
    assert wp.classify('好')['reason'] == 'empty'


def test_has_entity():
    """实体判据只认**机械可识别**的形式

    ⚠ 「用户住在中国重庆」不算命中：重庆没有「大学/学院/市/区/县」这类后缀，
    又没有数字/英文/书名号。我不为此维护一份城市词表（会长期腐化），
    而是接受这个盲区 —— 它只影响 contextless 那一类判定（需同时有指代 + 短），
    那条路对无后缀专名本来就宽松（不丢）。
    """
    assert wp.has_entity('用户住在中国重庆') is False   # 已知盲区，不掩盖
    assert wp.has_entity('在重庆市上学') is True        # 有后缀
    assert wp.has_entity('用 Python 写脚本') is True       # 英文
    assert wp.has_entity('读了《过秦论》') is True          # 书名号
    assert wp.has_entity('第 3 次') is True                # 数字


# ---------- B. 落层载荷 ----------
def test_event_payload_types():
    m = wp.classify('用户在 Python 基础关卡中 5 关全部满分')
    p = wp.event_payload(m)
    assert p['type'] == 'milestone'
    s = wp.classify('用户正在学习用 matplotlib 绘图，练习绘制轨迹点')
    ps = wp.event_payload(s)
    assert ps['type'] == 'event'
    assert ps['detail'] == s['text']
    assert len(ps['title']) <= 29


def test_bump_evidence():
    f = {'evidence': 2}
    assert wp.bump_evidence(f) == 3
    g = {}
    assert wp.bump_evidence(g) == 2, '缺字段时应从 1 起加'
    h = {'evidence': 'bad'}
    assert wp.bump_evidence(h) == 2


# ---------- C. 接线：写入路径真的按判定分流 ----------
class _Memories:
    """records MemoryEvents.add 的调用"""
    def __init__(self):
        self.calls = []

    def add(self, role, type_, title, detail='', emotion='', affection_at=None,
            origin='user'):
        self.calls.append({'role': role, 'type': type_, 'title': title,
                           'detail': detail, 'emotion': emotion})
        return {'id': 1}


@pytest.fixture
def pet(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    import desktop_pet as dp
    import memory_ledger as ml

    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    # ⛔ 绝不能让它写真实 memory.json
    p._save_memory = lambda *a, **k: True
    p.memories = _Memories()
    p._affection_now = lambda: 10.0
    p.chat_history_msgs = [
        {'role': 'user', 'content': '我在练 Python'},
        {'role': 'assistant', 'content': '好'},
        {'role': 'user', 'content': '今天压线过了 5 关'},
        {'role': 'assistant', 'content': '厉害'},
    ]
    p.memory_facts = []
    ml.set_path(str(tmp_path / 'ledger.jsonl'))
    yield p, dp
    ml.set_path(None)


def _run(p, dp, monkeypatch, payload):
    monkeypatch.setattr(dp, 'extract_memories',
                        lambda chat_fn, dialogue, existing='', max_tokens=400: payload)
    p._extract_worker()


def test_extract_routes_fact_event_drop(pet, monkeypatch):
    p, dp = pet
    _run(p, dp, monkeypatch, {
        'facts': [
            '用户爱吃重庆合川桃片，偏好甜味、老工艺、现切的',
            '用户在 Python 基础关卡中 5 关全部满分',
            '建议先把统计基础补齐，再考虑回测',
        ],
        'events': [],
        'update_facts': [],
    })
    contents = [f.get('content') for f in p.memory_facts]
    assert any('桃片' in (c or '') for c in contents), '稳定偏好应进 facts'
    assert not any('满分' in (c or '') for c in contents), '里程碑不该进 facts'
    assert len(p.memories.calls) == 1, '里程碑应写进 events'
    assert p.memories.calls[0]['type'] == 'milestone'
    assert '满分' in p.memories.calls[0]['detail']


def test_extract_records_ledger_for_drop(pet, monkeypatch):
    p, dp = pet
    import memory_ledger as ml
    _run(p, dp, monkeypatch, {
        'facts': ['建议先把统计基础补齐，再考虑回测'],
        'events': [], 'update_facts': [],
    })
    rows = [r for r in ml.read_all() if r.get('stage') == 'extract.facts']
    assert rows, '丢弃没有留痕 —— 之后无法回答「为什么没记住」'
    assert rows[0]['target'] == 'drop'
    assert rows[0]['reason'] == 'advice'


def test_existing_fact_only_bumps_evidence(pet, monkeypatch):
    """同一件事再说一遍 → 不新增一条，只累加 evidence"""
    p, dp = pet
    p.memory_facts = [{'id': 'f1', 'content': '用户爱吃重庆合川桃片',
                       'importance': 4, 'status': 'active', 'evidence': 1}]
    _run(p, dp, monkeypatch, {
        'facts': ['用户爱吃重庆合川桃片'],
        'events': [], 'update_facts': [],
    })
    assert len(p.memory_facts) == 1, '同一件事被写成了两条'
    assert p.memory_facts[0]['evidence'] == 2
    assert p.memory_facts[0]['importance'] == 4, '更新时不该把重要度降成默认 3'


def test_event_written_with_current_role(pet, monkeypatch):
    p, dp = pet
    p.current = 'pro'
    _run(p, dp, monkeypatch, {
        'facts': ['用户正在学习用 matplotlib 绘图，练习绘制轨迹点'],
        'events': [], 'update_facts': [],
    })
    assert p.memories.calls and p.memories.calls[0]['role'] == 'pro'


# ---------- D. 源码护栏：防回潮 ----------
def test_extract_worker_uses_policy():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    i = src.find('def _extract_worker')
    assert i > 0
    body = src[i:i + 4200]
    assert 'mwp.classify(' in body, (
        '_extract_worker 没走写入边界 —— 所有抽取结果会直接进 facts（回潮了）')


def test_prompt_has_boundary_rules():
    import memory_engine as me
    p = me.EXTRACT_PROMPT
    for kw in ('稳定属性', '一次性', '正在', '建议', 'update_facts'):
        assert kw in p, '抽取提示词缺边界说明：%r' % kw
