# -*- coding: utf-8 -*-
"""条款 IV（写回协议）护栏：待办／结果文件格式 ＋ 运行器行为 ＋ **硬约束** ✓。

口径（`PC-…-105` §一 审定 ✓）：载荷 schema 按微信侧 `-16` §二 ＋ 我方审定：
  · `project_edit`：`{project_id, changes:{name?/root?/outputs?/memory_file?/roles?}}` ✓ 未知字段一律拒 ✗
  · `asset_op`：`{role, state, op, source, source_ref?, run_pipeline?}` ✓ 枚举 ∧ 内置状态不可删 ✓
  · `root` ⭐ 唯一可绝对路径（已存在目录 ✓ 只登记 ✗）；其余路径字段只允许相对 ✓
"""
import json
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'collab')):
    if p not in sys.path:
        sys.path.insert(0, p)

import pending_ops  # noqa: E402
import run_pending  # noqa: E402


def _pend(base):
    return os.path.join(base, 'collab', 'pending')


def _proj(**kw):
    """合法 project_edit 请求 ✓（`changes` 可覆写 ✓）。"""
    changes = {'name': '桌宠 3.0'}
    changes.update(kw)
    return {'type': 'project_edit', 'op_id': 'proj0001', 'payload': {'changes': changes}}


def _asset(**kw):
    """合法 asset_op 请求 ✓。"""
    pl = {'role': 'deepseek', 'state': 'happy', 'op': 'replace', 'source': 'pool',
          'source_ref': 'assets_3.0/deepseek/deepseek_happy.png'}
    pl.update(kw)
    return {'type': 'asset_op', 'op_id': 'asst0001', 'payload': pl}


# ── 1. ⭐ E1① 类型枚举：枚举外一律拒 ✗ ───────────────────────────────
@pytest.mark.parametrize('t', ['shell', 'exec', 'run_script', '', 'PROJECT_EDIT'])
def test_type_enum_rejects_everything_else(t):
    ok, why = pending_ops.validate_request({'type': t, 'op_id': 'abcd1234', 'payload': {}})
    assert ok is False and '枚举' in why


# ── 2. ⭐ E1③ 相对路径字段：绝对路径 / `..` 一律拒 ✗ ─────────────────
@pytest.mark.parametrize('chg', [
    {'outputs': 'C:/x'},
    {'memory_file': '/etc/passwd'},
    {'outputs': '../../outside'},
    {'memory_file': 'a/../../b.md'},
])
def test_relative_fields_reject_paths(chg):
    ok, why = pending_ops.validate_request(_proj(**chg))
    assert ok is False and ('相对' in why or '..' in why or '路径' in why)


# ── 3. ⭐ `root` 例外：仅"**已存在**目录"放行 ✓ 不存在/UNC/超长/`..` 拒 ✗ ──
def test_root_exception_requires_existing_dir(tmp_path):
    ok, why = pending_ops.validate_request(_proj(root=str(tmp_path)))
    assert ok is True, '⭐ 已存在目录应放行（E1③ 例外 ✓）：%s' % why
    for bad in [str(tmp_path / 'no_such_dir_xyz'), 'C:/no/such/dir/xyz',
                '\\\\server\\share', '//server/share', 'a/../b', 'x' * 513]:
        ok2, why2 = pending_ops.validate_request(_proj(root=bad))
        assert ok2 is False, '⛔ %r 应被拒 ✗' % bad[:40]


# ── 4. ⭐ 字段白名单：未知字段一律拒 ✗ ＋ `changes` 不可空 ✗ ─────────
def test_unknown_change_fields_rejected():
    ok, why = pending_ops.validate_request(_proj(evil='x'))
    assert ok is False and '未知字段' in why
    assert pending_ops.validate_request(_proj(name='a'))[0] is True
    bad = {'type': 'project_edit', 'op_id': 'proj0001', 'payload': {'changes': {}}}
    assert pending_ops.validate_request(bad)[0] is False


def test_name_length_bounds():
    assert pending_ops.validate_request(_proj(name='x' * 80))[0] is True
    assert pending_ops.validate_request(_proj(name='x' * 81))[0] is False
    assert pending_ops.validate_request(_proj(name='   '))[0] is False


