# -*- coding: utf-8 -*-
"""向量检索 + 自适应阈值（2026-11-06）

## 为什么有这份测试

Owner：「向量接产品 + 自适应阈值。留出集 R@3 从 3/12 提到 11/12，组件写好了但没接。
卡在『阈值随库规模漂移』—— 库小时 0.51 合适，库大了区分度从 0.107 掉到 0.022。」

实测（固定余弦 0.51 的对照实验，脚本见 `tools/eval/experiment/`）：
    库 21 条  → 负样本误注入 7/42、无关查询 2/18
    库 521 条 → 负样本误注入 34/42、无关查询 16/18   召回几乎不变
⇒ 固定阈值必然随库增长失效。改为按本库相似度分布定标的 z 门槛。

## 口径（本文件锁住）

· z 门槛随库条数**单调收紧**，且有上下限
· 极小库（<10 条）退回绝对阈值 —— z 在 n 条样本上上限是 sqrt(n-1)，n=2 时够不到任何门槛
· 概念提问不注入（产品契约），向量路径同样先过守卫
· 组件不可用必须回退 BM25，不许因此不答话
· **库增长时负样本误注入必须基本不涨**（这是"自适应"的验收判据）
"""
import io
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import memory_embed as mb        # noqa: E402
import memory_engine as me       # noqa: E402

EV = os.path.join(BASE, 'tools', 'eval')


# ---------- A. 阈值函数本身 ----------
def test_threshold_grows_with_library_size():
    z21 = mb.adaptive_z_threshold(21)
    z121 = mb.adaptive_z_threshold(121)
    z521 = mb.adaptive_z_threshold(521)
    assert z21 < z121 < z521, '门槛没随库增长收紧：%r' % ((z21, z121, z521),)


def test_threshold_is_clamped():
    assert mb.adaptive_z_threshold(1) >= mb.ADAPTIVE_Z_MIN
    assert mb.adaptive_z_threshold(10 ** 7) <= mb.ADAPTIVE_Z_MAX


def test_threshold_at_reference_point():
    assert abs(mb.adaptive_z_threshold(mb.ADAPTIVE_REF_N) - mb.ADAPTIVE_Z0) < 1e-6


# ---------- B. 检索行为 ----------
class _Stub:
    """最小替身：只实现 search_adaptive 需要的东西"""

    def __init__(self, sims):
        import numpy as np
        self._np = np
        self.ok = True
        self._sims = np.asarray(sims, dtype='float32')

    def score(self, query, vecs):
        return self._sims

    def search_adaptive(self, query, vecs, texts, k=3, threshold=None,
                        definition_guard=True):
        return mb.Embedder.search_adaptive(self, query, vecs, texts, k=k,
                                           threshold=threshold,
                                           definition_guard=definition_guard)

    def top_k(self, query, vecs, texts, k=3, threshold=None):
        thr = mb.DEFAULT_THRESHOLD if threshold is None else float(threshold)
        out = []
        for i in self._np.argsort(-self._sims):
            if float(self._sims[int(i)]) < thr:
                break
            out.append({'index': int(i), 'score': float(self._sims[int(i)]),
                        'text': texts[int(i)]})
            if len(out) >= k:
                break
        return out


def test_adaptive_picks_only_outliers():
    """库内分布平坦时（没有离群点）→ 不注入"""
    sims = [0.30, 0.31, 0.32, 0.30, 0.29, 0.31, 0.30, 0.32, 0.30, 0.31,
            0.29, 0.30, 0.31, 0.30, 0.32, 0.30, 0.29, 0.31, 0.30, 0.31]
    st = _Stub(sims)
    got = st.search_adaptive('q', None, ['t%d' % i for i in range(len(sims))])
    assert got == [], '平坦分布里也注入了 —— 阈值没起作用：%r' % (got,)


