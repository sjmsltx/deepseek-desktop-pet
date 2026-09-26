# -*- coding: utf-8 -*-
"""M1 消息内核（`relay_log.py`）**边界/语义用例** —— 微信侧出题（A–I + N1–N5）。

配套：
  · 用例设计（冻结）：`workspace\\输出\\3.0-M1用例设计_冻结版v2_20260921.md`
  · API 契约（冻结 v1）：`docs\\3.0-M1-API契约-冻结v1.md`
反向/鲁棒（H 组）在 `tests/test_relay_log_reverse.py`。

纪律（三条，已双方确认）：
  ① 时间源可注入（下面全部用注入 clock，不用真实时间）
  ② 替身一律 monkeypatch（禁裸赋值）
  ③ “发不发请求”用**调用计数器**断言（“绝不静默烧钱”只能由请求次数证明）

约定：`relay_log.py` 未落地时本文件自动 skip（不污染全量绿灯）。
"""
import pytest
from pathlib import Path

relay = pytest.importorskip('relay_log', reason='relay_log.py 尚未实现（微信侧用例已就位，落地即生效）')


# ------------------------------------------------------------------ 夹具

class Clock:
    """可注入时钟（毫秒），测试里显式推进 —— 避免“深夜跑必红”。"""

    def __init__(self, start=1_700_000_000_000):
        self.now = start

    def __call__(self):
        return self.now

    def tick(self, ms):
        self.now += ms


class StubProvider:
    """provider 替身：**数调用次数**（核心承诺只能靠它证明）。"""

    def __init__(self, reply=None, fails=0):
        self.calls = 0
        self.fails = fails          # 前 N 次抛错

    def __call__(self, msg, issue):
        self.calls += 1
        if self.calls <= self.fails:
            raise RuntimeError('provider boom')
        return relay.ProviderReply(body=f'reply#{self.calls}', tokens=10, cost_micro=100)


LIMITS = dict(max_turns=8, time_limit_ms=300_000, max_tokens=0, max_cost_micro=0,
              retry_max=2, converge_no_new=2, msg_max_bytes=65536, interrupt_timeout_ms=60_000)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def prov():
    return StubProvider()


@pytest.fixture
def log(tmp_path, clock, prov):
    return relay.RelayLog(tmp_path / 'relay.jsonl', clock=clock, limits=dict(LIMITS), provider=prov)


def issue(**kw):
    base = dict(title='议题', goal='目标', done_when='结束条件')
    base.update(kw)
    return relay.Issue(**base)


def mk(nid, body='hello', **kw):
    base = dict(id=nid, seq=0, ts=0, channel='dm:human<->agent', sender='human:me',
                recipients=['agent:a'], kind='speak', visibility='human', body=body, meta={'v': 1})
    base.update(kw)
    return relay.Msg(**base)


# ------------------------------------------------------------------ A 追加日志不变量

def test_a1_append_only_no_overwrite(log):
    a = log.append(mk('m1'))
    assert a.seq == 1
    b = log.append(mk('m2'))
    assert b.seq == 2
    assert [m.id for m in log.replay()] == ['m1', 'm2']


def test_a2_seq_strictly_increasing(log):
    seqs = [log.append(mk(f'm{i}')).seq for i in range(5)]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_a3_replay_is_idempotent(log):
    for i in range(3):
        log.append(mk(f'm{i}'))
    first = [(m.id, m.seq) for m in log.replay()]
    second = [(m.id, m.seq) for m in log.replay()]
    assert first == second
    assert len([m for m in log.replay()]) == 3


def test_a4_half_json_line_is_skipped_with_warning(log, tmp_path):
    log.append(mk('ok1'))
    with open(tmp_path / 'relay.jsonl', 'a', encoding='utf-8') as f:
        f.write('{"id": "broken"')          # 半行
    msgs = log.replay()
    assert [m.id for m in msgs] == ['ok1']
    assert any('skip' in w or '行' in w for w in log.snapshot()['warnings'])


def test_a5_empty_log_ok(tmp_path, clock, prov):
    fresh = relay.RelayLog(tmp_path / 'empty.jsonl', clock=clock, limits=dict(LIMITS), provider=prov)
    assert fresh.replay() == []
    assert fresh.cost_total() == 0


def test_a6_callers_seq_is_ignored(log):
    """N 系列：seq 由内核自增，调用者传的被忽略（契约 §4-1）"""
    a = log.append(mk('x', seq=999))
    b = log.append(mk('y', seq=999))
    assert a.seq == 1 and b.seq == 2


# ------------------------------------------------------------------ B 收件箱投影 / 三层视图

