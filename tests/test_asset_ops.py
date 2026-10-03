# -*- coding: utf-8 -*-
"""`asset_op` 真执行护栏（Owner 2026-10-04 00:15 已批 ✓）。

口径三条（微信侧 `WX-…-20261004-02` §二 ✓）：① 先备份后写入 ✓ ② 逐文件＋逐张探针 ✓
③ dry-run 也落结果 ✓（且 ⭐ **不得**让真跑被幂等跳过 ✗）
"""
import hashlib
import io
import json
import os
import shutil
import sys

import pytest
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'collab')):
    if p not in sys.path:
        sys.path.insert(0, p)

import asset_ops  # noqa: E402
import pending_ops  # noqa: E402
import relay_server  # noqa: E402
import run_pending  # noqa: E402


def _png(path, color=(220, 60, 60), size=(120, 120), bg=(255, 255, 255)):
    """造一张"白底 ＋ 实心方块"的合成图 ✓（够管线与探针判 ✓ 且跑得快 ✓）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im = Image.new('RGB', size, bg)
    ImageDraw.Draw(im).rectangle([30, 30, size[0] - 30, size[1] - 30], fill=color)
    im.save(path)
    return path


def _hash(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()[:12]


@pytest.fixture()
def repo(tmp_path):
    """搭一个最小仓库：素材池 ＋ 管线脚本 ＋ 生效目录 ✓（⭐ 用合成图 ✗ 不碰真素材 ✓）。"""
    base = str(tmp_path)
    shutil.copytree(os.path.join(ROOT, 'assets_3.0', 'tools'),
                    os.path.join(base, 'assets_3.0', 'tools'))
    _png(os.path.join(base, 'assets_3.0', 'alpha', 'alpha_happy.png'))
    return base


def _req(op='replace', state='happy', **kw):
    pl = {'role': 'alpha', 'state': state, 'op': op, 'source': 'pool'}
    pl.update(kw)
    return {'type': 'asset_op', 'op_id': 'as0001', 'payload': pl}


# ── 1. ⭐ 先备份后写入：原件不被丢，且源图**字节不变** ─────────────────
def test_backup_before_write_and_source_intact(repo):
    src = os.path.join(repo, 'assets_3.0', 'alpha', 'alpha_happy.png')
    h0 = _hash(src)
    ok, detail, arts = asset_ops.do_asset_op(repo, _req()['payload'], dry=False)
    assert ok is True, detail
    bak = os.path.join(repo, 'assets_3.0', '_raw_backup', 'alpha', 'alpha_happy.png')
    assert os.path.isfile(bak), '⭐ 必须先备份原件 ✓'
    assert _hash(src) == h0, '⛔ 源图不得被改 ✗'


# ── 2. ⭐ 生效目录落图（白底主图）✓ ────────────────────────────────────
def test_insert_lands_effective_dir(repo):
    ok, detail, arts = asset_ops.do_asset_op(repo, _req(op='insert')['payload'], dry=False)
    assert ok is True, detail
    tgt = os.path.join(repo, 'assets', 'alpha', 'alpha_happy.png')
    assert os.path.isfile(tgt), '⭐ 生效目录应有该状态白底 ✓'
    assert any('assets/alpha/alpha_happy.png' in a for a in arts)


# ── 3. ⭐ 逐文件跑管线 → 产 _alpha/_chroma ＋ 探针 ✓ ─────────────────
def test_run_pipeline_produces_alpha_and_chroma(repo):
    ok, detail, arts = asset_ops.do_asset_op(repo, _req(op='run_pipeline')['payload'], dry=False)
    assert ok is True, detail
    d = os.path.join(repo, 'assets_3.0', 'alpha')
    assert os.path.isfile(os.path.join(d, 'alpha_happy_alpha.png')), '⭐ 应产出透明版 ✓'
    assert os.path.isfile(os.path.join(d, 'alpha_happy_chroma.png')), '⭐ 应产出绿底版 ✓'
    assert '探针' in detail or '完成' in detail


# ── 4. ⭐ dry-run：**不写任何东西** ✓ ────────────────────────────────
def test_dry_run_writes_nothing(repo):
    ok, detail, arts = asset_ops.do_asset_op(repo, _req()['payload'], dry=True)
    assert ok is True
    assert not os.path.exists(os.path.join(repo, 'assets', 'alpha', 'alpha_happy.png')), \
        '⛔ dry-run 不得落图 ✗'
    assert not os.path.isdir(os.path.join(repo, 'assets_3.0', '_raw_backup')), \
        '⛔ dry-run 不得建备份 ✗'
    assert 'dry-run' in detail


# ── 5. ⭐⭐ dry-run 结果落盘 ✓ 但**不得**让真跑被幂等跳过 ✗（最关键一条）──
def test_dry_run_result_is_recorded_but_not_consumed(repo):
    d = os.path.join(repo, 'collab', 'pending')
    pending_ops.write_pending(_req(), base_dir=d)
    st = run_pending.run(repo, dry=True)
    assert st['ok'] == 1
    rows = pending_ops.read_results(d)
    assert rows and rows[-1].get('dry_run') is True, '⭐ 预演也要落结果 ✓'
    assert not (repo and os.path.exists(os.path.join(repo, 'assets', 'alpha'))), '预演不落图 ✓'
    # ⭐ 真跑：**不得**被上面的 dry-run 结果跳过 ✗
    assert 'as0001' not in pending_ops.done_op_ids(d), '⛔ dry-run 不算已消费 ✗'
    st2 = run_pending.run(repo, dry=False)
    assert st2['skipped_done'] == 0 and st2['ok'] == 1, '⭐ 真跑必须真的执行 ✓'


# ── 6. ⭐ 未实现项必须**明报**（不装成功 ✗）──────────────────────────
@pytest.mark.parametrize('op', ['add_role', 'delete_state'])
def test_unimplemented_ops_report_honestly(repo, op):
    ok, detail, arts = asset_ops.do_asset_op(repo, _req(op=op)['payload'], dry=False)
    assert ok is False and '尚未实现' in detail
    assert not os.path.isdir(os.path.join(repo, 'assets_3.0', '_raw_backup')), '⛔ 未做任何改动 ✗'


# ── 7. ⭐ 探针真能抓"抠穿"（造一张中间挖空的图 ✓）────────────────────
def test_probe_detects_hole(tmp_path):
    p = str(tmp_path / 'holed_alpha.png')
    im = Image.new('RGBA', (120, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 100, 100], fill=(255, 0, 0, 255))
    d.rectangle([50, 50, 70, 70], fill=(0, 0, 0, 0))      # ⭐ 内部挖空（＝抠穿 signature ✓）
    im.save(p)
    fg, hole, ma, semi = asset_ops.probe_alpha(p)
    assert hole > 0.5, '⭐ 探针必须能抓出内部空洞 ✗（否则等于没探 ✓）'


def test_probe_passes_clean_image(tmp_path):
    p = _png(str(tmp_path / 'ok_alpha.png'))
    im = Image.open(p).convert('RGBA')
    im.save(str(tmp_path / 'ok2_alpha.png'))
    fg, hole, ma, semi = asset_ops.probe_alpha(str(tmp_path / 'ok2_alpha.png'))
    assert hole < 0.5 and ma > 230, '⭐ 干净实心图应过探针 ✓'


# ── 8. ⭐ 微信侧揪出的伪角色 bug：`_` 开头目录不得算角色 ✗ ─────────────
def test_assets_payload_skips_underscore_dirs(repo):
    os.makedirs(os.path.join(repo, 'assets_3.0', '_raw_backup', 'alpha'), exist_ok=True)
    _png(os.path.join(repo, 'assets_3.0', '_raw_backup', 'alpha', 'alpha_happy.png'))
    got = relay_server.assets_payload(base_dir=repo)
    assert not [k for k in got if k.startswith('_')], '⛔ `_` 开头目录不得成为伪角色 ✗'
    assert 'alpha' in got, '正常角色仍应在 ✓'



# ── 9. ⭐ set_portrait（Owner 2026-10-04 00:36「同意」✓）：只改一个字段 ──
def _cfg(tmp_path):
    """造一份最小档案 ✓（形状照真 `models.json`：appearance 嵌套 ✓）。"""
    import json
    d = {'version': 2, 'profiles': [
        {'key': 'flash', 'display_name': 'F', 'model_id': 'm1',
         'appearance': {'color': '#111', 'portrait': '', 'sub': 'x'}},
        {'key': 'pro', 'display_name': 'P', 'model_id': 'm2',
         'appearance': {'color': '#222', 'portrait': '', 'sub': 'y'}}]}
    p = os.path.join(str(tmp_path), 'models.json')
    with io.open(p, 'w', encoding='utf-8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)
    # ⚠️ 夹具坑（本批踩过 ✗）：最小档案**不是 registry 的规范形状** ✗
    #    → `save()` 会**规范化**写回 ✓ → “顶层只应有 appearance 变”会误判红 ✗
    #    → ⭐ 先经 registry 落一次盘，让基线＝规范形状 ✓（真 `models.json` 就是规范形状 ✓）
    import model_registry as _mr
    _mr.ModelRegistry(p).save()
    return p


def test_set_portrait_changes_only_that_field(tmp_path):
    import json
    base = str(tmp_path)
    p = _cfg(tmp_path)
    before = json.load(io.open(p, encoding='utf-8'))
    ok, detail, arts = asset_ops.do_asset_op(
        base, {'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': 'deepseek'}, dry=False)
    assert ok is True, detail
    after = json.load(io.open(p, encoding='utf-8'))
    f0 = [x for x in before['profiles'] if x['key'] == 'flash'][0]
    f1 = [x for x in after['profiles'] if x['key'] == 'flash'][0]
    assert [k for k in set(f0) | set(f1) if f0.get(k) != f1.get(k)] == ['appearance'], \
        '⭐ 顶层只应有 appearance 变 ✗'
    assert [k for k in set(f0['appearance']) | set(f1['appearance'])
            if f0['appearance'].get(k) != f1['appearance'].get(k)] == ['portrait'], \
        '⭐ appearance 里只应有 portrait 变 ✗'
    o0 = [x for x in before['profiles'] if x['key'] == 'pro'][0]
    o1 = [x for x in after['profiles'] if x['key'] == 'pro'][0]
    assert o0 == o1, '⛔ 别的角色一字不得动 ✗'
    assert '重启' in detail, '⭐ 必须说明"重启后生效"（契约 ③-1 启动读一次 ✓）✗'


def test_set_portrait_backs_up_config_first(tmp_path):
    base = str(tmp_path)
    _cfg(tmp_path)
    ok, detail, arts = asset_ops.do_asset_op(
        base, {'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': 'qwen'}, dry=False)
    assert ok is True, detail
    baks = [f for f in os.listdir(os.path.join(base, '_raw_backup')) if 'models.json' in f]
    assert baks, '⭐ 改档案前必须先备份 ✓（可回滚 ✓）'


def test_set_portrait_rejects_unknown_role_and_paths(tmp_path):
    base = str(tmp_path)
    _cfg(tmp_path)
    for pl, kw in (({'role': 'nobody', 'op': 'set_portrait', 'portrait_prefix': 'x'}, '不在档案'),
                   ({'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': '../etc'}, '单段'),
                   ({'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': 'a/b'}, '单段')):
        ok, detail, arts = asset_ops.do_asset_op(base, pl, dry=False)
        assert ok is False and kw in detail, '⛔ %s 应被拒 ✗' % pl


def test_set_portrait_dry_run_writes_nothing(tmp_path):
    base = str(tmp_path)
    p = _cfg(tmp_path)
    h0 = _hash(p)
    ok, detail, arts = asset_ops.do_asset_op(
        base, {'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': 'x'}, dry=True)
    assert ok is True and 'dry-run' in detail
    assert _hash(p) == h0, '⛔ dry-run 不得改档案 ✗'
    assert not os.path.isdir(os.path.join(base, '_raw_backup')), '⛔ dry-run 不得建备份 ✗'


def test_set_portrait_empty_means_unbind(tmp_path):
    base = str(tmp_path)
    _cfg(tmp_path)
    asset_ops.do_asset_op(base, {'role': 'flash', 'op': 'set_portrait',
                                 'portrait_prefix': 'qwen'}, dry=False)
    ok, detail, arts = asset_ops.do_asset_op(
        base, {'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': ''}, dry=False)
    assert ok is True and "''" in detail, '⭐ 空串 = 解绑 ✓ 应放行 ✓'


# ── 10. ⭐ 校验层：set_portrait **只收** {role, portrait_prefix} ✗ ────
def test_validation_set_portrait_payload_shape():
    ok = pending_ops.validate_request({'type': 'asset_op', 'op_id': 'sp0001', 'payload': {
        'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': 'deepseek'}})
    assert ok[0] is True, ok[1]
    for bad, kw in (({'role': 'flash', 'op': 'set_portrait'}, '缺'),
                    ({'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': 'x',
                      'state': 'happy'}, '不接受'),
                    ({'role': 'flash', 'op': 'set_portrait', 'portrait_prefix': 'a/b'}, '单段')):
        r = pending_ops.validate_request({'type': 'asset_op', 'op_id': 'sp0001', 'payload': bad})
        assert r[0] is False and kw in r[1], '⛔ %r 应被拒 ✗' % bad
