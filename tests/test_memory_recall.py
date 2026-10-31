# -*- coding: utf-8 -*-
"""骨架 A1/A2：事件检索 + L0 人格卡

A1 —— 事件记忆现在只有 recent(3)，按内容永远找不到。
      复用 memory_engine 的 BM25 + 同一套相关性闸门（GATE_MIN_MATCHED / COVERAGE）。
A2 —— L0 人格卡：身份类事实每次必注入、且有独立预算，不被普通记忆挤掉。
      build_core_block 写了却零生产调用，本测试锁住「必须真的接上」。
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import memory_events as me  # noqa: E402
import memory_engine as meng  # noqa: E402


@pytest.fixture()
def ev(tmp_path):
    return me.MemoryEvents(str(tmp_path / 'memories.json'))


def _seed(ev):
    ev.add('flash', 'event', '一起玩了扫雷，他连赢三局', '桌宠输得很惨')
    ev.add('flash', 'event', '聊到重庆合川的桃片', '他说喜欢老工艺现切的')
    ev.add('flash', 'event', '帮他调试 matplotlib 抛体轨迹', 'h/v0/g 参数算错了')
    ev.add('flash', 'event', '早上说晚安，疑似熬了一夜', '08:49 才睡')


# ---------- A1：按内容检索 ----------
def test_search_events_finds_by_content(ev):
    _seed(ev)
    hits = ev.search('扫雷')
    assert hits, '按内容检索不到（仍是 recent 语义）'
    assert '扫雷' in hits[0]['title'], '首条不是最相关的：%r' % (hits[0]['title'],)


def test_search_events_topic_isolation(ev):
    """查桃片不应把扫雷排到前面"""
    _seed(ev)
    hits = ev.search('合川桃片')
    assert hits and '桃片' in hits[0]['title'], '主题串了：%r' % ([h['title'] for h in hits],)


def test_search_events_gate_rejects_unrelated(ev):
    """完全不相关的查询必须空手而归（治「问什么都往记忆上靠」）"""
    _seed(ev)
    assert ev.search('量子力学傅里叶变换') == [], '闸门没拦住无关查询'


def test_search_events_excludes_noise(ev):
    ev.add('flash', 'event', '主动关心：别处用了约 ¥0.1500（12:29 → 12:34）', '余额 ¥29.62')
    ev.add('flash', 'event', '一起看了流星雨', '很冷但值得')
    hits = ev.search('别处用了')
    assert all('别处用了' not in h['title'] for h in hits), '噪音参与了检索'


def test_prompt_hint_prefers_relevant_over_recent(ev):
    """关键行为：相关的老回忆要能压过无关的新回忆"""
    _seed(ev)                      # 扫雷那条最早
    for i in range(5):
        ev.add('flash', 'event', '随手记 %d 号' % i, '无关内容')
    hint = ev.prompt_hint('flash', query='扫雷赢了三局')
    assert '扫雷' in hint, '检索没生效（仍只取最近几条）：\n%s' % hint
    # 真正的「排最前」断言：取第一个以「- 」开头的行（原来用 split('\n')[1]，
    #   而 hint 以 '\n\n' 开头，恒取到空串 ⇒ 断言退化成「没有随手记」）
    body = [l for l in hint.splitlines() if l.startswith('- ')]
    assert body, '注入段里没有任何条目'
    assert '扫雷' in body[0], '最相关那条没排第一：%r' % (body[0],)


def test_prompt_hint_without_query_keeps_old_behavior(ev):
    _seed(ev)
    hint = ev.prompt_hint('flash')
    assert '早上说晚安' in hint, '不传 query 时应退回「最近几条」'


def test_prompt_hint_query_keeps_noise_filter(ev):
    ev.add('flash', 'event', '主动关心：别处用了约 ¥0.1500', '余额 ¥29.62')
    ev.add('flash', 'event', '一起看了流星雨', '很冷')
    hint = ev.prompt_hint('flash', query='流星雨')
    assert '别处用了' not in hint, '检索路径漏掉了噪音过滤'


def test_search_events_respects_role(ev):
    ev.add('flash', 'event', '小蓝专属事件：一起看流星雨', '')
    ev.add('pro', 'event', '大蓝专属事件：一起看流星雨', '')
    hits = ev.search('流星雨', role='flash')
    assert all('小蓝' in h['title'] for h in hits), '串角色了：%r' % ([h['title'] for h in hits],)


# ---------- A2：L0 人格卡 ----------
def _facts():
    return [
        {'id': 'a', 'content': '我的名字叫小蓝（V4 Flash 桌宠）', 'importance': 5,
         'status': 'active', 'roles': 'both', 'updated_at': '2026-10-31T00:00:00'},
        {'id': 'b', 'content': 'Pro 模型姐姐的名字叫大蓝', 'importance': 5,
         'status': 'active', 'roles': 'both', 'updated_at': '2026-10-31T00:00:00'},
        {'id': 'c', 'content': '用户爱吃重庆合川桃片', 'importance': 3,
         'status': 'active', 'roles': 'both', 'updated_at': '2026-10-31T00:00:00'},
        {'id': 'd', 'content': '已失效的旧路径 E:\\ai工作站', 'importance': 5,
         'status': 'superseded', 'roles': 'both', 'updated_at': '2026-08-01T00:00:00'},
    ]


def test_build_l0_block_takes_identity_facts():
    block, used = meng.build_l0_block(_facts(), 'flash')
    assert '小蓝' in block and '大蓝' in block, 'L0 没收到身份事实：%r' % block
    # used 返回的是**对象列表**（按 id 剔除会误伤同 id 的另一条，见审核 M1）
    used_ids = [f.get('id') for f in used]
    assert 'a' in used_ids and 'b' in used_ids


def test_build_l0_block_skips_superseded():
    block, used = meng.build_l0_block(_facts(), 'flash')
    assert 'E:\\ai工作站' not in block, '失效事实混进 L0'
    assert 'd' not in [f.get('id') for f in used]


def test_build_l0_block_budget_caps():
    block, used = meng.build_l0_block(_facts(), 'flash', budget=40)
    assert len(block) <= 60, 'L0 超预算：%d 字' % len(block)
    assert used


def test_build_l0_block_role_filter():
    facts = _facts()
    facts[1]['roles'] = 'pro'
    block, _ = meng.build_l0_block(facts, 'flash')
    assert '大蓝' not in block, 'pro 专属事实串进 flash 的 L0'


def test_memory_block_has_l0_and_no_duplicate():
    """L0 与普通记忆块不能重复同一条（否则白占预算）"""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.memory_facts = _facts()
    p.memory_summaries = []
    block = p._memory_block()
    assert '小蓝' in block
    assert block.count('我的名字叫小蓝') == 1, 'L0 与普通块重复注入了同一条'


def test_l0_has_identity_criterion():
    """S4（审核）：原来 L0 没有任何身份判据，实质只是「重要度前 N 条」"""
    assert hasattr(meng, '_is_identity'), '缺身份判据函数'
    assert meng._is_identity('我的名字叫小蓝（V4 Flash 桌宠）')
    assert meng._is_identity('Pro 模型姐姐的名字叫大蓝')
    assert not meng._is_identity('用户爱吃重庆合川桃片'), '普通偏好被判成身份'


def test_l0_identity_always_in_even_when_budget_tiny():
    """身份条目不受预算限制（身份必须每轮在）"""
    facts = [
        {'id': 'i', 'content': '我的名字叫小蓝（V4 Flash 桌宠）', 'importance': 5,
         'status': 'active', 'roles': 'both', 'updated_at': '2026-10-31T00:00:00'},
        {'id': 'n', 'content': '用户爱吃重庆合川桃片' * 6, 'importance': 4,
         'status': 'active', 'roles': 'both', 'updated_at': '2026-10-31T00:00:00'},
    ]
    block, used = meng.build_l0_block(facts, 'flash', budget=10)
    assert '小蓝' in block, '预算极小也必须有身份条目：%r' % block
    assert '桃片' not in block, '非身份的长条目不该挤进 L0：%r' % block


def test_l0_budget_includes_prefix():
    """S2（审核）：预算必须含 ★n 前缀与换行，否则声明 320 实际 322"""
    facts = [{'id': str(i), 'content': '普通' * 6, 'importance': 3,
              'status': 'active', 'roles': 'both', 'updated_at': '2026-10-31T00:00:00'}
             for i in range(30)]
    block, _ = meng.build_l0_block(facts, 'flash', budget=100)
    assert len(block) <= 100, '超预算：%d 字（应含前缀）' % len(block)


def test_prompt_hint_order_is_chronological():
    """S1（审核）：reversed 两次导致注入顺序变成最新在前"""
    import tempfile
    d = tempfile.mkdtemp()
    e = me.MemoryEvents(__import__('os').path.join(d, 'm.json'))
    e.add('flash', 'event', '第一件事', '')
    e.add('flash', 'event', '第二件事', '')
    e.add('flash', 'event', '第三件事', '')
    hint = e.prompt_hint('flash')
    body = [l for l in hint.splitlines() if l.startswith('- ')]
    assert body[0].startswith('- 第一件事'), '应为时间正序（最早在前）：%r' % (body,)


def test_prompt_hint_pro_role_empty_is_safe():
    """pro 角色库内 0 条时必须返回空串（不能崩）

    事实依据（WX-155 §2.2）：affection.json 顶层只有 flash，
    pro 角色从未创建状态 ⇒ memories.json 里 role 全是 flash。
    这是「从没切过 pro」的结果，不是采集失败；这里锁住不崩。
    """
    import tempfile
    import os as _os
    d = tempfile.mkdtemp()
    e = me.MemoryEvents(_os.path.join(d, 'm.json'))
    e.add('flash', 'event', '只有 flash 有回忆', '')
    assert e.prompt_hint('pro') == '', 'pro 无数据时应返回空串'
    assert e.search('回忆', role='pro') == [], 'pro 检索应空手而归'