def test_adaptive_picks_clear_outlier():
    """有一个明显离群点 → 只取它"""
    sims = [0.30] * 20
    sims[7] = 0.78
    st = _Stub(sims)
    got = st.search_adaptive('q', None, ['t%d' % i for i in range(len(sims))])
    assert got and got[0]['index'] == 7, '离群点没被选中：%r' % (got,)
    assert got[0]['z'] > mb.adaptive_z_threshold(len(sims)) - 0.01


def test_small_library_falls_back_to_absolute():
    """2 条库：z 上限只有 1.0，任何 z 门槛都够不到 → 必须退回绝对阈值

    ⚠ 这是实测抓出来的：改完自适应后，2 条库的闸门用例全红（永不注入）。
    """
    sims = [0.90, 0.20]
    st = _Stub(sims)
    got = st.search_adaptive('q', None, ['a', 'b'])
    assert got, '极小库被 z 门槛闸死了'
    assert got[0]['index'] == 0


def test_definition_question_never_injects():
    sims = [0.99] * 20
    st = _Stub(sims)
    for q in ('扫雷是什么', '介绍一下骰子', '骰子怎么玩'):
        assert st.search_adaptive(q, None, ['t%d' % i for i in range(20)]) == [], (
            '概念提问「%s」仍注入了 —— 违反「记忆只作背景」契约' % q)


# ---------- C. 生产接线 ----------
def _emb():
    e = mb.get_embedder()
    return e


_needs_model = pytest.mark.skipif(
    not _emb().ok, reason='本机没有可用向量模型：%s' % (_emb().reason or '未知'))


def test_production_uses_vector_when_available():
    if not _emb().ok:
        pytest.skip('无模型')
    # ⚠ 库要到 MIN_N_FOR_Z 以上才走 z 路径（极小库退回绝对阈值，另有专门用例）
    facts = [
        {'id': 'f1', 'content': '用户爱吃重庆合川桃片，偏好甜味、老工艺', 'status': 'active'},
        {'id': 'f2', 'content': '用户是大二学生，专业是地理信息科学', 'status': 'active'},
        {'id': 'f3', 'content': '用户对古典诗词有兴趣，常让桌宠讲解', 'status': 'active'},
        {'id': 'f4', 'content': '用户正在学习 Python，会发代码片段请求分析', 'status': 'active'},
        {'id': 'f5', 'content': '用户的笔记本电脑是 ThinkPad', 'status': 'active'},
        {'id': 'f6', 'content': '用户的老家在重庆合川', 'status': 'active'},
        {'id': 'f7', 'content': '用户喜欢玩《战争雷霆》解压', 'status': 'active'},
        {'id': 'f8', 'content': '用户会日语谐音梗和桌宠开玩笑', 'status': 'active'},
        {'id': 'f9', 'content': '用户的姐姐叫大蓝，是 Pro 模型的形象', 'status': 'active'},
        {'id': 'f10', 'content': '用户在做重庆区县地理数据的分析', 'status': 'active'},
        {'id': 'f11', 'content': '用户爱背古文，会考据作者归属', 'status': 'active'},
        {'id': 'f12', 'content': '用户关注桌宠的记忆机制是否优化', 'status': 'active'},
    ]
    got = me.search_memory_for_injection(facts, '我平时吃什么零食', top_k=2)
    assert got, '语义相近的问题没召回（说明向量路径没生效）'
    assert any(c.get('via') == 'vector' for c in got), (
        '返回里没有 via=vector ⇒ 走的还是 BM25：%r' % (got,))
    assert any('桃片' in str(c.get('text', '')) for c in got), (
        '语义召回没打到目标记忆：%r' % ([c.get('text') for c in got],))


