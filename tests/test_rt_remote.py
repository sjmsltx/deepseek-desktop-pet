# -*- coding: utf-8 -*-
"""B-乙 v1 护栏：`rt_remote`（遥控消费器）—— 逐条对齐**冻结稿** 24 条 + §4 边界

冻结稿：`B乙-v1-用例设计-冻结版v1-20260926.md`（微信侧 ✓ Owner 18:44/18:48 批 ✓）
A 只读 6 · B 投递 5 · C 消费器 6 · D 守卫 7 ＋ §4 边界/反向
"""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / 'rt_remote.py'


# ── 测试夹具（⭐ 审计/通道/日志一律走 tmp ✓ 不污染真审计与真日志 ✗）──────
class Audit:
    """审计收集器 ✓ —— ⭐ 兼容**两种调用形状**：
    `audit(dict)`（`rt_view`/`rt_action` 风格 ✓）与 `audit(kind, actor, action, detail, …)`（`governance.log_event` 风格 ✓）
    """

    def __init__(self):
        self.rows = []

    def __call__(self, *a, **k):
        if len(a) == 1 and isinstance(a[0], dict):          # dict 形状 ✓
            rec = dict(a[0])
            self.rows.append({'kind': str(rec.get('kind') or rec.get('action') or ''),
                              'action': str(rec.get('action') or rec.get('kind') or ''), 'rec': rec})
        else:                                              # 位置参数形状 ✓
            self.rows.append({'kind': str(a[0] if a else ''),
                              'action': str(a[2] if len(a) > 2 else ''), 'rec': {'args': a}})
        return True

    def kinds(self):
        return [r['kind'] for r in self.rows]

    def actions(self):
        return [r['action'] for r in self.rows]


def _store(tmp_path):
    import rt_store
    return rt_store.Store(str(tmp_path / 'rt'))


def _relay(tmp_path, transport=None):
    import rt_relay
    return rt_relay.Relay(str(tmp_path / 'relay'), transport=transport)


def _gate(tmp_path, store):
    import rt_action
    import rt_relay
    return rt_action.make_gate(store=store, base_dir=str(tmp_path / 'gate'),
                               relay=rt_relay.Relay(str(tmp_path / 'relay2')))


def _seed(store, role='flash', n=3, day=None):
    """造 n 轮 L0+L1 ✓"""
    ptrs = []
    for i in range(1, n + 1):
        p = store.append(role, 'chat', '第%d轮正文%s' % (i, '甲' * 10), round_id='r-%03d' % i, turn_no=i)
        store.add_summary(p, '@%s 第%d轮摘要。' % (role, i), round_id='r-%03d' % i, turn_no=i, kind='chat')
        ptrs.append(p)
    return ptrs


def _rlog(tmp_path, name='relay.jsonl'):
    import relay_log
    return relay_log.RelayLog(str(tmp_path / name))


def _send(log, body, *, mid, seq=None, sender='phone', to='owner'):
    """向通道投一条**指令消息** ✓（L1 = visibility 'human' ✓ recipients=[owner] ✓）"""
    import relay_log
    if seq is None:
        seq = (log.snapshot()['seq'] + 1)
    return log.deliver(relay_log.Msg(id=mid, seq=seq, ts=0, channel='ch', sender=sender,
                                     recipients=[to], kind='speak', visibility='human', body=body))


def _disp(cmd_text, **kw):
    import rt_remote
    return rt_remote.dispatch(rt_remote.parse_command(cmd_text), **kw)


# ══════════ A 组 · 只读（6）══════════
def test_a1_status_summary(tmp_path):
    st = _store(tmp_path)
    _seed(st, 'flash', 3)
    out = _disp('状态', store=st, gate=_gate(tmp_path, st), audit=Audit(), budget={'used': 100})
    assert out['ok'] is True
    d = out['data']
    assert d['hall_count'] == 3 and 'budget' in d and 'pending' in d
    assert '大厅' in out['reply'] and '预算' in out['reply'] and '待确认' in out['reply']


