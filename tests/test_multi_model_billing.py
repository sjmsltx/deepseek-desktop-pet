# -*- coding: utf-8 -*-
"""多模型计费护栏（v6.62）：接第三方模型时的极端情况

要防的三件事：
① 第三方/中转档案被 DeepSeek 的峰谷规则**误加倍**
② 未配置价格的模型拿 DeepSeek 价目**编出一个像真的数字**
③ 官方调价后本地价格静默过期（现在有「核对官方价格」，且**只提示不自动改价**）

运行：python -m pytest tests/test_multi_model_billing.py -q
"""
import datetime
import json
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import price_check as pc                       # noqa: E402
import model_registry as mr                    # noqa: E402
from api_stats import ApiStats                 # noqa: E402

ApiStats.HOLIDAYS_CACHE = os.path.join(BASE, 'holidays_cache.json')
PEAK = datetime.datetime(2026, 9, 18, 10, 0)     # 周五 10:00 = 高峰
OFF = datetime.datetime(2026, 9, 18, 20, 0)      # 周五 20:00 = 空闲


def _reg(tmp_path, third_party=True):
    """建一个临时档案集：官方 flash + （可选）第三方模型"""
    reg = mr.ModelRegistry(str(tmp_path / 'models.json'))
    if third_party:
        reg.add_profile('third', '别家模型', 'glm-4-plus', copy_from='flash')
        p = reg.get('third')
        p.endpoint = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
        p.price = {'input': 10.0, 'cache': 2.0, 'output': 30.0}     # 固定价，没有 *_peak
        p.pricing_mode = 'auto'
        reg.save()
    return reg


# ---------------------------------------------------------------- ① 峰谷不误伤第三方

def test_official_endpoint_detection():
    assert mr.is_official_endpoint('https://api.deepseek.com/chat/completions') is True
    assert mr.is_official_endpoint('https://api.deepseek.com/beta/chat/completions') is True
    assert mr.is_official_endpoint('https://gw.example.com/deepseek/v1') is False
    assert mr.is_official_endpoint('http://127.0.0.1:8000/v1') is False
    assert mr.is_official_endpoint('') is False


def test_third_party_profile_not_doubled_at_peak(tmp_path):
    """第三方档案在官方高峰时段也必须按自己的固定价算，不能×2"""
    reg = _reg(tmp_path)
    st = ApiStats(str(tmp_path / 's.json'), registry=reg)
    p_off = st._price_for('glm-4-plus', OFF)[0]
    p_peak = st._price_for('glm-4-plus', PEAK)[0]
    assert p_off['output'] == 30.0 and p_peak['output'] == 30.0, '第三方价不应随官方峰谷变动'
    off = st._cost('glm-4-plus', 10000, 1000, 0, 10000, now=OFF)[0]
    peak = st._cost('glm-4-plus', 10000, 1000, 0, 10000, now=PEAK)[0]
    assert abs(off - peak) < 1e-12, '第三方模型高峰与空闲费用应相同'
    # 对照：官方档案仍按峰谷翻倍
    o_off = st._cost('deepseek-flash', 10000, 1000, 0, 10000, now=OFF)[0]
    o_peak = st._cost('deepseek-flash', 10000, 1000, 0, 10000, now=PEAK)[0]
    assert abs(o_peak - o_off * 2) < 1e-9


def test_pricing_mode_override(tmp_path):
    """手动把官方档案设成固定价 → 不再翻倍；把第三方设成官方峰谷 → 会翻倍"""
    reg = _reg(tmp_path)
    reg.set_param('flash', 'pricing_mode', 'flat')
    assert reg.uses_peak_pricing('deepseek-flash') is False
    reg.set_param('third', 'pricing_mode', 'deepseek_peak')
    reg.get('third').endpoint = 'https://open.bigmodel.cn/x'
    assert reg.uses_peak_pricing('glm-4-plus') is True
    assert reg.set_param('flash', 'pricing_mode', '乱写') is False, '非法值要拒绝'


def test_pricing_mode_roundtrip(tmp_path):
    reg = _reg(tmp_path)
    assert reg.save()
    reg2 = mr.ModelRegistry(str(tmp_path / 'models.json'))
    assert reg2.get('third').pricing_mode == 'auto'
    assert reg2.get('third').to_dict()['params']['pricing_mode'] == 'auto'


# ---------------------------------------------------------------- ② 未知价不编数字

def test_unknown_price_costs_zero_and_is_flagged(tmp_path):
    """没配价格的模型：费用记 0 + 标记 + 计数，不再拿 DeepSeek 价目估算"""
    reg = _reg(tmp_path, third_party=False)
    reg.add_profile('mystery', '未知价模型', 'some-model-xyz', copy_from='flash')
    p = reg.get('mystery')
    p.endpoint = 'https://other.example.com/v1/chat/completions'
    p.price = {}
    st = ApiStats(str(tmp_path / 's.json'), registry=reg)
    cost, unknown = st._cost('some-model-xyz', 10000, 1000, 0, 10000, now=OFF)
    assert cost == 0.0 and unknown is True, '未知价必须记 0 并标记（不给假数字）'
    st.record({'prompt_tokens': 10000, 'completion_tokens': 1000}, model='some-model-xyz')
    assert st.today.get('unknown') == 1, '统计里要单列未计费次数'
    assert st.today['cost'] == 0.0
    assert st.calls[-1].get('price_unknown') is True