def test_production_falls_back_to_bm25(monkeypatch):
    """组件不可用 → 回退 BM25，且返回值不带 via"""
    class _Down:
        ok = False
        reason = '测试：模型不可用'

        def encode(self, *a, **k):
            return None

    monkeypatch.setattr(mb, 'get_embedder', lambda *a, **k: _Down())
    facts = [{'id': 'f1', 'content': '用户爱背古文，会考据作者归属', 'status': 'active'},
             {'id': 'f2', 'content': '用户爱吃桃片', 'status': 'active'}]
    # 查询要含两个以上同 2-gram，否则 BM25 闸门本来就该挡住（那不是回退的错）
    got = me.search_memory_for_injection(facts, '背一下古文，考据作者', top_k=2)
    assert got, '回退 BM25 后连字面命中都没有'
    assert all(c.get('via') is None for c in got), '回退路径仍带了 via（说明没回退）'


def test_vector_off_switch(monkeypatch):
    """vector='off' 强制走 BM25（出问题时可一键回到旧行为）"""
    facts = [{'id': 'f1', 'content': '用户爱背古文，会考据作者归属', 'status': 'active'}]
    got = me.search_memory_for_injection(facts, '背一下古文', top_k=2, vector='off')
    assert all(c.get('via') is None for c in got)


# ---------- D. 验收判据：库变大时误注入不许暴涨 ----------
@_needs_model
def test_negatives_do_not_explode_with_library_growth():
    """库 18 → 318 条：向量这一路**多带的误注入必须是常数**

    为什么这样测：生产默认是「字面 ∪ 语义」，BM25 本身也会随库增长而变多
    （实测 2 → 8/42），直接卡总数会把 BM25 的锅算到自适应阈值头上。
    真正要锁的是**向量路新增了多少**——自适应生效就应该是常数：

        库 18 条：BM25 2/42，并集 6/42 ⇒ 向量多带 4
        库 318 条：BM25 8/42，并集 12/42 ⇒ 向量多带 4

    对照（固定 0.51）：库 21 条多带 5，库 521 条多带 22 —— 随库放大。

    ⚠ 这条判据被真锁验证修正过一次：最初写「总数不超小库 2 倍」，
      把阈值关掉后两边都 42，`42 <= 84` 反而通过（区分不了"生效"与"全放行"）。
    """
    import random
    neg = json.load(io.open(os.path.join(EV, 'negatives.json'), encoding='utf-8'))
    qs = []
    for _c, lst in neg.get('categories', {}).items():
        for q in (lst if isinstance(lst, list) else []):
            t = q.get('query') if isinstance(q, dict) else str(q)
            if t:
                qs.append(t)

    d = json.load(io.open(os.path.join(BASE, 'memory.json'), encoding='utf-8'))
    real = [f for f in d.get('facts', []) if f.get('status') == 'active']
    pool_path = os.path.join(EV, 'experiment', 'data', 'memories-1411.json')
    if not os.path.exists(pool_path):
        pytest.skip('缺少噪声池 memories-1411.json')
    pool = json.load(io.open(pool_path, encoding='utf-8')).get('facts', [])

    def extra(facts):
        me._VEC_CACHE.update({'fp': '', 'mat': None, 'texts': [], 'ids': []})
        bm = sum(1 for q in qs if me.search_memory_for_injection(facts, q, top_k=3,
                                                                 vector='off'))
        un = sum(1 for q in qs if me.search_memory_for_injection(facts, q, top_k=3))
        return un - bm

    rnd = random.Random(11)
    big = real + [dict(f, id='n%d' % i) for i, f in enumerate(rnd.sample(pool, 300))]
    e_small, e_big = extra(real), extra(big)
    assert e_big <= 8, (
        '库 318 条时向量多带 %d 条误注入（固定阈值实测多带 22）—— 自适应没起作用'
        % e_big)
    assert e_big <= e_small + 2, (
        '向量多带的误注入从 %d 涨到 %d —— 它应该与库规模无关' % (e_small, e_big))

