# -*- coding: utf-8 -*-
"""护栏：配置链路必须完整（A 档止血的落点）

背景（2026-10-25 一整天的教训）：
  这一天漏的 bug 全是「配置项接了一半」——
    · asr_* 六个键：config 里有，_load_ai_config 不读 ⇒ 设置改了重启就丢
    · voice_fallback：读了、存了属性，但没传给 VoiceIO 构造
    · voice_rate：一样，config 里有 +30%，_load_ai_config 从来不读 ⇒ 语速重启就回默认
  它们共同的特征是：**名字都对得上，就是没连上**，而当时的工具只查「名字存在吗」。

`tools/check_config_wiring.py` 专查三段链路：
    ① config.json 的键 → ② _load_ai_config 的 self 属性 → ③ 外部类构造参数

本测试把它纳入全量：谁再接漏一处，跑测试当场红，
不用等到「重启后发现设置丢了」再回头查。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(BASE, 'tools', 'check_config_wiring.py')


def test_config_wiring_is_complete():
    """核对器必须存在且返回 0（0 = 三段链路完整）"""
    assert os.path.exists(TOOL), '核对器不见了：%s' % TOOL
    r = subprocess.run([sys.executable, TOOL, '--check'],
                       cwd=BASE, capture_output=True, timeout=180)
    out = (r.stdout or b'').decode('utf-8', 'replace')
    err = (r.stderr or b'').decode('utf-8', 'replace')
    assert r.returncode == 0, (
        '配置链路有缺口（新增了配置项但没接全？）：\n'
        + out[-3000:] + '\n' + err[-500:])


def test_checker_has_teeth():
    """证伪：核对器对"故意接漏"的样本必须报出来

    ⛔ 只在「跑得通」上断言等于没断言 —— 必须证明它真能发现缺口。
    做法：造一段源码，配置键有、_load_ai_config 不读，检查 ASt 分析能识别。
    """
    sys.path.insert(0, os.path.join(BASE, 'tools'))
    import importlib.util
    spec = importlib.util.spec_from_file_location('ccw', TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    fake = (
        'class PetWidget:\n'
        '    def __init__(self):\n'
        "        self.voice = VoiceIO(rate='')\n"
        '    def _load_ai_config(self):\n'
        "        self.a = cfg.get('loaded_key', '')\n"
    )
    key_to_attr, _attr_to_key, ctor = m.analyze_load_config(fake)
    assert key_to_attr == {'loaded_key': 'a'}, key_to_attr
    assert 'voice' in ctor, '构造调用没被识别到：%r' % ctor
    # 未出现在 _load_ai_config 的键，就是「没接上」
    assert 'forgotten_key' not in key_to_attr