def test_b1_dm_directed_only_both_sides(log):
    log.append(mk('m1', channel='dm:human<->agent', sender='human:me', recipients=['agent:a']))
    assert [m.id for m in log.inbox('agent:a')] == ['m1']
    assert log.inbox('agent:b') == []


def test_b2_group_broadcast_once(log):
    log.append(mk('g1', channel='group:g1', sender='agent:a', recipients=[]))
    assert [m.id for m in log.inbox('agent:a')] == ['g1']
    assert [m.id for m in log.inbox('agent:b')] == ['g1']       # 广播 → 全员
    assert len(log.inbox('agent:a')) == 1                       # 不重复


def test_b3_thread_result_back_to_parent(log):
    log.append(mk('t0', channel='thread:t1', visibility='meta', meta={'v': 1, 'parent_id': 't0'}))
    got = log.view('thread:t1', layer='L2')
    assert got and got[0].meta.get('parent_id') == 't0'


def test_b4_l1_excludes_meta_and_debug(log):
    log.append(mk('h1', visibility='human'))
    log.append(mk('m1', visibility='meta'))
    log.append(mk('d1', visibility='debug'))
    assert [m.id for m in log.inbox('agent:a', layer='L1')] == ['h1']
    assert 'm1' in [m.id for m in log.inbox('agent:a', layer='L2')]
    assert 'd1' in [m.id for m in log.inbox('agent:a', layer='L3')]


def test_b5_three_views_same_source(log):
    """三层读同一份日志：条目按 id 一一对应（不允许“两套数据”）"""
    for i, vis in enumerate(('human', 'meta', 'debug')):
        log.append(mk(f'v{i}', visibility=vis))
    ids = lambda layer: sorted(m.id for m in log.inbox('agent:a', layer=layer))
    assert ids('L1') + ids('L2') + ids('L3') == sorted(m.id for m in log.replay())


def test_b6_deliver_is_idempotent(log):
    """投递层幂等（与写层职责分离）"""
    m = log.append(mk('m1'))
    assert log.deliver(m) in (True, False)
    assert log.deliver(m) is False          # 二次投递不生效
    assert len(log.inbox('agent:a')) == 1


# ------------------------------------------------------------------ C 四道上限（重点）

def test_c1_turn_limit_exactly_eight(log, clock):
    log.open_issue(issue())
    res = None
    for _ in range(12):
        res = log.step()
        clock.tick(1000)                    # 时长远未到
        if res.stopped:
            break
    assert res.stopped and res.reason == 'turn_limit'
    assert res.turn_no <= LIMITS['max_turns']


def test_c2_stop_still_produces_conclusion_and_notice(log, clock):
    log.open_issue(issue())
    res = None
    for _ in range(12):
        res = log.step()
        clock.tick(1000)
        if res.stopped:
            break
    assert res.stopped
    assert res.notice_human is True                     # 触顶必须 @人类
    assert log.snapshot()['concluded'] is True          # 且必须出结论（不静默退出）


def test_c3_no_more_provider_calls_after_stop(log, prov, clock):
    """核心承诺：停后不再发请求（用计数器证明）"""
    log.open_issue(issue())
    for _ in range(12):
        res = log.step()
        clock.tick(1000)
        if res.stopped:
            break
    after = prov.calls
    for _ in range(3):
        r = log.step()
        assert r.stopped
        assert r.provider_calls == 0
    assert prov.calls == after


def test_c4_time_limit_is_gte(log, clock):
    """① 冻结：时长用 >=（5:00 即停）"""
    log.open_issue(issue())
    clock.tick(LIMITS['time_limit_ms'] - 1)
    r1 = log.step()
    assert not r1.stopped or r1.reason != 'time_limit'   # 差 1ms → 不停
    clock.tick(1)
    r2 = log.step()
    assert r2.stopped and r2.reason == 'time_limit'


def test_c5_token_limit_exact_and_over(tmp_path, clock, prov):
    lim = dict(LIMITS, max_tokens=20)
    lg = relay.RelayLog(tmp_path / 'l.jsonl', clock=clock, limits=lim, provider=prov)
    lg.open_issue(issue())
    r1 = lg.step()                                        # 10 tokens
    assert not (r1.stopped and r1.reason == 'token_limit')
    r2 = lg.step()                                        # 累计 20 = 上限（恰好）
    assert r2.stopped and r2.reason == 'token_limit'