def test_a2_hall_n(tmp_path):
    st = _store(tmp_path)
    _seed(st, 'flash', 4)
    out = _disp('大厅 3', store=st, audit=Audit())
    assert out['ok'] is True and len(out['data']) == 3
    assert all(('round_id' in c and 'ptr' in c) for c in out['data'])


def test_a3_hall_default_five(tmp_path):
    st = _store(tmp_path)
    _seed(st, 'flash', 7)
    out = _disp('大厅', store=st, audit=Audit())
    assert len(out['data']) == 5, '默认应为 5 条 ✓'


def test_a4_channel_view(tmp_path):
    out = _disp('通道 flash', audit=Audit())
    assert out['ok'] is True and 'trace_kept' in out['data']
    assert '通道' in out['reply']


def test_a5_read_original_same_role(tmp_path):
    st = _store(tmp_path)
    ptrs = _seed(st, 'flash', 1)
    role, day, seq = ptrs[0].split('|')
    out = _disp('原文 %s %s %s' % (role, day, seq), store=st, audit=Audit(), requester='flash')
    assert out['ok'] is True and out['data']['ok'] is True
    assert '正文' in str(out['data']['rec'].get('text'))


def test_a6_read_original_cross_role_denied_with_audit(tmp_path):
    """⭐ 跨角色默认拒 ✗ + **明报**（不返回空 ✗）+ 写审计 ✓"""
    st = _store(tmp_path)
    ptrs = _seed(st, 'nova', 1)
    role, day, seq = ptrs[0].split('|')
    au = Audit()
    out = _disp('原文 %s %s %s' % (role, day, seq), store=st, audit=au, requester='owner')
    assert out['ok'] is True and out['data']['ok'] is False and out['data']['denied'] is True
    assert '拒绝' in out['reply'] and '显式索取' in out['reply']
    assert 'cross_read_denied' in au.actions(), au.actions()


# ══════════ B 组 · 投递（5）══════════
def test_b7_deliver_first_sent(tmp_path):
    rl = _relay(tmp_path)
    out = _disp('投递 r-001|flash 你好', relay=rl, audit=Audit())
    assert out['ok'] is True and out['data']['state'] == 'sent' and out['data']['ok'] is True
    assert (Path(tmp_path) / 'relay' / 'outbox' / 'r-001' / 'flash.md').is_file()


def test_b8_deliver_duplicate_no_resend(tmp_path):
    calls = []

    def spy(round_id, role, content):
        calls.append(round_id)
        return True

    rl = _relay(tmp_path, transport=spy)
    a = _disp('投递 r-002|flash x', relay=rl, audit=Audit())
    b = _disp('deliver r-002|flash x', relay=rl, audit=Audit())
    assert a['data']['state'] == 'sent' and b['data']['state'] == 'duplicate'
    assert len(calls) == 1, '⭐ 幂等：不重发 ✗'


def test_b9_deliver_failed_reports_reason(tmp_path):
    def boom(*_a):
        raise RuntimeError('通道写失败')

    rl = _relay(tmp_path, transport=boom)
    out = _disp('投递 r-003|flash y', relay=rl, audit=Audit())
    assert out['data']['ok'] is False and out['data']['state'] == 'failed'
    assert '通道写失败' in out['data']['reason'], '⭐ 不静默 ✗'


def test_b10_receipts_readable_and_normalized(tmp_path):
    import rt_action
    rl = _relay(tmp_path)
    _disp('投递 r-004|flash z', relay=rl, audit=Audit())
    with io.open(rl.receipts_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'idem_key': 'r-004|flash', 'round_id': 'r-004', 'role': 'flash',
                            'state': 'failed', 'reason': '事后失败'}, ensure_ascii=False) + '\n')
    rows = rt_action.receipts_for_ui(relay=rl, round_id='r-004')
    assert len(rows) == 1 and rows[0]['state'] == 'failed', '⭐ 同 key 归一取最新 ✓'