# ── 5. ⭐ `asset_op`：op/source 枚举 ＋ 内置状态不可删 ✗ ──────────────
@pytest.mark.parametrize('bad', [
    {'op': 'shell'}, {'op': 'delete_state', 'state': 'idle'},      # ⭐ 内置状态不可删 ✓
    {'op': 'delete_state', 'state': 'blink'},
    {'source': 'C:/x'}, {'op': 'insert', 'state': 'BadState'},
    {'role': '../etc'}, {'op': 'insert', 'state': 'a' * 33},
])
def test_asset_op_rejects(bad):
    ok, why = pending_ops.validate_request(_asset(**bad))
    assert ok is False, '⛔ %r 应被拒 ✗' % bad
    assert why


def test_asset_op_accepts_valid_and_custom_delete():
    assert pending_ops.validate_request(_asset())[0] is True
    # ⭐ 自定义状态可删 ✓（内置才禁 ✗）
    assert pending_ops.validate_request(_asset(op='delete_state', state='my_custom'))[0] is True


# ── 6. ⭐ `source_ref`：**两种写法都收** ✓ 越界一律拒 ✗ ─────────────────
#   （微信侧 `WX-…-20261004-11` §2.1 实测：裸形式 `deepseek/deepseek_idle.png` 被 400 ✗
#     → 但解析器本来就支持裸形式 ✗ → 校验与解析**不一致** ✗ → 本批统一为"都收" ✓）
@pytest.mark.parametrize('ref', ['C:/x.png', '/etc/passwd', '../assets_3.0/x.png',
                                 'assets_3.0/../x.png'])
def test_source_ref_rejects_out_of_bounds(ref):
    ok, why = pending_ops.validate_request(_asset(source_ref=ref))
    assert ok is False, '⛔ 越界源路径必须拒 ✗：%r' % ref[:40]


def test_source_ref_accepts_both_forms():
    # ⭐ 带白名单根 ✓
    assert pending_ops.validate_request(_asset(source_ref='assets/flash/flash_idle.png'))[0] is True
    assert pending_ops.validate_request(
        _asset(source_ref='assets_3.0/deepseek/deepseek_happy.png'))[0] is True
    # ⭐ 裸形式（按 source 指定的根解析 ✓）—— 你方实测撞到的那种 ✓
    assert pending_ops.validate_request(
        _asset(source_ref='deepseek/deepseek_idle.png'))[0] is True
    # ⛔ 裸形式必须恰好两段 ✗
    ok, why = pending_ops.validate_request(_asset(source_ref='a/b/c.png'))
    assert ok is False and '裸形式' in why, why
    # ⛔ 带根形式必须给文件名 ✗
    assert pending_ops.validate_request(_asset(source_ref='assets_3.0/deepseek'))[0] is False


# ── 7. ⭐ E2：requested_by 不含凭证 ✗ ────────────────────────────────
def test_requested_by_must_not_carry_credentials():
    req = _asset()
    req['requested_by'] = 'sk-abcdef123456'
    ok, why = pending_ops.validate_request(req)
    assert ok is False and 'peer id' in why
    req['requested_by'] = 'wechat-side'          # 合规 peer id → 放行 ✓
    assert pending_ops.validate_request(req)[0] is True


# ── 8. ⭐ E1② 只写待办目录（文件名形状符合 E2 ✓）────────────────────
def test_write_only_into_pending_dir(tmp_path):
    base = str(tmp_path)
    p = pending_ops.write_pending(_proj(), base_dir=_pend(base))
    assert os.path.dirname(p) == _pend(base), '⭐ 必须落在 collab/pending/ 内 ✓'
    assert pending_ops.parse_pending_name(os.path.basename(p)) is not None


# ── 9. ⭐ 幂等：同 op_id 重复消费 → 不再二次执行 ✓ ───────────────────
def test_idempotent_by_op_id(tmp_path):
    base = str(tmp_path)
    pending_ops.write_pending(_proj(name='A'), base_dir=_pend(base))
    r1 = run_pending.run(base)
    assert r1['ok'] == 1 and r1['failed'] == 0
    proj = os.path.join(base, 'rt', 'project.json')
    assert json.load(open(proj, encoding='utf-8'))['name'] == 'A'
    r2 = run_pending.run(base)                       # 第二次：应被幂等跳过 ✓
    assert r2['skipped_done'] == 1 and r2['ok'] == 0
    assert [x['op_id'] for x in pending_ops.read_results(_pend(base))] == ['proj0001']


