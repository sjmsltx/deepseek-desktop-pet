# -*- coding: utf-8 -*-
"""M1 消息内核（`relay_log.py`）**反向 / 鲁棒用例**（H 组 8 条）—— 微信侧出题。

口径（冻结版 v2 收窄后）：
  46→49 合并：**写层拒同 id（告警）** / **投递层幂等**，一层一件事
  47 乱序：限定“外部导入/合并日志”场景；**排序键用 `seq` 不用 `ts`**
  48 并发：收窄到**进程内**（单写者 + 队列；不做跨进程文件锁）
  50 超长：单条 **64 KB 超限拒绝**（`RelayTooLarge`），**不静默截断**
  51 时钟回拨：单调性由 `seq` 保证（`ts` 只作展示）
  52 日志被截断：启动校验“末行可解析 + 行数不减少”，异常告警
  53 盘写失败：**硬失败**（`RelayWriteError` → 上层停 + @人类）

约定：`relay_log.py` 未落地时本文件自动 skip。
"""
import json
import threading

import pytest

relay = pytest.importorskip('relay_log', reason='relay_log.py 尚未实现（反向用例已就位，落地即生效）')

LIMITS = dict(max_turns=8, time_limit_ms=300_000, max_tokens=0, max_cost_micro=0,
              retry_max=2, converge_no_new=2, msg_max_bytes=65536, interrupt_notice_ms=60_000)


class Clock:
    def __init__(self, start=1_700_000_000_000):
        self.now = start

    def __call__(self):
        return self.now

    def tick(self, ms):
        self.now += ms


@pytest.fixture
def log(tmp_path):
    return relay.RelayLog(tmp_path / 'r.jsonl', clock=Clock(), limits=dict(LIMITS),
                          provider=lambda m, i: relay.ProviderReply(body='ok'))


def mk(nid, body='x', **kw):
    base = dict(id=nid, seq=0, ts=0, channel='dm:human<->agent', sender='human:me',
                recipients=['agent:a'], kind='speak', visibility='human', body=body, meta={'v': 1})
    base.update(kw)
    return relay.Msg(**base)


# ---------------------------------------------------------------- 49（含 46）id 冲突与幂等

def test_h1_duplicate_id_rejected_by_writer(log):
    log.append(mk('dup'))
    with pytest.raises(getattr(relay, 'RelayDuplicateId')):
        log.append(mk('dup', body='second'))


def test_h2_duplicate_leaves_original_intact(log):
    log.append(mk('dup', body='first'))
    with pytest.raises(Exception):
        log.append(mk('dup', body='second'))
    got = [m for m in log.replay() if m.id == 'dup']
    assert len(got) == 1 and got[0].body == 'first'
    assert log.snapshot()['warnings']


def test_h3_deliver_is_idempotent_second_call_false(log):
    m = log.append(mk('d1'))
    log.deliver(m)
    assert log.deliver(m) is False
    assert len([x for x in log.inbox('agent:a') if x.id == 'd1']) == 1


# ---------------------------------------------------------------- 47 乱序（外部导入场景）

def test_h4_out_of_order_import_sorted_by_seq(log, tmp_path):
    """乱序只可能来自外部导入/合并日志 → 重放必须按 seq 排序（不看 ts）"""
    rows = [dict(id=f'm{i}', seq=i, ts=10 ** 9 - i * 1000, channel='dm:human<->agent',
                 sender='human:me', recipients=['agent:a'], kind='speak',
                 visibility='human', body=f'b{i}', meta={'v': 1}) for i in range(1, 4)]
    with open(tmp_path / 'r.jsonl', 'a', encoding='utf-8') as f:
        for r in reversed(rows):                    # 故意倒序写入
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    got = [m.seq for m in log.replay()]
    assert got == sorted(got) == [1, 2, 3]


def test_h5_seq_beats_ts_for_ordering(log, tmp_path):
    rows = [dict(id='a', seq=1, ts=2_000, **{}), dict(id='b', seq=2, ts=1_000, **{})]
    with open(tmp_path / 'r.jsonl', 'a', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(dict(r, channel='dm:human<->agent', sender='human:me',
                                    recipients=['agent:a'], kind='speak', visibility='human',
                                    body='x', meta={'v': 1}), ensure_ascii=False) + '\n')
    assert [m.id for m in log.replay()] == ['a', 'b']


# ---------------------------------------------------------------- 48 并发（进程内）

def test_h6_concurrent_inprocess_writes_no_loss(log):
    """单写者 + 队列：并发投递 → 顺序落盘、不丢不截断"""
    errs = []

    def worker(k):
        try:
            for j in range(10):
                log.append(mk(f'w{k}-{j}'))
        except Exception as e:                       # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    ids = [m.id for m in log.replay()]
    assert len(ids) == 40 and len(set(ids)) == 40
    seqs = [m.seq for m in log.replay()]
    assert seqs == sorted(seqs)


# ---------------------------------------------------------------- 50 超长

def test_h7_oversize_rejected_not_truncated(tmp_path):
    lg = relay.RelayLog(tmp_path / 'big.jsonl', clock=Clock(), limits=dict(LIMITS),
                        provider=lambda m, i: relay.ProviderReply(body='ok'))
    big = 'A' * (LIMITS['msg_max_bytes'] + 1)
    with pytest.raises(getattr(relay, 'RelayTooLarge')):
        lg.append(mk('big', body=big))
    assert lg.replay() == []                        # 不静默截断、不写半条


# ---------------------------------------------------------------- 51/52/53

def test_h8_clock_rollback_keeps_seq_monotonic(log):
    a = log.append(mk('m1', ts=999_999))
    b = log.append(mk('m2', ts=1))
    assert b.seq == a.seq + 1


def test_h9_truncated_log_detected(log, tmp_path):
    """末行不可解析 + 行数减少 → 必须告警（不做复杂校验）"""
    log.append(mk('m1'))
    log.append(mk('m2'))
    src = (tmp_path / 'r.jsonl').read_text(encoding='utf-8')
    (tmp_path / 'r.jsonl').write_text(src[:len(src) // 2], encoding='utf-8')   # 截断
    lg2 = relay.RelayLog(tmp_path / 'r.jsonl', clock=Clock(), limits=dict(LIMITS),
                         provider=lambda m, i: relay.ProviderReply(body='ok'))
    _ = lg2.replay()
    assert lg2.snapshot()['warnings']


def test_h10_disk_write_failure_is_hard_fail(log, monkeypatch):
    real_open = open

    def boom(*a, **kw):
        raise OSError('disk full')

    monkeypatch.setattr('builtins.open', boom)
    with pytest.raises(getattr(relay, 'RelayWriteError')):
        log.append(mk('m-x'))
    monkeypatch.setattr('builtins.open', real_open)
