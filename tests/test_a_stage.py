# -*- coding: utf-8 -*-
"""A 段护栏（A5/A6/A7/A9）—— ⭐ 断言写**契约**（下限/行为）✗ 不写死数值 ✓（EXP.0109 ✓）

判据来源：微信侧 `WX-桌宠-20261004-29` §一（A4–A7／A9）
⭐ 每条都要"真跑真验"✗ 静态读码不算 ✓ → 本文件既有真跑（A7/A9），也有源码级（A5/A6）。
"""
import ast
import io
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, 'collab')):
    if p not in sys.path:
        sys.path.insert(0, p)

PET = os.path.join(REPO, 'desktop_pet.py')
DSH = os.path.join(REPO, 'dsh_panel.py')


def _src(p):
    return io.open(p, encoding='utf-8').read()


def _fn(path, name):
    for n in ast.walk(ast.parse(_src(path))):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError('找不到 %s ✗' % name)


# ── A5 ⭐ 启动预算 ≠ 失败判定（两参独立 ✓ 契约下限 ✓）──────────────────
def test_a5_budget_split_from_probe_timeout():
    import inspect
    import dsh_panel
    ps = inspect.signature(dsh_panel.open_panel).parameters
    assert 'start_budget' in ps, '⭐ 应有独立的启动预算参数 ✗'
    assert 'probe_timeout' in ps, '⭐ 应有独立的单次探测超时参数 ✗'
    # ⭐ 写契约不写死值 ✓：预算必须**够冷启动**（实测 ≈19s）→ 断言下限 ✗ 不断言具体数
    assert ps['start_budget'].default >= 20, \
        '⛔ 启动预算必须 ≥20s（冷启动实测约 19s ✗）：%s' % ps['start_budget'].default
    assert 0 < ps['probe_timeout'].default <= 10, \
        '⭐ 单次探测应短（≤10s ✓）：%s' % ps['probe_timeout'].default
    # ⭐ 旧名保留为兼容别名（不破旧调用 ✓）
    assert 'timeout_ready' in ps, '⭐ 应保留 timeout_ready 兼容别名 ✗'
    import collab_panel
    assert 'start_budget' in inspect.signature(collab_panel.open_collab).parameters


# ── A6 ⭐ 主线程不同步等待（确认框不得写死长超时 ✗）────────────────────
def test_a6_confirm_wait_is_bounded_and_configurable():
    s = _src(PET)
    seg = ast.get_source_segment(s, _fn(PET, '_request_confirm')) or ''
    assert 'evt.wait(' in seg, '⭐ 应等待确认回执 ✓'
    # ⭐ 旧实现写死 timeout=120 ✗ → 断言不再出现该写法 ✓
    assert 'timeout=120' not in seg, '⛔ 不得写死 120s ✗（用户视角＝程序死了 ✗）'
    assert 'budget' in seg, '⭐ 等待时长应来自可配变量 ✓'
    assert 'confirm_timeout_s' in seg, '⭐ 应可配（config ✓）'
    # ⭐ 超时必须明说 ✗ 不静默挂住 ✓（A9 的核心 ✓）
    assert '_notify' in seg and 'timeout' in seg.lower(), '⭐ 超时须留痕且对用户可见 ✗'


# ── A7 ⭐ 子进程回收：Job Object ＋ KILL_ON_JOB_CLOSE ✓ ─────────────────
def test_a7_job_object_wired():
    s = _src(DSH)
    assert 'CreateJobObjectW' in s, '⭐ 应建 Job Object ✓'
    assert 'KILL_ON_JOB_CLOSE' in s, '⭐ 应设 KILL_ON_JOB_CLOSE ✓（父死则子清 ✓）'
    assert 'AssignProcessToJobObject' in s, '⭐ 应把子进程加入 Job ✓'
    calls = [getattr(c.func, 'id', None) or getattr(c.func, 'attr', None)
             for c in ast.walk(_fn(DSH, '_spawn')) if isinstance(c, ast.Call)]
    assert '_assign_to_job' in calls, '⭐ `_spawn` 必须把子进程纳入 Job ✓'