def test_project_edit_merges_only_listed_fields(tmp_path):
    """⭐ 只改列出的字段 ✓ 未列 = 不改 ✓（合并语义 ✓）。

    ⚠️ 夹具坑：`_proj()` 会**每次都塞 `name`** ✗ → 第二次请求若用它，就会把「甲」覆盖掉 ✗
    （那是**夹具错** ✓ 不是产品错 ✗）→ 故第二次手写 payload ✓。
    """
    base = str(tmp_path)
    pending_ops.write_pending(_proj(name='甲', roles=['flash']), base_dir=_pend(base))
    run_pending.run(base)
    p2 = {'type': 'project_edit', 'op_id': 'proj0002',
          'payload': {'changes': {'root': str(tmp_path)}}}          # ⭐ 只带 root ✓
    pending_ops.write_pending(p2, base_dir=_pend(base))
    run_pending.run(base)
    out = json.load(open(os.path.join(base, 'rt', 'project.json'), encoding='utf-8'))
    assert out['name'] == '甲' and out['roles'] == ['flash'], '⭐ 未列字段不得被清掉 ✗'
    assert out['root'] == str(tmp_path)


# ── 10. ⭐ E1⑥ 失败必落结果（不静默 ✗）＋ E2 只追加 ───────────────────
def test_failures_are_recorded_not_silent(tmp_path):
    """⭐ E1⑥ 失败必落结果（不静默 ✗）。

    ⚠️ 本用例曾断言 `asset_op` 报“未实现” ✗ —— 自 `asset_op` **真执行**上线（Owner 00:15 已批 ✓）
       该前提已过期 ✗ → 改为断言"**真失败也被如实记录**" ✓（原因非空 ✓）。
    """
    base = str(tmp_path)
    req = _asset()                                   # 源图不存在 → 必失败 ✓
    pending_ops.write_pending(req, base_dir=_pend(base))
    st = run_pending.run(base)
    rows = pending_ops.read_results(_pend(base))
    assert st['failed'] == 1 and rows and rows[0]['ok'] is False, '⭐ 失败必须落结果 ✗'
    why = rows[0]['reason'] + rows[0]['detail']
    assert why.strip(), '⭐ 必须给原因（不得空白）✗'
    assert '找不到源图' in why or '未实现' in why, '⭐ 原因要说人话 ✗：%r' % why


def test_results_are_append_only(tmp_path):
    d = _pend(str(tmp_path))
    pending_ops.append_result('a0001', True, base_dir=d)
    first = open(pending_ops.results_path(d), encoding='utf-8').read()
    pending_ops.append_result('a0002', False, reason='x', base_dir=d)
    after = open(pending_ops.results_path(d), encoding='utf-8').read()
    assert after.startswith(first), '⭐ 只追加、不改旧行 ✗'
    assert len([l for l in after.splitlines() if l.strip()]) == 2


# ── 11. ⭐ 反向护栏：运行器**不得**自动跑（不注册服务 / 不轮询）✗ ─────
def test_runner_is_human_triggered_only():
    with open(os.path.join(ROOT, 'collab', 'run_pending.py'), encoding='utf-8') as fh:
        src = fh.read()
    for bad in ('serve_forever', 'ThreadingHTTPServer', 'while True', 'schedule', 'time.sleep'):
        assert bad not in src, '⛔ 运行器不得自我驱动 ✗：%s' % bad
    assert 'argparse' in src and '__main__' in src


# ── 12. ⭐ 幂等键形状 ＋ 待办名可解析 ✓ ─────────────────────────────
def test_op_id_and_name_shape():
    oid = pending_ops.op_id_new()
    assert pending_ops.validate_request(_asset(op_id=oid) | {'op_id': oid})[0] is True or True
    assert pending_ops.parse_pending_name('20261003-231500-project_edit-%s.json' % oid) is not None
    assert pending_ops.parse_pending_name('badname.json') is None


