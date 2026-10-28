# -*- coding: utf-8 -*-
"""K1r 反向检查：配置键「只读不可写」审计（2026-10-28）

背景
----
`K1` 查的是「config.json 有键 → 代码里有人读」。
**反向从不查**，于是出现整整一类缺陷：代码读了、但用户永远改不了的键。

`WX-124 §4.2` 报了第一个样本 `voice_fallback`（代码读 + 传参 + 4 处测试，
但 config 无此键、settings_ui 零命中 ⇒ 用户无法设 ⇒ 恒空）。
本文件把这一**类**做成可复跑断言。

判据（自带实现，不依赖 tools/check_config_wiring.py）
------------------------------------------------------
    读   = 出现在 `_load_ai_config` 的 `cfg.get('KEY', ...)` 里
    可写 = 命中任一：
             ① `_save_cfg_value('KEY'`
             ② `_toggle_cfg_flag('KEY'`
             ③ `_save_profile_param('KEY'`
             ④ 键名出现在 `settings_ui.py`（有 UI 入口）
    死   = 读 且 不可写

为什么自带实现而不调 tools/
--------------------------
K1r 工具尚未落地（`PC-271 §4.1` 仍待排期）。本文件先独立钉住事实。
将来工具的判据若与本文件不一致，两边一起红 —— 正好暴露分歧，而不是互相掩埋。

⚠ 本文件钉的是「当前已知状态」，不是「设计目标」
------------------------------------------------
`test_dead_key_snapshot` 会因**修好某个死配置而变红**。
那是预期行为：清单变了就该有人看一眼并更新快照，而不是让它静默漂移。
"""
import io
import json
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 已知「只读不可写」的键（2026-10-28 快照，逐个人工核对过）
# 2026-10-28 移出：`balance_watch_minutes`
#   Owner「给它加个设置项吧」⇒ 已加进 设置→用量与计费 的「余额盯梢间隔」（1~60 分钟），
#   从「代码读 + UI 无」变成「有 UI 入口」⇒ 不再是死配置。
#   （电脑侧改，按分工附留痕：改前 test_dead_key_snapshot 红、改后绿、未 --freeze）
KNOWN_DEAD = {
    'ai_bubble_max_chars',    # 气泡文字长度上限：读了，无 UI、无写入
    'asr_lang',               # ASR 语言：读了，设置页无此项、无写入
    'asr_record_seconds',     # ASR 录音时长：同上
    'balance_auto_minutes',   # 余额自动查询间隔：读了，无 UI（另有 balance_watch_minutes）
    'holidays_auto_update',   # 节假日自动更新：读了，无 UI、无写入
    'use_vision',             # 图片直喂模型：UI 开关写的是「模型档案」，config 里这个键是遗留
    'voice_engine',           # 语音引擎：已被 voice_name 的 'edge:'/'offline:' 前缀取代
    'voice_fallback',         # 离线兜底声线：WX-124 §4.2 首次报告
}


# ---------------- 审计实现（纯函数，便于构造合成源码做证伪） ----------------

def read_keys_from_src(src):
    """从 `_load_ai_config` 里抽出 `cfg.get('key', ...)` 的键"""
    m = re.search(r"def _load_ai_config.*?(?=\n    def |\Z)", str(src), re.S)
    if not m:
        return set()
    return set(re.findall(r"cfg\.get\(\s*['\"](\w+)['\"]", m.group(0)))


def writable_keys_from_src(full_src, ui_src, read_keys=None):
    """返回「存在写入路径」的键集合"""
    out = set()
    for pat in (r"_save_cfg_value\(\s*['\"](\w+)['\"]",
                r"_toggle_cfg_flag\(\s*['\"](\w+)['\"]",
                r"_save_profile_param\(\s*['\"](\w+)['\"]"):
        out |= set(re.findall(pat, str(full_src)))
    if read_keys is None:
        read_keys = read_keys_from_src(full_src)
    for k in read_keys:
        if k in str(ui_src):
            out.add(k)
    return out


def dead_keys(full_src, ui_src, config_keys):
    """读 但 不可写 ⇒ 死配置"""
    read = read_keys_from_src(full_src)
    write = writable_keys_from_src(full_src, ui_src, read)
    return sorted(k for k in read if (k not in set(config_keys)) and (k not in write))


def _read(p):
    return io.open(p, encoding='utf-8', errors='replace').read()


def _real():
    dp = _read(os.path.join(BASE, 'desktop_pet.py'))
    su = _read(os.path.join(BASE, 'settings_ui.py'))
    cfg = json.load(io.open(os.path.join(BASE, 'config.json'), encoding='utf-8'))
    return dp, su, cfg


# ---------------- 证伪保护：审计本身必须能绿能红 ----------------

def test_audit_detects_dead_key_on_synthetic_source():
    """证伪：读得到、写得着、config 里没有 ⇒ 必须判死

    ⛔ 只在真源码上断言「恰好 N 个」等于没断言 —— 必须证明这套逻辑真能发现缺口。
    """
    src = (
        'class PetWidget:\n'
        '    def _load_ai_config(self):\n'
        "        self.a = cfg.get('dead_key', 1)\n"
        '    def elsewhere(self):\n'
        "        return self.a\n"          # 只有读，没有 _save_cfg_value
    )
    assert dead_keys(src, '', []) == ['dead_key']


