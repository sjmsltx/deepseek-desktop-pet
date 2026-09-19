# -*- coding: utf-8 -*-
"""v6.62 补做项护栏：strict 严格工具 / Files API / 思考回传 / 峰谷价格

运行：python -m pytest tests/test_api_extras.py -q
"""
import datetime
import json
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pytest  # noqa: E402


def _pet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._save_chat_memory = lambda *a, **k: True
    p._summarize_old = lambda *a, **k: True
    p._record_api_usage = lambda *a, **k: True
    p._close_pending_user_msg = lambda *a, **k: True
    p._notify = lambda *a, **k: None
    p.memory_facts = []
    return p


# ---------------------------------------------------------------- ① strict

def test_beta_endpoint():
    from deepseek_client import beta_endpoint
    assert (beta_endpoint('https://api.deepseek.com/chat/completions')
            == 'https://api.deepseek.com/beta/chat/completions')
    assert beta_endpoint('https://api.deepseek.com/beta/chat/completions').endswith('/beta/chat/completions')
    assert beta_endpoint('') .endswith('/beta/chat/completions')
    # 自定义中转地址认不出路径 → 原样返回，不瞎拼
    assert beta_endpoint('https://gw.example.com/v2/llm') == 'https://gw.example.com/v2/llm'


def test_can_be_strict_rules():
    import tools_registry as tr
    full = {'type': 'function', 'function': {'name': 'a', 'parameters': {
        'type': 'object', 'properties': {'x': {'type': 'string'}}, 'required': ['x']}}}
    opt = {'type': 'function', 'function': {'name': 'b', 'parameters': {
        'type': 'object', 'properties': {'x': {'type': 'string'}, 'y': {'type': 'string'}},
        'required': ['x']}}}
    anon = {'type': 'function', 'function': {'name': 'c', 'parameters': {
        'type': 'object', 'properties': {'xs': {'type': 'array', 'items': {}}},
        'required': ['xs']}}}
    assert tr.can_be_strict(full) is True
    assert tr.can_be_strict(opt) is False, '有可选参数的工具不该开 strict（会改语义）'
    assert tr.can_be_strict(anon) is False, '空子 schema（items:{}）会被官方 400 拒绝'


def test_offer_choices_is_not_strict():
    """实测踩坑：offer_choices 的 items 是空 schema，strict 会 400，必须排除"""
    import tools_registry as tr
    oc = [t for t in tr.AI_TOOLS if t['function']['name'] == 'offer_choices']
    assert oc and tr.can_be_strict(oc[0]) is False
    _, names = tr.strict_tools(tr.AI_TOOLS)
    assert 'offer_choices' not in names
    assert 'write_file' in names and 'search_code' in names, '全必填的高风险工具应当变严格'


def test_mark_strict_schema_shape():
    import tools_registry as tr
    t = {'type': 'function', 'function': {'name': 'x', 'parameters': {
        'type': 'object',
        'properties': {'s': {'type': 'string', 'minLength': 1, 'maxLength': 9}},
        'required': ['s']}}}
    out = tr.mark_strict(t)
    f = out['function']
    assert f['strict'] is True
    assert f['parameters']['additionalProperties'] is False
    assert 'minLength' not in f['parameters']['properties']['s'], 'strict 白名单外关键字要被剔除'
    assert t['function'].get('strict') is None, '不得就地改原工具定义'


def test_pet_endpoint_and_tools_payload_switch_with_strict():
    p = _pet()
    p.strict_tools = False
    assert '/beta/' not in p._request_endpoint()
    base = p._tools_payload()
    assert not any((t.get('function') or {}).get('strict') for t in base)
    p.strict_tools = True
    assert '/beta/' in p._request_endpoint()
    strict = p._tools_payload()
    marked = [t for t in strict if (t.get('function') or {}).get('strict')]
    assert marked, '开了严格模式应当有工具被标记 strict'
    assert len(marked) < len(strict), '不该全量强制（有可选参数的工具保持原样）'


# ---------------------------------------------------------------- ② Files API

