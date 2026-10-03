# -*- coding: utf-8 -*-
"""条款 IV（写回协议）护栏：待办／结果文件格式 ＋ 运行器行为 ＋ **七条硬约束** ✓。

口径：⭐ 本批只做"**读半 ＋ 文件格式**"（不依赖端点 ✓）；
      端点 `POST /api/pending` 与 `GET /api/assets` 属**下一批** ✓（本文件不测它们 ✓）。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'collab')):
    if p not in sys.path:
        sys.path.insert(0, p)

import pending_ops  # noqa: E402
import run_pending  # noqa: E402


def _base(tmp_path):
    return str(tmp_path)


def _pend(base):
    return os.path.join(base, 'collab', 'pending')


# ── 1. ⭐ E1① 类型枚举：枚举外一律拒 ✗ ───────────────────────────────
@pytest.mark.parametrize('t', ['shell', 'exec', 'run_script', '', 'PROJECT_EDIT'])
def test_type_enum_rejects_everything_else(t, tmp_path):
    ok, why = pending_ops.validate_request({'type': t, 'op_id': 'abcd1234', 'payload': {}})
    assert ok is False and '枚举' in why


# ── 2. ⭐ E1③ 载荷拒路径（绝对路径 ＋ `..`）──────────────────────────
@pytest.mark.parametrize('pl', [
    {'root': 'C:/Windows'},
    {'root': '/etc/passwd'},
    {'outputs': '../../outside'},
    {'memory': 'a/../../b.md'},
])
def test_payload_paths_are_rejected(pl):
    ok, why = pending_ops.validate_request({'type': 'project_edit', 'op_id': 'abcd1234', 'payload': pl})
    assert ok is False and ('路径' in why or '..' in why)


# ── 3. ⭐ E2：requested_by 不含凭证 ✗ ────────────────────────────────
def test_requested_by_must_not_carry_credentials():
    ok, why = pending_ops.validate_request({'type': 'asset_op', 'op_id': 'abcd1234',
                                            'payload': {}, 'requested_by': 'sk-abcdefghijklm'})
    assert ok is False and 'peer id' in why


# ── 4. ⭐ E1② 只写待办目录（文件名形状固定 ✓ 不带任意落点 ✗）──────────
def test_write_only_into_pending_dir(tmp_path):
    base = _base(tmp_path)
    p = pending_ops.write_pending({'type': 'project_edit', 'op_id': 'abcd1234',
                                   'payload': {'name': '桌宠 3.0'}}, base_dir=_pend(base))
    assert os.path.dirname(p) == _pend(base), '⭐ 必须落在 collab/pending/ 内 ✓'
    assert pending_ops.parse_pending_name(os.path.basename(p)) is not None, '文件名形状须符合 E2 ✓'


# ── 5. ⭐ 幂等：同 op_id 重复消费 → 结果一致且不再二次执行 ────────────
def test_idempotent_by_op_id(tmp_path):
    base = _base(tmp_path)
    pending_ops.write_pending({'type': 'project_edit', 'op_id': 'idem0001',
                               'payload': {'name': 'A'}}, base_dir=_pend(base))
    r1 = run_pending.run(base)
    assert r1['ok'] == 1 and r1['failed'] == 0
    proj = os.path.join(base, 'rt', 'project.json')
    assert os.path.isfile(proj) and json.load(open(proj, encoding='utf-8'))['name'] == 'A'
    r2 = run_pending.run(base)                       # 第二次：应被幂等跳过 ✓
    assert r2['skipped_done'] == 1 and r2['ok'] == 0
    assert [x['op_id'] for x in pending_ops.read_results(_pend(base))] == ['idem0001']


# ── 6. ⭐ E1⑥ 失败必落结果（未知类型 / 未实现类型 / 空名 三种）────────
@pytest.mark.parametrize('req,why_kw', [
    ({'type': 'asset_op', 'op_id': 'fail0001', 'payload': {}}, '未实现'),
    ({'type': 'project_edit', 'op_id': 'fail0002', 'payload': {'name': ''}}, '不能为空'),
    ({'type': 'project_edit', 'op_id': 'fail0003', 'payload': {'name': 'x' * 81}}, '超过'),
])
def test_failures_are_recorded_not_silent(tmp_path, req, why_kw):
    base = _base(tmp_path)
    pending_ops.write_pending(req, base_dir=_pend(base))
    st = run_pending.run(base)
    rows = pending_ops.read_results(_pend(base))
    assert st['failed'] == 1 and rows and rows[0]['ok'] is False, '⭐ 失败必须落结果 ✗'
    assert why_kw in (rows[0]['reason'] + rows[0]['detail'])


# ── 7. ⭐ E2 结果**只追加**（不改旧行 ✓）────────────────────────────
def test_results_are_append_only(tmp_path):
    d = _pend(_base(tmp_path))
    pending_ops.append_result('a0001', True, base_dir=d)
    first = open(pending_ops.results_path(d), encoding='utf-8').read()
    pending_ops.append_result('a0002', False, reason='x', base_dir=d)
    after = open(pending_ops.results_path(d), encoding='utf-8').read()
    assert after.startswith(first), '⭐ 新结果只能追加、不得改写旧行 ✗'
    assert len([l for l in after.splitlines() if l.strip()]) == 2


# ── 8. ⭐ 反向护栏：运行器**不得**自动跑（不注册服务 / 不轮询）✗ ──────
def test_runner_is_human_triggered_only():
    with open(os.path.join(ROOT, 'collab', 'run_pending.py'), encoding='utf-8') as fh:
        src = fh.read()
    for bad in ('serve_forever', 'ThreadingHTTPServer', 'while True', 'schedule', 'time.sleep'):
        assert bad not in src, '⛔ 运行器不得自我驱动 ✗：%s' % bad
    assert 'argparse' in src and '__main__' in src, '运行器必须是显式 CLI ✓'


# ── 9. ⭐ 幂等键形状 ＋ 待办名可解析（E2 ✓）──────────────────────────
def test_op_id_and_name_shape():
    oid = pending_ops.op_id_new()
    assert pending_ops.validate_request({'type': 'asset_op', 'op_id': oid, 'payload': {}})[0] is True
    assert pending_ops.parse_pending_name('20261003-231500-project_edit-%s.json' % oid) is not None
    assert pending_ops.parse_pending_name('badname.json') is None
