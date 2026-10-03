# -*- coding: utf-8 -*-
"""P0 护栏：**点 DSH 不得冻结主线程**（Owner 2026-10-04 01:53 实测"程序未响应"✗）

微信侧 `WX-桌宠-20261004-14` 确诊：旧实现主线程**同步**调 `open_panel()`（内部
`sleep(2)` 轮询最长 45s ＋ PowerShell 冷启动 ＋ 必要时**重启 DSH 服务** ✓）
→ 最坏 ≈60 秒 → Windows 判"程序未响应"✗

⭐ 本文件用 **AST 查真码** ✗（不查关键词 ✗ —— 否则会被注释／docstring 骗到 ✓，
   我自己就踩过这个自指坑 ✓）
"""
import ast
import io
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PET = os.path.join(REPO, 'desktop_pet.py')


def _src():
    return io.open(PET, encoding='utf-8').read()


def _fn(name):
    for n in ast.walk(ast.parse(_src())):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError('找不到 %s ✗' % name)


def _calls(fn):
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            nm = getattr(f, 'id', None) or getattr(f, 'attr', None)
            if nm:
                out.append(nm)
    return out


# ── 1. ⭐ 主线程函数里**不得**直接调 open_panel ✗ 也不得 sleep ✗ ────────
def test_main_thread_does_not_call_open_panel():
    c = _calls(_fn('_open_dsh_panel'))
    assert 'open_panel' not in c, '⛔ 主线程函数不得直接调 open_panel ✗（会冻结界面 ✗）'
    assert 'sleep' not in c, '⛔ 主线程不得 sleep ✗'
    assert 'Thread' in c, '⭐ 必须起后台线程 ✓'


# ── 2. ⭐ 实际调用必须在 worker 里 ✓ 且先问用户 ✓ ────────────────────
def test_worker_calls_panel_and_auto_starts():   # ⭐ 改：没跑就自动启动 ✓（不再先问 ✗）
    fn = _fn('_dsh_open_worker')
    c = _calls(fn)
    assert 'open_panel' in c, '⭐ 真调用应在 worker ✓'
    assert 'is_serving' in c, '⭐ 先探测服务 ✓'
    seg = ast.get_source_segment(_src(), fn) or ''
    # ⭐ Owner 02:29 实测："先问"的确认框在后台线程里**没弹出来** ✗ → 服务从未启动 ✗
    #    → 改为**服务没跑就自动启动** ✓（界面已不冻 ✓）
    assert 'is_serving' in seg, '⭐ 必须先探测服务状态 ✓'
    assert '_notify' in seg, '⭐ 状态提示走状态条 ✓（不弹气泡 ✗）'
    assert 'ui_call_signal' in seg, '⭐ 结果须经现成"回主线程"通道 ✓'


# ── 3. ⭐ 参数规格：默认不自动启动 ＋ 超时 10s ＋ 轮询 0.3s ────────────
def test_panel_signature_spec():
    import inspect
    import sys
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    import dsh_panel
    p = inspect.signature(dsh_panel.open_panel).parameters
    assert p['allow_start'].default is False, '⭐ 默认不得自动启动 ✗'
    # ⭐ 修正（微信侧 2026-10-04 03:4x，`WX-桌宠-20261004-25`）：
    #    原文写死 `== 10` ✗ —— 而 `876d17b` 已把默认值改成 **40**（⭐ 实测冷启动需 ~19s，
    #    10s 那次真的线上失败 ✗）⇒ 护栏与实现**脱钩** → 全量**红了一条**而没人看见 ✗
    #    ⇒ ⭐ 改为**下限**：只锁"够冷启动用"这一契约（19s → 留 1.5x 余量），
    #    ⛔ 不再写死具体数字 ✗（否则改一次值就要改一次护栏，护栏反成噪声 ✗）
    assert p['timeout_ready'].default >= 30, \
        '⭐ 超时下限须 ≥30s（冷启动实测 ~19s，见 876d17b）✓ 当前 %r' % p['timeout_ready'].default
    assert p['poll'].default == 0.3, '⭐ 轮询粒度 0.3s ✓'


# ── 4. ⭐ 探针有牙：旧实现用同一套检查**必须**判红 ✗ ───────────────────
def test_guard_has_teeth_on_old_implementation():
    old = ast.parse(
        "def _open_dsh_panel(self):\n"
        "    try:\n"
        "        from dsh_panel import open_panel\n"
        "        ok, msg = open_panel()\n"
        "    except Exception as exc:\n"
        "        ok, msg = False, repr(exc)\n").body[0]
    assert 'open_panel' in _calls(old), \
        '⛔ 护栏对旧实现未判红 ✗ ＝ 空扫 ✗（护栏无效 ✗）'