def test_b11_budget_deny_audits_and_no_delivery(tmp_path):
    calls = []
    rl = _relay(tmp_path, transport=lambda *a: calls.append(1))
    au = Audit()
    out = _disp('投递 r-005|flash q', relay=rl, audit=au,
                budget=lambda est: (False, '超额：已达今日上限', 20.0))
    assert out['ok'] is True and out['data']['ok'] is False
    assert '额度拒绝' in out['reply']
    assert 'budget_deny' in au.actions(), au.actions()
    assert calls == [], '⭐ 额度拒绝 → **不投递** ✗'


# ══════════ C 组 · 消费器（6）══════════
def test_c12_consumes_new_message(tmp_path):
    import rt_remote
    log = _rlog(tmp_path)
    st = _store(tmp_path)
    _seed(st, 'flash', 2)
    got = []
    c = rt_remote.RemoteConsumer(log, store=st, audit=Audit(), state_path=str(tmp_path / 'st.json'),
                                 emit=got.append)
    _send(log, '状态', mid='m-1')
    res = c.poll_once()
    assert len(res) == 1 and res[0]['state'] == 'done' and got and got[0]['msg_id'] == 'm-1'


def test_c13_last_seq_only_forward(tmp_path):
    """⭐ `last_seq` **只前进** ✓（不倒退 ✗）—— 已消费消息不得被执行第二次 ✓"""
    import rt_remote
    log = _rlog(tmp_path)
    calls = []
    c = rt_remote.RemoteConsumer(log, dispatch_fn=lambda cmd, **kw: (calls.append(cmd),
                                                                   {'ok': True, 'reply': 'x'})[1],
                                 audit=Audit(), state_path=str(tmp_path / 'st.json'))
    _send(log, '状态', mid='m-1')
    c.poll_once()
    n1 = len(calls)
    assert n1 == 1 and c.last_seq >= 1
    c.poll_once()
    assert len(calls) == n1, '⭐ 已消费不重执行 ✓'
    high = c.last_seq
    c.last_seq = high + 10
    c.poll_once()
    assert c.last_seq >= high + 10, '⭐ last_seq 只前进 ✓'
    c._save_state()
    c2 = rt_remote.RemoteConsumer(log, audit=Audit(), state_path=str(tmp_path / 'st.json'))
    assert c2.last_seq >= high + 10, '⭐ 水位可持久化 ✓'


def test_c14_restart_does_not_reconsume(tmp_path):
    import rt_remote
    log = _rlog(tmp_path)
    st_path = str(tmp_path / 'st.json')
    c1 = rt_remote.RemoteConsumer(log, audit=Audit(), state_path=st_path)
    _send(log, '状态', mid='m-1', seq=1)
    assert len(c1.poll_once()) == 1
    c2 = rt_remote.RemoteConsumer(log, audit=Audit(), state_path=st_path)   # 重启 ✓
    assert c2.last_seq == 1 and c2.poll_once() == [], '⭐ 重启不重复消费 ✓'


def test_c15_same_id_executed_once(tmp_path):
    import rt_remote
    log = _rlog(tmp_path)
    calls = []

    def d(cmd, **kw):
        calls.append(cmd)
        return {'ok': True, 'reply': 'x', 'data': None}

    c = rt_remote.RemoteConsumer(log, dispatch_fn=d, audit=Audit(), state_path=str(tmp_path / 'st.json'))
    _send(log, '状态', mid='m-dup', seq=1)
    c.poll_once()
    _send(log, '状态', mid='m-dup', seq=1)      # 同 id 二次到达 ✓
    c.poll_once()
    assert len(calls) == 1, '⭐ 同 id 只执行一次 ✓'


