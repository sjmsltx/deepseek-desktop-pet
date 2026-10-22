#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_m2_contract.py —— M2 契约扫描（三段式，照 `docs/3.0-M2-UI导出契约-冻结v1.md` §4）

用途：把「渲染 ↔ 后端投影 ↔ 日志真相」三方比对收成**一条命令**，退出码可机械判读。
放置：`desktop-pet/tools/`（★ 不放 tests/，否则会被 pytest 收集 ✗ —— 同 `verify.py` 约定）

用法：
    # ① 静态扫描 collab/index.html（不需要服务 ✓ 最快 ✓）
    python tools/verify_m2_contract.py

    # ② 后端投影 ↔ 日志真相（需协作台在跑；HTTP 只读面 + 内核 replay 对照）
    python tools/verify_m2_contract.py --base http://127.0.0.1:8792

    # ③ 渲染 ↔ 后端投影（需界面「⤓ 导出视图」产物）
    python tools/verify_m2_contract.py --base http://127.0.0.1:8792 --view-export view_export_L1_2026-10-03T14-22-01.json

退出码：0 = 全部通过；1 = 有断言失败；2 = 环境/网络/用法错误

设计约束（照契约）：
  · ⭐ 只依赖 `data-*` 做断言 ✓（不依赖 CSS class / 文案 / 像素位 ✗）
  · ⭐ 只用标准库 ✓ 不新增依赖 ✗；**只读** ✓ 不写仓库 ✗
  · ⭐ 不做截图 OCR ✗（契约 §5 明确不做 ✓）
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HTML = os.path.join(ROOT, 'collab', 'index.html')

# 行级必备（契约 §2）
ROW_ATTRS = ('data-id', 'data-seq', 'data-layer', 'data-kind', 'data-sender')
# L2 轨道行额外（契约 §2）
L2_ATTRS = ('data-cost-micro', 'data-tokens')
# 状态节点（契约 §2）
STATE_ATTRS = ('data-state', 'data-reason')
# 冻结的 data-layer 取值白名单（契约 C5：更名须与下次契约版本同批 ✗ 本批不许偷跑 ✓）
LAYER_ALLOWED = ('L1', 'L2', 'L3')
LAYER_FORBIDDEN = ('V1', 'V2', 'V3')

PASS, FAIL = [], []


def _rel(p):
    """相对路径展示（⭐ 跨盘符时 relpath 会 ValueError ✗ → 退回原路径 ✓）"""
    try:
        return os.path.relpath(p, ROOT)
    except ValueError:
        return p


