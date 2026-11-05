# -*- coding: utf-8 -*-
"""衰减模型：幂律（Owner 2026-11-02 拍板改）

## 为什么有这个文件

评审-171 §二 修正二：ACT-R 的 `B_i = ln(Σ t_j^(-d))`（d 默认 0.5），
理论依据 Schooler & Anderson 1997 —— 环境里一个事实被需要的几率本身按幂函数衰减。

旧实现（指数 `0.5^(a/30)`）在 3 年处权重 1.6e-10，系统等于认为「它从未发生」；
幂律在 3 年处仍有 0.095 —— 与「模糊的壳一直留着、只是细节掉了」这种真实记忆形状一致。

## 这组测试锁的是什么

1. **半衰期语义没变**：f(30)==0.5（两种模型同点），所以配置与既有断言都不用改
2. **尾部必须厚**：f(1000) 明显大于 0（这是改幂律的**唯一目的**）
3. **单调不增**、端点精确
4. **pinned / 身份条目不衰减**（不能因为换模型而破）
5. **星图与事件层同源**（防「写两份必然只修一份」）
"""
import ast
import io
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import memory_events as me  # noqa: E402

#: 幂律在各年龄的因子（d=0.5, T=10）。数值是算出来的，不是抄的：
#:   f(a) = (1 + a/10)^(-0.5)
EXPECT_POWER = {
    0.0: 1.0,
    10.0: (1 + 1.0) ** -0.5,        # 0.7071
    30.0: 0.5,                       # 半衰期：与指数模型同点（这是关键约束）
    90.0: (1 + 9.0) ** -0.5,         # 0.3162
    365.0: (1 + 36.5) ** -0.5,       # 0.1633
    1095.0: (1 + 109.5) ** -0.5,     # 0.0951
}


@pytest.fixture(autouse=True)
def _restore_model():
    """每条用例前后都恢复默认模型 —— 别让一条用例改全局状态影响下一条。"""
    orig = me.DECAY_MODEL
    me.DECAY_MODEL = 'power'
    yield
    me.DECAY_MODEL = orig


def test_default_model_is_power():
    """默认必须是幂律（Owner 2026-11-02 拍板）。"""
    assert me.DECAY_MODEL == 'power', '默认衰减模型不是幂律'
    assert me.POWER_D == 0.5, 'ACT-R 的 d 默认 0.5，被改了要先说明依据'


def test_half_life_point_unchanged():
    """⭐ 半衰期这一点必须仍是 0.5 —— 换模型不许改 HALF_LIFE_DAYS 的语义。

    这条是整个改造的「兼容锚」：既有测试断言 `decayed_weight(1.0, 30.0) < 0.55`，
    配置里的 30 天半衰期也靠它，换了模型若这里变了，等于偷偷改了配置含义。
    """
    assert abs(me.decay_factor(me.HALF_LIFE_DAYS) - 0.5) < 1e-9
    assert abs(me.decayed_weight(1.0, me.HALF_LIFE_DAYS) - 0.5) < 1e-9


@pytest.mark.parametrize('age', sorted(EXPECT_POWER))
def test_power_values(age):
    """幂律在这些年龄点的值与公式一致（逐点核，不只核端点）。"""
    want = EXPECT_POWER[age]
    got = me.decay_factor(age)
    assert abs(got - want) < 1e-9, '年龄 %s 天：期望 %.6f，实得 %.6f' % (age, want, got)


def test_tail_is_thick_the_whole_point_of_power_law():
    """⭐ 改幂律的唯一目的：长尾不许归零。

    判据能证伪：把 DECAY_MODEL 切回 'exponential'，这条立刻红。
    """
    v = me.decay_factor(1000)
    assert v > 0.05, '1000 天权重只剩 %.6f —— 幂律的长尾没实现' % v
    # 对照：指数模型下同一时刻已经等于 0
    me.DECAY_MODEL = 'exponential'
    v_exp = me.decay_factor(1000)
    assert v_exp < 1e-6, '指数模型 1000 天居然是 %.6f，对照失效' % v_exp
    me.DECAY_MODEL = 'power'