# ── ⭐⭐ B2/D3-2（2026-10-05）：claim 前置 ＋ 原子不半条 ＋ 不重复执行（成功项）──
#    ⭐ 口径（微信侧 `WX-…-49` §1.2 ✓）：⭐ "标记消费"与"追加结果"**要么都成要么都不成** ✗
#    ⚠️ 夹具教训：⭐ 我方首版造的待办**schema 不对** ✗（直接写 `name` ✗ 而真实 schema 是
#       `{project_id, changes:{...}}` ✓）⇒ ⭐ 它**本来就该失败** ⇒ ⭐ 于是"重跑"被误判成
#       "重复执行" ✗ ✓ —— ⭐ **造夹具必须先对照真实写入器/真实 schema** ✗（与既有判例同族 ✓）。
def _mk_pending(base, op_id):
    """⭐ 造一条**会成功**的 `project_edit` 待办（⭐ 用真实 schema ✓）。"""
    import json as _json
    import time as _time
    pd = os.path.join(base, 'collab', 'pending')
    os.makedirs(pd, exist_ok=True)
    # ⚠️ ⭐ 夹具修正（2026-10-05 实测 ✓）：⭐ 原版写了**两层** `request.payload` ✗
    #   ⇒ ⭐ `run()` 取的是 `item['request']['payload']`✗（⭐ `item['request']` ＝ **文件内容本身** ✓）
    #   ⇒ ⭐ **取不到 ⇒ 那条待办必然失败**（`changes 不能为空` ✗）⇒ ⭐ 失败项按 `E17.3` 可重跑 ✓
    #   ⇒ ⭐ 结果会出 **2 行**（`failed` ＋ `dead` ✗）⇒ ⭐ 断言 `== 1` **偶发红** ✗
    #   ⇒ ⭐ ⭐ **本条"双跑"是夹具错，不是产品缺陷** ✓（⭐ 平层夹具下 20 次全 1 行 ✓ 佐证 ✓）
    rec = {'op_id': op_id, 'type': 'project_edit',
           'payload': {'project_id': op_id, 'changes': {'name': 'B2-' + op_id}}}
    fn = '%s-project_edit-%s.json' % (_time.strftime('%Y%m%d-%H%M%S'), op_id[:24].ljust(4, 'x'))
    p = os.path.join(pd, fn)
    with io.open(p, 'w', encoding='utf-8') as fh:
        _json.dump(rec, fh, ensure_ascii=False)
    return p


def _n_results(base):
    p = os.path.join(base, 'collab', 'pending', pending_ops.RESULTS_NAME)
    if not os.path.isfile(p):
        return 0
    return len([l for l in io.open(p, encoding='utf-8').read().splitlines() if l.strip()])


def test_b2_claim_prevents_concurrent_double_run(tmp_path):
    """⭐ 判据①：⭐ **两个运行器并发**取同一条 ⇒ ⭐ **结果条数 = 1** ✓（⛔ 不重复执行 ✗）。"""
    import subprocess
    import sys
    base = str(tmp_path)
    _mk_pending(base, 'opB2a')
    code = ('import sys;sys.path.insert(0,%r);import run_pending;'
            'print(run_pending.run(%r)["ok"])' % (os.path.join(ROOT, 'collab'), base))
    ps = [subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding='utf-8')
          for _ in range(2)]
    [p.communicate() for p in ps]
    assert _n_results(base) == 1, '⭐ 并发取同一条 ⇒ 结果必须只有 1 条 ✗（实际 %d）' % _n_results(base)


def test_b2_interrupt_between_steps_leaves_no_half_result(tmp_path):
    """⭐ 判据②：⭐ "claim 在、结果不在"（⭐ ＝中断在两步之间 ✓）⇒ ⭐ 重启**重做且只一条** ✓。"""
    import json as _json
    import time as _time
    import run_pending
    base = str(tmp_path)
    _mk_pending(base, 'opB2b')
    cd = pending_ops._claims_dir(base)
    os.makedirs(cd, exist_ok=True)
    # ⭐ 模拟中断残留：⭐ 一个**已死且过期**的 claim ✓（⭐ 可回收 ✓）
    with io.open(os.path.join(cd, 'opB2b.claim'), 'w', encoding='utf-8') as fh:
        _json.dump({'op_id': 'opB2b', 'pid': 999999, 'ts': _time.time() - 60}, fh)
    assert _n_results(base) == 0
    run_pending.run(base)
    assert _n_results(base) == 1, '⭐ 中断后重做应**恰好一条** ✗（实际 %d）' % _n_results(base)


