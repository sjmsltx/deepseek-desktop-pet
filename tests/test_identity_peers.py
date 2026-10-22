# -*- coding: utf-8 -*-
"""identity 段护栏（契约条款 III D2 · 双方已同意 ✓ Owner 2026-10-03 批 ✓）。

口径：
  · ⭐ **未配置 = 一律放行** ✓（**行为与从前完全一致** ✓ —— 与额度那套同一个模式 ✓）
  · 已配置 → **白名单枚举** ✓；名单外 → ⛔ **不派发** ✗ ＋ 必写审计 ✓ ＋ 明报 ✓ ＋ 置为已消费（不重放 ✗）
  · ⛔ 不用密码/token ✗（零新增凭证 ✓）
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import relay_log  # noqa: E402
import rt_remote  # noqa: E402


# ── 1. ⭐ 未配置 = 放行（行为不变 ✓ 最要紧）────────────────────────────
@pytest.mark.parametrize('peers', [None, [], ['', '  ']])
def test_unset_allows_everything(peers):
    ok, why = rt_remote.sender_allowed('anyone-at-all', peers)
    assert ok is True and why == '', '未配置必须一律放行 ✓（行为与从前一致 ✓）'


# ── 2. 配置后：白名单内放行 / 名单外拒绝 ✓（含大小写归一 ✓）───────────
def test_whitelist_enumeration_and_case_folding():
    peers = ['o9cq807n3bgf4Jmpv18rApZlHyzM@im.wechat']
    assert rt_remote.sender_allowed('o9cq807n3bgf4Jmpv18rApZlHyzM@im.wechat', peers)[0] is True
    assert rt_remote.sender_allowed('o9cq807n3bgf4jmpv18rapzlhyzm@im.wechat', peers)[0] is True
    ok, why = rt_remote.sender_allowed('stranger@im.wechat', peers)
    assert ok is False and '不在白名单' in why


# ── 3. ⭐ 名单外 → ⛔ 不派发 ＋ 审计 ＋ 明报 ＋ 不重放（真跑消费器 ✓）────
def _mk(tmp_path, allowed_peers):
    ch = tmp_path / 'ch.jsonl'
    log = relay_log.RelayLog(str(ch))
    calls = []

    def fake_dispatch(cmd, **kw):
        calls.append(cmd)
        return {'ok': True, 'reply': 'ok', 'data': None}

    c = rt_remote.RemoteConsumer(log, dispatch_fn=fake_dispatch, state_path=str(tmp_path / 'st.json'),
                                 allowed_peers=allowed_peers)
    return log, c, calls


def _send(log, mid, sender, body, seq):
    log.deliver(relay_log.Msg(id=mid, seq=seq, ts=0, channel='remote', sender=sender,
                              recipients=['owner'], kind='speak', visibility='human', body=body))


def test_denied_sender_is_not_dispatched(tmp_path):
    log, c, calls = _mk(tmp_path, ['owner-ok'])
    _send(log, 'm1', 'stranger', '状态', 1)
    out = c.poll_once()
    assert calls == [], '⛔ 名单外必须**不派发** ✗'
    assert len(out) == 1 and out[0]['ok'] is False and '白名单' in out[0]['reply']
    assert out[0]['state'] == 'failed'
    # ⭐ 已消费（不重放 ✗）：再轮询一次不应再出结果
    assert c.poll_once() == []


def test_allowed_sender_is_dispatched(tmp_path):
    log, c, calls = _mk(tmp_path, ['owner-ok'])
    _send(log, 'm1', 'owner-ok', '状态', 1)
    out = c.poll_once()
    assert calls and out[0]['ok'] is True, '名单内应正常派发 ✓'


def test_unset_peers_keeps_old_behaviour(tmp_path):
    log, c, calls = _mk(tmp_path, None)
    _send(log, 'm1', 'whoever', '状态', 1)
    out = c.poll_once()
    assert calls and out[0]['ok'] is True, '⭐ 未配置时必须与从前一致 ✓'


# ── 4. ⭐ 口径：identity **不涉密码/token**（零新增凭证 ✓）──────────────
def test_identity_uses_no_credentials():
    with io.open(os.path.join(ROOT, 'rt_remote.py'), encoding='utf-8') as fh:
        src = fh.read()
    seg = src[src.index('def sender_allowed'):src.index('def _audit_write')]
    # ⚠️ 先剔除 docstring —— 里面**以禁止形式提到了** password/token ✗
    #    （上一批刚踩过同一坑：拿源码字串查敏感词 → 自己的文档把自己判红 ✓）
    body = seg.split('"""', 2)[-1] if seg.count('"""') >= 2 else seg
    for bad in ('password', 'passwd', 'token', 'secret', 'hashlib', 'hmac', 'bcrypt'):
        assert bad not in body.lower(), '⛔ identity 判定体不得引入凭证类机制 ✗：%s' % bad
    # 且构造点确实从配置读白名单 ✓（未配置 → None → 放行 ✓）
    assert "cfg.get('remote_allowed_peers')" in src