def test_c16_failure_not_silent(tmp_path):
    import pet_log
    import rt_remote
    logfile = pet_log.set_log_file(tmp_path / 'pet.log')      # ⭐ S2 注入 ✓ 不碰真日志 ✓
    try:
        log = _rlog(tmp_path)

        def boom(cmd, **kw):
            raise RuntimeError('派发炸了')

        c = rt_remote.RemoteConsumer(log, dispatch_fn=boom, audit=Audit(),
                                     state_path=str(tmp_path / 'st.json'))
        _send(log, '状态', mid='m-1', seq=1)
        res = c.poll_once()
        assert res and res[0]['state'] == 'failed', '⭐ 回执标 failed ✓'
        assert '派发炸了' in res[0]['reply']
        txt = io.open(logfile, encoding='utf-8').read() if Path(logfile).is_file() else ''
        assert '未成功' in txt or '失败' in txt, '⭐ 不静默（pet_log 留痕）✗'
    finally:
        pet_log.reset()


def test_c17_interval_configurable(tmp_path):
    import rt_remote
    log = _rlog(tmp_path)
    d = rt_remote.RemoteConsumer(log).interval_ms
    assert d == rt_remote.DEFAULT_INTERVAL_MS == 2000, '默认建议 2000 ✓'
    assert rt_remote.RemoteConsumer(log, interval_ms=500).interval_ms == 500
    assert rt_remote.RemoteConsumer(log, interval_ms=1).interval_ms >= 200, '下限保护 ✓'


# ══════════ D 组 · 守卫/护栏（7）══════════
def test_d18_whitelist_reject_and_audit(tmp_path):
    au = Audit()
    out = _disp('瞎写一条', audit=au)
    assert out['ok'] is False and '未知命令' in out['reply']
    assert 'reject' in au.actions(), au.actions()


@pytest.mark.parametrize('txt', ['确认 d-20260926-0001', 'confirm x', '否决 x', 'reject x', 'approve x'])
def test_d19_confirm_reject_forever_forbidden(txt):
    import rt_remote
    cmd = rt_remote.parse_command(txt)
    assert cmd['ok'] is False and cmd['forbidden'] is True, cmd
    ok, why = rt_remote.is_allowed(cmd)
    assert ok is False and ('禁止' in why or '白名单' in why)


def test_d20_feed_rejected():
    import rt_remote
    cmd = rt_remote.parse_command('投喂 一块蛋糕')
    assert cmd['ok'] is False and cmd['forbidden'] is True
    assert rt_remote.is_allowed(cmd)[0] is False


def test_d21_step_disabled_by_default():
    import rt_remote
    for txt in ('step', '推一回合', '步进'):
        cmd = rt_remote.parse_command(txt)
        assert cmd['ok'] is False and cmd['forbidden'] is True, txt


def test_d22_no_network_ast():
    src = io.open(MOD, encoding='utf-8').read()
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods |= {a.name.split('.')[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split('.')[0])
    banned = {'urllib', 'requests', 'socket', 'http', 'subprocess', 'ftplib', 'telnetlib'}
    assert not (mods & banned), mods & banned


def test_d23_no_store_append_bypass():
    """⭐ 遥控路径**禁** `store.append` ✗（只许 `rt_view`/`rt_action` ✓）

    ⚠️ 用 **AST 查真码** ✓（不查文本 ✓）—— 否则会误伤自己注释里的字面词 ✗（此前踩过 ✗）
    """
    tree = ast.parse(io.open(MOD, encoding='utf-8').read())
    bad_calls = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute):                       # x.append / gate.confirm …
            base = getattr(f.value, 'id', '')
            if (base == 'store' and f.attr == 'append') or (base == 'gate' and f.attr in
                                                            ('confirm', 'reject', 'draft')):
                bad_calls.append('%s.%s' % (base, f.attr))
        elif isinstance(f, ast.Name) and f.id in ('confirm_draft', 'reject_draft', 'draft_for_human'):
            bad_calls.append(f.id)
    assert bad_calls == [], '⛔ 遥控路径不得直连产品动作 ✗：%s' % bad_calls
    # ⭐ 只许复用 rt_view / rt_action ✓
    src = io.open(MOD, encoding='utf-8').read()
    assert 'import rt_view' in src and 'import rt_action' in src


