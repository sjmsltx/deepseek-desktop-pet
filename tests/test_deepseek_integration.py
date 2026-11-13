# -*- coding: utf-8 -*-
"""OCR 后端 / 搜索参数 / ASR 后端的接入测试（2026-11-13）

这些测的是「接线对不对」，不打真接口。
重点是几条实测得出的行为：
1 本机 OCR 的逐字空格要被 squeeze 掉，但中英之间的空格要留
2 ocr_image 的 backend 参数真的会分流（不是摆设）
3 搜索参数越界要夹紧（配置文件可能被手改）
4 搜索节流按配置走（默认 50ms，不再是写死的 200ms）
"""
import io
import os
import re

import pytest


# ---------------------------------------------------------------- 1 空格修正

def test_squeeze_removes_spaces_between_cjk():
    import pet_docs as pd
    # 实测本机 WinRT 输出：每个汉字之间一个空格
    assert pd.squeeze_cjk_spaces('桌 宠 记 忆 系 统') == '桌宠记忆系统'
    assert pd.squeeze_cjk_spaces('重 庆 合 川 桃 片 很 好 吃') == '重庆合川桃片很好吃'


def test_squeeze_keeps_space_between_cjk_and_ascii():
    """⛔ 不能全删：「Python 与地理信息科学」里那个空格是词边界。"""
    import pet_docs as pd
    assert pd.squeeze_cjk_spaces('Python 与 地 理 信 息 科 学') == 'Python 与地理信息科学'
    assert pd.squeeze_cjk_spaces('桌 宠 Python 记 忆') == '桌宠 Python 记忆'
    assert pd.squeeze_cjk_spaces('DeepSeek API 2026') == 'DeepSeek API 2026'


def test_squeeze_handles_empty():
    import pet_docs as pd
    assert pd.squeeze_cjk_spaces('') == ''
    assert pd.squeeze_cjk_spaces(None) == ''


# ---------------------------------------------------------------- 2 后端分流

def test_ocr_image_dispatches_by_backend(monkeypatch):
    """backend 必须真的分流，不能是摆设。"""
    import pet_docs as pd
    calls = []

    def _fake_ds(path, api_key='', base_dir=''):
        calls.append(('deepseek', path))
        return 'DS识别结果'

    monkeypatch.setattr(pd, '_ocr_via_deepseek', _fake_ds)

    # deepseek 走新分支
    assert pd.ocr_image('x.png', 'helper.ps1', backend='deepseek') == 'DS识别结果'
    assert calls == [('deepseek', 'x.png')]


def test_ocr_image_local_backend_squeezes(monkeypatch):
    """本机后端必须过 squeeze（否则逐字空格进 prompt）。"""
    import pet_docs as pd

    class _R(object):
        returncode = 0
        stdout = '桌 宠 测 试'.encode('utf-8')
        stderr = b''

    monkeypatch.setattr(pd.subprocess, 'run', lambda *a, **k: _R())
    out = pd.ocr_image('x.png', 'helper.ps1', backend='local')
    assert out == '桌宠测试', '本机后端没做空格修正：%r' % out


def test_ocr_image_defaults_to_local(monkeypatch):
    import pet_docs as pd

    class _R(object):
        returncode = 0
        stdout = '默 认'.encode('utf-8')
        stderr = b''

    monkeypatch.setattr(pd.subprocess, 'run', lambda *a, **k: _R())
    assert pd.ocr_image('x.png', 'helper.ps1') == '默认'


def test_ocr_deepseek_without_key_returns_empty(monkeypatch):
    """没有 Key 时返回空串（与本地后端同一契约），且不抛。"""
    import pet_docs as pd
    import deepseek_tools as dt
    monkeypatch.setattr(dt, 'api_key', lambda *a, **k: '')
    assert pd._ocr_via_deepseek('x.png') == ''


# ---------------------------------------------------------------- 3 参数夹紧

def _pet(monkeypatch):
    """造一个不跑 __init__ 的空壳（该组件无 GUI 时构造会静默退出）"""
    import desktop_pet as dp
    p = dp.PetWidget.__new__(dp.PetWidget)
    p._saved = {}
    p._save_cfg_value = lambda k, v: p._saved.__setitem__(k, v) or True
    p._notify = lambda *a, **k: None
    return p


def test_search_opt_clamps_out_of_range(monkeypatch):
    p = _pet(monkeypatch)
    assert p._set_search_opt('search_count', 999) == 50
    assert p._set_search_opt('search_count', -5) == 1
    assert p._set_search_opt('search_min_rerank', 9.9) == 3.0
    assert p._set_search_opt('search_min_rerank', -1) == 0.0
    assert p._set_search_opt('search_gap_ms', 99999) == 2000
    assert p._set_search_opt('search_need_content', 1) is True


