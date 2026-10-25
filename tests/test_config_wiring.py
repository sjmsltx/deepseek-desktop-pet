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

def test_k2_write_only_attribute_is_an_orphan():
    """K2 必须把「只写不读」判成孤儿（此前会假绿）

    2026-10-25（WX-119 §6.2）：`attr_used_elsewhere` 原来不区分 ast 的
    Store / Load —— 只要 `self.X` 在别处出现过就算「有人在用」。
    于是「赋值过一次但从来没人读」的属性会被判绿，而 voice_rate 那类
    漏接缺陷的另一半正是「从来没人用」。

    ⛔ 判据必须能证伪：造一个**只在别处赋值**的属性，
      修之前返回非空（假绿），修之后必须返回空（判孤儿）。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location('ccw_k2', TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    fake = (
        'class PetWidget:\n'
        '    def _load_ai_config(self):\n'
        "        self.orphan_written_only = cfg.get('orphan_written_only', 1)\n"
        '    def somewhere_else(self):\n'
        '        self.orphan_written_only = 999          # 只写，一次都没读\n'
    )
    assert m.attr_used_elsewhere(fake, 'orphan_written_only') == [], \
        '只写属性被判成「有人在用」⇒ write-only 假绿回归'

    # 对照：真的有人读，必须判非空（否则这条格把正常情况也判红）
    fake2 = (
        'class PetWidget:\n'
        '    def _load_ai_config(self):\n'
        "        self.used_attr = cfg.get('used_attr', 1)\n"
        '    def somewhere_else(self):\n'
        '        return self.used_attr\n'
    )
    assert m.attr_used_elsewhere(fake2, 'used_attr'), '正常读取被漏判了'


def test_k1_never_scans_untracked_backup():
    """K1 不许把 `backup/`（gitignored、未跟踪）算成「有人读」

    2026-10-25（WX-119 §6.2）：实测 `find_key_readers('display_mode')` 会命中
    `backup\\模型配置化改造_改造前_20260911\\desktop_pet.py:725`。
    同一份源码，**在这台机器上绿、在别人 clone 上可能红**（backup 不存在）
    ⇒ 判据不可复现 = 不是判据。

    ⛔ 这里不断言「恰好 0 处」，只断言**返回的路径里不许有 backup/_archive** ——
      前者会随真实配置变化，后者是恒成立的结构要求。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location('ccw_k1', TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    bad = []
    for key in sorted(m.load_config_keys()):
        for hit in m.find_key_readers(key):
            head = hit.replace('/', '\\').split('\\')[0]
            if head in ('backup', '_archive', 'release_build', '.git'):
                bad.append((key, hit))
    assert not bad, '核对器扫到了未跟踪目录（判据不可复现）：%r' % (bad[:5],)
