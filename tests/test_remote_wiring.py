# -*- coding: utf-8 -*-
"""B-乙 接入小批护栏 —— ⭐ **开关关着时行为必须与接线前完全一致** ✗（钉住 ✓）

微信侧 `WX-桌宠-20260926-22` §六 决策：① 开关 = **配置文件项** ✓（`config.json` 新增 `remote_control` ✓
**默认关** ✗ 最小侵入 ✓）② 设置页图形开关 = 后续小批（界面侧 ✓ 本批不做 ✗）③ 接入 = 独立小批 ✓
⭐ 唯一硬要求：**开关关着时行为必须与现在完全一致**✗ → 本文件用**一条用例钉住** ✓
"""
from __future__ import annotations

import ast
import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'desktop_pet.py'
MOD = ROOT / 'rt_remote.py'


# ── ① ⭐ 钉住：关着 → 工厂返回 None 且**什么都不构造** ✗ ─────────────
def test_disabled_config_builds_nothing(tmp_path, monkeypatch):
    import rt_remote

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError('⛔ 开关关着时**不得构造** RemoteConsumer ✗')

    monkeypatch.setattr(rt_remote, 'RemoteConsumer', Boom)
    for cfg in ({}, {'remote_control': False}, {'remote_control': 0}, None, 'x'):
        assert rt_remote.build_consumer_from_config(cfg, base_dir=str(tmp_path)) is None, cfg
    # 关着时**不得**产生任何文件/目录 ✓（零副作用 ✓）
    assert list(tmp_path.rglob('*')) == [], '关着时不得写盘 ✗'


def test_enabled_config_builds_consumer(tmp_path):
    import rt_remote
    out = rt_remote.build_consumer_from_config(
        {'remote_control': True, 'remote_interval_ms': 1500}, base_dir=str(tmp_path))
    assert out is not None and out.interval_ms == 1500
    # 装配齐了 store / relay / gate ✓（目录惰性创建 ✓ 故不断言目录存在 ✗）
    assert out.store is not None and out.relay is not None and out.gate is not None
    # 状态文件路径落在 logs/ 下 ✓（且此时尚未写盘 ✓）
    assert 'remote_state.json' in out.state_path


# ── ② 源码护栏：默认 False ✓ + 接线块在 if 守卫内 ✓ ─────────────────
def test_app_wiring_is_guarded_and_off_by_default():
    src = io.open(APP, encoding='utf-8').read()
    # ⭐ 默认值必须是 False ✓（照抄既有 active_chat 惯用法 ✓）
    assert re.search(r"_rc_cfg\.get\('remote_control',\s*False\)", src), '⛔ 默认值须为 False ✗'
    assert 'self.remote_consumer = None' in src and 'self.remote_timer = None' in src
    # ⭐ 构造/起定时器必须都在 `if bool(_rc_cfg.get('remote_control', False)):` 之下 ✓
    i_if = src.index("if bool(_rc_cfg.get('remote_control', False)):")
    i_build = src.index('rt_remote.build_consumer_from_config(')
    i_timer = src.index('self.remote_timer.start(')
    assert i_if < i_build < i_timer, '⛔ 接线与定时器必须在开关守卫内 ✗'
    # ⭐ 接入异常走 `_silent_log` ✓（不静默 ✗ 也不拖垮主程序 ✓）
    assert "_silent_log('remote_wiring'" in src
    assert "_silent_log('remote_poll'" in src


def test_app_startup_path_unchanged_without_flag(tmp_path, monkeypatch):
    """⭐ 无该键时：装配只读一行配置 ✓ 不构造任何遥控对象 ✓（= 行为与现在一致 ✗）"""
    import rt_remote
    calls = []
    monkeypatch.setattr(rt_remote, 'RemoteConsumer', lambda *a, **k: calls.append(1))
    cfgpath = tmp_path / 'config.json'
    cfgpath.write_text('{"active_chat": false}', encoding='utf-8')
    import json
    cfg = json.loads(cfgpath.read_text(encoding='utf-8'))
    assert rt_remote.build_consumer_from_config(cfg, base_dir=str(tmp_path)) is None
    assert calls == []


# ── ③ 模块级：装配函数本身**不写 L0 / 不投递** ✗ ───────────────────
def test_end_to_end_channel_command_consumed(tmp_path):
    """⭐ 端到端（桌宠侧 ✓）：**真通道里一条命令 → 自动消费 → 回执** ✓

    2026-09-26 端到端小批：补上 `relay_log` 注入（此前传 None ✗ → 读不到通道 ✗）
    """
    import relay_log
    import rt_remote
    ch = tmp_path / 'ch.jsonl'
    c = rt_remote.build_consumer_from_config(
        {'remote_control': True, 'remote_channel': str(ch)}, base_dir=str(tmp_path))
    assert c is not None
    assert c.log is not None, '⭐ 通道必须已注入 ✓（不得再为 None ✗）'
    got = []
    c.emit = got.append
    # 模拟手机侧：往通道写一条命令 ✓
    log = relay_log.RelayLog(str(ch))
    log.deliver(relay_log.Msg(id='m-1', seq=1, ts=0, channel='ch', sender='owner',
                              recipients=['owner'], kind='speak', visibility='human', body='状态'))
    res = c.poll_once()
    assert len(res) == 1 and res[0]['state'] == 'done', res
    assert got and '状态' in got[0]['reply'], got
    assert c.last_seq >= 1
    # ⭐ 幂等：再轮询不重执行 ✓
    assert c.poll_once() == []
    # ⭐ 未知命令也**要回话** ✗（不静默）
    log.deliver(relay_log.Msg(id='m-2', seq=9, ts=0, channel='ch', sender='owner',
                              recipients=['owner'], kind='speak', visibility='human', body='乱写'))
    r2 = c.poll_once()
    assert r2 and '未知命令' in r2[0]['reply']


def test_factory_never_appends_or_delivers():
    tree = ast.parse(io.open(MOD, encoding='utf-8').read())
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == 'build_consumer_from_config':
            bad = [x.attr for x in ast.walk(n) if isinstance(x, ast.Attribute)
                   and x.attr in ('append', 'deliver', 'confirm', 'reject')]
            assert bad == [], '⛔ 装配函数不得写 L0/投递/确认 ✗：%s' % bad
