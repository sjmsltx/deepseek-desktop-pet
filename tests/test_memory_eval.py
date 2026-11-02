# -*- coding: utf-8 -*-
"""记忆质量回归集的门禁版（2026-11-02 建，同日闸门调参后更新）

## 定位：**锁现状，不是要求完美**

起因（WX-168 §五 建议2 / WX-170 §三）：本项目全仓 0 条记忆质量回归用例，
改 BM25 阈值、改闸门、改衰减全靠手感。记忆系统最坏的一种退化是**不报错、召回开始给错答案**。

所以这个文件断的是「**不低于已知基线**」，不是「全绿」。

## 两组用例，分开报（这是本轮最重要的实验设计）

| 组 | 条数 | 用途 |
|---|---|---|
| **开发集**（`recall`） | 6 | 调参时看的就是它 |
| **留出集**（`holdout`） | 12 | **调参时不参与**，选完才验收 |

为什么要分：2026-11-02 实测，只在开发集上选参会选出 devR3 100% 的参数，
而留出集只有 42% —— **过拟合 58 个点**。合并成一组就永远发现不了。

## 当前基线（闸门 GATE_MIN_COVERAGE 0.34→0.15 之后）

| 指标 | 基线 | 说明 |
|---|---|---|
| R@1（开发集） | 33% | 6 条中 2 条 |
| R@3（开发集） | 33% | 6 条中 2 条 |
| H_R@1（留出集） | 17% | 12 条中 2 条 |
| H_R@3（留出集） | 25% | 12 条中 3 条 |
| EVID | 100% | 召回的全是原文，没有编的 |
| FALSE | 100% | 无关的话没命中 |
| NOISE | 100% | 可重算播报没被召回 |
| SUPERSEDED | 100% | 失效事实没冒充现状 |

## ⚠️ 两处已知缺口（都写在测试里，看得见摸得着）

### 缺口 A：开发集 4 条未达标 —— 词汇空白 / 虚词稀释，不是闸门能救的

- r01「我叫什么名字？」→ 库里「我的名字叫小蓝」，共享 token 只有「名字」，coverage 0.2
- r02「我爱吃什么东西」→ 共享「爱吃」，coverage 0.167
- r03「我在学什么编程语言？」→ 查询里**没有 "Python" 这个词**，字面匹配无解
- r04「我平时玩什么游戏解压」→ 文档里**没有「游戏」这个词**（原文是「玩《战争雷霆》」）

⇒ 前两条是虚词稀释，后两条是词汇空白。四条都要靠同义词/语义层，调闸门只能顾此失彼
（把阈值降到 0.15 能救 r01/r02，但会破坏「概念提问不抬记忆」那条契约 —— 实测过）。

### 缺口 B：留出集只有 25% —— BM25 字面匹配的天花板

留出集 12 条里有 9 条返回空，典型：
- h03「我大几」 / h08「我读大几了来着」 vs 库里「用户是大二学生」→ 无共同 2-gram
- h04「我平时拿什么当零食」 vs 「爱吃重庆合川桃片」→ 无共同实词
- h05「我在练哪门编程」 vs 「在学习/练习 Python」→ 查询里没有 python

**这 25% 不是参数能救的。** 实测：把闸门全关（matched=0、cov=0），留出集也只有 42%。
⇒ 真正的瓶颈是「字面匹配打不过同义改写」，要加同义词表或语义检索，那是另一件事。

⛔ 所以别指望调 GATE_* 把 H_R@3 提到 80% —— 数据已经证明做不到。
"""
import io
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
# eval_memory.py 在 tools/ 下，不在包路径里 —— 显式加进去（它自己也会算 BASE）
_TOOLS = os.path.join(BASE, 'tools')
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

#: 2026-11-02 基线。**只许上调，不许为了变绿往下改。**
#: ⚠ 基线一律写**分数**（几条中几条），不写四舍五入后的小数。
#:   踩过：eval 侧 round(...,3) 把 4/6 打成 0.667，而基线写 0.67 ⇒ 0.667 >= 0.67-1e-9 为假，
#:   测试红了但其实是精度问题，不是退化。分数写法既精确又自解释。
BASELINE = {
    'R@1': 2 / 6,        # 开发集 6 条中 2 条进第 1（闸门 0.28）
    'R@3': 2 / 6,        # 开发集 6 条中 2 条进前 3
    'H_R@1': 2 / 12,     # 留出集 12 条中 2 条进第 1
    'H_R@3': 3 / 12,     # 留出集 12 条中 3 条进前 3
    'EVID': 1.0,
    'FALSE': 1.0,
    'NOISE': 1.0,
    'SUPERSEDED': 1.0,
}

#: 容差：eval 侧把比率 round 到 3 位小数，比较时留够余量。
TOL = 1e-3


@pytest.fixture(scope='module')
def result():
    import eval_memory
    return eval_memory.run()


def test_cases_file_is_real_data_based():
    """用例文件必须存在且四类都有 —— 防「文件被清空后测试全绿」。"""
    p = os.path.join(BASE, 'tools', 'eval', 'cases.json')
    assert os.path.exists(p), 'cases.json 不见了'
    d = json.load(io.open(p, encoding='utf-8'))
    for k in ('recall', 'holdout', 'false', 'noise', 'superseded'):
        assert d.get(k), '用例里 %s 类是空的' % k