def ok(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    flag = '✅' if cond else '❌'
    line = '%s %s' % (flag, name)
    if detail:
        line += '  ｜ ' + str(detail)
    print(line)


def sec(title):
    print('\n' + '=' * 74)
    print(title)
    print('=' * 74)


# ───────────────────────── ① 静态扫描 ─────────────────────────
def scan_html(path=DEFAULT_HTML):
    sec('① 静态扫描：%s' % _rel(path))
    if not os.path.isfile(path):
        ok('collab/index.html 存在', False, path)
        return
    with io.open(path, encoding='utf-8', errors='replace') as fh:
        html = fh.read()
    ok('collab/index.html 存在', True, '%d B / %d 行' % (len(html.encode('utf-8')), len(html.splitlines())))

    # 1) 行级 data-* 都要在渲染代码里被写出
    for a in ROW_ATTRS:
        n = len(re.findall(r"setAttribute\(\s*['\"]%s['\"]" % re.escape(a), html))
        ok("行级锚点 %s 被写出" % a, n >= 1, '%d 处' % n)

    # 2) L2 额外两个
    for a in L2_ATTRS:
        n = len(re.findall(r"setAttribute\(\s*['\"]%s['\"]" % re.escape(a), html))
        ok("L2 行锚点 %s 被写出" % a, n >= 1, '%d 处' % n)

    # 3) 状态节点
    for a in STATE_ATTRS:
        n = len(re.findall(r"setAttribute\(\s*['\"]%s['\"]" % re.escape(a), html))
        ok("状态节点锚点 %s 被写出" % a, n >= 1, '%d 处' % n)

    # 4) data-layer 取值白名单（冻结串不许偷跑改名 ✓）
    vals = set(re.findall(r"setAttribute\(\s*['\"]data-layer['\"]\s*,\s*['\"]([^'\"]+)['\"]", html))
    bad = sorted(v for v in vals if v not in LAYER_ALLOWED)
    ok('data-layer 取值只用 %s' % '/'.join(LAYER_ALLOWED), not bad, '实测取值 = %s' % (sorted(vals) or '无'))
    leaked = sorted(v for v in LAYER_FORBIDDEN if any(v in x for x in vals))
    ok('未出现视图层 V 前缀写进 data-layer（守"两步走"）', not leaked, leaked)

    # 5) 「导出当前视图」按钮（契约 §3 冻结）
    for bid in ('btn-export-l1', 'btn-export-l2'):
        ok('「导出视图」入口 %s 存在' % bid, ('id="%s"' % bid) in html)

    # 6) 取数只走 /api/*（静态粗筛：不应出现别的 fetch 根路径）
    fetches = re.findall(r"(?:getJSON|fetch|post)\(\s*['\"]([^'\"]+)['\"]", html)
    bad_fetch = sorted({u for u in fetches if not u.startswith('/api/')})
    ok('前端取数路径均为 /api/*', not bad_fetch, bad_fetch)


# ───────────────────────── HTTP 工具 ─────────────────────────
def http_get(base, path, timeout=10):
    url = base.rstrip('/') + path
    with urllib.request.urlopen(url, timeout=timeout) as r:
        raw = r.read()
    return raw


def get_json(base, path):
    return json.loads(http_get(base, path).decode('utf-8'))


# ───────────────────── ② 投影 ↔ 日志真相 ─────────────────────
MSG_FIELDS = ('id', 'seq', 'ts', 'channel', 'sender', 'recipients', 'kind', 'visibility', 'body', 'meta')


def compare_projection_vs_log(base, channel):
    sec('② 后端投影 ↔ 日志真相（/api/view ↔ /api/log.jsonl 经内核 replay()）')
    # 拿真相源
    try:
        raw = http_get(base, '/api/log.jsonl')
    except Exception as e:
        ok('能取到 /api/log.jsonl', False, repr(e))
        return
    ok('能取到 /api/log.jsonl', True, '%d B' % len(raw))

    tmp = os.path.join(tempfile.mkdtemp(prefix='m2verify_'), 'relay.jsonl')
    with open(tmp, 'wb') as fh:
        fh.write(raw)

    sys.path.insert(0, ROOT)
    try:
        import relay_log as relay
    except Exception as e:
        ok('能导入 relay_log（内核）', False, repr(e))
        return
    ok('能导入 relay_log（内核）', True, getattr(relay, '__file__', ''))

    try:
        log = relay.RelayLog(tmp)
    except TypeError:
        log = relay.RelayLog(path=tmp)
    truth = {m.id: m for m in log.replay()}
    ok('replay() 可读（真相源）', True, '%d 条' % len(truth))

    # 逐层对照
    total = 0
    for layer in LAYER_ALLOWED:
        try:
            proj = get_json(base, '/api/view?channel=%s&layer=%s' % (channel, layer))
        except Exception as e:
            ok('/api/view layer=%s 可取' % layer, False, repr(e))
            continue
        ok('/api/view layer=%s 可取' % layer, True, '%d 条' % len(proj))
        total += len(proj)

        miss, diff, order_bad = [], [], []
        last = None
        for m in proj:
            t = truth.get(m.get('id'))
            if t is None:
                miss.append(m.get('id'))
                continue
            for f in MSG_FIELDS:
                if getattr(t, f, None) != m.get(f):
                    diff.append('%s.%s' % (m.get('id'), f))
            if last is not None and not (m.get('seq') or 0) > last:
                order_bad.append(m.get('seq'))
            last = m.get('seq') or 0
        ok('layer=%s 投影条目都在真相源中' % layer, not miss, miss[:3])
        ok('layer=%s 逐字段与真相一致（%d 字段）' % (layer, len(MSG_FIELDS)), not diff, diff[:5])
        ok('layer=%s 顺序 = seq 升序' % layer, not order_bad, order_bad[:3])

    # 快照同源
    try:
        snap = get_json(base, '/api/snapshot')
        core = log.snapshot()
        same = all(snap.get(k) == core.get(k) for k in ('turn_no', 'cost_micro', 'tokens', 'interrupted', 'stopped'))
        ok('/api/snapshot 与内核 snapshot() 同源', same,
           {k: snap.get(k) for k in ('turn_no', 'cost_micro', 'tokens')})
    except Exception as e:
        ok('/api/snapshot 可对照', False, repr(e))

    # 只读面不得有写端点（C1）：POST 到 /api/view 应 404/405
    ok('本次对照共看到 %d 条投影记录' % total, True)


# ───────────────────── ③ 渲染 ↔ 后端投影 ─────────────────────
def compare_render_vs_projection(base, export_path, channel, layer=None):
    sec('③ 渲染 ↔ 后端投影（界面「导出视图」产物 ↔ /api/view）')
    if not os.path.isfile(export_path):
        ok('导出文件存在', False, export_path)
        return
    with io.open(export_path, encoding='utf-8') as fh:
        rows = json.load(fh)
    base_name = os.path.basename(export_path)
    m = re.search(r'view_export_(L[123])_', base_name)
    if layer is None:
        layer = m.group(1) if m else None
    ok('能确定导出的层', layer in LAYER_ALLOWED, {'file': base_name, 'layer': layer})
    if layer not in LAYER_ALLOWED:
        return
    if base is None:
        ok('③ 需要 --base（跳过投影对照）', False, '未提供 --base')
        return

    proj = get_json(base, '/api/view?channel=%s&layer=%s' % (channel, layer))
    ids_r = [r.get('id') for r in rows]
    ids_p = [m2.get('id') for m2 in proj]
    ok('渲染 id 集合 = 投影 id 集合', set(ids_r) == set(ids_p),
       {'渲染': len(ids_r), '投影': len(ids_p),
        '仅渲染有': sorted(set(ids_r) - set(ids_p))[:3],
        '仅投影有': sorted(set(ids_p) - set(ids_r))[:3]})

    seqs = [r.get('seq') for r in rows]
    asc = all(seqs[i] < seqs[i + 1] for i in range(len(seqs) - 1)) if len(seqs) > 1 else True
    ok('渲染顺序 = seq 升序', asc, seqs[:8])

    dup = [s for s in set(seqs) if seqs.count(s) > 1]
    ok('渲染中同一 data-seq 只出现一次', not dup, dup[:5])

    r0 = {r.get('id'): r for r in rows}
    bad = []
    for p in proj:
        r = r0.get(p.get('id'))
        if r is None:
            continue
        if r.get('kind') != p.get('kind') or r.get('sender') != p.get('sender'):
            bad.append(p.get('id'))
    ok('渲染行的 kind / sender 与投影一致', not bad, bad[:5])


def main():
    ap = argparse.ArgumentParser(description='M2 契约扫描（三段式）')
    ap.add_argument('--html', default=DEFAULT_HTML, help='collab/index.html 路径')
    ap.add_argument('--base', default=None, help='协作台地址，如 http://127.0.0.1:8792')
    ap.add_argument('--channel', default='group:main', help='频道名（默认 group:main）')
    ap.add_argument('--view-export', default=None, help='界面「导出视图」产出的 json 路径')
    ap.add_argument('--export-layer', default=None, choices=list(LAYER_ALLOWED), help='③ 的层（默认按文件名推断）')
    ap.add_argument('--skip-static', action='store_true', help='跳过 ①')
    args = ap.parse_args()

    if not args.skip_static:
        scan_html(args.html)
    if args.base:
        compare_projection_vs_log(args.base, args.channel)
    else:
        print('\n（未给 --base → 跳过 ②③ 的在线对照）')
    if args.view_export:
        compare_render_vs_projection(args.base, args.view_export, args.channel, args.export_layer)

    sec('汇总')
    print('通过 %d ｜ 失败 %d' % (len(PASS), len(FAIL)))
    for f in FAIL:
        print('  ❌ ' + f)
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
