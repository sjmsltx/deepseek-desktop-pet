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
    # ⭐ S3：with 关句柄（原本一行读漏句柄 → ResourceWarning ✗）
    with open(APP, encoding='utf-8') as _fh:
        src = _fh.read()
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


# ── ⭐ emit 约定对齐（修 `TypeError: 'dict' object is not callable` ✗）─────
def test_emit_convention_is_bridged_in_host():
    """微信侧真机联测报的 `desktop_pet.py:431 TypeError: 'dict' object is not callable` ✗

    约定：**消费器 `emit` 收 dict** ✓（`rt_remote` 原样传回执 dict ✓）
    → host 端**不得**直接接 `ui_call_signal.emit` ✗（那个 lambda 会把参数当可调用 ✗）
    → 必须经 `_remote_emit` **桥接** ✓
    """
    # ⭐ S3：with 关句柄（原本一行读漏句柄 → ResourceWarning ✗）
    with open(APP, encoding='utf-8') as _fh:
        src = _fh.read()
    assert 'emit=self._remote_emit' in src, '⭐ 接线必须走桥接 ✗'
    assert 'emit=self.ui_call_signal.emit' not in src, '⛔ 不得直连 ui_call_signal.emit ✗'
    assert 'def _remote_emit(self, ev):' in src
    assert 'self.ui_call_signal.emit(lambda: self._remote_on_result(ev))' in src, \
        '⭐ 桥接须包成可调用再 emit ✓'
    assert 'def _remote_on_result(self, ev):' in src


# ── ⭐ 回执／审计落点（微信侧 §三③："回执未落盘"待查 ✓ 用例钉住 ✓）─────
def test_receipt_and_audit_landing_points(tmp_path):
    """⭐ 口径（真机联测解释 ✓）：
    · **回执** 只在 `投递` 类命令时产生 ✓ → 落 `<base>/remote/receipts.jsonl` ✓
    · **只读** 命令（如 `状态`）**不产生回执** ✗（预期 ✓，不是丢失 ✗）
    · **审计** 走 `governance.log_event` ✓ → 落**既有审计目录** `logs/audit_<日期>.jsonl` ✓（**不在 `remote/`** ✗）
    """
    import os

    import relay_log
    import rt_remote
    ch = tmp_path / 'ch.jsonl'
    c = rt_remote.build_consumer_from_config(
        {'remote_control': True, 'remote_channel': str(ch)}, base_dir=str(tmp_path))
    assert c is not None
    log = relay_log.RelayLog(str(ch))

    def _send(mid, body, seq):
        log.deliver(relay_log.Msg(id=mid, seq=seq, ts=0, channel='r', sender='owner',
                                  recipients=['owner'], kind='speak', visibility='human', body=body))

    _send('m-1', '状态', 1)                       # 只读 ✓
    c.poll_once()
    assert not (tmp_path / 'remote' / 'receipts.jsonl').exists(), '⭐ 只读命令**不应**产生回执 ✗'

    _send('m-2', '投递 r-x|flash 你好', 2)        # 投递 ✓
    c.poll_once()
    rp = tmp_path / 'remote' / 'receipts.jsonl'
    assert rp.is_file() and 'r-x|flash' in io.open(rp, encoding='utf-8').read(), \
        '⭐ 投递应落回执 ✓（<base>/remote/receipts.jsonl ✓）'