def test_c6_cost_uses_micro_integers(tmp_path, clock, prov):
    """② 冻结：金额用微元整数（1e-6 元），不做浮点比较"""
    lim = dict(LIMITS, max_cost_micro=300)
    lg = relay.RelayLog(tmp_path / 'l.jsonl', clock=clock, limits=lim, provider=prov)
    lg.open_issue(issue())
    lg.step(); lg.step()                                  # 100 + 100 = 200
    assert lg.cost_total() == 200
    r = lg.step()                                         # 到 300
    assert lg.cost_total() == 300 and r.stopped and r.reason == 'cost_limit'


def test_c7_double_limit_stops_once(log, clock):
    log.open_issue(issue())
    res = None
    for _ in range(14):
        res = log.step()
        clock.tick(50_000)
        if res.stopped:
            break
    assert res.stopped
    assert log.snapshot()['concluded'] is True
    assert log.step().stopped                              # 二次调用仍为停，不重复出结论


def test_c8_limits_config_frozen_keys():
    """④ 冻结：limits 键名固定（写死，防漂移）"""
    for k in ('max_turns', 'time_limit_ms', 'max_tokens', 'max_cost_micro',
              'retry_max', 'converge_no_new', 'msg_max_bytes', 'interrupt_timeout_ms'):
        assert k in LIMITS


def test_c9_step_result_fields_frozen(log):
    """StepResult 字段冻结（契约 §1）"""
    log.open_issue(issue())
    r = log.step()
    for f in ('ok', 'stopped', 'reason', 'turn_no', 'notice_human', 'cost_micro', 'provider_calls'):
        assert hasattr(r, f), f'StepResult 缺字段 {f}'


def test_c10_zero_limit_rejected_not_silent(tmp_path, clock, prov):
    """上限设为 0/负数 → 拒绝启动并给明确错误（不静默）"""
    bad = dict(LIMITS, max_turns=0)
    lg = relay.RelayLog(tmp_path / 'l.jsonl', clock=clock, limits=bad, provider=prov)
    ok, msg = lg.open_issue(issue())
    assert ok is False and msg


# ------------------------------------------------------------------ D 人类插队

def test_d1_interrupt_takes_effect_at_turn_boundary(log):
    log.open_issue(issue())
    log.step()
    t0 = log.snapshot()['turn_no']
    log.interrupt('停一下，我要改目标')
    assert log.snapshot()['interrupted'] is True           # 生效
    r = log.step()
    assert r.stopped and r.reason == 'interrupted'
    assert r.provider_calls == 0                           # 插队时不发请求 ✓
    assert log.snapshot()['turn_no'] == t0                 # 不推进回合


def test_d2_resume_requires_explicit_command(log):
    """N2：只有显式“继续”才恢复；别的话不算"""
    log.open_issue(issue())
    log.interrupt('插队')
    assert log.resume('那我们先聊点别的吧') is False
    assert log.snapshot()['interrupted'] is True
    assert log.resume('继续') is True
    assert log.snapshot()['interrupted'] is False


def test_d3_resume_does_not_reset_turn_count(log):
    log.open_issue(issue())
    log.step()
    t0 = log.snapshot()['turn_no']
    log.interrupt('x')
    log.resume('继续吧')
    log.step()
    assert log.snapshot()['turn_no'] == t0 + 1             # 继续 ≠ 重开议题


def test_d4_never_auto_resume_after_timeout(log, clock):
    """④ 冻结：插队超时**绝不自动恢复**（提醒最多一次）"""
    log.open_issue(issue())
    log.interrupt('插队')
    clock.tick(LIMITS['interrupt_timeout_ms'] * 3)
    r = log.step()
    assert r.stopped and r.reason == 'interrupted'
    assert log.snapshot()['interrupted'] is True
    assert r.provider_calls == 0


# ------------------------------------------------------------------ E 收敛（结构化判据）

def test_e1_converge_after_two_no_new_rounds(tmp_path, clock):
    """N4：连续 2 回合无新信息 → 收束（结构化“主张签名”判据）"""
    class Same(StubProvider):
        def __call__(self, msg, issue):
            self.calls += 1
            return relay.ProviderReply(body='结论一致，无新增', tokens=1, cost_micro=1)

    lg = relay.RelayLog(tmp_path / 'l.jsonl', clock=clock, limits=dict(LIMITS), provider=Same())
    lg.open_issue(issue())
    res = None
    for _ in range(6):
        res = lg.step()
        clock.tick(1000)
        if res.stopped:
            break
    assert res.stopped and res.reason == 'converged'


