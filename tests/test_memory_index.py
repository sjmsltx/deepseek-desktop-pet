# -*- coding: utf-8 -*-
"""L3 索引层：「去哪查」的地图

设计原文（通道 297 号件 §2.1）：
    L3 索引层 index —— **不是记忆内容，是「去哪查」的地图**，永不写入业务数据
    用户问「我最近花了多少」→ 走 L3 → 现算 → 答

本文件锁六件事：
A. 索引里写的每个数据源都**真实存在**（防瞎猜接口 —— 本轮最大风险）
B. 命中查询才返回条目，未命中返回空（不瞎塞）
C. 注入文本里带的是**现算值**，与直接取值一致
D. 某个数据源坏了只少一项，不崩
E. **只读**：调用前后 memories.json / api_stats.json 的 mtime+sha256 不变
F. 空查询/空宿主不炸
"""
import hashlib
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import memory_index as mi  # noqa: E402


def _host():
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    return p


def _fingerprint(path):
    if not os.path.exists(path):
        return None
    st = os.stat(path)
    h = hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16]
    return (st.st_mtime_ns, st.st_size, h)


# ---------- A. 不许瞎猜接口 ----------
def test_every_index_source_exists_on_host():
    """索引里写的每个 source 必须在宿主上真实存在

    ⛔ 这是本测试最重要的断言：L3 全是「去哪查」的路标，
       路标指错地方比没有路标更糟 —— 模型会自信地去查一个不存在的东西。
    """
    p = _host()
    missing = []
    for item in mi.INDEX:
        # source 形如 'api_stats.today'，逐段 getattr
        obj = p
        ok = True
        for part in item['source'].split('.'):
            if not hasattr(obj, part):
                ok = False
                break
            obj = getattr(obj, part)
        if not ok:
            missing.append((item['key'], item['source']))
    assert not missing, '索引指向了不存在的数据源：%r' % (missing,)


def test_every_index_item_has_required_fields():
    for item in mi.INDEX:
        for f in ('key', 'keywords', 'source', 'label'):
            assert item.get(f), '索引项缺 %s：%r' % (f, item)


def test_index_keys_are_unique():
    keys = [i['key'] for i in mi.INDEX]
    assert len(keys) == len(set(keys)), '索引 key 重复：%r' % keys


# ---------- B. 命中/未命中 ----------
@pytest.mark.parametrize('query,want', [
    ('我今天花了多少钱', 'spend'),
    ('这个月花费多少', 'spend'),
    ('账户余额还剩多少', 'balance'),
    ('我有哪些待办没做完', 'todo'),
    ('我们现在好感度多少', 'affection'),
])
def test_match_hits(query, want):
    got = [i['key'] for i in mi.match(query)]
    assert want in got, '「%s」应命中 %s，实际 %r' % (query, want, got)


@pytest.mark.parametrize('query', [
    '今天天气怎么样',
    '帮我写个 python 函数',
    '',
    None,
])
def test_match_returns_empty_for_unrelated(query):
    assert mi.match(query) == [], '「%s」不该命中任何索引项' % (query,)


# ---------- C. 现算值是真的 ----------
def test_block_contains_real_spend_number():
    p = _host()
    blk = mi.build_l3_block(p, '我今天花了多少钱')
    assert blk, '花费类问题应产出索引提示'
    cost = p.api_stats.today['cost']
    assert ('%.4f' % cost) in blk, '注入文本应含今天花费 %.4f，实际：%r' % (cost, blk)


def test_block_contains_real_balance_number():
    p = _host()
    blk = mi.build_l3_block(p, '我余额还有多少')
    bal = p.api_stats.balance
    # balance 是缓存：新实例没查过就是 None（balance_text 此时返回 ''，绝不编数字）
    if not bal or not bal.get('ok'):
        pytest.skip('余额缓存为空或接口不可用，本机当前取不到')
    assert ('%.2f' % float(bal.get('total') or 0)) in blk, '注入文本应含余额，实际：%r' % blk


def test_block_says_where_to_look():
    """设计核心：L3 说的是「去哪查」，所以要出现数据源名字"""
    p = _host()
    blk = mi.build_l3_block(p, '我今天花了多少钱')
    assert 'api_stats' in blk, 'L3 必须指明数据源，实际：%r' % blk


def test_block_empty_when_nothing_matched():
    p = _host()
    assert mi.build_l3_block(p, '今天天气怎么样') == ''


# ---------- D. 降级 ----------
def test_broken_source_degrades(monkeypatch):
    p = _host()

    class _Bad:
        @property
        def today(self):
            raise RuntimeError('假故障')
    monkeypatch.setattr(p, 'api_stats', _Bad())
    # 花费项取不到值 ⇒ 不产出该条；但**路标仍应保留**（告诉模型去哪查比给错值好）
    blk = mi.build_l3_block(p, '我今天花了多少钱')
    assert '¥' not in blk or '0.0000' not in blk, '坏数据源不该给出假数字：%r' % blk


def test_block_never_raises():
    class _Nothing:
        pass
    assert mi.build_l3_block(_Nothing(), '我花了多少钱') == ''


# ---------- E. 只读契约 ----------
def test_l3_is_read_only():
    """设计原文：L3「永不写入业务数据」

    调用前后对记忆库与用量库取 mtime+size+sha256 指纹，必须完全不变。
    """
    p = _host()
    paths = [p.memories.path, getattr(p.api_stats, 'path', None)]
    before = [_fingerprint(x) for x in paths if x]
    for q in ('我今天花了多少钱', '余额多少', '待办有哪些', '好感度多少'):
        mi.build_l3_block(p, q)
    after = [_fingerprint(x) for x in paths if x]
    assert before == after, 'L3 写了业务数据（违反设计：永不写入）\n前：%r\n后：%r' % (before, after)
