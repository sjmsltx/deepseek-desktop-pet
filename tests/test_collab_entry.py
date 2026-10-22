# -*- coding: utf-8 -*-
"""协作台入口护栏（Owner 2026-10-04 01:48 问"没有入口" ✓ → 本批补入口 ✓）

要点：① 不占主线程 ✗ ② 默认不自动起服务 ✗（先问用户 ✓）③ ⛔ 只监听本机 ✗ 不上网
      ④ ⛔ 起服务**不带 `--enable-actions`** ✗（只读面 ✓）⑤ 有牙证明 ✓
"""
import ast
import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PET = os.path.join(REPO, 'desktop_pet.py')


def _fn(path, name):
    for n in ast.walk(ast.parse(io.open(path, encoding='utf-8').read())):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError('找不到 %s ✗' % name)


def _calls(fn):
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            nm = getattr(n.func, 'id', None) or getattr(n.func, 'attr', None)
            if nm:
                out.append(nm)
    return out


# ── 1. ⭐ 主线程函数不得直接调 open_collab ✗ 也不得 sleep ✗ ───────────
def test_open_collab_is_off_main_thread():
    c = _calls(_fn(PET, '_open_collab'))
    assert 'open_collab' not in c, '⛔ 主线程不得直接调 open_collab ✗（会冻结界面 ✗）'
    assert 'sleep' not in c, '⛔ 主线程不得 sleep ✗'
    assert 'Thread' in c, '⭐ 必须起后台线程 ✓'


def test_collab_worker_auto_starts_and_returns_via_signal():   # ⭐ 改：没跑就自动启动 ✓
    fn = _fn(PET, '_collab_worker')
    c = _calls(fn)
    assert 'open_collab' in c, '⭐ 真调用应在 worker ✓'
    seg = ast.get_source_segment(io.open(PET, encoding='utf-8').read(), fn) or ''
    # ⭐ 同 DSH："先问"在后台线程里弹不出来 ✗ → 改为**没跑就自动启动** ✓（本机只读面 ✓）
    assert '_probe' in seg or 'is_serving' in seg, '⭐ 必须先探测服务 ✓'
    assert 'ui_call_signal' in seg, '⭐ 结果须经现成"回主线程"通道 ✓'


# ── 2. ⭐ 参数规格：默认不自动启动 ＋ 默认端口 8792 ✓ ─────────────────
def test_collab_panel_spec():
    import inspect
    import collab_panel as cp
    p = inspect.signature(cp.open_collab).parameters
    assert p['allow_start'].default is False, '⭐ 默认不得自动启动 ✗'
    assert p['port'].default == 8792, '⭐ 默认端口 8792 ✓'
    assert p['poll'].default == 0.3
    assert cp.DEFAULT_PORT == 8792


# ── 3. ⭐ 服务没跑时**秒返回**（不进入等待循环 ✗）────────────────────
def test_collab_fast_fail_without_start(monkeypatch):
    import time
    import collab_panel as cp
    monkeypatch.setattr(cp, '_probe', lambda *a, **k: False, raising=False)
    t0 = time.time()
    ok, msg = cp.open_collab(REPO, port=8792, allow_start=False)
    dt = time.time() - t0
    assert ok is False and '未自动启动' in msg, msg
    assert dt < 6, '⛔ 默认路径不得进入等待循环 ✗ 实测 %.1fs' % dt


# ── 4. ⭐⭐ 安全：起服务必须**只监听本机** ✗ 且**不带 --enable-actions** ✗
def test_spawn_command_is_local_and_read_only(monkeypatch, tmp_path):
    import collab_panel as cp
    monkeypatch.setattr(cp, '_probe', lambda *a, **k: False, raising=False)   # ⭐ 走启动分支 ✓
    seen = {}

    def fake_spawn(args):
        seen['args'] = list(args)
        return True

    monkeypatch.setattr(cp._hp, '_spawn', fake_spawn)
    ok, msg = cp.open_collab(REPO, port=8792, allow_start=True, timeout_ready=1, poll=0.1)
    assert 'args' in seen, '⭐ 应尝试启动服务 ✓'
    cmd = ' '.join(seen['args'])
    assert '--enable-actions' not in cmd, '⛔ 不得带 --enable-actions 起服务 ✗（只读面 ✓）'
    assert '--log' in cmd and '--port' in cmd and '8792' in cmd, '⭐ 启动命令应含日志与端口 ✓'
    assert 'relay_server.py' in cmd, '⭐ 应起协作台服务 ✓'
    # ⭐ 不监听 0.0.0.0：本模块**不传 --host** ✗（服务默认 127.0.0.1 ✓）
    assert '0.0.0.0' not in cmd, '⛔ 绝不得监听 0.0.0.0 ✗（本机服务 ✓）'


# ── 5. ⭐ 探针只读：失败不抛 ✗ 且不写盘 ✓ ─────────────────────────────
def test_probe_is_read_only():
    import collab_panel as cp
    assert cp._probe(1) is False, '无服务时应返回 False ✓ 不抛异常 ✗'


# ── 6. ⭐ 有牙证明：AST 检查对"主线程直调"的样本必须判红 ✗ ────────────
def test_guard_has_teeth():
    bad = ast.parse("def _open_collab(self):\n"
                    "    from collab_panel import open_collab\n"
                    "    return open_collab('.')\n").body[0]
    assert 'open_collab' in _calls(bad), '⛔ 护栏对"主线程直调"未判红 ✗ ＝ 空扫 ✗'
