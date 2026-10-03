# -*- coding: utf-8 -*-
"""Owner 02:13「两个入口点了没效果」的根因护栏（`T` 局部别名陷阱 ✓）

事故：`T` 是菜单函数里的**局部别名**（`T = self._t` ✓），我新写的方法里没有它 ✗
     → `NameError` 被 `except` 吞掉 ✗ → **点菜单什么都不发生** ✗（pet.log 实证 ✓）

⭐ 两条教训写成两类护栏：
  ① **作用域护栏**：任何用 `T(` 的函数必须自己定义 `T = self._t` ✗（全局扫 ✓ 防复发 ✓）
  ② ⭐ **能真跑的用例**：直接调用那两个入口方法 ✓ —— 我上一版只有 AST 静态检查 ✗
     所以"测试绿／真机红" ✗（今晚第七例同族 ✓）
"""
import ast
import io
import os
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
PET = os.path.join(REPO, 'desktop_pet.py')


# ── ① ⭐ 作用域护栏：bare `T(` 只能出现在定义了 `T = self._t` 的函数里 ✗ ──
def test_no_bare_T_outside_alias_scope():
    src = io.open(PET, encoding='utf-8').read()
    tree = ast.parse(src)
    # 找出定义了 `T = self._t` 的函数行区间
    defs = []
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef):
            for sub in ast.walk(n):
                if isinstance(sub, ast.Assign) and any(
                        getattr(t, 'id', None) == 'T' for t in sub.targets):
                    defs.append((n.lineno, getattr(n, 'end_lineno', n.lineno)))
                    break
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef):
            # 该函数内是否用了 bare T(
            uses = any(isinstance(c, ast.Call) and getattr(c.func, 'id', None) == 'T'
                       for c in ast.walk(n))
            if not uses:
                continue
            defines = any(a <= n.lineno and getattr(n, 'end_lineno', n.lineno) <= b for a, b in defs)
            if not defines:
                bad.append(n.name)
    assert not bad, ('⛔ 这些函数用了 bare `T(` 却没定义 `T = self._t` ✗ '
                     '（会被 NameError 静默吞掉 ✗）：%s' % bad)


def test_scope_guard_has_teeth():
    """⭐ 有牙：人造样本必须判红 ✗"""
    sample = ast.parse("def f(self):\n    return T('x')\n")
    fn = sample.body[0]
    uses = any(isinstance(c, ast.Call) and getattr(c.func, 'id', None) == 'T'
               for c in ast.walk(fn))
    assert uses, '⛔ 护栏未能识别 bare T( ✗ ＝ 空扫 ✗'


# ── ② ⭐ 真跑：直接调用两个入口方法（stub self ✓ 不开窗口 ✓）────────────
class _Sig:
    def __init__(self):
        self.items = []

    def emit(self, fn):
        self.items.append(fn)
        try:
            fn()                       # ⭐ 真执行（否则 busy 永不复位 → 测试空等 15s ✗）
        except Exception:
            pass


class _Stub:
    """最小替身：只提供两个入口方法真正会用到的成员 ✓"""
    _collab_busy = False
    _dsh_busy = False

    def __init__(self, confirm=False):
        self.msgs = []
        self.config = {}
        self.confirm = confirm
        self.ui_call_signal = _Sig()

    def _notify(self, m, ms=None, **kw):      # ⭐ 新代码会传 ms= ✓
        self.msgs.append(m)

    def say_plain(self, m):
        self.msgs.append(m)

    def _t(self, key):
        return key                     # 只回 key ✓ 不需要真文案 ✓

    def _request_confirm(self, m):
        return self.confirm