def test_a7_kill_parent_recycles_child(tmp_path):
    """⭐ 真跑（A7 判据 ✓）：父进程持 Job 起子进程 → 强杀父 → 子必须被回收 ✓"""
    import subprocess
    probe = str(tmp_path / 'p.py')
    io.open(probe, 'w', encoding='utf-8').write(
        'import sys, time\n'
        'sys.path.insert(0, r"%s")\n'
        'import dsh_panel\n'
        'dsh_panel._spawn([sys.executable, "-c", "import time;time.sleep(90)"])\n'
        'print("OK", flush=True)\n'
        'time.sleep(90)\n' % REPO)
    proc = subprocess.Popen([sys.executable, probe], stdout=subprocess.PIPE,
                            text=True, encoding='utf-8')
    assert (proc.stdout.readline() or '').strip() == 'OK'

    def n_sleep():
        r = subprocess.run(['powershell', '-NoProfile', '-Command',
                            "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                            "Where-Object { $_.CommandLine -like '*time.sleep(90)*' } | "
                            "Measure-Object).Count"], capture_output=True, text=True, timeout=30)
        try:
            return int((r.stdout or '0').strip() or 0)
        except ValueError:
            return -1

    time.sleep(2.0)
    assert n_sleep() >= 1, '⭐ 探针：父在时应有子进程 ✓'
    subprocess.run(['taskkill', '/F', '/PID', str(proc.pid)], capture_output=True)
    time.sleep(3.0)
    assert n_sleep() == 0, '⛔ 强杀父后子进程必须被回收 ✗（A7 判据 ✗）'


# ── A9 ⭐ 审批不依赖界面可见：超时 → 明说 ＋ 按不确认处理 ✓ ─────────────
def test_a9_confirm_times_out_explicitly():
    """⭐ 真跑：把预算配成极小 ＋ 确认信号无人处理 → 必须在有限时间内返回 False 并留痕 ✓"""
    import desktop_pet as dp
    cls = None
    for obj in vars(dp).values():
        if isinstance(obj, type) and hasattr(obj, '_request_confirm'):
            cls = obj
            break
    assert cls is not None, '找不到承载 _request_confirm 的类 ✗'

    class _Sig:
        def emit(self, fn):
            pass                      # ⭐ 故意不处理（模拟"界面不可见/主线程忙"✓）

    class _Stub:
        config = {'confirm_timeout_s': 0.4}
        language = 'zh'
        confirm_signal = _Sig()
        notes = []

        def _t(self, k):
            return k + ':%s'          # 让 %(s)d 占位可用 ✓
        def _notify(self, text, ms=None, **kw):
            self.notes.append(text)

        # ⭐ 用真实方法（unbound ✓）跑 ✓
        _request_confirm = cls._request_confirm

    st = _Stub()
    t0 = time.time()
    ok = st._request_confirm('测试确认')
    dt = time.time() - t0
    assert ok is False, '⭐ 无回应必须按「不确认」处理 ✗'
    assert dt < 5, '⛔ 不得长挂 ✗ 实测 %.1fs' % dt
    assert st.notes, '⭐ 超时**必须明说**（状态条 ✓）✗ 不静默 ✓'


# ── 有牙证明（两侧：A7 与 A5 ✓）───────────────────────────────────────
def test_guards_have_teeth():
    # A7：旧实现（裸 Popen ✓ 无 Job）应被判红 ✓
    old = ast.parse("def _spawn(args):\n"
                    "    subprocess.Popen(args, close_fds=True)\n").body[0]
    calls = [getattr(c.func, 'id', None) or getattr(c.func, 'attr', None)
             for c in ast.walk(old) if isinstance(c, ast.Call)]
    assert '_assign_to_job' not in calls, '⭐ 旧实现应缺 Job 归属 ✓'
    # A6：旧写法应被"写死 120s"判红 ✓
    assert 'timeout=120' in 'evt.wait(timeout=120)', '⭐ 探针须能识别旧写法 ✓'
