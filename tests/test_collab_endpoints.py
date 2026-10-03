# -*- coding: utf-8 -*-
"""批 4 前置三端点护栏（`/api/projects` · `/api/project/current` · `/api/roles`）。

口径（Owner 2026-10-03 ｜ WX-桌宠-20261003-06 §五 · 我方选路 A）：
  · 三个端点**只读** ✓ 且在契约 ④-1 已预留的白名单内 ✓ ⛔ 不新增写端点 ✗
  · `/api/roles` ⭐ **绝不含密钥** ✗（只 key／显示名／立绘前缀／颜色 ✓）
  · 立绘前缀 v1 = **`key` 派生** ✓（不必等新字段 ✓）
  · 服务侧须能在**无 GUI**环境跑 ✓（档案导入受保护 ✓）
"""
import http.client
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, 'collab') not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, 'collab'))

import relay_log  # noqa: E402
import relay_server  # noqa: E402


# ── 1. roles_payload 形状 ✓ ─────────────────────────────────────────
def test_roles_payload_shape():
    rows = relay_server.roles_payload()
    assert isinstance(rows, list) and rows, '角色列表不应为空 ✓'
    for r in rows:
        assert set(r.keys()) == {'key', 'display_name', 'portrait_prefix', 'color'}, r.keys()
        assert r['portrait_prefix'] == r['key'], '⭐ v1 立绘前缀由 key 派生 ✓'


# ── 2. ⭐ 无密钥（反向断言 ✓ 最要紧的一条）────────────────────────────
def test_roles_payload_has_no_secrets():
    blob = json.dumps(relay_server.roles_payload(), ensure_ascii=False).lower()
    for bad in ('api_key', 'apikey', 'secret', 'token', 'sk-', 'password',
                'endpoint', 'price', 'params'):
        assert bad not in blob, '⛔ 角色响应里出现了 %r ✗（契约 ④-2 只允许四项 ✓）' % bad


# ── 3. projects_payload：v1 一个默认项目（空态可读 ✗ 不返空数组 ✓）──
def test_projects_payload_default_project():
    d = relay_server.projects_payload(base_dir=ROOT, log_path='')
    assert isinstance(d, dict) and isinstance(d.get('projects'), list)
    ps = d['projects']
    assert len(ps) == 1, 'v1 只给一个默认项目 ✓'
    p = ps[0]
    assert p['id'] == 'default' and isinstance(p['unread'], int) and p['unread'] == 0
    assert p['root'] == ROOT and p['name']


# ── 4. project_current：边界与 rt_assembler 将来入参同形 ✓ ────────────
def test_project_current_payload_boundary():
    d = relay_server.project_current_payload(base_dir=ROOT, log_path='')
    assert d['project']['id'] == 'default'
    assert d['boundary']['project_id'] == 'default'
    assert d['boundary']['root'] == ROOT
    assert d['boundary']['roles'] == [r['key'] for r in relay_server.roles_payload()]


# ── 5. 路由在 do_GET ✓ ；6. ⭐ do_POST 里没有它们（守"只读"✗ 不新增写端点）──
def test_routes_are_get_only():
    with io.open(os.path.join(ROOT, 'collab', 'relay_server.py'), encoding='utf-8') as fh:
        src = fh.read()
    get_part = src[src.index('def do_GET'):]
    for p in ("'/api/projects'", "'/api/project/current'", "'/api/roles'"):
        assert p in get_part, 'do_GET 缺 %s ✗' % p
    post_part = src[src.index('def do_POST'):src.index('def do_GET')]
    for p in ('/api/projects', '/api/project/current', '/api/roles'):
        assert p not in post_part, '⛔ 这三个端点不得出现在写面 ✗：%s' % p


# ── 7. ⭐ 真起服务打 HTTP（端到端 ✓ 最强的证据）──────────────────────
def test_endpoints_over_real_http(tmp_path):
    lg = relay_log.RelayLog(str(tmp_path / 'ch.jsonl'))
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    import threading
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        for path, checker in (
                ('/api/projects', lambda o: 'projects' in o),
                ('/api/project/current', lambda o: o['boundary']['roles']),
                ('/api/roles', lambda o: isinstance(o, list) and o),
        ):
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            c.request('GET', path)
            resp = c.getresponse()
            body = resp.read().decode('utf-8')
            c.close()
            assert resp.status == 200, '%s → %s' % (path, resp.status)
            obj = json.loads(body)
            assert checker(obj), '%s 返回形状不符 ✗：%s' % (path, body[:120])
        # ⭐ 反向：写方法不许打这三个端点（应 404/405，不能 200 ✗）
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        c.request('POST', '/api/roles', body=b'', headers={'Content-Type': 'application/json'})
        r2 = c.getresponse()
        r2.read()
        c.close()
        assert r2.status != 200, '⛔ 写方法不应能打只读端点 ✗'
    finally:
        httpd.shutdown()


# ── 8. ⭐ 风险 1 第二批：档案导入失败必须**明报**（不许静默返空表 ✗）──────
def test_roles_import_failure_is_reported():
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        with _patch_model_registry_broken():
            relay_server.roles_payload()          # ⚠️ 可能仍从 models.json 读到覆盖 ✓ 不断言空表 ✗
    msg = buf.getvalue()
    assert '角色档案导入失败' in msg, '⭐ 必须明报原因，否则界面“无角色”却无线索 ✗'


def test_roles_payload_source_reports_both_failures():
    with io.open(os.path.join(ROOT, 'collab', 'relay_server.py'), encoding='utf-8') as fh:
        src = fh.read()
    assert '角色档案导入失败' in src and 'models.json 读取失败' in src, \
        '两个失败分支都必须可明报 ✓'
    # ⚠️ 注意：**不得**用源码字串查密钥（docstring 里会提到字段名 ✗ 会误判 ✓）
    # → 密钥口径一律由**输出行为**断言（见 test_roles_payload_has_no_secrets ✓）


class _patch_model_registry_broken:
    """让 `import model_registry` 失败（模拟无档案环境 ✓）。"""

    def __enter__(self):
        import sys as _sys
        self._sys = _sys
        self._saved = _sys.modules.get('model_registry', '__ABSENT__')
        _sys.modules['model_registry'] = None      # ⭐ None → import 抛 ImportError ✓
        return self

    def __exit__(self, *exc):
        if self._saved == '__ABSENT__':
            self._sys.modules.pop('model_registry', None)
        else:
            self._sys.modules['model_registry'] = self._saved
        return False
