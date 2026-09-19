# -*- coding: utf-8 -*-
"""v6.62 三件 API 可选项的护栏测试

1. 思考开关/强度真正进请求体（原先只驱动 UI，等于没关思考）
2. 图片直送模型（视觉），失败回退本地 OCR
3. JSON 结构化输出（记忆抽取 + 重排）

运行：python -m pytest tests/test_api_options.py -q
"""
import io
import json
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pytest  # noqa: E402


# ---------------------------------------------------------------- 通用

def _pet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    # 切断一切落盘/统计副作用，测试只关心发出去的报文
    p._save_chat_memory = lambda *a, **k: True
    p._summarize_old = lambda *a, **k: True
    p._record_api_usage = lambda *a, **k: True
    p._close_pending_user_msg = lambda *a, **k: True
    p._notify = lambda *a, **k: None
    p.memory_facts = []
    p.deepseek_api_key = 'sk-test-key'
    p._current_api_key = lambda: 'sk-test-key'
    return p


def _make_png(path, text='余额 70.68', size=(420, 140)):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', size, 'white')
    d = ImageDraw.Draw(img)
    try:
        fnt = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 40)
    except Exception:
        fnt = None
    d.text((20, 40), text, font=fnt, fill='black')
    img.save(path)
    return path


# ---------------------------------------------------------------- ① 思考接线

