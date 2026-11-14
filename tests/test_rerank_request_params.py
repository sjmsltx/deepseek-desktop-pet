# -*- coding: utf-8 -*-
"""rerank 请求参数的回归锁（2026-11-14）

## 为什么这组锁必须存在

`_rerank_memories` 原先有三个缺陷，全都不报错、只静默变差：

  ① 没关思考 ⇒ 推理 token 与正文共享 max_tokens ⇒ 实测 27/29 截断、正文 0 字
  ② 上限 60 ⇒ 配合①等于必然截断
  ③ 没传 temperature ⇒ 同一候选集两次跑出 13 / 16 条不同结果

其中①最阴：请求体里**看不出毛病**（不传 thinking 就是默认开启），
只有打开 `finish_reason` 才看得见。所以锁要钉住「显式发了什么」，而不是
「代码里写了什么」。

## 六条锁

1 显式关思考（不是靠默认值）
2 上限 ≥ 200
3 温度显式固定 0（**缺席也算红** —— 缺席正是原来的 bug）
4 结构化输出没被改坏
5 弃权语义未回归（`{"ids":[]}` → 空列表）
6 与 `_thinking_fields()` 的字段形状保持一致（防两处漂移）
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(scope='module')
def dp():
    try:
        import desktop_pet
    except Exception as exc:                     # pragma: no cover
        pytest.skip('desktop_pet 不可导入：%s' % exc)
    return desktop_pet


def _stub(dp, model='deepseek-flash'):
    p = dp.PetWidget.__new__(dp.PetWidget)
    p.current = 'flash'
    p._current_model = lambda: model
    p._current_api_key = lambda: 'test-key'
    p._record_api_usage = lambda r, fb='': None
    p._parse_rerank_ids = dp.PetWidget._parse_rerank_ids
    return p


CANDS = [{'id': 'a', 'text': '我的名字叫小蓝'}, {'id': 'b', 'text': '用户爱吃桃片'},
         {'id': 'c', 'text': '用户在做遥感作业'}]


def _capture(dp, monkeypatch, content='{"ids": [1]}', usage=None):
    """抓发出的请求体，并返回一个假响应（不真的打网络）"""
    box = {}

    def fake(key, data):
        box['body'] = json.loads(data.decode())
        return {'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}],
                'usage': usage or {'completion_tokens': 10},
                'model': box['body'].get('model')}

    monkeypatch.setattr(dp, 'chat_completions', fake)
    return box


def test_thinking_is_explicitly_disabled(dp, monkeypatch):
    """必须**显式**发 thinking.disabled —— 不传等于默认开启思考。

    这就是原缺陷的形状：请求体看着干干净净，实际推理把 60 token 吃光。
    """
    box = _capture(dp, monkeypatch)
    dp.PetWidget._rerank_memories(_stub(dp), '桌宠叫什么', CANDS)
    body = box['body']
    assert 'thinking' in body, '请求体没带 thinking —— 不传即走 API 默认「思考开启」'
    assert body['thinking'] == {'type': 'disabled'}, \
        'thinking 必须是 disabled，实际 %r' % (body['thinking'],)
    assert 'reasoning_effort' not in body, \
        '关思考时不该再发 reasoning_effort（与 disabled 自相矛盾）'


def test_max_tokens_has_headroom(dp, monkeypatch):
    box = _capture(dp, monkeypatch)
    dp.PetWidget._rerank_memories(_stub(dp), '桌宠叫什么', CANDS)
    mt = box['body'].get('max_tokens')
    assert mt is not None, 'med 请求体没有 max_tokens'
    assert mt >= 200, 'max_tokens=%r 太小（关思考后正文虽只有 10~15 字，但要留余量）' % (mt,)


def test_temperature_is_explicitly_zero(dp, monkeypatch):
    """温度**缺席也算红**。

    原来正是「没传」⇒ 走 API 默认偏高 ⇒ 同一候选集两次跑出 13 与 16 条，
    任何改动都无法验证。与 EXTRACT_TEMPERATURE 同一理由。
    """
    box = _capture(dp, monkeypatch)
    dp.PetWidget._rerank_memories(_stub(dp), '桌宠叫什么', CANDS)
    body = box['body']
    assert 'temperature' in body, '请求体没带 temperature —— 缺席就是原来那个 bug'
    assert body['temperature'] == 0.0, 'temperature 必须固定 0.0，实际 %r' % (body['temperature'],)


def test_response_format_still_json_object(dp, monkeypatch):
    """结构化输出别被顺手改坏（v6.62 的成果）。"""
    box = _capture(dp, monkeypatch)
    dp.PetWidget._rerank_memories(_stub(dp), '桌宠叫什么', CANDS)
    assert box['body'].get('response_format') == {'type': 'json_object'}


def test_abstain_semantics_not_regressed(dp, monkeypatch):
    """模型说 `{"ids":[]}` ⇒ 必须返回空（不许硬塞候选）。"""
    _capture(dp, monkeypatch, content='{"ids": []}')
    got = dp.PetWidget._rerank_memories(_stub(dp), '桌宠叫什么', CANDS)
    assert got == [], '弃权被兜底成 %r —— 又替模型做决定了' % (got,)


def test_single_candidate_skips_api(dp, monkeypatch):
    """候选 ≤1 条时不调模型（2026-11-12 的优化，别被这轮改动弄丢）。"""
    called = {'n': 0}

    def fake(key, data):
        called['n'] += 1
        return {'choices': [{'message': {'content': '{"ids":[1]}'}, 'finish_reason': 'stop'}]}

    monkeypatch.setattr(dp, 'chat_completions', fake)
    got = dp.PetWidget._rerank_memories(_stub(dp), 'q', [{'id': 'x', 'text': 'only'}])
    assert called['n'] == 0, '候选只有 1 条却仍调了 API'
    assert got == ['x']


def test_thinking_fields_shape_matches_product_helper(dp):
    """`RERANK_THINKING_FIELDS` 必须与 `_thinking_fields()` 关闭态的**形状一致**。

    两处都描述「关思考」这件事，若 `_thinking_fields` 将来改了字段名而这里没跟，
    请求体会被 API 静默忽略（不报错，退化成默认开思考）——
    那就是原缺陷重演，而且看不出来。这条锁让漂移立刻红。
    """
    p = dp.PetWidget.__new__(dp.PetWidget)
    p.reasoning_enabled = False
    p.reasoning_effort = 'high'
    off = dp.PetWidget._thinking_fields(p)
    assert off == dp.RERANK_THINKING_FIELDS, (
        '_thinking_fields() 关闭态 = %r，而 RERANK_THINKING_FIELDS = %r\n'
        '两处必须一致，否则 rerank 的「关思考」会悄悄失效' % (off, dp.RERANK_THINKING_FIELDS))


def test_docs_no_longer_claim_the_old_bug():
    """docstring 与 tooltip 不许再把「60 token / 49%」当现状描述。

    这是本项目最容易复发的一类缺陷：改了行为不改文档，
    下一个人照着文档去「修」一个已经不存在的问题。
    ⚠ 判据只扫**说明文字**里是否还把 60 当现行参数，不扫常量定义处。
    """
    src = io.open(os.path.join(ROOT, 'desktop_pet.py'), encoding='utf-8').read()
    i = src.find('def _rerank_memories')
    assert i > 0
    doc = src[i:i + 4000]
    assert '未修' not in doc.split('"""')[1], 'docstring 还写着「未修」'
    assert 'RERANK_THINKING_FIELDS' in doc, 'docstring 没指向新常量'

    su = io.open(os.path.join(ROOT, 'settings_ui.py'), encoding='utf-8').read()
    j = su.find('ck_rerank.setToolTip(')
    assert j > 0
    tip = su[j:j + 700]
    assert '60 token' not in tip, 'tooltip 还把 60 token 当现状'
    assert '49%' not in tip, 'tooltip 还把 49% 当现状'