def test_power_always_above_exponential_after_half_life():
    """过了半衰期之后，幂律必须**恒高于**指数（这是模型差异的方向，不是巧合）。"""
    for age in (31, 45, 60, 90, 180, 365, 730, 1825, 3650):
        me.DECAY_MODEL = 'power'
        p = me.decay_factor(age)
        me.DECAY_MODEL = 'exponential'
        e = me.decay_factor(age)
        assert p > e, '年龄 %d 天：幂律 %.6f 不高于指数 %.6f' % (age, p, e)


def test_monotonic_non_increasing():
    """全局单调不增（1000 个采样点逐个比，不抽样）。"""
    prev = me.decay_factor(0)
    for i in range(1, 1000):
        v = me.decay_factor(i * 3.65)
        assert v <= prev + 1e-15, '在 %.1f 天处上翘' % (i * 3.65)
        prev = v


def test_endpoints_exact():
    """端点：0 天必须恰好 1，不需要衰减的条目不能被偷偷削一点。"""
    assert me.decay_factor(0) == 1.0
    assert me.decay_factor(0.0) == 1.0


def test_negative_and_bad_age_is_safe():
    """负年龄 / 非数字不许抛，也不许返回 >1（未来时间戳不该让权重放大）。"""
    assert me.decay_factor(-5) == 1.0
    assert me.decay_factor('abc') == 0.0
    assert me.decay_factor(None) == 0.0


def test_pinned_still_immune():
    """钉住条目跨模型都不衰减（换模型不许破这条）。"""
    for model in ('power', 'exponential'):
        me.DECAY_MODEL = model
        assert me.decayed_weight(0.8, 1000, pinned=True) == 0.8


def test_identity_still_immune():
    """身份类（名字/称呼）跨模型都不衰减。"""
    ident = {'title': '我的名字叫小蓝', 'time': '2026-08-02 13:21', 'weight': 0.55}
    for model in ('power', 'exponential'):
        me.DECAY_MODEL = model
        assert abs(me.effective_weight(ident) - 0.55) < 1e-9


def test_weight_cap_still_applies():
    """base 超过 WEIGHT_MAX 仍要夹住（幂律不许放大权重）。"""
    assert me.decayed_weight(5.0, 0) == me.WEIGHT_MAX


def test_starmap_shares_the_same_function():
    """⭐ 结构钉：星图亮度必须用**同一个**衰减函数，不许再写第二份公式。

    2026-11-02 实测：改之前 memory_starmap.py 自带 `HALF_LIFE_DAYS = 30.0`
    和一行 `0.5 ** (age/30)` —— 那是全仓第二份衰减实现。
    本仓已经因为「写两份」踩过三次（is_sensitive_path / screenAt / USER_CONFIG_PATH）。
    """
    import memory_starmap as sm
    assert sm._decay_factor is me.decay_factor, '星图用的是另一份衰减函数'
    assert sm.HALF_LIFE_DAYS == me.HALF_LIFE_DAYS, '半衰期两处不一致'

    src = io.open(os.path.join(BASE, 'memory_starmap.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    # 不许再出现「0.5 ** (…/…)」这种字面指数衰减写法
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Pow):
            seg = ast.get_source_segment(src, n) or ''
            if '0.5' in seg and '**' in seg:
                bad.append((n.lineno, seg[:60]))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'pow':
            seg = ast.get_source_segment(src, n) or ''
            if '0.5' in seg:
                bad.append((n.lineno, seg[:60]))
    assert not bad, '星图里又出现字面指数衰减：%r' % bad


def test_brightness_uses_decay_factor():
    """星图亮度实际取值：老星星要保留保底亮度（0.42），不能因幂律变暗到看不见。"""
    import memory_starmap as sm
    # 不构造 QWidget，直接核公式常量：0.42 + 0.58 * f(age)
    src = io.open(os.path.join(BASE, 'memory_starmap.py'), encoding='utf-8').read()
    assert '0.42 + 0.58 * _decay_factor(' in src, '亮度的保底 0.42 被改掉了'