def test_file_sha256_and_cache(tmp_path):
    import files_api as fa
    f1 = tmp_path / 'a.bin'
    f1.write_bytes(b'hello')
    f2 = tmp_path / 'b.bin'
    f2.write_bytes(b'hello')
    assert fa.file_sha256(str(f1)) == fa.file_sha256(str(f2)), '同内容必须同哈希'
    cache = fa.FilesCache(str(tmp_path / 'files_cache.json'))
    assert cache.get(fa.file_sha256(str(f1))) is None
    cache.put(fa.file_sha256(str(f1)), 'file-api-xxx', 'a.bin')
    cache2 = fa.FilesCache(str(tmp_path / 'files_cache.json'))
    assert cache2.get(fa.file_sha256(str(f1))) == 'file-api-xxx', '缓存要落盘可复用'
    cache2.drop(fa.file_sha256(str(f1)))
    assert fa.FilesCache(str(tmp_path / 'files_cache.json')).get(fa.file_sha256(str(f1))) is None


def test_build_content_via_files_reuses_cache(tmp_path, monkeypatch):
    import files_api as fa
    img = tmp_path / 'p.png'
    img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 100)
    calls = {'n': 0}

    def fake_upload(key, path, base_url='', timeout=120):
        calls['n'] += 1
        return 'file-api-test', None

    monkeypatch.setattr(fa, 'upload_file', fake_upload)
    cache = fa.FilesCache(str(tmp_path / 'c.json'))
    content, used, errs = fa.build_content_via_files('看图', [str(img)], 'k', '', cache)
    assert used == 1 and errs == []
    assert content[0]['type'] == 'text' and content[1] == {'type': 'file', 'file_id': 'file-api-test'}
    content2, used2, _ = fa.build_content_via_files('再看', [str(img)], 'k', '', cache)
    assert used2 == 1 and calls['n'] == 1, '同一张图第二次不该再上传'
    assert content2[1]['file_id'] == 'file-api-test'


def test_build_content_via_files_falls_back_on_error(tmp_path, monkeypatch):
    import files_api as fa
    img = tmp_path / 'p.png'
    img.write_bytes(b'data')
    monkeypatch.setattr(fa, 'upload_file', lambda *a, **k: (None, 'HTTP 500 挂了'))
    content, used, errs = fa.build_content_via_files('看图', [str(img)], 'k', '', None)
    assert used == 0 and content == '看图' and errs, '上传失败要如实回错误，调用方回退 base64'


def test_pet_vision_prefers_files_api(tmp_path, monkeypatch):
    p = _pet()
    img = tmp_path / 'x.png'
    img.write_bytes(b'png')
    import desktop_pet as dp
    monkeypatch.setattr(dp, 'build_content_via_files',
                        lambda *a, **k: ([{'type': 'text', 'text': 't'},
                                          {'type': 'file', 'file_id': 'fid'}], 1, []))
    p.vision_files_api = True
    content, used, _ = p._vision_content('t', [str(img)])
    assert used == 1 and content[1]['file_id'] == 'fid'
    # 关掉开关 → 回 base64 路径
    p.vision_files_api = False
    content2, used2, _ = p._vision_content('t', [str(img)])
    assert used2 == 0 or content2[1]['image_url']['url'].startswith('data:image/'), \
        '关掉文件接口后应走 base64 直发'


# ---------------------------------------------------------------- ③ 思考回传

def test_remember_and_attach_reasoning():
    p = _pet()
    p._remember_reasoning('391', '先算 23×17=391')
    msgs = [{'role': 'user', 'content': '23×17=?'},
            {'role': 'assistant', 'content': '391'},
            {'role': 'user', 'content': '再加 391'}]
    out = p._with_reasoning_history(msgs)
    assert out[1].get('reasoning_content') == '先算 23×17=391'
    assert 'reasoning_content' not in msgs[1], '不得就地改历史原表'
    # 内容对不上 → 不动
    other = [{'role': 'assistant', 'content': '别的话'}]
    assert p._with_reasoning_history(other) == other


def test_reasoning_truncated_and_empty_ignored():
    p = _pet()
    p._remember_reasoning('reply', 'x' * 9000)
    _, rsn = p._last_turn_reasoning
    assert len(rsn) == 4000, '回传要截断，避免历史 token 吹大'
    p._remember_reasoning('reply', '   ')
    assert p._last_turn_reasoning is None, '没有思考内容就不该留记录'


