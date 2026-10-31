# -*- coding: utf-8 -*-
"""性格 × 好感度矩阵：钉住「真的不一样」。

⛔ 这组存在的理由（Owner 2026-10-31）：
   「好感度对于体验感觉没什么太大区别，根本感受不到什么大的差别」

   实测到两条机械原因：
     ① `affection.json` 里 affection 已是 **200/200 封顶** ⇒ 永远停在「灵魂伴侣」
     ② 性格在 prompt 里只是个词（「当前性格：温柔」），与阶段**从未交叉**
        ⇒ 温柔/傲娇/吐槽/元气/高冷 拿到的注入文本**完全相同**

   本文件钉住 ②：同阶段不同性格必须产出不同文本。
"""
import hashlib
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import affection_engine as ae  # noqa: E402

PERSONAS = ['温柔', '傲娇', '吐槽', '元气', '高冷']


def _h(t):
    return hashlib.md5(t.encode('utf-8')).hexdigest()


def test_five_personas_differ_at_same_stage():
    """⭐ 同一阶段下五种性格必须产出不同文本（改前完全相同）"""
    texts = {p: ae.build_relationship_matrix(120, p) for p in PERSONAS}
    assert len({_h(t) for t in texts.values()}) == 5, \
        '五种性格文本有重复：%r' % ({p: _h(t)[:8] for p, t in texts.items()},)


def test_five_stages_differ_at_same_persona():
    """同一性格下五个阶段必须不同"""
    texts = [ae.build_relationship_matrix(a, '傲娇') for a in (40, 95, 120, 155, 200)]
    assert len({_h(t) for t in texts}) == 5, '五个阶段文本有重复'


def test_chemistry_grids_add_extra_block():
    """化学反应格要多出一段（相加之外的新东西）"""
    t = ae.build_relationship_matrix(200, '高冷')
    assert '这个组合的特有表现' in t, '灵魂伴侣×高冷 缺少特例段'
    assert '嘴上最淡' in t, '特例内容缺失'
    # 反例：没有特例的组合不该有这段
    t2 = ae.build_relationship_matrix(95, '温柔')
    assert '这个组合的特有表现' not in t2


def test_persona_layer_has_taboo():
    """每种性格都必须带一条禁忌（防止以后被删成空壳）"""
    for p, lay in ae.PERSONA_LAYERS.items():
        assert len(lay) == 4, '%s 的性格层结构不对（应 4 段）' % p
        assert '⛔' in lay[3], '%s 缺少禁忌条款' % p


def test_affection_200_hits_last_stage_range():
    """200 必须命中区间（改前 170 <= 200 < 200 为假，靠 fallthrough 兜）"""
    lo, hi = ae.STAGES[-1][0], ae.STAGES[-1][1]
    assert lo <= 200 < hi, '200 没落在末段区间 %r' % ((lo, hi),)
    assert ae.stage_from_affection(200)[0] == '灵魂伴侣'


def test_affection_floor_to_zero_has_stage():
    """好感度掉到 0 也要有阶段（为下一轮减分留空间）"""
    assert ae.stage_from_affection(0)[0] == '初见', '0 没有对应阶段'
    assert ae.stage_from_affection(30)[0] == '初见'


def test_stage_floor_constant_is_defined():
    """减分地板常量已立好（下一轮实现减分时直接用）"""
    assert ae.STAGE_FLOOR == '熟悉'
    names = [s[2] for s in ae.STAGES]
    assert ae.STAGE_FLOOR in names, '地板阶段名不在 STAGES 里'


def test_unknown_persona_falls_back_without_crash():
    """未知/空性格不许崩，退回「只有阶段」并明确说未设置"""
    for p in ('', None, '不存在的性格'):
        t = ae.build_relationship_matrix(200, p)
        assert t, '返回空文本'
        assert '未设置' in t, '非法性格没给「未设置」提示：%r' % (t[:40],)


def test_matrix_includes_stage_and_persona_headings():
    """矩阵文本必须同时包含阶段与性格两个标题（结构契约）"""
    t = ae.build_relationship_matrix(120, '吐槽')
    assert '【当前关系】' in t
    assert '亲密' in t
    assert '【你的性格底色：吐槽】' in t


def test_engine_matrix_prompt_uses_personality(tmp_path):
    """AffectionEngine.matrix_prompt 必须把 personality 真的用上"""
    eng = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    a = eng.matrix_prompt('flash', '温柔')
    b = eng.matrix_prompt('flash', '高冷')
    assert a != b, 'engine 层没把 personality 传下去（两种性格文本相同）'
