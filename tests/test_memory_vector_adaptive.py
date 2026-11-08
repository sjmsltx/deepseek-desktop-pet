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

import types

import numpy as np
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
    """有一个明显离群点 → 只取它，且 z 达标。

    ⚠ 库规模取 ADAPTIVE_REF_N + 20（46 条），**必须在校准点以上**：
    2026-11-08 起小库（< ADAPTIVE_REF_N）改走「余弦+gap」分支、不再产出 z，
    本条断言的 z 只对 z 分支成立。原来用 20 条 —— 那正好落在小库区间，
    改判据后 z 恒为占位 0.0 ⇒ 该用例当场变红（红的原因是用例位置错了，不是功能坏了）。
    """
    n = mb.ADAPTIVE_REF_N + 20
    sims = [0.30] * n
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


# ---------- E. 小库判据（余弦 + gap，不用 z），2026-11-08 ----------
def _stub_with(sims):
    st = _Stub(sims)
    return st


def test_small_library_uses_gap_not_z():
    """小库（< ADAPTIVE_REF_N）走「余弦 + gap」分支：不产出 z，z 恒为 0.0。

    起因：z 在 n 条样本上上限只有 √(n-1)（n=15 时 3.74、n=18 时 4.12），
    门槛 2.5 已占去大半量程 ⇒ 18 条库上 9/21 条用例的 z 落在门槛 ±0.5 内，
    库规模一动就翻面（清理删 3 条后 h06/h08 从命中变不命中，而余弦几乎没变）。
    """
    n = mb.ADAPTIVE_REF_N - 3          # 18 条，在小库区间内
    sims = [0.0] * n
    sims[0], sims[1] = 0.80, 0.60      # 明显胜出
    st = _stub_with(sims)
    got = st.search_adaptive('q', None, ['t%d' % i for i in range(n)])
    assert got, '小库在明显胜出时应当注入'
    assert got[0]['z'] == 0.0, '小库分支不该产出 z 值，实际 %r' % (got[0]['z'],)


def test_small_library_rejects_when_gap_too_small():
    """小库：top1 与 top2 咬得太近（< SMALL_LIB_GAP）时不注入。

    这是小库判据的核心约束：没有明显第一名就当作「说不清」。
    """
    n = mb.ADAPTIVE_REF_N - 3
    sims = [0.0] * n
    sims[0], sims[1] = 0.70, 0.70 - (mb.SMALL_LIB_GAP / 2.0)
    st = _stub_with(sims)
    got = st.search_adaptive('q', None, ['t%d' % i for i in range(n)])
    assert got == [], 'gap 不足时仍注入：%r' % (got,)


def test_small_library_rejects_below_abs_floor_without_clear_winner():
    """小库：低于绝对下限、且没有明显胜出时，不注入。

    ⚠ 注意「且没有明显胜出」这个前提。小库分支保留了 `ADAPTIVE_GAP_BYPASS` 旁路：
    gap ≥ 0.10 时即使余弦低于下限也放行 —— 因为有些**真召回**就是这样
    （实测「我平时吃什么零食」→ 桃片：余弦 0.404 < 0.50，但 gap 0.100）。
    本条构造的是「低于下限 + 与第二名咬得很近」，两个条件都不满足，应当拒绝。
    """
    n = mb.ADAPTIVE_REF_N - 3
    sims = [0.0] * n
    sims[0] = mb.ADAPTIVE_ABS_FLOOR - 0.05
    sims[1] = sims[0] - 0.01            # gap 0.01 < 旁路阈值 0.10
    st = _stub_with(sims)
    got = st.search_adaptive('q', None, ['t%d' % i for i in range(n)])
    assert got == [], '低于下限且无明确胜出，仍注入：%r' % (got,)


def test_small_library_clear_winner_bypasses_floor():
    """小库：明显胜出时绕过绝对下限（这条旁路必须留着，否则真召回会丢）。"""
    n = mb.ADAPTIVE_REF_N - 3
    sims = [0.0] * n
    sims[0] = mb.ADAPTIVE_ABS_FLOOR - 0.05   # 低于下限
    sims[1] = sims[0] - 0.15                 # 但 gap 0.15 ≥ 旁路 0.10
    st = _stub_with(sims)
    got = st.search_adaptive('q', None, ['t%d' % i for i in range(n)])
    assert got, '明显胜出却被下限拦住 —— 旁路失效了'
    assert got[0]['index'] == 0