def test_d24_three_audit_categories(tmp_path):
    """⭐ 关键动作三类审计 ✓：遥控入口 ✓ 投递 ✓ 额度拒绝 ✓"""
    st = _store(tmp_path)
    _seed(st, 'flash', 1)
    au = Audit()
    _disp('状态', store=st, audit=au)                        # 遥控入口 ✓
    rl = _relay(tmp_path)
    _disp('投递 r-100|flash hi', relay=rl, audit=au)         # 投递 ✓
    _disp('投递 r-101|flash hi', relay=rl, audit=au,
          budget=lambda est: (False, '超额', 1.0))           # 额度拒绝 ✓
    acts = au.actions()
    assert '状态' in acts and '投递' in acts and 'budget_deny' in acts, acts
    # ⭐ 本模块自己的入口审计 kind 统一为 `remote` ✓（嵌套调用走 dict 形状 ✓ 各自带 action 名 ✓）
    assert 'remote' in [r['kind'] for r in au.rows], '遥控入口审计 kind 应为 remote ✓'


# ══════════ §4 边界 / 反向 ══════════
@pytest.mark.parametrize('txt', ['', '   ', '\n\t  ', None])
def test_s4_empty_or_blank(txt):
    import rt_remote
    cmd = rt_remote.parse_command(txt)
    assert cmd['ok'] is False and cmd['error']
    assert rt_remote.is_allowed(cmd)[0] is False


def test_s4_overlong():
    import rt_remote
    cmd = rt_remote.parse_command('状态' + '啊' * (rt_remote.MAX_TEXT + 5))
    assert cmd['ok'] is False and '过长' in cmd['error']


def test_s4_control_chars_and_emoji():
    import rt_remote
    assert rt_remote.parse_command('\x01状态\x02')['ok'] is True
    assert rt_remote.parse_command('状态 🙂')['ok'] is True


def test_s4_hall_clamped_to_20(tmp_path):
    st = _store(tmp_path)
    _seed(st, 'flash', 1)
    cmd = __import__('rt_remote').parse_command('大厅 999')
    assert cmd['args']['limit'] == 20, '⭐ 钳到上限 20 ✓'


def test_s4_channel_file_deleted_no_crash(tmp_path):
    """⭐ 通道文件被删/损坏 → 不崩 ✓ 记警 ✓ 后续可恢复 ✓"""
    import pet_log
    import rt_remote
    logfile = pet_log.set_log_file(tmp_path / 'pet.log')
    try:
        log = _rlog(tmp_path)

        class Boom:
            def inbox(self, *_a, **_k):
                raise RuntimeError('文件被删了')

        c = rt_remote.RemoteConsumer(Boom(), audit=Audit(), state_path=str(tmp_path / 'st.json'))
        assert c.poll_once() == [], '不崩 ✓'
        txt = io.open(logfile, encoding='utf-8').read()
        assert '读收件箱失败' in txt, '⭐ 记警 ✓'
    finally:
        pet_log.reset()


def test_s4_same_id_concurrent_once(tmp_path):
    import rt_remote
    log = _rlog(tmp_path)
    calls = []
    c = rt_remote.RemoteConsumer(log, dispatch_fn=lambda cmd, **kw: (calls.append(cmd),
                                                                   {'ok': True, 'reply': 'x'})[1],
                                 audit=Audit(), state_path=str(tmp_path / 'st.json'))
    _send(log, '状态', mid='m-c', seq=1)
    for _ in range(5):
        c.poll_once()
    assert len(calls) == 1, '⭐ 同 id 高并发只执行一次 ✓'