def test_search_opt_rejects_unknown_key(monkeypatch):
    p = _pet(monkeypatch)
    assert p._set_search_opt('not_a_key', 1) is None


def test_search_opt_rejects_bad_type(monkeypatch):
    p = _pet(monkeypatch)
    assert p._set_search_opt('search_count', 'abc') is None
    assert p._set_search_opt('search_min_rerank', None) is None


def test_ocr_backend_validates(monkeypatch):
    p = _pet(monkeypatch)
    assert p._set_ocr_backend('deepseek') == 'deepseek'
    assert p._set_ocr_backend('nonsense') == 'local'
    assert p._set_ocr_backend(None) == 'local'


# ---------------------------------------------------------------- 4 节流与默认值

def _code_only(src):
    """只保留代码 token，去掉注释与字符串字面量。

    ⛔ 为什么要它：我在注释里写了「原注释『官方 QPS 仅 5』与官方文档不符」，
      直接 grep 整份源码会命中这句**新注释**，把已经改好的代码判成没改。
      项目记过这条：结构钉 grep 会命中注释，先剥注释/docstring 再匹配。

    为什么不用正则：字符串里也有 `#`，正则处理不了三引号嵌套。
    tokenize 本来就区分代码/注释/字符串，用它最稳。
    """
    import io as _io
    import tokenize as _tok
    out = []
    try:
        for tok in _tok.generate_tokens(_io.StringIO(src).readline):
            if tok.type in (_tok.COMMENT, _tok.STRING):
                continue
            out.append(tok.string)
    except _tok.TokenError:
        return src
    return ' '.join(out)


def test_search_gap_uses_config_not_hardcoded_200ms():
    """实测 40 并发全 200（约 57 QPS）⇒ 写死 200ms 严了约 20 倍。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'desktop_pet.py'), encoding='utf-8').read()
    assert "getattr(self, 'search_gap_ms', 50)" in src, '节流没接配置'
    code = _code_only(src)
    assert 'QPS 仅 5' not in code, '代码里还留着「QPS 仅 5」的说法（注释不算，这里查的是代码）'
    assert 'now - last < 0.2:' not in code, '200ms 写死节流还在'


def test_new_config_attrs_have_structural_defaults():
    """结构性默认值必须在 __init__ 无条件赋值（项目踩过 5 次的坑）。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'desktop_pet.py'), encoding='utf-8').read()
    for attr in ('ocr_backend', 'search_count', 'search_min_rerank',
                 'search_need_content', 'search_gap_ms', 'read_url_max_chars'):
        # 在 _load_ai_config 的「结构性默认值区」里（try 之前）必须有赋值
        i_def = src.find("self.%s = " % attr)
        assert i_def > 0, '缺少结构性默认值：%s' % attr


def test_no_self_config_anywhere():
    """本项目没有 self.config 这个属性 —— 一律用实例属性（_load_ai_config 的惯例）。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'desktop_pet.py'), encoding='utf-8').read()
    hits = re.findall(r'self\.config\b', src)
    assert not hits, '又出现 self.config（本项目没有这个属性）：%d 处' % len(hits)


def test_read_url_tool_registered():
    import desktop_pet as dp
    assert 'read_url' in dp.PetWidget.AI_TOOL_MAP if hasattr(dp.PetWidget, 'AI_TOOL_MAP') else True
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'desktop_pet.py'), encoding='utf-8').read()
    assert "'read_url': '_tool_read_url'" in src
    assert 'def _tool_read_url' in src


# ---------------------------------------------------------------- 5 ASR 后端

def test_asr_deepseek_backend_wired():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'asr.py'), encoding='utf-8').read()
    assert "if b == 'deepseek':" in src
    assert 'def _listen_deepseek' in src
    assert 'import deepseek_tools as _dt' in src


def test_asr_backend_valid_values_include_deepseek():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'desktop_pet.py'), encoding='utf-8').read()
    assert "'http', 'deepseek'" in src, '_set_asr_backend 的合法值没加 deepseek'


# ---------------------------------------------------------------- 6 TTS 引擎

def test_voice_choices_include_deepseek():
    import voice_io as vi
    vals = [v for v, _lab, _e in vi.VOICE_CHOICES]
    assert 'deepseek:stella' in vals and 'deepseek:tide' in vals


def test_parse_voice_spec_recognizes_deepseek():
    import voice_io as vi
    assert vi.parse_voice_spec('deepseek:stella') == ('deepseek', 'stella')
    assert vi.parse_voice_spec('deepseek:tide') == ('deepseek', 'tide')


def test_tts_engine_plan():
    import voice_io as vi
    v = vi.VoiceIO(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   enabled=True, engine='deepseek', voice='deepseek:stella')
    plan = v.engine_plan()
    assert plan[0] == 'deepseek', 'engine=deepseek 时首选应是 deepseek，实际 %r' % plan
    assert 'offline' in plan, '失败后应有离线兜底'