def test_large_library_still_uses_z():
    """库 ≥ ADAPTIVE_REF_N 时必须仍走 z 分支（新分支不许外溢到校准点以上）。"""
    n = mb.ADAPTIVE_REF_N + 20
    sims = [0.0] * n
    sims[0] = 0.80
    st = _stub_with(sims)
    got = st.search_adaptive('q', None, ['t%d' % i for i in range(n)])
    assert got, '大库明显离群点没被选中'
    assert got[0]['z'] != 0.0, '大库仍应走 z 分支（不该返回占位 0.0）'


def test_small_lib_gap_can_be_disabled():
    """SMALL_LIB_GAP=None 时退回旧的纯 z 路径（便于对照与回滚）。"""
    n = mb.ADAPTIVE_REF_N - 3
    sims = [0.0] * n
    sims[0], sims[1] = 0.80, 0.60
    orig = mb.SMALL_LIB_GAP
    try:
        mb.SMALL_LIB_GAP = None
        st = _stub_with(sims)
        got = st.search_adaptive('q', None, ['t%d' % i for i in range(n)])
        # ⚠ 2026-11-08：原来写 `if got:` 包住断言 —— got 为空时整个断言被跳过，
        #   等于一条空测试。外部复核指出。现在先断言「确实注入了」再断言走的是 z 分支。
        assert got, '关闭小库判据后应当走 z 分支并注入，实际返回空'
        assert got[0]['z'] != 0.0, '关闭后应走 z 分支（z 不该是占位 0.0）'
    finally:
        mb.SMALL_LIB_GAP = orig


# ---------- F. 旁路只许放行第一名（2026-11-08，外部复核必改①）----------
def _embedder_with(sims):
    """造一个只喂固定相似度的 Embedder（走产品 search_adaptive 本体）"""
    st = mb.Embedder.__new__(mb.Embedder)
    st._np = np
    arr = np.array(sims, dtype=np.float64)
    st.score = types.MethodType(lambda self, q, vecs: arr, st)
    return st


def _texts(n):
    return ['t%d' % i for i in range(n)]


def test_bypass_releases_only_one_item_when_top_is_below_floor():
    """明显胜出但 top1 低于下限时，只放行 top1 —— 不许把 k 条都放进来。

    改前实测：k=3 返回 3 条，第 3 条余弦 0.0000（完全无关的条目被注入）。
    """
    n = mb.ADAPTIVE_REF_N - 3
    sims = [0.0] * n
    sims[0], sims[1] = 0.45, 0.30        # win = 0.15 ≥ 旁路 0.10；两者都 < 0.50
    st = _embedder_with(sims)
    for k in (1, 2, 3):
        got = st.search_adaptive('q', None, _texts(n), k=k)
        assert len(got) == 1, (
            'k=%d 时放行了 %d 条 —— 旁路只许放行第一名（改前的缺陷正是放行 k 条）'
            % (k, len(got)))
        assert got[0]['index'] == 0


def test_bypass_never_injects_zero_similarity_items():
    """余弦 0.0000 的条目绝不能被注入 —— 这是最坏的一种「放行」。

    改前 k=3 时它确实注入了（第 3 条）。这条直接钉住那个具体后果。
    """
    n = mb.ADAPTIVE_REF_N - 3
    sims = [0.0] * n
    sims[0], sims[1] = 0.45, 0.30
    st = _embedder_with(sims)
    got = st.search_adaptive('q', None, _texts(n), k=5)
    zeros = [g for g in got if g['score'] <= 0.0]
    assert not zeros, '注入了余弦 0 的条目：%r' % (zeros,)


def test_normal_path_still_returns_up_to_k_when_all_above_floor():
    """不触发旁路、多条都过下限时，仍然要能返回 k 条。

    ⚠ 这条防的是「为了修旁路把正常路径改成只返 1 条」——最常见的连带伤害。
    """
    n = mb.ADAPTIVE_REF_N - 3
    sims = [0.0] * n
    sims[0], sims[1], sims[2] = 0.90, 0.80, 0.70   # 全部 ≥ 0.50
    st = _embedder_with(sims)
    got = st.search_adaptive('q', None, _texts(n), k=3)
    assert len(got) == 3, '正常路径应返回 3 条，实际 %d' % len(got)


def test_bypass_does_not_apply_when_win_is_small():
    """窗口不够大时，即使 top1 过下限也不该走旁路（旁路是给「明显胜出」用的）。"""
    n = mb.ADAPTIVE_REF_N - 3
    sims = [0.0] * n
    sims[0], sims[1] = 0.45, 0.45 - (mb.ADAPTIVE_GAP_BYPASS / 2)
    st = _embedder_with(sims)
    got = st.search_adaptive('q', None, _texts(n), k=3)
    assert got == [], 'win 不足却注入了：%r' % (got,)