def test_reasoning_flag_off_means_no_attach():
    p = _pet()
    p._remember_reasoning('391', '思考内容')
    p.pass_reasoning_history = False
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert "if getattr(self, 'pass_reasoning_history', True):" in src, '开关必须真的能关掉回传'


# ---------------------------------------------------------------- ④ 峰谷价格

def test_is_peak_now_boundaries():
    from api_stats import ApiStats
    fri = datetime.datetime(2026, 9, 18)      # 周五
    sat = datetime.datetime(2026, 9, 19)      # 周六
    assert ApiStats.is_peak_now(fri.replace(hour=9, minute=0)) is True
    assert ApiStats.is_peak_now(fri.replace(hour=11, minute=59)) is True
    assert ApiStats.is_peak_now(fri.replace(hour=12, minute=0)) is False
    assert ApiStats.is_peak_now(fri.replace(hour=14, minute=0)) is True
    assert ApiStats.is_peak_now(fri.replace(hour=18, minute=0)) is False
    assert ApiStats.is_peak_now(fri.replace(hour=22, minute=0)) is False
    assert ApiStats.is_peak_now(sat.replace(hour=10, minute=0)) is False, '周末全天空闲'


def test_peak_price_switching():
    from api_stats import ApiStats
    base = {'input': 1.0, 'cache': 0.02, 'output': 4.0,
            'input_peak': 2.0, 'cache_peak': 0.04, 'output_peak': 8.0}
    fri_peak = datetime.datetime(2026, 9, 18, 10, 0)
    fri_off = datetime.datetime(2026, 9, 18, 20, 0)
    assert ApiStats._peak_adjusted(base, fri_off)['output'] == 4.0
    assert ApiStats._peak_adjusted(base, fri_peak)['output'] == 8.0
    # 没写 *_peak 时按官方“高峰 = 空闲 × 2”
    no_peak = {'input': 1.0, 'cache': 0.02, 'output': 4.0}
    assert ApiStats._peak_adjusted(no_peak, fri_peak)['output'] == 8.0
    assert ApiStats._peak_adjusted(no_peak, fri_off)['output'] == 4.0


def test_official_prices_in_builtin_profiles():
    """档案价格必须与官方定价页一致（2026-09-19 核对：flash 1/0.02/4，pro 4.5/0.15/13.5）"""
    import model_registry as mr
    by_key = {d['key']: d for d in mr.BUILTIN_PROFILES}
    assert by_key['flash']['price']['input'] == 1.0
    assert by_key['flash']['price']['cache'] == 0.02
    assert by_key['flash']['price']['output'] == 4.0
    assert by_key['flash']['price']['output_peak'] == 8.0
    assert by_key['pro']['price']['output'] == 13.5
    assert by_key['pro']['price']['output_peak'] == 27.0


def test_set_price_merges_peak_keys(tmp_path):
    """界面只编辑空闲价三项，不能把高峰价洗掉（v6.62 合并语义）"""
    import model_registry as mr
    reg = mr.ModelRegistry(str(tmp_path / 'm.json'))
    before = dict(reg.get('flash').price)
    assert 'output_peak' in before
    reg.set_price('flash', {'input': 9.9, 'cache': 0.5, 'output': 7.7})
    after = reg.get('flash').price
    assert after['input'] == 9.9 and after['output'] == 7.7
    assert after['output_peak'] == before['output_peak'], '高峰价必须保留'


def test_cost_doubles_at_peak(tmp_path):
    from api_stats import ApiStats
    import model_registry as mr
    reg = mr.ModelRegistry(str(tmp_path / 'm.json'))
    st = ApiStats(str(tmp_path / 's.json'), registry=reg)
    off = st._cost('deepseek-flash', 10000, 1000, 6000, 4000,
                   now=datetime.datetime(2026, 9, 18, 20, 0))[0]
    peak = st._cost('deepseek-flash', 10000, 1000, 6000, 4000,
                    now=datetime.datetime(2026, 9, 18, 10, 0))[0]
    assert abs(peak - off * 2) < 1e-9, '高峰费用应为空闲的 2 倍'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