def test_eval_runs_on_real_library(result):
    """评估必须跑在真实库上（不是空表上的空洞通过）。"""
    assert result['counts']['facts_active'] >= 15, (
        'active facts 只有 %d 条，评估等于没测' % result['counts']['facts_active'])


@pytest.mark.parametrize('metric', ['R@1', 'R@3', 'H_R@1', 'H_R@3',
                                    'EVID', 'FALSE', 'NOISE', 'SUPERSEDED'])
def test_not_below_baseline(result, metric):
    """每一类都不许低于基线。改检索/闸门/衰减后跑一遍就知道有没有把东西弄坏。"""
    got = result['counts'][metric]
    want = BASELINE[metric]
    assert got >= want - TOL, (
        '%s 掉到 %.0f%%，基线是 %.0f%% —— 本轮改动把召回弄坏了：\n%s'
        % (metric, got * 100, want * 100,
           '\n'.join('  %s %r → %r' % (x['id'], x['query'], x.get('top'))
                     for grp in ('recall', 'false', 'noise', 'superseded')
                     for x in result[grp]
                     if not x.get('r3', x.get('empty', x.get('clean', True))))))


def test_evidence_is_verbatim(result):
    """召回的必须是库里**逐字**的原文，不许是模型改写过的「像那么回事」。"""
    bad = [x for x in result['evidence'] if not x['verbatim']]
    assert not bad, '召回内容与库原文不一致：%r' % bad


def test_false_positive_is_zero(result):
    """无关的话必须一条都不命中（false positive 会把噪声每轮塞进 prompt）。"""
    bad = [x for x in result['false'] if not x['empty']]
    assert not bad, '无关问句命中了记忆：%r' % [(x['id'], x['top']) for x in bad]


def test_noise_never_recalled(result):
    """可重算的机械播报（余额/花费）不许被当成记忆召回 —— Owner 第一原则。"""
    bad = [x for x in result['noise'] if not x['clean']]
    assert not bad, '余额播报被召回：%r' % [(x['id'], x['top']) for x in bad]


def test_superseded_never_recalled(result):
    """已失效（superseded）的事实不许冒充现状 —— 比召回率更要紧。"""
    bad = [x for x in result['superseded'] if not x['clean']]
    assert not bad, '失效事实被当现状召回：%r' % [(x['id'], x['top']) for x in bad]


def test_gap_a_dev_vocabulary_holes(result):
    """缺口 A 的可执行记录：开发集里那 2 条是**词汇空白**，不是闸门问题。

    这条在缺口存在时通过、被修好时变红（提醒删掉本函数并上调 R@3 基线）。
    """
    miss = {x['id'] for x in result['recall'] if not x['r3']}
    if not miss:
        pytest.fail('开发集已经全中（R@3=100%）—— 请上调 BASELINE 的 R@1/R@3 并删掉本函数。')
    assert miss <= {'r01', 'r02', 'r03', 'r04'}, (
        '开发集未达标的不止 r01~r04，多出来的会掩盖真实退化：%r'
        % (miss - {'r01', 'r02', 'r03', 'r04'}))


def test_gap_b_holdout_ceiling_is_literal_matching(result):
    """缺口 B 的可执行记录：留出集召回低是 BM25 字面匹配的天花板，调参数救不了。

    实测依据（2026-11-02，见 memory_engine.GATE_MIN_COVERAGE 注释）：
    把闸门全关（matched=0、cov=0），留出集也只有 42%；
    当前 0.15 是「零纯噪声前提下」的最优点（25%）。

    这条在缺口存在时通过；若哪天 H_R@3 冲到高位，说明加了同义词/语义层 ——
    那时请上调基线并删掉本函数。
    """
    h = result['counts']['H_R@3']
    if h >= 0.80:
        pytest.fail('留出集召回已到 %.0f%%（多半是加了同义词/语义层）—— '
                    '请上调 BASELINE 的 H_R@1/H_R@3 并删掉本函数。' % (h * 100))
    assert h >= BASELINE['H_R@3'] - TOL, (
        '留出集掉到 %.0f%%，基线 %.0f%% —— 本轮改动把召回弄坏了'
        % (h * 100, BASELINE['H_R@3'] * 100))


def test_holdout_never_used_for_tuning():
    """⭐ 结构钉：留出集不许被调参代码读到。

    判据：`search_memory` / `memory_engine` 里不许出现 'holdout' 字样，
    也不许读 cases.json。防止哪天有人「顺手」在选参逻辑里读留出集 —— 那就等于没有验证集。
    """
    for fn in ('memory_engine.py',):
        p = os.path.join(BASE, fn)
        src = io.open(p, encoding='utf-8').read()
        assert 'holdout' not in src, '%s 里出现了 holdout，调参代码可能偷看留出集' % fn
        assert 'cases.json' not in src, '%s 里出现 cases.json，产品代码不许读用例' % fn