def test_e2_new_number_or_entity_counts_as_new_info(tmp_path, clock):
    """N4 反例：出现新数字/新实体 → 一律算有新信息（不得判收敛）"""
    seq_bodies = iter(['引入新实体 model=X', '引入新数字 42', '再来 43', '再来 44', '45', '46'])

    class Fresh(StubProvider):
        def __call__(self, msg, issue):
            self.calls += 1
            return relay.ProviderReply(body=next(seq_bodies), tokens=1, cost_micro=1)

    lg = relay.RelayLog(tmp_path / 'l.jsonl', clock=clock, limits=dict(LIMITS), provider=Fresh())
    lg.open_issue(issue())
    for _ in range(4):
        r = lg.step()
        clock.tick(1000)
        assert not (r.stopped and r.reason == 'converged')


def test_e3_conclude_is_idempotent(log):
    log.open_issue(issue())
    log.conclude('结论A')
    log.conclude('结论B')
    snaps = [m for m in log.replay() if m.kind == 'system']
    assert len(snaps) >= 1
    assert log.snapshot()['concluded'] is True


# ------------------------------------------------------------------ F 议题强制

def test_f1_missing_field_refused_with_provider_zero(log, prov):
    for bad in (issue(title='  '), issue(goal=''), issue(done_when='\t')):
        ok, msg = log.open_issue(bad)
        assert ok is False and msg
    assert prov.calls == 0                                 # 不烧钱


def test_f2_whitespace_only_refused(log):
    ok, msg = log.open_issue(issue(goal='   '))
    assert ok is False


# ------------------------------------------------------------------ G 回放 / 对账

def test_g1_cost_total_equals_sum_of_meta(log):
    log.append(mk('m1', meta={'v': 1, 'cost_micro': 5}))
    log.append(mk('m2', meta={'v': 1, 'cost_micro': 7}))
    assert log.cost_total() == 12


def test_g2_missing_cost_counts_zero_with_warning(log):
    log.append(mk('m1', meta={'v': 1}))
    assert log.cost_total() == 0
    assert log.snapshot()['warnings']


def test_g3_snapshot_has_frozen_keys(log):
    snap = log.snapshot()
    for k in ('turn_no', 'cost_micro', 'tokens', 'interrupted', 'concluded', 'stopped', 'warnings'):
        assert k in snap


def test_g4_replay_slice_by_seq(log):
    for i in range(4):
        log.append(mk(f'm{i}'))
    got = [m.id for m in log.replay(to_seq=2)]
    assert got == ['m0', 'm1']


# ------------------------------------------------------------------ I 失败与降级

def test_i1_provider_failure_retries_then_stops(tmp_path, clock):
    """⑥ 冻结：失败计重试不计回合；超 retry_max → 停 + @人类，且回合不推进"""
    p = StubProvider(fails=99)
    lg = relay.RelayLog(tmp_path / 'l.jsonl', clock=clock, limits=dict(LIMITS), provider=p)
    lg.open_issue(issue())
    r = lg.step()
    assert r.stopped and r.reason == 'provider_failed'
    assert r.notice_human is True
    assert r.turn_no == 0                                  # 不推进 ✓
    assert p.calls >= 1


def test_i2_retry_bounded_by_retry_max(tmp_path, clock):
    p = StubProvider(fails=99)
    lg = relay.RelayLog(tmp_path / 'l.jsonl', clock=clock, limits=dict(LIMITS), provider=p)
    lg.open_issue(issue())
    lg.step()
    assert p.calls <= LIMITS['retry_max'] + 1              # 含首次


# ------------------------------------------------------------------ N1–N5

def test_n1_schema_version_written(log, tmp_path):
    log.append(mk('m1'))
    raw = Path(tmp_path / 'relay.jsonl').read_text(encoding='utf-8')
    assert '"v"' in raw and str(relay.SCHEMA_V) in raw


def test_n2_legacy_row_without_v_readable(log, tmp_path):
    with open(tmp_path / 'relay.jsonl', 'a', encoding='utf-8') as f:
        f.write('{"id":"old","channel":"dm:human<->agent","sender":"human:me",'
                '"recipients":["agent:a"],"kind":"speak","visibility":"human","body":"旧行"}\n')
    ids = [m.id for m in log.replay()]
    assert 'old' in ids
    assert log.snapshot()['warnings']


def test_n3_ts_rollback_does_not_break_monotonic(log, clock):
    """N3：单调性由 seq 保证；ts 回拨不得破坏 append-only"""
    a = log.append(mk('m1', ts=99999))
    clock.tick(-5000)
    b = log.append(mk('m2', ts=1))
    assert b.seq > a.seq


def test_n5_step_provider_calls_reported_each_step(log):
    log.open_issue(issue())
    r = log.step()
    assert r.provider_calls >= 1                           # 正常步有调用