def test_thinking_fields_three_states():
    p = _pet()
    p.reasoning_enabled, p.reasoning_effort = True, 'high'
    assert p._thinking_fields() == {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'}
    p.reasoning_enabled = False
    assert p._thinking_fields() == {'thinking': {'type': 'disabled'}}
    p.reasoning_enabled, p.reasoning_effort = True, 'none'
    assert p._thinking_fields() == {'thinking': {'type': 'disabled'}}, 'none 等价于关，不该再发 enabled'
    p.reasoning_effort = 'max'
    assert p._thinking_fields()['reasoning_effort'] == 'max'


def test_thinking_fields_clamps_garbage():
    p = _pet()
    p.reasoning_enabled, p.reasoning_effort = True, '乱写'
    assert p._thinking_fields()['reasoning_effort'] == 'high'


def test_request_payload_carries_thinking(monkeypatch):
    """真跑一遍 _ai_worker，抓它发出去的请求体"""
    p = _pet()
    seen = {}

    def fake_stream(key, data, **kw):
        seen['payload'] = json.loads(data.decode('utf-8'))
        yield 'done', {'content': '好的', 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}

    import desktop_pet as dp
    monkeypatch.setattr(dp, 'stream_chat_completions', fake_stream)
    p.reasoning_enabled, p.reasoning_effort, p.temperature = True, 'low', 0.7
    p._ai_worker('你好')
    rp = seen['payload']
    assert rp['thinking'] == {'type': 'enabled'}
    assert rp['reasoning_effort'] == 'low'
    assert rp['temperature'] == 0.7
    # 关思考后：只发 disabled，不再发 effort
    p.reasoning_enabled = False
    p._ai_worker('再问一句')
    rp2 = seen['payload']
    assert rp2['thinking'] == {'type': 'disabled'}
    assert 'reasoning_effort' not in rp2


def test_empty_retry_payload_disables_thinking():
    """空回复重试属于「该直接说话」，源码里必须显式关思考"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    seg = src.split('data2 = jsonlib.dumps(')[1][:900]
    assert "'thinking': {'type': 'disabled'}" in seg


# ---------------------------------------------------------------- ② 视觉

def test_encode_image_data_url_roundtrip(tmp_path):
    import vision_helper as vh
    from PIL import Image
    p = _make_png(str(tmp_path / 'a.png'))
    url, err = vh.encode_image_data_url(p)
    assert err is None and url.startswith('data:image/')
    head, b64 = url.split(',', 1)
    raw = __import__('base64').b64decode(b64)
    assert Image.open(io.BytesIO(raw)).size == (420, 140), '尺寸该保持不变（未超长边）'


def test_encode_shrinks_and_caps_big_image(tmp_path):
    """4000×3000 噪声图：必须缩到长边 1568 且编码后 ≤ 2MB"""
    import vision_helper as vh
    from PIL import Image
    import random
    img = Image.new('RGB', (4000, 3000))
    px = img.load()
    rnd = random.Random(7)
    for y in range(0, 3000, 4):
        for x in range(0, 4000, 4):
            c = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
            for dy in range(4):
                for dx in range(4):
                    px[x + dx, y + dy] = c
    src = str(tmp_path / 'big.png')
    img.save(src)
    url, err = vh.encode_image_data_url(src)
    assert err is None
    raw = __import__('base64').b64decode(url.split(',', 1)[1])
    assert len(raw) <= vh.MAX_BYTES, '单图必须压在 2MB 以内'
    assert Image.open(io.BytesIO(raw)).size[0] <= 1568


def test_build_vision_content_shapes(tmp_path):
    import vision_helper as vh
    p = _make_png(str(tmp_path / 'b.png'))
    content, used, errs = vh.build_vision_content('看图', [p])
    assert used == 1 and errs == []
    assert content[0] == {'type': 'text', 'text': '看图'}
    assert content[1]['type'] == 'image_url'
    assert content[1]['image_url']['url'].startswith('data:image/')
    # 无图 → 原样返回字符串
    assert vh.build_vision_content('纯文字', []) == ('纯文字', 0, [])
    # 坏路径 → 0 张 + 有错误说明（调用方据此回退 OCR）
    c2, u2, e2 = vh.build_vision_content('x', [str(tmp_path / 'nope.png')])
    assert u2 == 0 and e2 and c2 == 'x'


def test_pet_vision_ready_and_content(tmp_path):
    p = _pet()
    p.vision_enabled = True
    assert p._vision_ready() is True
    p.vision_enabled = False
    assert p._vision_ready() is False
    img = _make_png(str(tmp_path / 'c.png'))
    content, used, _ = p._vision_content('看图', [img])
    assert used == 1 and isinstance(content, list)
    assert p._vision_content('无图', [])[0] == '无图'
    assert p._vision_content('坏图', [str(tmp_path / 'no.png')])[1] == 0


def test_vision_call_sites_wired():
    """调用点护栏：拖图 / 附件发送 / 全屏截图三条路都要走视觉判定"""
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert src.count('if self._vision_ready():') >= 2
    assert 'images=vision_imgs' in src
    assert 'def ask_ai(self, text, images=None)' in src
    # 任务队列要带着图片走，否则排队后就丢图了
    assert "{'text': text, 'images': images, 'ts'" in src
    assert "self._run_task(t['text'], t.get('images'))" in src


def test_vision_falls_back_to_ocr(monkeypatch):
    """图片编码全失败 → 自动回退本地 OCR，不让用户白等"""
    p = _pet()
    calls = {}

    def fake_stream(key, data, **kw):
        calls['payload'] = json.loads(data.decode('utf-8'))
        yield 'done', {'content': 'ok', 'usage': {}}

    import desktop_pet as dp
    monkeypatch.setattr(dp, 'stream_chat_completions', fake_stream)
    monkeypatch.setattr(dp, 'ocr_image', lambda path, ps1: 'OCR识别出来的文字')
    p.vision_enabled = True
    p._ai_worker('看图', ['C:/definitely/not/here.png'])
    content = calls['payload']['messages'][-1]['content']
    assert 'OCR' in content and 'OCR识别出来的文字' in content


# ---------------------------------------------------------------- ③ JSON 输出

def test_extract_chat_uses_json_object(monkeypatch):
    p = _pet()
    seen = {}

    def fake_post(key, data, **kw):
        seen['payload'] = json.loads(data.decode('utf-8'))
        return {'choices': [{'message': {'content': '{}'}}], 'usage': {}}

    import desktop_pet as dp
    monkeypatch.setattr(dp, 'chat_completions', fake_post)
    p._extract_chat([{'role': 'user', 'content': 'x'}], 400)
    assert seen['payload']['response_format'] == {'type': 'json_object'}


def test_parse_rerank_ids_variants():
    p = _pet()
    assert p._parse_rerank_ids('{"ids": [2, 4]}') == [2, 4]
    assert p._parse_rerank_ids('{"ids": 3}') == [3]
    assert p._parse_rerank_ids('{"ids": ["5"]}') == [5]
    assert p._parse_rerank_ids('前面废话 {"ids": [1,3]} 后面废话') == [1, 3]
    assert p._parse_rerank_ids('1,3') == [1, 3]        # 旧格式回退
    assert p._parse_rerank_ids('') == []
    assert p._parse_rerank_ids('完全不是编号') == []


def test_rerank_memories_json_payload_and_pick(monkeypatch):
    p = _pet()
    seen = {}

    def fake_post(key, data, **kw):
        seen['payload'] = json.loads(data.decode('utf-8'))
        return {'choices': [{'message': {'content': '{"ids": [2, 1]}'}}], 'usage': {}}

    import desktop_pet as dp
    monkeypatch.setattr(dp, 'chat_completions', fake_post)
    cands = [{'id': 'a', 'text': '记忆A'}, {'id': 'b', 'text': '记忆B'}, {'id': 'c', 'text': '记忆C'}]
    picked = p._rerank_memories('问题', cands)
    assert seen['payload']['response_format'] == {'type': 'json_object'}
    assert 'JSON' in seen['payload']['messages'][0]['content']
    assert picked == ['b', 'a'], '顺序应按相关度保留'
    # 解析失败 → 兜底取前三条
    monkeypatch.setattr(dp, 'chat_completions',
                        lambda k, d, **kw: {'choices': [{'message': {'content': '呃'}}], 'usage': {}})
    assert p._rerank_memories('问题', cands) == ['a', 'b', 'c']


# ---------------------------------------------------------------- ④ 档案层

def test_clamp_effort_normalizes():
    import model_registry as mr
    assert mr.clamp_effort('none') == 'none'
    assert mr.clamp_effort('LOW') == 'low'
    assert mr.clamp_effort('minimal') == 'low'
    assert mr.clamp_effort('medium') == 'high'
    assert mr.clamp_effort('xhigh') == 'high'
    assert mr.clamp_effort('乱写') == 'high'
    assert mr.clamp_effort(None, 'low') == 'low'


def test_profile_effort_and_vision_roundtrip(tmp_path):
    import model_registry as mr
    path = str(tmp_path / 'models.json')
    reg = mr.ModelRegistry(path)
    reg.set_param('flash', 'effort', 'low')
    reg.set_field('flash', 'vision', False)
    assert reg.save()
    reg2 = mr.ModelRegistry(path)
    p = reg2.get('flash')
    assert p.effort == 'low' and p.vision is False and p.supports_vision is False
    assert reg2.get('flash').to_dict()['params']['effort'] == 'low'


def test_vision_falls_back_to_official_capability(tmp_path):
    """档案没写 vision 时按官方能力表兜底：flash 能看图、pro 不能"""
    import model_registry as mr
    reg = mr.ModelRegistry(str(tmp_path / 'm.json'))
    p = reg.get('flash')
    p.vision = None
    assert p.supports_vision is True
    q = reg.get('pro')
    q.vision = None
    assert q.supports_vision is False


def test_builtin_profiles_declare_vision():
    import model_registry as mr
    by_key = {d['key']: d for d in mr.BUILTIN_PROFILES}
    assert by_key['flash'].get('vision') is True
    assert by_key['pro'].get('vision') is False


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
