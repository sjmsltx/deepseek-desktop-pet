# -*- coding: utf-8 -*-
"""M1 内核 · **状态可回放**测试（webchat 侧自查补充）。

背景（真实 bug）：`conclude()` / `interrupt()` 原本只在内存里改标志位 ✗ ——
重启服务后新实例从日志重建，"已收束/已暂停"丢失 → 界面显示 running ✗。
这直接违反 P1 验收的「**可回放**」：**状态必须是日志的函数**。

本文件锁定：同一份日志，新实例必须重建出同样的状态。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

relay = pytest.importorskip('relay_log', reason='relay_log.py 尚未实现')


def test_concluded_state_survives_reload(tmp_path):
    p = tmp_path / 'r.jsonl'
    log = relay.RelayLog(p)
    log.open_issue(relay.Issue('T', 'G', 'D'))
    log.conclude('cost_limit')
    assert log.snapshot()['stopped'] is True

    fresh = relay.RelayLog(p)                       # 模拟"重启服务"
    snap = fresh.snapshot()
    assert snap['concluded'] is True, '收束状态必须能从日志重建（否则刷新/重启后界面状态错）'
    assert snap['stopped'] is True
    assert snap['stop_reason'] == 'cost_limit'


def test_interrupt_state_survives_reload(tmp_path):
    p = tmp_path / 'r.jsonl'
    log = relay.RelayLog(p)
    log.open_issue(relay.Issue('T', 'G', 'D'))
    log.interrupt('停一下')
    assert log.snapshot()['interrupted'] is True

    fresh = relay.RelayLog(p)
    assert fresh.snapshot()['interrupted'] is True, '暂停状态也必须可重建'


def test_resume_state_survives_reload(tmp_path):
    p = tmp_path / 'r.jsonl'
    log = relay.RelayLog(p)
    log.open_issue(relay.Issue('T', 'G', 'D'))
    log.interrupt('停一下')
    assert log.resume('继续') is True

    fresh = relay.RelayLog(p)
    assert fresh.snapshot()['interrupted'] is False, '显式“继续”也写日志 → 新实例不应还是暂停'


def test_reload_does_not_double_count(tmp_path):
    """重建不得把成本/token 重复累计（投影行 billable=False）。"""
    p = tmp_path / 'r.jsonl'
    log = relay.RelayLog(p)
    log.append({'id': 'a', 'channel': 'group:main', 'sender': 'agent:x', 'recipients': [],
                'kind': 'speak', 'visibility': 'human', 'body': 'x',
                'meta': {'v': 1, 'tokens': 5, 'cost_micro': 50}})
    log.append({'id': 'b', 'channel': 'group:main', 'sender': 'system',
                'recipients': ['agent:x'], 'kind': 'reply', 'visibility': 'meta',
                'body': '投递', 'meta': {'v': 1, 'tokens': 5, 'cost_micro': 50, 'billable': False}})
    fresh = relay.RelayLog(p)
    assert fresh.cost_total() == 50 and fresh.token_total() == 5