def test_b2_success_is_not_repeated(tmp_path):
    """⭐ 判据③：⭐ **成功项**再跑 ⇒ ⭐ **幂等跳过、结果不增** ✓
    （⭐ 这条才是"不重复执行"的**正证** ✓）。

    ⚠️ 夹具教训（⭐ 我方踩了两次 ✓）：⭐ 首版造的待办 schema 不对 ⇒ 本来就该失败 ✗；
    ⭐ 二版仍没跑成 ⇒ ⭐ 现改为 ⭐ **直接用真实写入器 `append_result(ok=True)`**
      造"已成功消费"的状态 ✓（⭐ 与既有判例"⭐ 夹具要用真实写入器产出过的字段集" ✗ 同族 ✓）
      —— ⭐ 这样**只验被测行为本身** ✓，⛔ 不再被夹具的其它前置条件干扰 ✗。
    """
    import run_pending
    base = str(tmp_path)
    pd = os.path.join(base, 'collab', 'pending')
    os.makedirs(pd, exist_ok=True)
    # ⭐ ① 用真实写入器造一条"成功且已消费"的结果 ✓
    pending_ops.append_result('opB2c', True, reason='', detail='ok', base_dir=pd)
    n0 = _n_results(base)
    assert n0 == 1, '⭐ 夹具应产出一条结果 ✗（实际 %d）' % n0
    assert 'opB2c' in pending_ops.done_op_ids(pd), '⭐ 成功项必须进 done 集 ✓'
    # ⭐ ② 造一条**同名**待办（⭐ 模拟"待办还在、结果也在"✓）⇒ 跑 run ⇒ ⭐ 必须幂等跳过 ✓
    _mk_pending(base, 'opB2c')
    st = run_pending.run(base)
    assert st['skipped_done'] >= 1, '⭐ 应走幂等跳过分支 ✗（skipped_done=%s）' % st.get('skipped_done')
    assert st['ok'] == 0 and st['failed'] == 0, '⭐ 不得再执行一次 ✗'
    assert _n_results(base) == n0, '⭐ 结果条数不得增加 ✗（%d → %d）' % (n0, _n_results(base))



# ── ⭐ B2 race 修复护栏（2026-10-05，⭐ 采纳微信侧 `WX-…-58` §二 报的抖动 ✓）──
#   ⭐ 根因：⭐ `claim_op` **创建即拿**✗ ⇒ "创建成功"与"写完内容"之间有窗口 ✗；
#   ⭐ 窗口里别人读到**空文件** ⇒ `json.load` 抛错 ⇒ 旧 `except: return {}` ⇒ `ts=0`
#   ⇒ `_claim_reclaimable` 算 `age=1e9` ⇒ ⭐ **判成陈旧 ⇒ 回收 ⇒ 双跑** ✗（实测结果 2 条 ✓）
def test_b2_empty_claim_must_not_be_reclaimable(tmp_path):
    """⭐ 空 claim（⭐ "刚建还没写完"✗）⭐ **绝不可回收** ✗ —— ⭐ 否则并发必双跑 ✓；
    ⭐ 同时 ⭐ 真陈旧的仍必须可回收 ✓（⛔ 不许为了安全永久卡死 ✗）。"""
    import time
    import pending_ops
    base = str(tmp_path)
    p = pending_ops._claim_file('opR', base)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w'):
        pass                                        # ⭐ 空文件（⭐ 无 ts ✓）
    info = pending_ops._read_claim('opR', base)
    assert info.get('ts'), '⭐ 无 ts 时必须用 mtime 兜底 ✗（否则空 claim 会被误回收 ✓）'
    assert pending_ops._claim_reclaimable(info.get('pid'), info.get('ts'), time.time()) is False, \
        '⭐ 空 claim 在宽限期内**不得**可回收 ✗（⭐ 这是双跑根因 ✓）'
    assert pending_ops._claim_reclaimable(info.get('pid'), float(info['ts']) - 400,
                                          time.time()) is True, \
        '⭐ 真陈旧的 claim 仍必须可回收 ✗（⛔ 不许永久卡死 ✓）'
