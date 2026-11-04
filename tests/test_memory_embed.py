# -*- coding: utf-8 -*-
"""memory_embed 单测（2026-11-04 新增）

分两段：
  · **降级段**：不需要模型，恒可跑 —— 保证「模型缺失时不许崩、不许静默」
  · **能力段**：需要真模型（设 PET_EMBED_DIR 或放 models/bge-small-zh-v1.5/，
    没模型自动 skip）

⚠ 能力段刻意**检查语义方向**而不只是「跑通」：
  只断言 shape/不抛错，等于没验证（本项目 2026-09-20 的教训：
  「流程跑通 ≠ 做对」）。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_embed as me  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 评测时下载的模型缓存（gitignore，可重下）
EVAL_CACHE = os.path.join(ROOT, 'tools', 'eval', 'experiment', '_embed_probe')


def _have_model():
    d, _why = me._find_model_dir(EVAL_CACHE if os.path.isdir(EVAL_CACHE) else None)
    return d


needs_model = pytest.mark.skipif(_have_model() is None,
                                 reason='无本地模型（设 PET_EMBED_DIR 或放 models/）')


@pytest.fixture
def embedder():
    """★ 必须把找到的模型目录显式传进去。

    第一版这里调 me.get_embedder() 不带路径 ⇒ 组件去默认位置 models/ 找 ⇒
    找不到 ⇒ 6 个能力测试全 skip，却显示「通过」。
    （教训：skip 也是「没验证」，报绿之前先看 skipped 有几个。）
    """
    me.reset()
    d = _have_model()
    if d is None:
        pytest.skip('无本地模型')
    e = me.get_embedder(d)
    assert e.ok, '找到模型目录 %s 却加载失败：%s' % (d, e.reason)
    return e


# ═══════════════ 降级段（不需要模型） ═══════════════

def test_missing_model_reports_specific_reason(tmp_path):
    """模型目录不存在时：ok=False，且 reason 要说清楚缺什么、怎么补（不许静默）"""
    me.reset()
    e = me.Embedder(str(tmp_path / 'not-here'))
    assert e.ok is False
    assert e.reason, '不可用必须留原因'
    assert ('模型' in e.reason) or ('缺' in e.reason), \
        '原因要具体到「缺什么」，实际：%r' % e.reason
    # 提示要给出补救路径，否则用户干瞪眼
    assert (me.ENV_MODEL_DIR in e.reason) or ('models' in e.reason), \
        '原因里应给出补救办法，实际：%r' % e.reason


def test_unavailable_returns_none_not_raise(tmp_path):
    """不可用时所有取值接口返回 None/空，绝不抛异常（调用方要能无脑回退）"""
    e = me.Embedder(str(tmp_path / 'nope'))
    assert e.encode(['x']) is None
    assert e.score('x', [[0.0] * me.EMBED_DIM]) is None
    assert e.top_k('x', [[0.0] * me.EMBED_DIM], ['t']) == []
    assert e.search('x', [[0.0] * me.EMBED_DIM], ['t']) == []


def test_status_is_never_silent(tmp_path):
    me.reset()
    me.get_embedder(str(tmp_path / 'nope'))
    s = me.status()
    assert '不可用' in s and len(s) > 10, '状态句必须说明原因，实际：%r' % s
    assert me.AVAILABLE is False


@pytest.mark.parametrize('q,expect', [
    ('扫雷是什么', True),
    ('介绍一下骰子', True),
    ('骰子是啥', True),
    ('这个报错什么意思', True),
    ('讲讲考研数学二', True),
    ('Python 有什么用的', True),
    # 以下是在问「我」，不该被守卫拦
    ('我平时玩什么游戏解压', False),
    ('我爱吃啥', False),
    ('我大几', False),
    ('我累得不行的时候会去玩那个坦克的游戏', False),
])
def test_definition_question_guard(q, expect):
    """「在问概念」与「在问我」必须分开 —— 这是 test_memory_gate 的语义契约"""
    assert me.is_definition_question(q) is expect


def test_guard_known_gap():
    """已知覆盖缺口（记下来，别装作守卫万无一失）

    「扫雷怎么玩」问的是玩法，按契约也不该注入用户偏好，
    但词表里没有它 ⇒ 守卫放行。这是遗留风险，不是本测试要修的 bug。
    """
    assert me.is_definition_question('扫雷怎么玩') is False


def test_content_key_changes_with_content():
    """内容变了 key 必须变 —— 否则 update_facts 改写后还拿旧向量"""
    a = me.VectorCache.content_key('用户爱吃桃片')
    b = me.VectorCache.content_key('用户爱吃桃片')
    c = me.VectorCache.content_key('用户不爱吃桃片了')
    assert a == b
    assert a != c


def test_cache_fingerprint_mismatch_forces_rebuild(tmp_path):
    """模型指纹不符 → 必须判定缓存失效（否则新旧向量混用，cosine 无意义）"""
    import numpy as np
    path = str(tmp_path / 'v.npz')
    # 伪造一份「旧模型」的缓存
    np.savez_compressed(path,
                        fingerprint=np.array('old-model|x|512|128'),
                        ids=np.array(['a'], dtype=object),
                        keys=np.array(['k' * 16], dtype=object),
                        vecs=np.zeros((1, me.EMBED_DIM), dtype='float32'))
    c = me.VectorCache(path)
    c.fp = 'new-model|y|512|128'
    assert c.load() is False
    assert '指纹' in c.load_error


def test_cache_missing_file_is_quiet(tmp_path):
    """缓存文件不存在不算错误（首次运行）"""
    c = me.VectorCache(str(tmp_path / 'none.npz'))
    assert c.load() is False
    assert c.load_error == ''


# ═══════════════ 能力段（需要真模型） ═══════════════

@needs_model
def test_encode_shape_and_normalized(embedder):
    v = embedder.encode(['用户是大二学生', '用户爱喝拿铁'])
    assert v.shape == (2, me.EMBED_DIM)
    import numpy as np
    norms = np.linalg.norm(v, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4), '必须 L2 归一化，否则 cosine 不可比'


@needs_model
def test_semantic_direction_is_right(embedder):
    """★ 关键：同义改写要**比**无关句更近（只验 shape 等于没验）"""
    import numpy as np
    v = embedder.encode([
        '用户是大二学生',
        '我读大几了来着',                      # 同义
        '用户爱吃重庆合川桃片',                 # 无关
    ])
    sim_same = float(np.dot(v[0], v[1]))
    sim_diff = float(np.dot(v[0], v[2]))
    assert sim_same > sim_diff + 0.05, \
        '同义句相似度没明显高于无关句：%.3f vs %.3f' % (sim_same, sim_diff)


@needs_model
def test_holdout_query_hits_correct_fact(embedder):
    """留出集的真实问法要能命中真实记忆（语义检索的核心价值）"""
    facts = ['我的名字叫小蓝（V4 Flash 桌宠）',
             '用户是大二学生',
             '用户爱吃重庆合川桃片，偏好甜味、老工艺、现切的',
             '用户在学习/练习 Python，会把自己写的代码片段发给桌宠',
             '用户累了/解压时会玩《战争雷霆》（War Thunder）',
             '用户通过 AutoClaw（桌面 AI 协作平台）来强化小蓝桌宠']
    vecs = embedder.encode(facts)
    cases = [('我大几', '大二'), ('我平时拿什么当零食', '桃片'),
             ('我放松的时候打什么游戏', '战争雷霆')]
    for q, needle in cases:
        hits = embedder.top_k(q, vecs, facts, k=3, threshold=0.0)
        assert hits, '「%s」什么都没召回' % q
        assert any(needle in h['text'] for h in hits), \
            '「%s」top3 里没有「%s」，实际：%s' % (
                q, needle, [h['text'][:16] for h in hits])


@needs_model
def test_search_guards_definition_questions(embedder):
    """守卫生效：概念提问即使余弦很高也不返回"""
    facts = ['用户喜欢在桌宠里玩扫雷和 Farkle 骰子']
    vecs = embedder.encode(facts)
    raw = embedder.top_k('扫雷是什么', vecs, facts, k=3, threshold=0.0)
    assert raw, '（前提）不加守卫时本来会命中 —— 否则这个测试没意义'
    assert embedder.search('扫雷是什么', vecs, facts, k=3, threshold=0.0) == []


@needs_model
def test_cache_roundtrip_and_incremental(embedder, tmp_path):
    """缓存能存能读；只编码新增项（已缓存的不重算）"""
    path = str(tmp_path / 'v.npz')
    c = me.VectorCache(path, embedder.model_dir)
    facts = [{'id': 'a', 'content': '用户是大二学生'},
             {'id': 'b', 'content': '用户爱吃桃片'}]
    mat, texts = c.sync(facts, embedder)
    assert mat is not None and mat.shape == (2, me.EMBED_DIM)
    assert texts == ['用户是大二学生', '用户爱吃桃片']
    assert c.save() is True

    c2 = me.VectorCache(path, embedder.model_dir)
    assert c2.load() is True
    assert c2.ids == ['a', 'b']

    # 加一条新的 + 改一条旧的 → 只该重算这两条
    facts2 = [{'id': 'a', 'content': '用户是大二学生'},     # 不变
              {'id': 'b', 'content': '用户现在不爱吃桃片了'},  # 变了
              {'id': 'c', 'content': '用户爱喝拿铁'}]        # 新增
    calls = {'n': 0}
    real_encode = embedder.encode

    def counting(texts_):
        calls['n'] += len(texts_)
        return real_encode(texts_)

    embedder.encode = counting
    try:
        mat2, _t = c2.sync(facts2, embedder)
    finally:
        embedder.encode = real_encode
    assert mat2 is not None and mat2.shape == (3, me.EMBED_DIM)
    assert calls['n'] == 2, '应只编码 2 条（b 变更 + c 新增），实际 %d' % calls['n']


@needs_model
def test_cache_survives_missing_dir(embedder, tmp_path):
    """缓存目录不存在也要能建（首次运行）"""
    path = str(tmp_path / 'deep' / 'dir' / 'v.npz')
    c = me.VectorCache(path, embedder.model_dir)
    c.sync([{'id': 'a', 'content': '用户是大二学生'}], embedder)
    assert c.save() is True
    assert os.path.exists(path)

# ═══════════════ 校准条件（降级段，不需要模型） ═══════════════

def test_calibration_quiet_on_int8_size():
    """校准时的模型大小（22.9MB）不该告警"""
    assert me.calibration_warning(22.9) == ''
    assert me.calibration_warning(23.5) == ''       # ±25% 内都算同一个量化


def test_calibration_warns_on_fp32_size():
    """fp32（90.5MB）必须告警 —— 实测它的余弦整体低约 0.02，沿用 0.51 会漏"""
    w = me.calibration_warning(90.5)
    assert w, '换了量化却没告警'
    assert '重校准' in w
    assert '90.5' in w and '22.9' in w


def test_calibration_tolerates_bad_input():
    for bad in (None, 'abc', 0, -1, b'x'):
        assert me.calibration_warning(bad) == ''


def test_calibration_band_is_documented():
    """校准条件必须写在代码里，不能只活在这轮对话里"""
    assert me.CALIBRATION['model_tag'] == me.MODEL_TAG
    lo, hi = me.CALIBRATION['band']
    assert lo < me.DEFAULT_THRESHOLD <= hi, (
        '当前阈值 %.3f 不在记录的稳健带 %s 内' % (me.DEFAULT_THRESHOLD, (lo, hi)))
    assert me.CALIBRATION['library_size'] > 0