# ---------- D. 极小库走产品入口（2026-11-08） ----------
def test_small_library_through_product_entry_does_not_raise():
    """库 < MIN_N_FOR_Z 时，向量结果里没有 z —— 产品入口不许因此抛 KeyError。

    起因（外部复核指出）：`search_adaptive` 在 n < MIN_N_FOR_Z 时退回绝对阈值分支，
    该分支走 `top_k`，返回形状只有 index/score/text，**没有 z**。
    而 `search_memory_vector` 直接取 `h['z']` ⇒ KeyError，再被上层兜底吞掉、
    静默退回 BM25 ⇒ 新装用户（记忆 < 10 条）语义检索完全不生效，
    日志只说「向量检索异常」，排查方向会被带偏。

    ⚠ 本用例走的是**产品函数** search_memory_vector，不是内层 search_adaptive ——
      原来那条 test_small_library_falls_back_to_absolute 只测内层，
      所以外层这个 KeyError 一直没被测到。
    """
    if not _emb().ok:
        pytest.skip('无模型')
    facts = [
        {'id': 'f1', 'content': '用户爱吃重庆合川桃片，偏好甜味、老工艺', 'status': 'active'},
        {'id': 'f2', 'content': '用户是大二学生，专业是地理信息科学', 'status': 'active'},
        {'id': 'f3', 'content': '用户对古典诗词有兴趣，常让桌宠讲解', 'status': 'active'},
        {'id': 'f4', 'content': '用户的笔记本电脑是 ThinkPad', 'status': 'active'},
        {'id': 'f5', 'content': '用户喜欢玩《战争雷霆》解压', 'status': 'active'},
    ]
    assert len(facts) < mb.MIN_N_FOR_Z, '前置条件变了：库条数必须小于 %d' % mb.MIN_N_FOR_Z
    # ⚠ 问句必须与库内某条足够接近：小库走绝对阈值 0.51，泛问句（如「我平时吃什么零食」）
    #   根本过不了线 ⇒ 走不到 h['z'] 那一行，测不出原缺陷。
    #   实测（2026-11-08，5 条库）：「我平时吃什么零食」0 条；下面这句 0.993 过线。
    got = me.search_memory_vector(facts, '用户爱吃重庆合川桃片', top_k=2)
    assert got is not None, '返回 None 表示被当成组件不可用了'
    assert got, '5 条库语义召回应能命中桃片那条（走绝对阈值分支）'
    for c in got:
        assert 'z' in c, '小库分支缺 z 字段：%r' % (sorted(c.keys()),)
        assert c['z'] == 0.0, '小库分支的 z 应为占位 0.0，实际 %r' % (c['z'],)
        assert c.get('via') == 'vector'


def test_small_library_injection_finds_target():
    """极小库走完整注入入口，必须真的把目标记忆抬出来（不是只不抛异常）。"""
    if not _emb().ok:
        pytest.skip('无模型')
    facts = [
        {'id': 'f1', 'content': '用户爱吃重庆合川桃片，偏好甜味、老工艺', 'status': 'active'},
        {'id': 'f2', 'content': '用户是大二学生，专业是地理信息科学', 'status': 'active'},
        {'id': 'f3', 'content': '用户对古典诗词有兴趣，常让桌宠讲解', 'status': 'active'},
        {'id': 'f4', 'content': '用户的笔记本电脑是 ThinkPad', 'status': 'active'},
    ]
    got = me.search_memory_for_injection(facts, '用户爱吃重庆合川桃片', top_k=2)
    assert got, '4 条库在这个问句上没召回，说明向量路被 KeyError 掉了'
    assert any('桃片' in str(c.get('text', c.get('content', ''))) for c in got), (
        '没打到目标记忆：%r' % ([c.get('text') for c in got],))
    # ⭐ 关键断言：必须是**向量**给的，不能是 KeyError 之后 BM25 兜底的
    #   （只断言「召回到了」没有牙 —— 兜底路径同样能召回，注入缺陷时仍然绿）
    assert any(c.get('via') == 'vector' for c in got), (
        '召回不是向量路给的 ⇒ 说明向量那一步抛异常被兜底了：%r' % (got,))
