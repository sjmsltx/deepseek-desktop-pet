# -*- coding: utf-8 -*-
"""星图连线：从「几何相邻」改成「有关系的连实线 + 同类细线」

背景（Owner 2026-10-31）：
    「他每个事件之间有关系吗？其实我觉得有关系的给他连接起来才比较好，
      当然其实在某一个大类里面的可以用那种细线连接也行。」

现状核实（改前）：连线是**同类别内按极角排序后连相邻两颗**，
    纯几何位置，不代表任何语义关系 —— 图例写「同类别的相邻经历」是夸大。

改后口径（必须诚实标在代码与图例里）：
    强边 = 文本词重叠（中文 2-gram + 英文整词，去停用词）Jaccard ≥ 阈值
         —— 这是**可验证的词面证据**，不是「我理解它们有关系」
    弱边 = 同类别内的最小生成树（保证连通、不杂乱）

本文件锁六件事：
A. 词重叠判定真能挑出有意义配对（用真实数据里的已知关系当夹具）
B. 停用词生效（「用户」「桌宠」不能把一切连起来）
C. 强边可跨类（真关系不分星团）
D. 弱边只在同类内，且同类 n 点最多 n-1 条（不爆炸）
E. 每点强边数有上限（防一个中心点辐射成毛球）
F. 不改动 load_stars 的星点数据（只加边，不动点）
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import memory_starmap as ms  # noqa: E402


def _star(text, cat='human', key=None):
    return {'text': text, 'imp': 3, 'age': 10.0, 'kind': 'fact',
            'cat': cat, 'detail': '', 'time': '2026-10-01',
            'key': key or ('t:%d' % (abs(hash(text)) % 99999))}


# ---------- A. 词重叠真能挑出关系 ----------
def test_terms_drops_stopwords():
    """「用户」「桌宠」这类泛词必须被滤掉，否则什么都相连"""
    t = ms.terms('用户会用日语梗和桌宠开玩笑')
    assert '用户' not in t, '停用词「用户」没被滤掉：%r' % sorted(t)
    assert '桌宠' not in t, '停用词「桌宠」没被滤掉'
    assert '日语' in t, '实词「日语」被误滤'


def test_terms_keeps_english_as_word_not_fragments():
    """英文按整词，不许切成 'py'/'ho'/'on' 这种碎片"""
    t = ms.terms('用户在学习 Python 的 matplotlib')
    assert 'python' in t and 'matplotlib' in t
    assert 'ho' not in t and 'yt' not in t, '英文被切成碎片了：%r' % sorted(t)


def test_jaccard_real_pair_is_high():
    a = _star('用户会用日语梗（如「この変態」）和桌宠开玩笑、逗它玩')
    b = _star('用户会用日语谐音梗（如「阿姨洗铁路」）向桌宠表达亲近/开玩笑')
    assert ms.jaccard(a['text'], b['text']) >= ms.STRONG_EDGE_JACCARD, \
        '真实相关的一对没达到强边阈值：%.3f' % ms.jaccard(a['text'], b['text'])


def test_jaccard_unrelated_pair_is_low():
    a = _star('用户爱吃重庆合川桃片，偏好甜味、老工艺')
    b = _star('用户爱背古文，会考据作者归属（如贾谊《过秦论》）')
    assert ms.jaccard(a['text'], b['text']) < ms.STRONG_EDGE_JACCARD, \
        '无关的一对超过了强边阈值：%.3f' % ms.jaccard(a['text'], b['text'])


# ---------- B/C/D/E. build_edges 结构 ----------
def _demo_stars():
    return [
        _star('用户会用日语梗和桌宠开玩笑', 'human', 'k1'),
        _star('用户会用日语谐音梗向桌宠开玩笑', 'human', 'k2'),
        _star('用户爱背古文会考据作者归属过秦论', 'study', 'k3'),
        _star('用户的古典文学兴趣涉及过秦论', 'study', 'k4'),
        _star('用户在 Python 基础关卡满分', 'mile', 'k5'),
        _star('用户在学习 Python 的 matplotlib', 'study', 'k6'),
    ]


def test_strong_edges_can_cross_categories():
    """真关系不分星团：Python 学习(study) ↔ 满分关卡(mile) 必须连上"""
    stars = _demo_stars()
    strong, weak = ms.build_edges(stars)
    cross = [e for e in strong if stars[e[0]]['cat'] != stars[e[1]]['cat']]
    assert cross, '跨类的强边一条都没有（真关系应当可以跨类）'


def test_weak_edges_stay_inside_category():
    stars = _demo_stars()
    _strong, weak = ms.build_edges(stars)
    for i, j, *_ in weak:
        assert stars[i]['cat'] == stars[j]['cat'], \
            '弱边跨了类别：%s(%s) - %s(%s)' % (stars[i]['text'][:12], stars[i]['cat'],
                                            stars[j]['text'][:12], stars[j]['cat'])


def test_weak_edges_do_not_explode():
    """同类 n 个点，弱边最多 n-1 条（最小生成树），不是 n*(n-1)/2"""
    stars = [_star('同类内容第%d条测试文本' % i, 'human', 'p%d' % i) for i in range(8)]
    _strong, weak = ms.build_edges(stars)
    assert len(weak) <= len(stars) - 1, '弱边 %d 条，超过 n-1=%d，会变成毛球' % (
        len(weak), len(stars) - 1)


def test_strong_edges_per_node_capped():
    """每个点的强边数有上限，防一个中心点辐射几十条"""
    txt = '用户会说日语梗开玩笑'
    stars = [_star(txt + '第%d次' % i, 'human', 'c%d' % i) for i in range(10)]
    strong, _weak = ms.build_edges(stars)
    deg = {}
    for i, j, *_ in strong:
        deg[i] = deg.get(i, 0) + 1
        deg[j] = deg.get(j, 0) + 1
    assert all(v <= ms.STRONG_EDGES_PER_NODE for v in deg.values()), \
        '有点的强边超过上限 %d：%r' % (ms.STRONG_EDGES_PER_NODE, deg)


def test_no_self_loops_and_no_duplicates():
    stars = _demo_stars()
    strong, weak = ms.build_edges(stars)
    for edges, name in ((strong, 'strong'), (weak, 'weak')):
        seen = set()
        for i, j, *_ in edges:
            assert i != j, '%s 有自环' % name
            k = (min(i, j), max(i, j))
            assert k not in seen, '%s 有重复边 %r' % (name, k)
            seen.add(k)


def test_edges_use_real_jaccard_as_weight():
    """强边要带权重（画线时按关系强度给不同亮度）"""
    stars = _demo_stars()
    strong, _ = ms.build_edges(stars)
    assert strong, '没有强边，无法验证权重'
    for e in strong:
        assert len(e) >= 3 and isinstance(e[2], float), '强边缺权重：%r' % (e,)
        assert e[2] >= ms.STRONG_EDGE_JACCARD


# ---------- F. 不改星点数据 ----------
def test_build_edges_does_not_mutate_stars():
    stars = _demo_stars()
    before = [dict(s) for s in stars]
    ms.build_edges(stars)
    assert stars == before, 'build_edges 改动了星点数据'


# ---------- 真实数据冒烟 ----------
def test_real_data_builds_edges():
    stars, _dead, _n = ms.load_stars()
    if len(stars) < 2:
        pytest.skip('真实记忆不足 2 条')
    strong, weak = ms.build_edges(stars)
    # 23 个星点、内容明显有重合（日语梗/过秦论/Python）⇒ 强边不该是 0
    assert strong, '真实数据上一条强边都没连出来（判据可能过严）'
    assert len(strong) < len(stars) * 3, '强边 %d 条太多，线会糊成一团' % len(strong)
