# -*- coding: utf-8 -*-
"""记忆质量回归集的门禁版（2026-11-02 建，同日闸门调参后更新）

## 定位：**锁现状，不是要求完美**

起因（评审-168 §五 建议2 / 评审-170 §三）：本项目全仓 0 条记忆质量回归用例，
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
    # 2026-11-06 上调：接入向量检索（自适应阈值）后，同一套用例、同一个库
    #   R@1 2/6→6/6、R@3 2/6→6/6、H_R@1 2/12→10/12、H_R@3 3/12→10/12、纯检索 1/5→6/7
    #   ⚠ 2026-11-07 更正（评审-183 §三/§5.2）：这行原来写 9/12 与 3/5，与下面常量（10/12、6/7）
    #     以及 L188 的「到 10/12」互相矛盾。常量为准，注释是旧的。
    #   ⚠ 纯检索分母 5→7 的原因**未查明**（已排除 11-06 迁到 events 的那 3 条：
    #     它们是 GIS 分析/matplotlib/Python 关卡，不在任何 holdout 用例的答案里）。
    #     实测口径：n=7 hit=6，ids = h02 h04 h05 h06 h09 h10 h11。
    'R@1': 6 / 6,        # 开发集 6 条全部进第 1
    'R@3': 6 / 6,        # 开发集 6 条全部进前 3
    'H_R@1': 10 / 12,    # 留出集 12 条中 10 条进第 1
    'H_R@3': 10 / 12,    # 留出集 12 条中 10 条进前 3
    # 纯检索口径（排除 L0 常驻块已含的用例）。实测 6/7。
    # 为什么单列：H_R@3 里有一部分是 L0 撑的，纯检索才反映"检索本身"。
    'H_R@3_pure': 6 / 7,
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
    for k in ('recall', 'holdout', 'entity', 'false', 'noise', 'superseded'):
        assert d.get(k), '用例里 %s 类是空的' % k


def test_eval_runs_on_real_library(result):
    """评估必须跑在真实库上（不是空表上的空洞通过）。"""
    assert result['counts']['facts_active'] >= 15, (
        'active facts 只有 %d 条，评估等于没测' % result['counts']['facts_active'])


@pytest.mark.parametrize('metric', ['R@1', 'R@3', 'H_R@1', 'H_R@3', 'H_R@3_pure',
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
    """缺口 A（开发集 4 条词汇空白）**已于 2026-11-06 关闭** —— 保留名字做锚点。

    关闭依据：接入向量检索后开发集 6/6 全中（原缺口 r01~r04 全部命中）。
    按本文件原有约定，「缺口修好就上调基线并删掉缺口断言」——
    断言已删，基线已在 BASELINE 里上调到 6/6。

    ⛔ 不要把旧断言加回来：那会要求 R@3 掉回 33% 才算通过。
    真正防退化的是上面的 test_not_below_baseline。
    """
    assert result['counts']['R@3'] >= 1.0 - 1e-9, (
        '开发集 R@3 掉到 %.0f%%（基线 100%%），说明向量检索没生效或被回退' %
        (result['counts']['R@3'] * 100))
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


# ══════════ 用例数钉（评审-173 §七 第 4 条）══════════

# ══════════ 两处旧缺口已关闭（2026-11-06）══════════
#
# 历史：
#   · 缺口 B（留出集 25% 天花板）—— 向量 + 自适应阈值 + 并集后到 10/12，已删掉
#     对应的「缺口仍在」断言（它会在修好时故意变红提醒删）
#   · 实体混淆 e01/e02（问「我名字」返回「姐姐的名字」）—— 已修好，e03 也命中，
#     同样删掉断言
#
# ⛔ 删除不等于不用管：防退化现在完全靠 BASELINE 与 test_not_below_baseline。
#    上调基线是这次改动的一部分（见 BASELINE 注释里的对照数字）。


def test_case_count_is_pinned():
    """⭐ 用例数只许增不许减 —— 否则删掉难例就能让 R@3 虚高。

    为什么需要（评审-173 §七 第 4 条原话）：

        R@3 = 命中/用例数 ⇒ 删难例比修 bug 更容易制造 100%
        现在 2/6=33%；把 r02 r04 删掉 → 2/4=50%；只留 r05 → 1/1=100% → 触发「修好了」

    这与 `test_holdout_never_used_for_tuning` **防的不是同一件事**：
      · 那条防「调参时偷看留出集」
      · 这条防「删用例让分母变小」
    删用例不违反那条（删完 holdout 变短，memory_engine.py 里照样没 'holdout' 字样）。
    """
    import json as _json
    d = _json.load(io.open(os.path.join(BASE, 'tools', 'eval', 'cases.json'),
                           encoding='utf-8'))
    assert len(d['recall']) >= 6, '开发集只剩 %d 条（基线 6）—— 删用例会让 R@3 虚高' % len(d['recall'])
    assert len(d.get('holdout', [])) >= 12, '留出集只剩 %d 条（基线 12）' % len(d.get('holdout', []))
    assert len(d.get('entity', [])) >= 4, '实体区分类只剩 %d 条（基线 4）' % len(d.get('entity', []))
    assert len(d.get('false', [])) >= 4, '无关问句只剩 %d 条（基线 4）' % len(d.get('false', []))


def test_holdout_size_matches_declared_baseline():
    """留出集条数与基线分母一致 —— 防「改了用例数但忘改基线」。

    ⚠ 第一版这里写了 `assert denom == n_hold or True` —— 一个恒真的废断言。
      自己复查时发现：`or True` 让整行永远通过，等于没写。
    """
    import json as _json
    d = _json.load(io.open(os.path.join(BASE, 'tools', 'eval', 'cases.json'),
                           encoding='utf-8'))
    n_hold = len(d.get('holdout', []))
    assert n_hold == 12, (
        '留出集变成 %d 条了（基线 12）。若是有意扩，请同时：'
        '①上调 BASELINE 的 H_R@1/H_R@3 ②更新本文件头部表格 ③重算 H_R@3_pure 基线' % n_hold)
    assert len(d['recall']) == 6, '开发集变成 %d 条了（基线 6）' % len(d['recall'])


# ══════════ 实体混淆（评审-173 §五 第 1 条）══════════

def test_pure_recall_is_a_subset(result):
    """⭐ 纯检索口径的命中集必须是全路径口径命中集的**子集**。

    ⚠ 第一版我写的是 `pure <= full` 比比率 —— 无效：
      两者分母不同（5 条 vs 12 条），0.20 <= 0.25 只是巧合，
      换个数据集就可能 2/5=40% > 3/12=25% 而其实没毛病。
      正确判据是**集合包含关系**而不是数值大小。

    实测（0.30）：全路径命中 h01 h02 h12；纯检索命中 h02
    ⇒ {h02} ⊆ {h01, h02, h12} ✓
    """
    hit_full = {x['id'] for x in result['holdout'] if x['r3']}
    cp = result.get('counts_pure') or {}
    assert cp, 'counts_pure 缺失'
    assert cp['n'] < 12, (
        '纯检索用例数 %d = 全部 12 条，L0 过滤没生效（_has_any 传参错了？）' % cp['n'])
    # 纯检索命中的用例 = 全路径命中 ∩ 纯检索用例集
    pure_ids = set(cp['ids'])
    hit_pure = hit_full & pure_ids
    assert cp['hit'] == len(hit_pure), (
        '纯检索命中数 %d 与「全路径命中 ∩ 纯检索用例」%d 不一致：%r vs %r'
        % (cp['hit'], len(hit_pure), cp['hit'], len(hit_pure)))
    # 且纯检索用例集必须是留出集子集
    assert pure_ids <= {x['id'] for x in result['holdout']}, '纯检索用例不在留出集里' 

