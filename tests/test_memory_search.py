# -*- coding: utf-8 -*-
"""「搜共同经历」护栏（v6.63）

搜索入口要满足：
- 只搜本地数据、**不花 API**（默认不做 LLM 重排）
- 事实走既有 BM25 管线但**不过闸门**（用户主动搜 ≠ 自动注入，宁多不少）
- 事件按 2-gram 关键词命中，分组展示不混排
- 没结果要明说「没找到」，不编

运行：python -m pytest tests/test_memory_search.py -q
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import memory_search as ms      # noqa: E402

FACTS = [
    {'id': 'f1', 'content': '用户喜欢在晚上写代码', 'importance': 4, 'status': 'active',
     'updated_at': '2026-09-10'},
    {'id': 'f2', 'content': '用户养了一只叫团子的猫', 'importance': 5, 'status': 'active',
     'updated_at': '2026-09-11'},
    {'id': 'f3', 'content': '用户考研目标是西南大学', 'importance': 5, 'status': 'active',
     'updated_at': '2026-09-12'},
    {'id': 'f4', 'content': '已删除的旧事实：喜欢跑步', 'importance': 3, 'status': 'deleted',
     'updated_at': '2026-09-01'},
]
EVENTS = [
    {'type': 'event', 'time': '2026-09-01 20:00', 'title': '一起玩了扫雷',
     'detail': '连输三局，最后赢了一把', 'affection_at': 12},
    {'type': 'milestone', 'time': '2026-09-05 10:00', 'title': '好感度突破 20',
     'detail': '', 'affection_at': 20},
    {'type': 'event', 'time': '2026-09-08 21:00', 'title': '给桌宠换了主题',
     'detail': '换成了星空主题', 'affection_at': 22},
]


def test_tokens_cjk_bigram_and_words():
    toks = ms._tokens('扫雷 saolei 123')
    assert '扫雷' in toks and 'saolei' in toks and '123' in toks
    assert ms._tokens('') == []


def test_facts_via_existing_pipeline_without_gate():
    """事实检索走 memory_engine.search_memory，且不过闸门（只命中 1 个词也给结果）"""
    res = ms.search_memories(FACTS, [], '猫')
    assert len(res['facts']) == 1 and res['facts'][0]['id'] == 'f2'
    assert res['facts'][0]['kind'] == 'fact'


def test_deleted_facts_excluded():
    res = ms.search_memories(FACTS, [], '跑步')
    assert all(f['id'] != 'f4' for f in res['facts']), '已删除的事实不该被搜出来'


def test_events_keyword_scoring_and_order():
    res = ms.search_memories([], EVENTS, '扫雷')
    assert len(res['events']) == 1
    e = res['events'][0]
    assert e['title'] == '一起玩了扫雷' and e['score'] > 0 and e['kind'] == 'event'
    # 标题命中应优先于仅描述命中
    res2 = ms.search_memories([], EVENTS, '主题')
    assert res2['events'] and res2['events'][0]['title'] == '给桌宠换了主题'


def test_no_match_returns_empty_and_clear_text():
    res = ms.search_memories(FACTS, EVENTS, '量子计算机')
    assert res['facts'] == [] and res['events'] == []
    txt = ms.format_hits(res)
    assert '没找到' in txt and '量子计算机' in txt


def test_empty_query_no_hits():
    res = ms.search_memories(FACTS, EVENTS, '   ')
    assert ms.total_hits(res) == 0


def test_format_groups_and_carries_time():
    res = ms.search_memories(FACTS, EVENTS, '扫雷 猫')
    txt = ms.format_hits(res)
    assert '关于「扫雷 猫」' in txt
    assert '✨ 共同经历' in txt or '🧠 记住的事' in txt
    assert '2026-09-01 20:00' in txt or '团子' in txt


def test_format_english():
    res = ms.search_memories(FACTS, EVENTS, '扫雷')
    txt = ms.format_hits(res, is_en=True)
    assert 'Shared experiences' in txt or 'Facts' in txt


def test_rerank_is_optional_and_no_network_by_default():
    """护栏：默认不传 rerank（不调 LLM、不花 API）"""
    src = open(os.path.join(BASE, 'memory_search.py'), encoding='utf-8').read()
    assert 'rerank=None' in src
    assert 'api.deepseek.com' not in src and 'chat_completions' not in src
    called = {'n': 0}

    def fake_rerank(query, cands):
        called['n'] += 1
        return [cands[-1]['id']] + [c['id'] for c in cands[:-1]]

    res = ms.search_memories(FACTS, [], '代码', rerank=fake_rerank)
    assert called['n'] == 1 and res['facts'], '显式传 rerank 时应被调用（宿主可选用）'


# ---------------------------------------------------------------- 接线护栏

def test_pet_wiring_recall_command_and_album_search():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert '/回忆' in src, '聊天端要有 /回忆 命令'
    assert 'memory_search' in src, '要真的调用检索模块'
    assert 'searcher=' in src, '回忆相册要能把检索器传进去'
    ui = open(os.path.join(BASE, 'affection_ui.py'), encoding='utf-8').read()
    assert 'searcher' in ui and 'QLineEdit' in ui, '回忆相册要有搜索框'


def test_album_search_box_filters(monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import affection_ui as au
    from PySide6.QtWidgets import QLineEdit

    class _Store:
        def all(self, role):
            return list(EVENTS)

    dlg = au.MemoriesDialog(_Store(), 'flash', '小蓝', None,
                            searcher=lambda q: ms.search_memories([], EVENTS, q))
    box = dlg.findChild(QLineEdit)
    assert box is not None
    assert dlg.list.count() == len(EVENTS), '默认应显示完整时间线'
    box.setText('扫雷')
    dlg._apply_search()
    texts = [dlg.list.item(i).text() for i in range(dlg.list.count())]
    assert any('扫雷' in t for t in texts)
    assert not any('换了主题' in t for t in texts), '搜索后应只剩命中项'
    box.setText('')
    dlg._apply_search()
    assert dlg.list.count() == len(EVENTS), '清空搜索应回到完整时间线'
    dlg.close()


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))