def _run(name, stub):
    """在**后台线程**里调（方法内部会再起线程 ✓ 用 join 等它 ✓）。"""
    import desktop_pet as dp
    cls = None
    for obj in vars(dp).values():
        if isinstance(obj, type) and hasattr(obj, name):
            cls = obj
            break
    assert cls is not None, '找不到承载 %s 的类 ✗' % name
    fn = getattr(cls, name)
    # ⭐ 把 worker 方法也绑到 stub 上（否则 self._xxx_worker 不存在 ✗ —— 本桩踩过 ✓）
    for w in ('_collab_worker', '_dsh_open_worker', '_collab_done', '_dsh_open_done'):
        if hasattr(cls, w):
            setattr(stub, w, __import__('types').MethodType(getattr(cls, w), stub))
    # ⚠️ 上限压到各 3s（真流程 <1s ✓）—— 异常时只会**响亮失败** ✗ 不会坐等 30s ✗
    t = threading.Thread(target=fn, args=(stub,), daemon=True)
    t.start()
    t.join(timeout=3)
    for _ in range(12):                # 最多 3s ✓
        threading.Event().wait(0.25)
        if (not getattr(stub, '_collab_busy', False)) and (not getattr(stub, '_dsh_busy', False)):
            break


def test_open_collab_runs_without_name_error(monkeypatch):
    """⭐ 真调 `_open_collab`：不得出现 NameError ✗（旧版必炸 ✗）

    ⚠️ 把探测打桩 ✗（否则每次冷启 PowerShell ✓ 单个用例要 12s ✗ —— 本件要验的是**作用域** ✓）
    """
    import collab_panel as _cp
    monkeypatch.setattr(_cp, '_probe', lambda *a, **k: False, raising=False)
    # ⭐ 修正（微信侧 2026-10-04 03:5x，`WX-桌宠-20261004-26`）：⭐ **必须同时打桩 `open_collab`** ✗
    #    —— `a2caabc` 把 `_collab_worker` 改成「服务没跑就**自动启动**」（⛔ 不再先问 ✗），
    #    故本用例的 `_Stub(confirm=False)` **已拦不住启动** ✗ → ⭐ 实测本用例**真起了服务**
    #    且**不回收**（跑完残留 `relay_server.py` 占住 **8792** ＋ 污染仓库 `collab/relay.log` ✗）。
    #    同文件第三个用例早就打桩了此路径并注明「否则会真去起服务…且会留孤儿进程」✓，
    #    首例在 a2caabc 改行为时没同步更新 ✗。⭐ 本用例验的是**作用域（T 未定义）** ✓，打桩不影响其意图 ✓。
    monkeypatch.setattr(_cp, 'open_collab',
                        lambda *a, **k: (False, '（桩：未启动）'), raising=False)
    stub = _Stub(confirm=False)        # 不启动服务 ✓
    _run('_open_collab', stub)
    assert stub.msgs, '⭐ 至少应给一次提示（说明没静默 ✗）'
    joined = ' | '.join(str(x) for x in stub.msgs)
    assert "name 'T' is not defined" not in joined, '⛔ T 未定义 ✗：%s' % joined
    assert 'collab' in joined or '未自动启动' in joined or '取消' in joined, \
        '⭐ 提示应与协作台相关 ✓：%s' % joined


def test_open_dsh_panel_runs_without_name_error(monkeypatch):
    import dsh_adapter as _ad
    monkeypatch.setattr(_ad, 'is_serving', lambda *a, **k: False, raising=False)
    stub = _Stub(confirm=False)
    _run('_open_dsh_panel', stub)
    joined = ' | '.join(str(x) for x in stub.msgs)
    assert "name 'T' is not defined" not in joined, '⛔ T 未定义 ✗：%s' % joined


def test_ui_call_signal_used_for_callback(monkeypatch):
    """⭐ 结果必须经 `ui_call_signal` 回主线程 ✓（⛔ 不在 worker 里直接碰 UI ✗）"""
    import collab_panel as _cp
    monkeypatch.setattr(_cp, '_probe', lambda *a, **k: False, raising=False)
    # ⭐ 打桩真实启动：否则会**真去起服务**（十几秒 ✗ 用例等不到 ✓ 且会留孤儿进程 ✗）
    monkeypatch.setattr(_cp, 'open_collab',
                        lambda *a, **k: (False, '（桩：未启动）'), raising=False)
    stub = _Stub(confirm=False)
    _run('_open_collab', stub)
    assert stub.ui_call_signal.items, '⭐ 应通过 ui_call_signal 回主线程 ✓'
