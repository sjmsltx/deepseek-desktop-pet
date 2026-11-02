# -*- coding: utf-8 -*-
"""记忆质量回归集的门禁版（2026-11-02 建）

## 定位：**锁现状，不是要求完美**

起因（WX-168 §五 建议2 / WX-170 §三）：本项目全仓 0 条记忆质量回归用例，
改 BM25 阈值、改闸门、改衰减全靠手感。记忆系统最坏的一种退化是**不报错、召回开始给错答案**。

所以这个文件断的是「**不低于已知基线**」，不是「全绿」。

## 2026-11-02 首次跑出的基线（真实库 21 条 active facts）

| 指标 | 基线 | 说明 |
|---|---|---|
| R@1 | 33% | 6 条 recall 用例里 2 条命中第 1 |
| R@3 | 33% | 同上 |
| EVID | 100% | 召回的全是原文，没有编的 |
| FALSE | 100% | 无关的话没命中 |
| NOISE | 100% | 可重算播报没被召回 |
| SUPERSEDED | 100% | 失效事实没冒充现状 |

## ⚠️ R@3 只有 33% 是**已知缺口**，不是用例写错

实测诊断（2026-11-02 22:52）：

```
问「我爱吃什么东西」
  tokenize → ['我爱','爱吃','吃什','什么','么东','东西']      ← 6 个 token，5 个是虚词
  无闸门 top1 → 「用户爱吃重庆合川桃片……」score=3.1439 matched=1 coverage=0.167
  带闸门     → 0 条        （GATE_MIN_MATCHED=2 且 coverage 需 ≥0.34）
```

⇒ **闸门参数是按陈述句调的，用在自然问句上过严**：
中文 2-gram 把「什么/东西/我在/平时」这类虚词都算进分母，coverage 被稀释到 0.11~0.20，
而 matched 又只有 1（一句话只撞上一个实词）⇒ 4/6 条问句被整条拒掉。

真实影响：「用户爱吃桃片」「用户在学 Python」「累了会玩战争雷霆」这些偏好，
**用自然问法问不出来**（身份类不受影响，它走 L0 常驻注入，不经检索）。

⛔ 我没有擅自改 GATE_MIN_MATCHED —— 那条闸门本来是防「勉强相关的记忆每轮都注入」的，
   松开会把噪声放进 prompt，属产品取舍，得 Owner 拍。
   本文件只把它**固定成可执行的记录**：`test_known_gap_question_phrasing_is_still_open`
   会在缺口被修好时变红，提醒回来上调基线。
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
BASELINE = {
    'R@1': 0.33,
    'R@3': 0.33,
    'EVID': 1.0,
    'FALSE': 1.0,
    'NOISE': 1.0,
    'SUPERSEDED': 1.0,
}


@pytest.fixture(scope='module')
def result():
    import eval_memory
    return eval_memory.run()


def test_cases_file_is_real_data_based():
    """用例文件必须存在且四类都有 —— 防「文件被清空后测试全绿」。"""
    p = os.path.join(BASE, 'tools', 'eval', 'cases.json')
    assert os.path.exists(p), 'cases.json 不见了'
    d = json.load(io.open(p, encoding='utf-8'))
    for k in ('recall', 'false', 'noise', 'superseded'):
        assert d.get(k), '用例里 %s 类是空的' % k


def test_eval_runs_on_real_library(result):
    """评估必须跑在真实库上（不是空表上的空洞通过）。"""
    assert result['counts']['facts_active'] >= 15, (
        'active facts 只有 %d 条，评估等于没测' % result['counts']['facts_active'])


@pytest.mark.parametrize('metric', ['R@1', 'R@3', 'EVID', 'FALSE', 'NOISE', 'SUPERSEDED'])
def test_not_below_baseline(result, metric):
    """每一类都不许低于基线。改检索/闸门/衰减后跑一遍就知道有没有把东西弄坏。"""
    got = result['counts'][metric]
    want = BASELINE[metric]
    assert got >= want - 1e-9, (
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


def test_known_gap_question_phrasing_is_still_open(result):
    """⭐ 已知缺口的**可执行记录**：自然问句的命中率仍低于 100%。

    这条**故意**在缺口存在时通过、在缺口被修好后**变红**。
    变红不是坏了，是提醒：回来上调 BASELINE 里的 R@1/R@3，并更新本文件与
    cases.json 的说明（缺口已闭合，别再把它当已知问题讲）。

    缺口本体见本文件头部注释：闸门 GATE_MIN_MATCHED=2 / coverage≥0.34
    是按陈述句调的，中文 2-gram 把「什么/东西/我在」算进分母 ⇒ 自然问句被整条拒掉。
    """
    r3 = result['counts']['R@3']
    if r3 >= 1.0:
        pytest.fail(
            '自然问句的召回已经修好了（R@3=100%%）—— 这是好事，'
            '请上调 BASELINE 的 R@1/R@3、删掉本文件里「已知缺口」那段说明，'
            '并把这条测试改成普通的基线断言。')
    # 缺口仍在：确认它没恶化到 0（0 意味着连现在能命中的两条也没了）
    assert r3 >= BASELINE['R@3'] - 1e-9
