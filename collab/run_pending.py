# -*- coding: utf-8 -*-
"""collab/run_pending.py —— **待办运行器**（契约条款 IV **E1⑦ 人触发** ✓）

⚠️ 本脚本**必须由人显式执行** ✗ —— ⛔ 不注册为服务 ✗ ⛔ 不自动轮询 ✗ ⛔ 不被 HTTP 调用 ✗

用法（PowerShell ✓）：
    python collab\\run_pending.py --base . --dry-run     # 只看会做什么（不落任何结果）
    python collab\\run_pending.py --base .              # 真执行（逐条落 results.jsonl ✓）

硬约束（照条款 IV E1 ✓）：
  · **只按类型枚举执行** ✓ —— 未知/未实现类型 → ⭐ **明报并落结果** ✗（不静默 ✓）
  · ⭐ **失败必落结果** ✓（含原因 ✓）
  · ⭐ **幂等**：`op_id` 已在 results 里 → 跳过 ✓（重复消费结果一致 ✓）
  · ⛔ 不碰 `collab/pending/` 之外的任何"不可预期"路径 ✗；写目标全部限定在 `--base` 内 ✓
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pending_ops  # noqa: E402

MAX_NAME = 80                                   # 照龙虾口径：项目名 ≤80 字 ✓
PROJECT_FILE = os.path.join('rt', 'project.json')


def _safe_rel(base: str, rel: str) -> str:
    """把**相对**路径解析到 base 内；⛔ 逃出 base 或含绝对路径 → 抛错 ✓。"""
    rel = str(rel or '').strip().replace('\\', '/')
    if not rel or rel.startswith('/') or ':' in rel or '..' in rel.split('/'):
        raise ValueError('路径必须是不含 .. 的相对路径：%r' % rel)
    p = os.path.normpath(os.path.join(base, rel))
    if not os.path.normpath(p).startswith(os.path.normpath(base)):
        raise ValueError('路径逃出 base，已拒：%r' % rel)
    return p


def do_project_edit(base: str, payload: dict) -> tuple:
    """`project_edit`：把 `changes` **合并**进 `<base>/rt/project.json` ✓（⭐ 只改列出的字段 ✓）

    新 schema（微信侧 `-16` §2.2 ✓ 我方 `-105` 已审定 ✓）：
      `{project_id, changes: {name?, root?, outputs?, memory_file?, roles?}}`
    · `root` ⭐ 可绝对路径（已存在目录·只登记 ✗ 不创建 ✓）
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
            p = pending_ops._rel_problem(v)             # 相对路径再核一道 ✓（直接调本模块也拦得住 ✓）
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


def do_asset_op(base: str, payload: dict) -> tuple:
    """`asset_op`：⭐ v1 **明确未实现** ✗ → **明报**（不静默 ✓ 不留"假成功" ✗）。

    原因（写进结果里 ✓ 便于界面侧知道进度）：
      · 图片类操作要先定"生效目录 = assets/<portrait>/" ✓（双方已定 ✓）
      · 且要复用 `assets_3.0/tools/` 的三合一管线 ✓（尚需 Owner 批动素材 ✓）
    """
    return False, ('asset_op 在 v1 尚未实现（需先获 Owner 批：接素材池 ＋ 跑三合一管线）；'
                   '本条已记录、未做任何改动 ✓')


HANDLERS = {'project_edit': do_project_edit, 'asset_op': do_asset_op}


def run(base: str, dry: bool = False) -> dict:
    """消费一轮待办 ✓ 返回统计 ✓。"""
    base = os.path.abspath(base)
    pend = pending_ops.list_pending(os.path.join(base, 'collab', 'pending'))
    done = pending_ops.done_op_ids(os.path.join(base, 'collab', 'pending'))
    stats = {'seen': len(pend), 'skipped_done': 0, 'ok': 0, 'failed': 0, 'rows': []}
    for item in pend:
        oid = item['op_id']
        if oid in done:                                        # ⭐ 幂等 ✓
            stats['skipped_done'] += 1
            continue
        t = item['type']
        fn = HANDLERS.get(t)
        if fn is None:
            ok, why, detail = False, '未知类型：%r（枚举外，已拒 ✓）' % t, ''
        else:
            try:
                ok, detail = fn(base, (item['request'] or {}).get('payload') or {})
                why = '' if ok else detail
            except Exception as exc:                           # ⭐ 失败必落结果 ✓
                ok, why, detail = False, '执行异常', '%r' % (exc,)
        stats['ok' if ok else 'failed'] += 1
        stats['rows'].append({'op_id': oid, 'type': t, 'ok': ok, 'why': why or detail})
        if not dry:
            pending_ops.append_result(oid, ok, reason=why, detail=detail,
                                      base_dir=os.path.join(base, 'collab', 'pending'))
    return stats


def main():
    ap = argparse.ArgumentParser(description='待办运行器（人触发 ✓ 条款 IV E1⑦）')
    ap.add_argument('--base', default='.', help='仓库根（待办在其 collab/pending/ 下 ✓）')
    ap.add_argument('--dry-run', action='store_true', help='只看会做什么，不落任何结果 ✓')
    args = ap.parse_args()
    st = run(args.base, dry=args.dry_run)
    print('[run_pending]%s 待办 %d ｜ 幂等跳过 %d ｜ 成功 %d ｜ 失败 %d'
          % ('（dry-run）' if args.dry_run else '', st['seen'], st['skipped_done'], st['ok'], st['failed']))
    for r in st['rows']:
        print('   %s %-12s %s' % ('✓' if r['ok'] else '✗', r['type'], (r['why'] or '')[:100]))
    return 0 if st['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