def test_known_price_still_works_multimodel(tmp_path):
    """同一份统计里官方与第三方模型各按自己的价目算"""
    reg = _reg(tmp_path)
    st = ApiStats(str(tmp_path / 's.json'), registry=reg)
    st.record({'prompt_tokens': 1000, 'completion_tokens': 500}, model='deepseek-flash')
    c1 = st.calls[-1]['cost']
    st.record({'prompt_tokens': 1000, 'completion_tokens': 500}, model='glm-4-plus')
    c2 = st.calls[-1]['cost']
    assert c1 > 0 and c2 > 0 and c1 != c2
    assert st.today.get('unknown', 0) == 0
    assert st.by_model.get('deepseek-flash', {}).get('count') == 1
    assert st.by_model.get('glm-4-plus', {}).get('count') == 1


# ---------------------------------------------------------------- ③ 官方价核对

def test_parse_pricing_html(monkeypatch):
    html = ('<table><tr><td>模型</td><td>deepseek-flash(1)</td><td>deepseek-v4-pro</td></tr>'
            '<tr><td>价格(2)</td><td>百万tokens输入（缓存命中）</td><td>空闲时段</td>'
            '<td>0.02元</td><td>0.15元</td></tr>'
            '<tr><td>高峰时段</td><td>0.04元</td><td>0.30元</td></tr>'
            '<tr><td>百万tokens输入（缓存未命中）</td><td>空闲时段</td><td>1元</td><td>4.5元</td></tr>'
            '<tr><td>高峰时段</td><td>2元</td><td>9.0元</td></tr>'
            '<tr><td>百万tokens输出</td><td>空闲时段</td><td>4元</td><td>13.5元</td></tr>'
            '<tr><td>高峰时段</td><td>8元</td><td>27.0元</td></tr></table>')
    prices, err = pc.parse_pricing_html(html)
    assert err is None
    assert prices['deepseek-flash'] == {'cache': 0.02, 'cache_peak': 0.04, 'input': 1.0,
                                        'input_peak': 2.0, 'output': 4.0, 'output_peak': 8.0}
    assert prices['deepseek-v4-pro']['output_peak'] == 27.0


def test_parse_pricing_html_bad_input():
    prices, err = pc.parse_pricing_html('<table><tr><td>没有价格</td></tr></table>')
    assert prices == {} and err
    prices2, err2 = pc.parse_pricing_html('')
    assert prices2 == {} and err2


def test_compare_only_official_profiles(tmp_path):
    """第三方档案不该被官方价目比对（价目体系不同）"""
    reg = _reg(tmp_path)
    official = {'deepseek-flash': {'input': 1.0, 'output': 4.0},
                'deepseek-v4-pro': {'input': 4.5, 'output': 13.5}}
    diffs = pc.compare_with_profiles(official, reg.profiles())
    assert diffs == [], '本地官方价与给定官方价一致时不该报差异'
    official['deepseek-flash']['output'] = 9.9
    diffs2 = pc.compare_with_profiles(official, reg.profiles())
    assert len(diffs2) == 1 and diffs2[0]['field'] == 'output' and diffs2[0]['official'] == 9.9
    assert all(d['key'] != 'third' for d in diffs2), '第三方档案不参与比对'


def test_apply_prices_only_touches_official(tmp_path):
    reg = _reg(tmp_path)
    before = dict(reg.get('third').price)
    done, errs = pc.apply_prices(reg, {'deepseek-flash': {'input': 7.0, 'cache': 0.5, 'output': 8.0}})
    assert 'flash' in done and 'third' not in done and not errs
    assert reg.get('flash').price['input'] == 7.0
    assert reg.get('third').price == before, '第三方档案价格不得被动'


def test_local_prices_match_official_builtin():
    """出厂档案价与官方定价页（2026-09-19 核对值）一致"""
    by_key = {d['key']: d for d in mr.BUILTIN_PROFILES}
    assert by_key['flash']['price'] == {'input': 1.0, 'cache': 0.02, 'output': 4.0,
                                        'input_peak': 2.0, 'cache_peak': 0.04, 'output_peak': 8.0}
    assert by_key['pro']['price'] == {'input': 4.5, 'cache': 0.15, 'output': 13.5,
                                      'input_peak': 9.0, 'cache_peak': 0.30, 'output_peak': 27.0}
    for k in ('flash', 'pro'):
        assert by_key[k]['params']['pricing_mode'] == 'auto'


def test_source_guard_no_silent_price_estimate():
    """护栏：未知价不得再用 DEFAULT_PRICE 编数字"""
    src = open(os.path.join(BASE, 'api_stats.py'), encoding='utf-8').read()
    seg = src.split('def _cost(')[1][:600]
    assert 'return 0.0, True' in seg, '价格未知时必须记 0 并标记'
    assert 'DEFAULT_PRICE' not in seg, '不得再用兜底价估算未知模型费用'


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))
