# -*- coding: utf-8 -*-
"""新增测试：配置加载的三种情形（这次踩到的都是"配置读不进来"这一类）

背景（2026-10-25 一串实测）：
  · asr_* 从来没被加载 ⇒ 设置里的后端重启就丢
  · 我把 asr 段缩进写错 4 格 ⇒ 没有 config.json 时抛 UnboundLocalError，
    整段配置全不加载（语音/模型参数/待办…）；而且 voice_local_* 被裹进 if 里
  · voice_fallback 没传进 VoiceIO 构造 ⇒ 首次构造后恒为 ''，要等下次热加载

这三条的共同点：**真实 config.json 一直存在，所以从没被走到**。
是 conftest 隔离 config 之后才照出来的 —— 所以隔离本身要当护栏用，
这些用例也都要在"没有 config"的前提下跑。
"""
import io
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


def _write_cfg(path, data):
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False))


def test_no_config_file_does_not_break_config_loading(monkeypatch, tmp_path):
    """没有 config.json 时不得抛 UnboundLocalError（缩进错那次就是这么炸的）

    这是**首次运行**的真实路径：用户还没生成 config.json。
    缩进错的那一版会在这里抛 UnboundLocalError，被外层 except 吞掉，
    于是整段配置（语音、模型参数、待办…）全都不加载。
    """
    import desktop_pet as dp

    cfg = tmp_path / 'config.json'
    assert not cfg.exists()
    monkeypatch.setattr(dp, 'CONFIG_PATH', str(cfg), raising=False)

    seen = []
    real = dp._silent_log

    def spy(tag, exc=None, **kw):
        seen.append((str(tag), str(exc or '')))
        try:
            return real(tag, exc, **kw)
        except TypeError:
            return real(tag, exc)

    monkeypatch.setattr(dp, '_silent_log', spy)

    p = dp.PetWidget()
    try:
        bad = [t for t in seen if 'UnboundLocalError' in t[1]]
        assert not bad, '没有 config.json 时抛了 UnboundLocalError：%r' % bad
        assert not any('734' in t[0] for t in seen), \
            '_load_ai_config 外层 except 被触发（说明内部有异常）：%r' % seen[:3]
    finally:
        p.deleteLater()


def test_all_voice_and_asr_keys_load(monkeypatch, tmp_path):
    """asr_* / voice_local_* / voice_fallback 全部要读进来

    ⛔ 判据必须能证伪：断言"读到的是配置文件里的值"，不是"有默认值就行"。
       asr_* 从来没加载的那一版，这里会拿到默认 'auto' / ''，断言立刻红。
    """
    import desktop_pet as dp

    cfg = tmp_path / 'config.json'
    _write_cfg(cfg, {
        'asr_backend': 'http',
        'asr_lang': 'zh-CN',
        'asr_http_url': 'https://x/asr',
        'asr_record_seconds': 8,
        'voice_local_url': 'http://127.0.0.1:9880',
        'voice_local_ref': 'ref.wav',
        'voice_local_prompt': '参考文本',
        'voice_fallback': 'Yaoyao',
    })
    monkeypatch.setattr(dp, 'CONFIG_PATH', str(cfg), raising=False)

    p = dp.PetWidget()
    try:
        assert p.asr_backend == 'http', p.asr_backend
        assert p.asr_http_url == 'https://x/asr'
        assert p.asr_record_seconds == 8
        assert p.voice_local_url == 'http://127.0.0.1:9880'
        assert p.voice_local_ref == 'ref.wav'
        assert p.voice_local_prompt == '参考文本'
        assert p.voice_fallback == 'Yaoyao'
        if getattr(p, 'asr', None) is not None:
            assert p.asr.backend_name == 'http'
            assert p.asr.record_seconds == 8
        if getattr(p, 'voice', None) is not None:
            # 构造时就要拿到 —— 上一版漏了构造参数，这里会拿到 ''
            assert p.voice.fallback_voice == 'Yaoyao', \
                'voice 构造时没拿到 fallback_voice（要等下次热加载才生效）'
    finally:
        p.deleteLater()


def test_voice_local_keys_load_without_asr_engine(monkeypatch, tmp_path):
    """没有 self.asr 时，voice_local_* / voice_fallback 仍要加载

    缩进错的那一版把它们裹进了 `if getattr(self,'asr') is not None:`，
    于是只有 asr 引擎存在时才加载 —— 语义完全错。
    """
    import desktop_pet as dp

    cfg = tmp_path / 'config.json'
    _write_cfg(cfg, {
        'asr_backend': 'whisper',
        'asr_whisper_exe': 'D:/w/main.exe',
        'voice_local_url': 'http://127.0.0.1:9881',
        'voice_fallback': 'Huihui',
    })
    monkeypatch.setattr(dp, 'CONFIG_PATH', str(cfg), raising=False)

    p = dp.PetWidget()
    try:
        try:
            del p.asr
        except AttributeError:
            p.asr = None
        p._load_ai_config()
        assert p.voice_local_url == 'http://127.0.0.1:9881'
        assert p.voice_fallback == 'Huihui'
        assert p.asr_backend == 'whisper'
        assert p.asr_whisper_exe == 'D:/w/main.exe'
    finally:
        p.deleteLater()


def test_session_isolates_real_config():
    """跑测试期间，CONFIG_PATH 不得指向仓库里那份真实 config.json

    这是「测试不许改用户配置」的护栏。2026-10-25 实测：function 级隔离不够 ——
    session 收尾阶段（Qt 析构）仍会写窗口位置，跑一次全量 Owner 的 x/y 就变了。
    所以改成 session 级，并在这里钉住。

    ⛔ 判据能证伪：如果隔离失效，CONFIG_PATH 会等于 BASE/config.json，断言立刻红。
    """
    import desktop_pet as dp

    real = os.path.join(BASE, 'config.json')
    cur = os.path.abspath(str(dp.CONFIG_PATH))
    assert cur != os.path.abspath(real), \
        '测试期间的 CONFIG_PATH 指向了真实配置（隔离失效，会改 Owner 的数据）：%s' % cur