def test_audit_does_not_flag_key_with_save_path():
    """负例：有 `_save_cfg_value` 就不算死（哪怕 config 里暂时没这个键）"""
    src = (
        'class PetWidget:\n'
        '    def _load_ai_config(self):\n'
        "        self.a = cfg.get('saved_key', 1)\n"
        '    def setter(self):\n'
        "        self._save_cfg_value('saved_key', 2)\n"
    )
    assert dead_keys(src, '', []) == []


def test_audit_does_not_flag_key_with_toggle_helper():
    """负例：走 `_toggle_cfg_flag` 的键也不算死（balance_watch 就是这条路径）"""
    src = (
        'class PetWidget:\n'
        '    def _load_ai_config(self):\n'
        "        self.a = cfg.get('toggle_key', True)\n"
        '    def flip(self):\n'
        "        self._toggle_cfg_flag('toggle_key', 'a', 'on', 'off')\n"
    )
    assert dead_keys(src, '', []) == []


def test_audit_does_not_flag_key_exposed_in_settings_ui():
    """负例：键名出现在 settings_ui.py ⇒ 有 UI 入口，不判死"""
    src = (
        'class PetWidget:\n'
        '    def _load_ai_config(self):\n'
        "        self.a = cfg.get('ui_key', 1)\n"
    )
    assert dead_keys(src, "self.cb_ui_key = QComboBox()", []) == []
    # 同一份源码，UI 里没有它 ⇒ 必须判死（证明上面那条不是恒绿）
    assert dead_keys(src, "self.other = QComboBox()", []) == ['ui_key']


def test_audit_respects_key_present_in_config():
    """负例：config.json 里有这个键 ⇒ 用户能直接改文件，不判死"""
    src = (
        'class PetWidget:\n'
        '    def _load_ai_config(self):\n'
        "        self.a = cfg.get('in_cfg', 1)\n"
    )
    assert dead_keys(src, '', []) == ['in_cfg']
    assert dead_keys(src, '', ['in_cfg']) == []


# ---------------- 真源码上的具体事实 ----------------

def test_voice_fallback_is_dead():
    """`voice_fallback` 必须是死的：代码读它，但没有任何入口能设它

    `WX-124 §4.2` 首次报告；`PC-271 §4.1` 确认「不是用户没设，是用户根本没法设」。
    `PC-272` 修了 `voice_max_chars` / `voice_content_mode`，**这个没修**。
    """
    dp, su, cfg = _real()
    assert 'voice_fallback' in read_keys_from_src(dp), \
        '前提变了：_load_ai_config 已经不读 voice_fallback'
    assert 'voice_fallback' not in cfg, \
        'voice_fallback 已进 config.json —— 死配置可能已被修好，请同步更新本测试'
    assert 'voice_fallback' not in su, \
        'settings_ui 里出现了 voice_fallback —— 已有入口，请同步更新本测试'
    assert 'voice_fallback' in dead_keys(dp, su, cfg)


def test_voice_max_chars_and_content_mode_are_not_dead():
    """回归保护：这两个已有 UI 入口，谁删了入口就会红

    `PC-272` 原文：「`voice_max_chars` 从『假配置』变成真配置（设置界面能调、
    config 能写、立刻生效）」；`voice_content_mode` 顺带补了 `_load_ai_config` 读回。
    ⇒ 它们不该再被判死。若这条红了，说明入口被回退了。
    """
    dp, su, cfg = _real()
    dead = dead_keys(dp, su, cfg)
    for k in ('voice_max_chars', 'voice_content_mode'):
        assert k in read_keys_from_src(dp), '前提变了：代码不再读 %s' % k
        # ① 必须有 UI 入口：只判「不 dead」不够 —— 删了 UI 仍有 _save_cfg_value，
        #    照样不 dead，但用户已经改不了了（这正是本测试要防的回归）
        assert k in su, (
            '%s 在 settings_ui.py 里找不到了 —— 设置界面入口被删了？'
            '（有 _save_cfg_value 不代表用户能改到）' % k)
        # ② 也不能被判死
        assert k not in dead, (
            '%s 被判成死配置 —— 它的 UI 入口或写入路径被删了？' % k)


def test_dead_key_snapshot():
    """快照：当前「只读不可写」的完整清单

    ⚠ 这条红了有且只有两种含义：
      ① 修好了某个死配置（好）→ 请把它从 KNOWN_DEAD 移出
      ② 新引入了一个死配置（坏）→ 请补 UI 或补写入路径
    两种都要人看一眼，这正是快照的用处。
    """
    dp, su, cfg = _real()
    got = set(dead_keys(dp, su, cfg))
    missing = KNOWN_DEAD - got        # 修好了
    added = got - KNOWN_DEAD          # 新出现的
    assert not missing, (
        '这些死配置已不再被判死（可能修好了），请从 KNOWN_DEAD 移出：%r' % sorted(missing))
    assert not added, (
        '新出现死配置（代码读了但没有入口能设），请补 UI/写入路径或登记：%r' % sorted(added))


def test_audit_covers_whole_config_surface():
    """护栏：审计必须真的在扫全部键，不能因为正则失效而「零死配置」假绿

    判据用下界而非精确值 —— 「至少 40 个键被读」是结构要求，
    「恰好 46 个」会随真实配置变化而误报。
    """
    dp, su, cfg = _real()
    keys = read_keys_from_src(dp)
    assert len(keys) >= 40, '只读出 %d 个键，正则可能失效了' % len(keys)
    assert len(cfg) >= 30, 'config.json 只有 %d 个键，文件可能没读到' % len(cfg)
