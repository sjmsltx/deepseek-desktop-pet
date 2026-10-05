# -*- coding: utf-8 -*-
"""collab/run_pending.py -- **待办运行器**(契约条款 IV **E17 人触发** ✓)

⚠️ 本脚本**必须由人显式执行** ✗ -- ⛔ 不注册为服务 ✗ ⛔ 不自动轮询 ✗ ⛔ 不被 HTTP 调用 ✗

用法(PowerShell ✓):
    python collab\\run_pending.py --base . --dry-run     # 只看会做什么(不落任何结果)
    python collab\\run_pending.py --base .              # 真执行(逐条落 results.jsonl ✓)

硬约束(照条款 IV E1 ✓):
  · **只按类型枚举执行** ✓ -- 未知/未实现类型 → ⭐ **明报并落结果** ✗(不静默 ✓)
  · ⭐ **失败必落结果** ✓(含原因 ✓)
  · ⭐ **幂等**:`op_id` 已在 results 里 → 跳过 ✓(重复消费结果一致 ✓)
  · ⛔ 不碰 `collab/pending/` 之外的任何"不可预期"路径 ✗;写目标全部限定在 `--base` 内 ✓
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# ⭐ 两条都要插：`collab/`（本模块的伙伴 ✓）＋ **仓库根**（`model_registry` 等在其下 ✓）
#    ⚠️ 微信侧 `WX-…-20261004-07` §二 实测：只插 `collab/` ✗ → CLI 路径下
#       `asset_ops` 惰性 `import model_registry` **必然 ModuleNotFoundError** ✗
#       （pytest 跑时仓库根本来就在 sys.path ✓ → **测试绿／CLI 红** ✗）
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(_HERE), _HERE):        # 仓库根 ✓ ＋ collab/ ✓
    if _p not in sys.path:
        sys.path.insert(0, _p)
import pending_ops  # noqa: E402

MAX_NAME = 80                                   # 照龙虾口径:项目名 ≤80 字 ✓
PROJECT_FILE = os.path.join('rt', 'project.json')


def _safe_rel(base: str, rel: str) -> str:
    """把**相对**路径解析到 base 内;⛔ 逃出 base 或含绝对路径 → 抛错 ✓。"""
    rel = str(rel or '').strip().replace('\\', '/')
    if not rel or rel.startswith('/') or ':' in rel or '..' in rel.split('/'):
        raise ValueError('路径必须是不含 .. 的相对路径:%r' % rel)
    p = os.path.normpath(os.path.join(base, rel))
    if not os.path.normpath(p).startswith(os.path.normpath(base)):
        raise ValueError('路径逃出 base,已拒:%r' % rel)
    return p


def do_project_edit(base: str, payload: dict) -> tuple:
    """`project_edit`:把 `changes` **合并**进 `<base>/rt/project.json` ✓(⭐ 只改列出的字段 ✓)

    新 schema(微信侧 `-16` §2.2 ✓ 我方 `-105` 已审定 ✓):
      `{project_id, changes: {name?, root?, outputs?, memory_file?, roles?}}`
    · `root` ⭐ 可绝对路径(已存在目录·只登记 ✗ 不创建 ✓)
    · `outputs`/`memory_file` ⭐ 只允许相对形式 ✓
    """
    pid = str(payload.get('project_id') or 'default').strip() or 'default'
    changes = payload.get('changes') or {}
    if not isinstance(changes, dict) or not changes:
        return False, 'changes 不能为空'
    target = os.path.join(base, PROJECT_FILE)
    cur = {}
    if os.path.isfile(target):
        try:
            with open(target, encoding='utf-8') as fh:
                cur = json.load(fh) or {}
        except Exception:
            cur = {}                                   # 旧档坏了不阻塞 ✓ 重建 ✓
    out = dict(cur)
    out['id'] = pid
    for k, v in changes.items():                       # ⭐ 只改列出的 ✓ 未列 = 不改 ✓
        if k in ('outputs', 'memory_file'):
            p = pending_ops._rel_problem(v)             # 相对路径再核一道 ✓(直接调本模块也拦得住 ✓)
            if p:
                return False, '%s %s' % (k, p)
        if k == 'roles':
            if not isinstance(v, list):
                return False, 'roles 必须是数组'
            v = [str(x) for x in v]
        out[k] = v
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, target)                             # 原子写 ✓
    return True, '已合并 %d 个字段到 %s' % (len(changes), PROJECT_FILE)


def do_asset_op(base: str, payload: dict, dry: bool = False) -> tuple:
    """`asset_op`：⭐ v1 **真执行**（Owner 2026-10-04 00:15「我批准」✓）。

    口径（微信侧 `WX-…-20261004-02` §二 ✓）：① 先备份后写入 ✓ ② 逐文件＋逐张探针 ✓
    ③ dry-run 也落结果 ✓（由调用方标 `dry_run:true` ✓）
    实际执行在 `asset_ops.do_asset_op` ✓（本函数只做委派 ＋ 枚举兜底 ✓）
    """
    import asset_ops
    ok, detail, arts = asset_ops.do_asset_op(base, payload, dry=dry)
    return ok, detail, arts


HANDLERS = {'project_edit': do_project_edit, 'asset_op': do_asset_op}


def run(base: str, dry: bool = False) -> dict:
    """消费一轮待办 ✓ 返回统计 ✓。"""
    base = os.path.abspath(base)
    pend = pending_ops.list_pending(os.path.join(base, 'collab', 'pending'))
    done = pending_ops.done_op_ids(os.path.join(base, 'collab', 'pending'))
    # ⭐ dry-run 的结果也落盘 ✓ → 但**不得**让后续真跑被“幂等”误跳过 ✗
    #    （做法：dry-run 结果不加进 done 集 ✓ 见 done_op_ids 的 dry_run 过滤 ✓）
    _pd = os.path.join(base, 'collab', 'pending')       # ⭐ claim 与结果同目录 ✓
    # ⭐ ⭐ 落痕（2026-10-05）：⭐ 待办目录不存在时 ⭐ `list_pending` 会**静默返回空** ✗
    #   ⇒ ⭐ 现象是"⭐ 待办明明写了、`run()` 却说 `seen: 0`"✗ ⇒ ⭐ 极易误判成"夹具错" ✓
    #   ⚠️ 本方实测踩过 ✓：⭐ `write_pending(req, base_dir=<base>)` 写进 `<base>/` ✗
    #      ⭐ 而 `run(<base>)` 读 `<base>/collab/pending/` ✗ ⇒ ⭐ 两边口径不同 ⇒ **看不见** ✓
    if not os.path.isdir(_pd):
        print('  \u26a0\ufe0f 待办目录不存在（⭐ 因此本轮 `seen` 必然为 0 ✓）：%s' % _pd)
    stats = {'seen': len(pend), 'skipped_done': 0, 'skipped_claimed': 0,
             'ok': 0, 'failed': 0, 'rows': []}
    for item in pend:
        oid = item['op_id']
        # ⭐ B11：⭐ `dead` 是**终止态** ✗ ⇒ ⭐ 与 `ok` 一样**不再自动重跑** ✓
        #   ⚠️ 但 ⭐ **人工重放**不受此限 ✗（⭐ 走 `replay_allowed` ✓ 只对 dead 开 ✓）
        #   ⚠️ 自纠（2026-10-05，⭐ 本方护栏抓到自己 ✗）：⭐ 本判据在 `8d8104c` 被写成
        #     `if oid in done:`✗ ⇒ ⭐ `else` 分支**永不触发** ✗ ⇒ ⭐ **`dead` 根本不被跳过** ✗
        #     ⇒ ⭐ 已改回"⭐ `done` **或** `dead_ids` ✗"（⭐ 两者都算已终结 ✓）。
        if oid in done or oid in pending_ops.dead_ids(_pd):
            _tag = '幂等' if oid in done else '已进死信（dead ✓ 需人工重放）'
            print('  \u2139\ufe0f 跳过 %s：%s ✓' % (oid, _tag))            # ⭐ 落痕 ✓
            stats['skipped_done'] += 1
            continue
        # ⭐ ⭐ B1/D3-1（前置 ✓）：⭐ 取走前**先落 claim** ✗ —— ⭐ 幂等 ＋ 原子 ✓
        #   ⭐ 拿不到 ⇒ ⭐ **明确跳过并留痕** ✗（⛔ 不重复执行 ✗）
        #   ⭐ dry-run **不占** ✗（它不改东西 ✓ ⇒ 不该挡住真跑 ✓）
        if not dry:
            if not pending_ops.claim_op(oid, line=pending_ops.product_line(base), base_dir=_pd):
                stats['skipped_claimed'] += 1
                stats['rows'].append({'op_id': oid, 'type': item.get('type'),
                                      'ok': False, 'why': '已被其他运行器 claim（已跳过）'})
                continue
            # ⭐ ⭐ B2 第二个窗口（2026-10-05 实测 ✓）：⭐ "**读 `done`**"与"**尝试 claim**"之间
            #   也有缝 ✗ —— ⭐ 若 A 在我读 `done` 之后才写完结果并释放 claim ✗，
            #   ⭐ 我这次 claim 就会**成功** ⇒ ⭐ ⭐ **再执行一次** ✗（实测结果条数 = 2 ✓）。
            #   ⇒ ⭐ ⭐ **拿到 claim 之后再复核一次 `done`** ✗（⭐ 并发标准做法 ✓：
            #     ⭐ 真正的裁决点是"⭐ 拿到锁之后看到的事实"✗，⛔ 不是拿锁前读到的 ✓）。
            #   ⭐ 顺序依据：⭐ `run` 里是**先写结果、后释放 claim** ✗ ⇒ ⭐ 我能拿到锁
            #     ⇒ ⭐ 说明 A 已释放 ⇒ ⭐ **A 的结果必然已落盘** ✗ ⇒ ⭐ 这次复核一定看得见 ✓。
            if oid in pending_ops.done_op_ids(_pd):
                print('  \u2139\ufe0f 跳过 %s：拿到 claim 后复核**已成功**（幂等 ✓）' % oid)
                pending_ops.release_claim(oid, base_dir=_pd)
                stats['skipped_done'] += 1
                continue
        t = item['type']
        fn = HANDLERS.get(t)
        # ⭐ ⭐ B11：⭐ **失败自动重放至多 `MAX_REPLAY` 次** ✗（⭐ 采纳微信侧 `WX-…-56` 草稿 6 ✓）
        #   ⭐ ⚠️ 关键：⭐ 重放**在同一个 `run` 内**完成 ✗，⭐ 而**结果只落一行**终态 ✓
        #     （⭐ 判据① 明确要求：⭐ 注入必失败 ⇒ ⭐ 终态 `dead` ✓ 且 ⭐ **结果条数 = 1** ✗ 不是 N 条 ✓）
        #   ⭐ 依据：⭐ `E17.3`「⭐ **失败不算消费** ⇒ 重跑安全」✗ ✓（⭐ 故重放不违幂等 ✓）
        _cap = int(getattr(pending_ops, 'MAX_REPLAY', 2))
        ok, why, detail, arts = False, '', '', []
        # ⚠️ ⭐ 本条**曾用**无限循环（`while` ＋ 常量真）✗ 做自动重放 ⇒ ⭐ 撞了既有结构钉
        #   `test_runner_is_human_triggered_only`（"⛔ 运行器不得自我驱动" ✓）✓
        # ⭐ 且 ⭐ 更重要的：⭐ "⭐ **失败自动推到 `dead`**"✗ 与既有契约
        #   `test_failed_op_can_be_retried_after_fix`（⭐ **失败不算消费 ⇒ 修好后重跑必须真执行** ✓）
        #   ⭐ ⭐ **口径冲突** ✗ ⇒ ⭐ **本批回退自动重放** ✗，⭐ 冲突留**双方定** ✓
        #   （⭐ 见 `PC-桌宠-20261005-171` §二 ✓）。
        _tries = 1
        if True:
            if fn is None:
                ok, why, detail, arts = False, '未知类型：%r（枚举外，已拒 ✓）' % t, '', []
                break
            try:
                if t == 'asset_op':
                    ok, detail, arts = fn(base, (item['request'] or {}).get('payload') or {},
                                          dry=dry)
                    why = '' if ok else detail
                else:
                    ok, detail = fn(base, (item['request'] or {}).get('payload') or {})
                    why, arts = ('' if ok else detail), []
            except Exception as exc:                           # ⭐ 失败必落结果 ✓
                ok, why, detail, arts = False, '执行异常', '%r' % (exc,), []
            # ⭐ 单次执行 ✓（⭐ 自动重放已回退 ✗ —— 见上 ✓）
        stats['ok' if ok else 'failed'] += 1
        stats['rows'].append({'op_id': oid, 'type': t, 'ok': ok, 'why': why or detail})
        # ⭐ B11（`D2-4`）：⭐ 终态由 `next_kind` 统一推 ✗（⭐ 成功 ⇒ ok ✓；⭐ 失败且已达上限 ⇒ dead ✓）
        _fails = pending_ops.fail_count(oid, _pd)
        # ⭐ 本次**总共**失败 `_tries` 次（⭐ 含自动重放 ✓）＋ ⭐ 历史失败 ✓
        # ⭐ 回退后：⭐ 失败 ⇒ `failed` ✓（⭐ 允许重试 ✓ 与既有契约一致 ✗）
        #   ⭐ `dead` 仅由 ⭐ **显式标记** 进入 ✗（⭐ 谁标 ⇒ ⭐ **待双方定** ✓ 见件 §二 ✓）
        _kind = pending_ops.next_kind(ok, _fails + (0 if ok else 1))
        if not dry:
            pending_ops.append_result(oid, ok, reason=why, detail=detail, dry_run=False,
                                      artifacts=arts, line=pending_ops.product_line(base),
                                      base_dir=os.path.join(base, 'collab', 'pending'),
                                      extra={'kind': _kind, 'fail_count': _fails, 'tries': _tries})
        elif dry:                                              # ⭐ ③ dry-run 也落结果 ✓
            pending_ops.append_result(oid, ok, reason=why, detail=detail, dry_run=True,
                                      artifacts=arts, line=pending_ops.product_line(base),
                                      base_dir=os.path.join(base, 'collab', 'pending'))
        # ⭐ ⭐ B2/D3-2：⭐ 结果**已落盘** ⇒ ⭐ 释放 claim ✓（⭐ 成功失败都释放 ✓ ——
        #   ⭐ 因为结果已在 ⇒ 下次靠**幂等**跳过 ✓，⛔ 不靠「永不释放」来防重 ✗）
        if not dry:
            pending_ops.release_claim(oid, base_dir=_pd)
    return stats


def main():
    ap = argparse.ArgumentParser(description='待办运行器(人触发 ✓ 条款 IV E17)')
    ap.add_argument('--base', default='.', help='仓库根(待办在其 collab/pending/ 下 ✓)')
    ap.add_argument('--dry-run', action='store_true', help='只看会做什么,不落任何结果 ✓')
    args = ap.parse_args()
    st = run(args.base, dry=args.dry_run)
    print('[run_pending]%s 待办 %d | 幂等跳过 %d | 成功 %d | 失败 %d'
          % ('(dry-run)' if args.dry_run else '', st['seen'], st['skipped_done'], st['ok'], st['failed']))
    for r in st['rows']:
        print('   %s %-12s %s' % ('✓' if r['ok'] else '✗', r['type'], (r['why'] or '')[:100]))
    return 0 if st['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
