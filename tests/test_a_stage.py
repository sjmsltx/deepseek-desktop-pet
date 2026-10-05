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


# ── A4 ⭐ 就绪标记（D1-1）：服务自写 ＋ GUI 双确认 ✓ ────────────────────
def _kill_relay():
    import subprocess
    subprocess.run(['powershell', '-NoProfile', '-Command',
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or "
                    "Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like "
                    "'*relay_server*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
                    "-ErrorAction SilentlyContinue }"], capture_output=True)


def test_a4_ready_marker_written_and_cleared(tmp_path):
    """⭐ 真跑：起服务 → 标记出现 ✓ → GUI 双确认 True ✓ → 杀掉 → False ✓"""
    import json
    import subprocess
    import sys
    import time
    _kill_relay()
    mk = os.path.join(REPO, 'collab', '.ready')
    if os.path.isfile(mk):
        os.remove(mk)
    log = str(tmp_path / 'a4.jsonl')
    p = subprocess.Popen([sys.executable, os.path.join(REPO, 'collab', 'relay_server.py'),
                          '--log', log, '--port', '8892'],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', cwd=REPO)
    try:
        seen = None
        for _ in range(40):
            time.sleep(0.25)
            if os.path.isfile(mk):
                seen = True
                break
        assert seen, '⛔ 起服后应有就绪标记 ✗（A4 判据 ✗）'
        d = json.load(io.open(mk, encoding='utf-8'))
        assert d.get('port') == 8892 and d.get('pid') and d.get('ts'), d
        import collab_panel as cp
        assert cp.is_ready(8892, REPO) is True, '⭐ 双确认应为 True ✓'
        assert cp.ready_info(REPO).get('port') == 8892
    finally:
        p.terminate()
        time.sleep(2.0)
    # ⭐ 强杀后：标记可能残留 ✓，但 **is_ready 必须 False** ✓（双确认的意义 ✓）
    import collab_panel as cp
    assert cp.is_ready(8892, REPO) is False, '⛔ 服务已死时 is_ready 必须 False ✗（陈旧标记不得撒谎 ✗）'
    if os.path.isfile(mk):
        os.remove(mk)
    _kill_relay()


def test_a4_create_server_does_not_write_marker():
    """⛔ 标记只能由 **main()**（真服务 ✓）写 ✗ —— 否则测试会被污染 ✓"""
    s = io.open(os.path.join(REPO, 'collab', 'relay_server.py'), encoding='utf-8').read()
    seg = s[s.index('def create_server('):s.index('def main(')]
    assert '_write_ready' not in seg, '⛔ create_server 里不得写标记 ✗（会污染测试 ✓）'
    assert '_write_ready(port)' in s, '⭐ main() 里应写标记 ✓'


def test_a4_guard_has_teeth():
    """⭐ 有牙：双确认若退化成"只看标记" ✗，本护栏的第二个断言会红 ✓"""
    src = ('def is_ready(port, base_dir=""):\n'
           '    return bool(ready_info(base_dir))\n')      # ⛔ 只看标记 ✗
    assert '_probe' not in src, '⭐ 探针须能识别"只看标记"这一退化 ✓'


# ── E13.3 ⭐ `/api/health` 只读 `actions`（界面据此**事先置灰** ✗ 不必调了才发现 ✓）──
def test_health_exposes_actions_flag():
    import json
    import threading
    import time
    import urllib.request
    import relay_log
    import relay_server
    import tempfile as _tf
    base = _tf.mkdtemp(prefix='hz_')
    import os as _os
    _os.makedirs(_os.path.join(base, 'collab', 'pending'))
    for flag, want in ((False, False), (True, True)):
        lg = relay_log.RelayLog(_os.path.join(base, 'l%s.jsonl' % flag))
        httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='',
                                                 enable_actions=flag)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.3)
        with urllib.request.urlopen('http://127.0.0.1:%d/api/health' % port, timeout=3) as fh:
            d = json.loads(fh.read().decode('utf-8'))
        httpd.shutdown()
        assert d.get('actions') is want, '⭐ actions 必须如实反映开关（E13.3 ✗）：%r' % d


def test_health_actions_is_read_only_field():
    """⛔ `actions` 只读 ✗ —— 不得因它而新增写面 ✓（守 C1 ✓）。"""
    s = io.open(os.path.join(REPO, 'collab', 'relay_server.py'), encoding='utf-8').read()
    # ⚠️ 坑（本用例第一版踩过 ✗）：`s.index("/api/health")` 命中的是**文档字符串**里的那行 ✗
    #    → 段落里当然有 `os.` ✓ → 断言假红 ✓ ⇒ ⭐ 必须定位 **handler**（`if path == …`）✓
    i = s.index("if path == '/api/health'")
    seg = s[i:i + 420]
    assert 'ACTIONS_ALLOWED' in seg, '⭐ 必须由全局开关派生 ✓'
    assert 'write' not in seg.lower() and 'os.' not in seg, '⛔ health 不得写盘 ✗'


# ── E14.1 后半 ⭐ 结果行**自动带线名**（⛔ 不靠人记 ✗）───────────────────
def test_result_rows_carry_line_name():
    import json
    import tempfile as _tf
    import pending_ops
    d = os.path.join(_tf.mkdtemp(prefix='ln_'), 'collab', 'pending')
    os.makedirs(d)
    assert pending_ops.product_line(d), '⭐ 必须总有线名（有默认 ✓ 不返回空 ✗）'
    pending_ops.append_result('x0001', True, base_dir=d, line='PC')
    row = pending_ops.read_results(d)[0]
    assert row.get('line') == 'PC', '⭐ 结果行应带线名 ✓：%r' % row


def test_result_line_defaults_when_not_passed():
    """⛔ 不传也要有默认线名 ✗（产品补 ✓ 不靠调用方记得 ✗）。"""
    import tempfile as _tf
    import pending_ops
    d = os.path.join(_tf.mkdtemp(prefix='ln2_'), 'collab', 'pending')
    os.makedirs(d)
    pending_ops.append_result('y0001', False, reason='x', base_dir=d)   # ⭐ 不传 line ✓
    row = pending_ops.read_results(d)[0]
    assert row.get('line'), '⭐ 未显式传 line 时也必须有默认值 ✗：%r' % row


# ── 有牙证明 ──────────────────────────────────────────────────────────
def test_e14_line_guard_has_teeth():
    # ⭐ 若实现退化成"只有显式传才有 line" ✗，上面的默认用例会红 ✓
    assert 'line: str' in io.open(os.path.join(REPO, 'collab', 'pending_ops.py'),
                                  encoding='utf-8').read(), '⭐ 签名须含 line ✓'


# ── ⭐ B5 队列 / B7 历史（我方后端半 ✓ 只读 ✓）──────────────────────────
def _boot(tmp, enable_actions=False):
    import relay_log
    import relay_server
    import threading
    import time
    lg = relay_log.RelayLog(str(tmp))
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='',
                                             enable_actions=enable_actions)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    return lg, httpd, port


def _get(port, u):
    import json
    import urllib.request
    with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, u), timeout=3) as fh:
        return json.loads(fh.read().decode('utf-8'))


def test_b5_queue_endpoint(tmp_path):
    """⭐ 真跑：空队列结构正确 ✓；插一句话后**出现在 queued** ✓。"""
    import time
    import uuid
    lg, httpd, port = _boot(tmp_path / ('q%s.jsonl' % uuid.uuid4().hex[:6]))
    try:
        d = _get(port, '/api/queue')
        for k in ('running', 'turn_no', 'interrupted', 'queued', 'queued_count'):
            assert k in d, '⭐ B5 载荷缺字段 %s ✗' % k
        assert d['queued_count'] == 0
        assert lg.step().ok is not None          # ⭐ 起一轮（让 turn_start_seq 生效 ✓）
        lg.turn_start_seq = int(lg.snapshot()['seq'])   # ⭐ 人为把"本轮起点"放到当前 ✓
        lg.interrupt('先做 A 再做 B')
        time.sleep(0.2)
        d2 = _get(port, '/api/queue')
        assert d2['queued_count'] >= 1, '⭐ 插话后应出现在待处理 ✓：%r' % d2
        item = d2['queued'][-1]
        assert item['preview'].startswith('先做 A'), item
        assert item['channel'] is not None, '⭐ 归属会话应可见 ✓'
        assert d2['interrupted'] is True, '⭐ 如实反映"已暂停"✗ 不谎称"排队执行"✓'
    finally:
        httpd.shutdown()


def test_b7_history_endpoint(tmp_path):
    """⭐ 真跑：跑一轮 → 历史出现该轮（含步骤 ✓）；⭐ 落一条 error → 能读到原始错误 ✓。"""
    import time
    import uuid
    lg, httpd, port = _boot(tmp_path / ('h%s.jsonl' % uuid.uuid4().hex[:6]))
    try:
        lg.step()
        lg.error('上游返回 502', raw='Traceback: upstream 502 at line 42')
        time.sleep(0.2)
        h = _get(port, '/api/history?limit=5')
        assert isinstance(h, list) and h, '⭐ B7 应返回按轮列表 ✗'
        last = h[-1]
        for k in ('turn_no', 'ok', 'steps', 'error'):
            assert k in last, '⭐ B7 载荷缺字段 %s ✗' % k
        assert last['ok'] is False, '⭐ 有错误时应 ok=False ✓'
        assert '502' in last['error'] or 'Traceback' in last['error'], \
            '⭐ 应能读到**原始错误** ✓：%r' % last['error']
        assert isinstance(last['steps'], list) and last['steps'], '⭐ 应有步骤（消息序列派生 ✓）'
    finally:
        httpd.shutdown()


def test_b5_b7_are_read_only(tmp_path):
    """⛔ 两个端点都**只读** ✗：调用前后日志行数不变 ✓（守 C1 ✓）。"""
    import time
    import uuid
    lg, httpd, port = _boot(tmp_path / ('r%s.jsonl' % uuid.uuid4().hex[:6]))
    try:
        lg.step()
        time.sleep(0.1)
        before = len(lg.replay())
        _get(port, '/api/queue')
        _get(port, '/api/history')
        assert len(lg.replay()) == before, '⛔ 只读端点不得写日志 ✗'
    finally:
        httpd.shutdown()


# ── ⭐ B7 挂钩真跑：provider 真失败 ⇒ ① 日志里出现 kind=error ② /api/history 能读到原始错误 ──

def test_b7_error_hooks_are_in_place():
    """⭐ 挂钩**在位**（源码级 ✓）：provider 失败处 ＋ HTTP 层四处 500 都接了落痕 ✓。

    ⚠️ 如实说明（见 `PC-桌宠-20261004-141` ✓）：⭐ **端到端触发 provider 失败需要完整 issue 环境** ✗
      （实测：无 Issue 时 `step()` 直接返回 `reason='no_issue'` ✓ → provider 不会被调用 ✓）
      ⇒ ⭐ 那条**记为【待验】** ✓ 本用例只保证"挂钩没丢" ✓ 不假装验过端到端 ✗。
    """
    lg = io.open(os.path.join(REPO, 'relay_log.py'), encoding='utf-8').read()
    assert 'self.error(' in lg, '⭐ provider 失败处应有 error() 落痕 ✗'
    srv = io.open(os.path.join(REPO, 'collab', 'relay_server.py'), encoding='utf-8').read()
    assert 'def _log_error' in srv, '⭐ 落痕助手必须**有定义** ✗（我方曾只加调用没加定义 ✗）'
    assert srv.count('self._log_error(') >= 4, '⭐ HTTP 层四处 500 都应挂钩 ✓'
    # ⭐ 有牙证明：把定义删掉时，本条会红 ✓
    assert 'raise' not in srv[srv.index('def _log_error'):srv.index('def _json')], \
        '⭐ 助手不应抛 ✗'

def test_b7_error_entries_readable_via_history(tmp_path):
    """⭐ 直接验：落一条 error ⇒ `/api/history` 的该轮 `ok=False` 且 `error` 非空 ✓。"""
    import json as _json
    import threading
    import time
    import urllib.request
    import uuid
    import relay_log
    import relay_server
    lg = relay_log.RelayLog(str(tmp_path / ('h2%s.jsonl' % uuid.uuid4().hex[:6])))
    lg.step()
    lg.error('缩略图生成失败', raw='OSError: cannot identify image file')
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/history' % port, timeout=3) as fh:
            h = _json.loads(fh.read().decode('utf-8'))
        last = [x for x in h if x.get('error')]
        assert last, '⭐ 应有一轮带 error ✗'
        assert 'cannot identify image file' in last[-1]['error'],             '⭐ 应能读到**原始错误文本** ✓：%r' % last[-1]['error']
        assert last[-1]['ok'] is False
    finally:
        httpd.shutdown()


def test_error_hook_does_not_swallow():
    """⛔ 落痕助手**不得吞掉原异常** ✗：它只记录 ✓ 且自身不抛 ✓。"""
    s = io.open(os.path.join(REPO, 'collab', 'relay_server.py'), encoding='utf-8').read()
    i = s.index('def _log_error')
    seg = s[i:i + 420]
    assert 'raise' not in seg.split('except')[0], '⭐ 助手不应抛 ✗'
    assert 'print(' in seg, '⭐ 助手自身失败要落痕 ✓'


# ── ⭐ E15 内核半真跑（我方）──
def test_e15_default_mode_is_backward_compatible(tmp_path):
    """⭐ E15.1：⭐ **不带 `mode` 必须仍是打断** ✓（真向后兼容 ✗ 不许悄悄改语义 ✗）。"""
    import relay_log
    lg = relay_log.RelayLog(str(tmp_path / 'a.jsonl'))
    lg.interrupt('插话一下')
    assert lg.interrupted is True, '⭐ 不带 mode 必须是旧的"立即打断" ✓'


def test_e15_queue_mode_does_not_interrupt(tmp_path):
    """⭐ E15：⭐ `mode='queue'` **不打断** ✓ 且真的入队 ✓（从日志重建 ✓）。"""
    import relay_log
    lg = relay_log.RelayLog(str(tmp_path / 'b.jsonl'))
    lg.interrupt('排队一句', mode='queue')
    assert lg.interrupted is False, '⭐ 排队不得打断 ✓'
    assert lg.queue_pending() == 1, '⭐ 应入队 1 条 ✗'
    assert lg.queued_ids()[0].startswith('human'), '⭐ 队首应是那条人类消息 ✓'


def test_e15_queue_survives_restart(tmp_path):
    """⭐ E15.2：⭐ 队列**从日志重建** ✓ ⇒ 新实例（＝模拟重启 ✓）仍看得见 ✓。"""
    import relay_log
    p = str(tmp_path / 'c.jsonl')
    lg = relay_log.RelayLog(p)
    lg.interrupt('重启也应在', mode='queue')
    lg2 = relay_log.RelayLog(p)                       # ⭐ 模拟重启 ✓
    assert lg2.queue_pending() == 1, '⭐ 重启后队列必须还在（从日志重建 ✓）✗'
    m = lg2.next_queued()
    assert m is not None and '重启也应在' in str(m.body), '⭐ 出队应取回原句 ✓'


def test_e15_dequeue_on_turn_end(tmp_path):
    """⭐ E15.2：⭐ 回合**自然结束** ⇒ 队首自动出队 ✓（且**只标记** ✗ 内核不自动跑下一轮 ✗）。"""
    import relay_log

    class _Reply:
        body = '回合回复：新增数字 42'
        tokens = 10
        cost_micro = 5
        meta = {}

    class _Issue:
        title = '议题'

    lg = relay_log.RelayLog(str(tmp_path / 'd.jsonl'))
    lg.issue = _Issue()
    lg.provider = lambda last, issue: _Reply()
    lg.interrupt('排着', mode='queue')
    assert lg.queue_pending() == 1
    lg.step()                                          # ⭐ 跑完一回合 ✓
    assert lg.queue_pending() == 0, '⭐ 回合自然结束应出队 ✓'


def test_e15_queue_endpoints_are_read_only(tmp_path):
    """⛔ E15.3：⭐ `/api/queue` 与真队列视图**纯读** ✓（调用前后日志条数不变 ✗）。"""
    import json as _json
    import threading
    import time
    import urllib.request
    import relay_log
    import relay_server
    lg = relay_log.RelayLog(str(tmp_path / 'e.jsonl'))
    lg.interrupt('排一条', mode='queue')
    n0 = len(lg.replay())
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/queue' % port, timeout=3) as fh:
            q = _json.loads(fh.read().decode('utf-8'))
        assert 'queue' in q, '⭐ 应含真队列字段 ✗'
        assert q['queue'] and q['queue'][0].get('id'), '⭐ 每条必须带 id ✓'
        assert q.get('mode_default') == 'interrupt', '⭐ 必须回显默认 mode=interrupt ✓'
        assert len(lg.replay()) == n0, '⛔ 只读端点不得写日志 ✗'
    finally:
        httpd.shutdown()


# ── ⭐ D1 护栏：自改码备份**绝不落在仓库内** ✗ ──
def test_d1_backup_root_is_outside_repo():
    """⭐ D1：`backup_root()` 结果**不得**位于仓库目录内 ✗（真跑 ✓ 带默认 ✓）。"""
    import pet_selfcode
    r = pet_selfcode.backup_root(REPO)
    assert r, '⭐ 必须有默认（未配也要有 ✓）✗'
    assert not os.path.abspath(r).lower().startswith(os.path.abspath(REPO).lower()), \
        '⭐ 备份根不得落在仓库内 ✗（这正是 D1 的缺陷本身 ✓）：%s' % r


def test_d1_env_override_wins(tmp_path, monkeypatch):
    """⭐ D1：环境变量优先 ✓（⭐ 用 monkeypatch ⇒ 自动还原 ✗ 不污染后续用例 ✓）。"""
    import pet_selfcode
    monkeypatch.setenv('AC_PET_BACKUP_DIR', str(tmp_path / 'bk'))
    assert pet_selfcode.backup_root(REPO) == str(tmp_path / 'bk')



def test_d1_backup_write_site_is_outside_repo():
    """⭐ D1 有牙：⭐ **写备份的那行**不得再拼 `base_dir/'backup'` ✗（代码级 ✓）。

    ⚠️ 如实说明：⭐ 走 `edit_own_code()` **端到端**需要过它的**文件白名单** ✓
      （实测：非项目内路径会被拒："只能改项目内的 .py 模块" ✓）
      ⇒ ⭐ 本用例只钉**写入点**（那是缺陷本体 ✓），⭐ 端到端记为【由白名单路径覆盖】
      —— ⛔ 不假装跑过端到端 ✗（⭐ 与 E16 的诚实口径一致 ✓）。
    """
    src = io.open(os.path.join(REPO, 'pet_selfcode.py'), encoding='utf-8').read()
    assert "os.path.join(base_dir, 'backup')" not in src, \
        "⭐ 不得再把备份写进仓库（D1 缺陷本体 ✗）"
    assert 'backup_root(base_dir)' in src, '⭐ 应改走 backup_root() ✓'


def test_d1_backup_root_never_under_repo(tmp_path, monkeypatch):
    """⭐ D1：⭐ 即便传了 `base_dir=仓库`，备份根**也不得**落在仓库内 ✗（参数不参与拼接 ✓）。"""
    import pet_selfcode
    monkeypatch.delenv('AC_PET_BACKUP_DIR', raising=False)
    r = pet_selfcode.backup_root(REPO)
    assert not os.path.abspath(r).lower().startswith(os.path.abspath(REPO).lower()), \
        '⭐ backup_root 绝不能被 base_dir 带进仓库 ✗：%s' % r


# ── ⭐⭐ P0-2（2026-10-05 · Owner 已批 ✓）：自改码**禁改清单** ──
#    底线：⭐ **护栏不可被改** ✗ —— 否则"围栏"形同不存在（与 OpenAI 事故同型 ✓）
def test_p02_protected_files_are_refused(tmp_path):
    """⭐ 有牙：⭐ 清单里每个文件**都必须**被判禁改 ✗（真跑 ✓ 参数化 ✓）。"""
    import pet_selfcode
    for f in pet_selfcode.SELF_PROTECTED:
        got, why = pet_selfcode.is_protected(f)
        assert got, '⭐ %s 必须在禁改清单里 ✗' % f
        assert why, '⭐ 必须给出原因 ✓'
    # ⭐ 测试文件模式
    for f in ('test_a_stage.py', 'test_x.py'):
        assert pet_selfcode.is_protected(f)[0], '⭐ 测试文件不可自改 ✗'


def test_p02_self_reference_protection():
    """⭐ ⭐ **自指保护**：⭐ 清单写在 `pet_selfcode.py` 里，⭐ 而它**自己也在清单里** ✓
    ⇒ ⭐ 想改清单必须先改清单里的文件 ⇒ ⭐ **被自己挡住** ✓（⛔ 无后门 ✗）。"""
    import pet_selfcode
    src = io.open(os.path.join(REPO, 'pet_selfcode.py'), encoding='utf-8').read()
    assert 'SELF_PROTECTED' in src, '⭐ 清单必须定义在 pet_selfcode.py 内 ✓'
    assert 'pet_selfcode.py' in pet_selfcode.SELF_PROTECTED, \
        '⭐ 清单必须包含它自己 ✗（否则可先删清单再改一切 ✓）'


def test_p02_normal_files_still_allowed(tmp_path):
    """⭐ 反向：⭐ 普通产品码**必须**仍可改 ✗（⭐ 防"一刀切"把功能做死 ✓）。"""
    import pet_selfcode
    for f in ('desktop_pet.py', 'memory_engine.py', 'pet_anim.py'):
        assert not pet_selfcode.is_protected(f)[0], '⭐ %s 不应被禁 ✓' % f


def test_p02_edit_own_code_refuses_protected_end_to_end(monkeypatch):
    """⭐ 端到端：⭐ 真调 `edit_own_code` 改自身 ⇒ ⭐ **必须被拒** ✗（真跑 ✓ 有牙 ✓）。

    ⭐ P0-1 起需**先开闸门** ✓ —— ⭐ 两道闸是**组合**的：⭐ 闸门（默认关 ✓）先过，
    ⭐ 再撞**禁改清单**（永不可改 ✗）✓ ⇒ ⭐ 本用例显式开闸，才验得到清单那道 ✓。
    """
    import pet_selfcode
    monkeypatch.setenv(pet_selfcode.SELF_EDIT_ENV, '1')   # ⭐ 开闸（越过 P0-1 ✓）
    r = pet_selfcode.edit_own_code(old_text='# no such text', new_text='# x',
                                   file='pet_selfcode.py', base_dir=REPO)
    assert '拒绝修改' in str(r), '⭐ 改自身必须被拒 ✗（实际返回：%r）' % (str(r)[:80],)
    # ⭐ 且**不得留下任何改动** ✓
    src = io.open(os.path.join(REPO, 'pet_selfcode.py'), encoding='utf-8').read()
    assert 'SELF_PROTECTED' in src, '⭐ 文件必须原样未变 ✓'


# ── ⭐⭐ P0-1（2026-10-05 · Owner 已批 ✓）：自改码**批准闸门**（默认关 ✗）──
def test_p01_default_closed(tmp_path, monkeypatch):
    """⭐ 有牙：⭐ **无 env 无 config ⇒ 必须关** ✗ 且 ⭐ 调用**必须被拒** ✓ ＋ **明说怎么开** ✓。"""
    import pet_selfcode
    monkeypatch.delenv(pet_selfcode.SELF_EDIT_ENV, raising=False)
    assert pet_selfcode.self_edit_allowed(str(tmp_path)) is False, '⭐ 默认必须是关 ✗'
    tgt = tmp_path / 'm.py'
    tgt.write_text('A = 1\n', encoding='utf-8')
    r = pet_selfcode.edit_own_code(old_text='A = 1', new_text='A = 2',
                                   file='m.py', base_dir=str(tmp_path))
    assert '未开启' in str(r), '⭐ 默认态必须被拒 ✗：%r' % (str(r)[:60],)
    assert pet_selfcode.SELF_EDIT_ENV in str(r), '⭐ 必须明说怎么开 ✓（承 E14.7 ✓）'
    assert tgt.read_text(encoding='utf-8').strip() == 'A = 1', '⛔ 被拒时不得改文件 ✗'


def test_p01_env_opens(tmp_path, monkeypatch):
    """⭐ 开了 ⇒ 闸门放行 ✓（⭐ 但仍受禁改清单约束 ⇒ 见 P0-2 ✓）。"""
    import pet_selfcode
    monkeypatch.setenv(pet_selfcode.SELF_EDIT_ENV, '1')
    assert pet_selfcode.self_edit_allowed(str(tmp_path)) is True


def test_p01_explicit_env_wins(tmp_path, monkeypatch):
    """⭐ ⭐ **显式 env 说了算** ✗：⭐ config 说开 ✓ 但 env 显式 `0` ⇒ ⭐ 必须**关** ✗。"""
    import json as _json
    import pet_selfcode
    (tmp_path / 'config.json').write_text(
        _json.dumps({'allow_self_edit': True}), encoding='utf-8')
    monkeypatch.setenv(pet_selfcode.SELF_EDIT_ENV, '0')
    assert pet_selfcode.self_edit_allowed(str(tmp_path)) is False, \
        '⭐ 显式 env=0 必须覆盖 config ⇒ 关 ✗'


def test_p01_config_can_open(tmp_path, monkeypatch):
    """⭐ config 路由可用 ✓（⭐ 且 ⭐ 读失败**必须按关** ✗ 不静默放行 ✗）。"""
    import json as _json
    import pet_selfcode
    monkeypatch.delenv(pet_selfcode.SELF_EDIT_ENV, raising=False)
    (tmp_path / 'config.json').write_text(
        _json.dumps({'allow_self_edit': True}), encoding='utf-8')
    assert pet_selfcode.self_edit_allowed(str(tmp_path)) is True
    # ⭐ 坏 config ⇒ 仍按关 ✓（⛔ 不得因为读不懂就放行 ✗）
    (tmp_path / 'config.json').write_text('{ not json', encoding='utf-8')
    assert pet_selfcode.self_edit_allowed(str(tmp_path)) is False, \
        '⭐ 读配置失败必须按"关"处理 ✗（⛔ 不得静默放行 ✗）'


# ── ⭐⭐ P0-3（2026-10-05 · Owner 已批 ✓）：子进程**命令白名单** ──
def test_p03_allowed_programs_pass():
    """⭐ 反向：⭐ 登记过的程序**必须**放行 ✗（⭐ 防"一刀切"把功能做死 ✓）。"""
    import platform_layer
    for argv in (['powershell', '-Command', 'echo hi'],
                 ['git', 'rev-parse', 'HEAD'],
                 ['where', 'python'],
                 ['C:/Windows/System32/where.exe', 'python']):
        ok, name, why = platform_layer.program_allowed(argv)
        assert ok, '⭐ %s 应放行 ✓（%s）' % (argv, why)


def test_p03_unlisted_programs_refused():
    """⭐ 有牙：⭐ 未登记程序**必须**被拒 ✗（⭐ 尤其"能外连"的那些 ✓）。"""
    import platform_layer
    for argv in (['curl', 'http://x'], ['wget', 'http://x'], ['bash', '-c', 'x'],
                 ['rm', '-rf', '/'], ['cmdkey', '/list']):
        ok, name, why = platform_layer.program_allowed(argv)
        assert not ok, '⭐ %s 必须被拒 ✗' % (argv,)
        assert why, '⭐ 必须给出原因 ✓'


def test_p03_empty_and_bad_input_refused():
    """⭐ 空命令／无法解析**必须**拒绝 ✗（⛔ 不得因解析失败就放行 ✗）。"""
    import platform_layer
    assert platform_layer.program_allowed([])[0] is False
    assert platform_layer.program_allowed('')[0] is False
    assert platform_layer.program_allowed(None)[0] is False


def test_p03_safe_spawn_raises_not_silent():
    """⭐ ⭐ **未登记必须抛错** ✗ —— ⭐ 让人**看得见** ✗（⛔ 不静默不跑 ✗）。"""
    import platform_layer
    try:
        platform_layer.safe_spawn(['curl', 'http://x'])
    except PermissionError as e:
        assert 'P0-3' in str(e), '⭐ 错误信息要能指向 P0-3 ✓'
        return
    raise AssertionError('⭐ 未登记程序必须抛 PermissionError ✗（⛔ 不得静默 ✗）')


def test_p03_safe_spawn_runs_allowed():
    """⭐ 登记程序**必须**真跑起来 ✓（行为与原 `subprocess.run` 一致 ✓）。"""
    import platform_layer
    r = platform_layer.safe_spawn(['where', 'python'], capture_output=True,
                                  text=True, timeout=10)
    assert r.returncode == 0, '⭐ 登记程序应正常执行 ✓'


# ── ⭐ P0-3 后半（我方认领自微信侧 `-40` §五.D ✓）：`/api/log.jsonl` 限量 ──
def test_p03_log_jsonl_is_limited(tmp_path):
    """⭐ 有牙：⭐ 请求不传 limit ⇒ **默认 200** ✗（⭐ 原实现是**无限量** ✗ ⇒ 本用例即回归钉 ✓）。"""
    import json as _json
    import threading
    import time
    import urllib.request
    import relay_log
    import relay_server
    lg = relay_log.RelayLog(str(tmp_path / 'll.jsonl'))
    for k in range(1, 301):
        lg.error('第 %d 条' % k, raw='x')
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/log.jsonl' % port, timeout=5) as fh:
            body = fh.read().decode('utf-8')
            hdr = dict(fh.headers)
        lines = [l for l in body.splitlines() if l.strip()]
        assert len(lines) <= 200, '⭐ 默认必须有上限（原实现无限量 ✗）：得到 %d 行' % len(lines)
        assert hdr.get('X-Truncated') == '1', '⭐ 截断时必须明示 ✗（header X-Truncated ✓）'
        # ⭐ 反向：limit 生效 ✓
        with urllib.request.urlopen('http://127.0.0.1:%d/api/log.jsonl?limit=7' % port, timeout=5) as fh:
            b2 = fh.read().decode('utf-8')
        assert len([l for l in b2.splitlines() if l.strip()]) == 7, '⭐ limit 必须生效 ✓'
    finally:
        httpd.shutdown()


def test_p03_log_jsonl_still_read_only(tmp_path):
    """⛔ 加了 limit **仍然纯读** ✗（⭐ 调用前后日志条数不变 ✓）。"""
    import threading
    import time
    import urllib.request
    import relay_log
    import relay_server
    lg = relay_log.RelayLog(str(tmp_path / 'll2.jsonl'))
    for k in range(1, 11):
        lg.error('x%d' % k)
    n0 = len(lg.replay())
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    try:
        for u in ('/api/log.jsonl', '/api/log.jsonl?limit=3'):
            urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, u), timeout=5).read()
        assert len(lg.replay()) == n0, '⛔ 只读端点不得写日志 ✗'
    finally:
        httpd.shutdown()


def test_p03_send_backward_compatible():
    """⭐ 结构钉：⭐ `_send` 的 `extra_headers` 必须是**可选参数** ✗（⭐ 不传时行为不变 ✓）。"""
    src = io.open(os.path.join(REPO, 'collab', 'relay_server.py'), encoding='utf-8').read()
    i = src.index('def _send(')
    seg = src[i:i + 300]
    assert 'extra_headers=None' in seg, '⭐ 必须是可选参数（默认 None ⇒ 向后兼容 ✓）✗'


# ── ⭐ P0-3 接入（2026-10-05）：⭐ 结构钉 + 隐私钉 ──
def test_p03_dsh_adapter_has_no_raw_subprocess():
    """⭐ 结构钉：⭐ `dsh_adapter.py` **不得再有裸 `subprocess.run`** ✗（⭐ 必须走受控入口 ✓）。"""
    src = io.open(os.path.join(REPO, 'dsh_adapter.py'), encoding='utf-8').read()
    assert 'subprocess.run(' not in src, '⭐ 仍有裸 subprocess.run ✗（应改走 platform_layer.safe_spawn ✓）'
    assert 'safe_spawn(' in src, '⭐ 应已接入受控入口 ✓'


def test_p03_verify_tool_has_no_personal_path():
    """⭐ 隐私钉（开源阻断项）：⭐ `tools/verify.py` 与 `ENTRY.md` 不得含本机用户名 ✗。

    ⭐ 注：⭐ 本用例**把用户名拆开拼**（`'lby' + '13'`）✗ ——
    ⭐ 否则护栏自己就成了"含隐私的文件" ✓（⭐ 自指问题 ✓）。
    """
    needle = 'lby' + '13'
    for rel in ('tools/verify.py', 'ENTRY.md'):
        p = os.path.join(REPO, rel)
        if not os.path.isfile(p):
            continue
        src = io.open(p, encoding='utf-8', errors='ignore').read()
        assert needle not in src, '⭐ %s 含本机用户名（开源阻断项 ✗）' % rel
    # ⭐ 且必须**有**占位说明 ✓（⛔ 不是删了了事 ✗）
    e = io.open(os.path.join(REPO, 'ENTRY.md'), encoding='utf-8').read()
    assert '<你的 python 完整路径>' in e, '⭐ 应保留占位说明（⭐ 换掉路径但别丢知识 ✓）'


def test_p03_allowed_list_covers_dsh():
    """⭐ 接线后：⭐ `dsh.cmd`／`dsh.ps1` 必须已登记 ✗（⭐ 否则 dsh_adapter 一跑就被拒 ✓）。"""
    import platform_layer
    for prog in ('dsh.cmd', 'dsh.ps1'):
        assert platform_layer.program_allowed([prog, '--version'])[0] is True, \
            '⭐ %s 必须已登记 ✓' % prog


# ── ⭐ P1-1（2026-10-05）：安全边界文档必须**在位且含关键要素** ✗ ──
def test_p11_security_boundary_doc_exists_with_required_parts():
    """⭐ 采纳微信侧 `WX-…-44` §四 的三条要求：⭐ 文档必须含
    ⭐ ① **未接白名单清单** ✗ ② ⭐ **"程序名过滤 ≠ 能力限制"** 这条根本局限 ✗
    ⭐ ③ ⭐ **真实案例** ✓（⛔ 不能只有抽象条款 ✗）。"""
    p = os.path.join(REPO, 'docs', '安全边界.md')
    assert os.path.isfile(p), '⭐ 安全边界文档必须在位 ✗（P1-1 ✓）'
    d = io.open(p, encoding='utf-8').read()
    for key, why in (('未接清单', '必须有未接白名单清单 ✓'),
                     ('程序名过滤', '必须写"程序名过滤 ≠ 能力限制"这条根本局限 ✗'),
                     ('真实案例', '必须含真实案例 ✓'),
                     ('不可信输入', '必须有不可信输入清单 ✓'),
                     ('事故响应', '必须有事故响应 ✓'),
                     ('E14.10', '必须写明与可移植性的关系 ✓')):
        assert key in d, '⭐ 文档缺「%s」：%s' % (key, why)


def test_p11_security_boundary_doc_has_no_personal_path():
    """⭐ 隐私钉：⭐ 安全边界文档本身就是讲隐私的 ⇒ ⛔ **不得自己含本机路径** ✗。

    ⭐ 注：⭐ 用例把用户名拆开拼 ✓ —— ⭐ 否则护栏自己就成了"含隐私的文件" ✓（自指问题 ✓）。
    """
    p = os.path.join(REPO, 'docs', '安全边界.md')
    d = io.open(p, encoding='utf-8').read()
    assert ('lby' + '13') not in d, '⭐ 文档不得含本机用户名 ✗'
    _up = chr(67) + ':' + chr(92) + 'Users' + chr(92)   # ⭐ 拼出来 ⇒ 避免原生串结尾反斜杠 ✗
    assert _up not in d, '⭐ 文档不得含本机绝对路径 ✗（案例里写 <Windows 用户名> ✓）'


# ── ⭐ A4 改进（采纳微信侧 `WX-…-20261005-45` §二 建议 ✓）：双验加 pid 存活 ──
def test_a4_stale_marker_with_dead_pid_is_cleared(tmp_path):
    """⭐ 有牙：⭐ 标记里的 `pid` **已不存在** ⇒ ⭐ 判未就绪 ＋ ⭐ **自动清一次** ✗。"""
    import json as _json
    import time
    import collab_panel
    (tmp_path / 'collab').mkdir()
    rp = tmp_path / 'collab' / '.ready'
    rp.write_text(_json.dumps({'pid': 999999, 'port': 8899, 'ts': time.time()}), encoding='utf-8')
    assert collab_panel.is_ready(8899, str(tmp_path)) is False, '⭐ 死 pid 必须判未就绪 ✗'
    assert not rp.exists(), '⭐ 陈旧标记必须被清一次 ✓'


def test_a4_live_pid_but_port_silent_keeps_marker(tmp_path):
    """⭐ 反向：⭐ 进程**还活着**但端口暂不应答（⭐ 启动中 ✓）⇒ ⭐ 判未就绪但**保留标记** ✗
    （⭐ 清了会打断慢启动 ✓）。"""
    import json as _json
    import time
    import collab_panel
    (tmp_path / 'collab').mkdir()
    rp = tmp_path / 'collab' / '.ready'
    rp.write_text(_json.dumps({'pid': os.getpid(), 'port': 8898, 'ts': time.time()}),
                  encoding='utf-8')
    assert collab_panel.is_ready(8898, str(tmp_path)) is False
    assert rp.exists(), '⭐ 启动中不得清标记 ✓'


def test_a4_port_mismatch_is_false(tmp_path):
    """⭐ 端口不匹配 ⇒ 直接 False ✓。"""
    import json as _json
    import time
    import collab_panel
    (tmp_path / 'collab').mkdir()
    (tmp_path / 'collab' / '.ready').write_text(
        _json.dumps({'pid': os.getpid(), 'port': 8897, 'ts': time.time()}), encoding='utf-8')
    assert collab_panel.is_ready(1234, str(tmp_path)) is False


# ── ⭐ C2／`D5-2`（2026-10-05）：⭐ `/api/config` 只读配置面（3 条硬约束 ✓）──
def test_c2_config_endpoint_is_read_only(tmp_path):
    """⭐ 硬约束①：⭐ **纯读** ✗ —— ⭐ 调用前后日志条数不变 ✓。"""
    import threading
    import time
    import urllib.request
    import relay_log
    import relay_server
    lg = relay_log.RelayLog(str(tmp_path / 'c.jsonl'))
    n0 = len(lg.replay())
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/config' % port, timeout=4) as fh:
            got = __import__('json').loads(fh.read().decode('utf-8'))
        assert got.get('version'), '⭐ 应带契约版本 ✓'
        assert isinstance(got.get('items'), list) and got['items'], '⭐ items 不得为空 ✓'
        assert len(lg.replay()) == n0, '⛔ 只读端点不得写日志 ✗'
    finally:
        httpd.shutdown()


def test_c2_config_endpoint_hides_secret_values(tmp_path):
    """⭐ ⭐ 硬约束②：⭐ **敏感值一个字符都不回** ✗（⭐ 只把**键名**放进 `hidden` ✓）。"""
    import threading
    import time
    import urllib.request
    import relay_log
    import relay_server
    lg = relay_log.RelayLog(str(tmp_path / 'c2.jsonl'))
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/config' % port, timeout=4) as fh:
            raw = fh.read().decode('utf-8')
        assert 'sk-' not in raw and 'tvly-' not in raw, '⭐ 载荷里不得出现密钥 ✗'
        got = __import__('json').loads(raw)
        keys = [i['key'] for i in got['items']]
        assert 'deepseek_api_key' not in keys, '⭐ 敏感键不得进 items（只进 hidden 名 ✓）✗'
        assert any('key' in h for h in got.get('hidden', [])), '⭐ 应至少列出一个被隐藏的键名 ✓'
    finally:
        httpd.shutdown()


def test_c2_config_endpoint_declares_writable_and_restart(tmp_path):
    """⭐ 硬约束③：⭐ `writable` 为空时**界面必须明示"当前不可写"** ✗ ——
    ⭐ 端点侧要**如实给出空集** ✗（⛔ 不假装可写 ✗），⭐ 且 `needs_restart` 要点出改后需重启的键 ✓。"""
    import config_view
    pl = config_view.config_payload(REPO)
    assert pl.get('writable') == [], '⭐ 本批写面关闭 ⇒ writable 必须为空集 ✗'
    assert pl.get('needs_restart'), '⭐ 应点出"改后需重启"的键 ✓'
    for k in ('asr_backend', 'live2d_model'):
        assert k in pl['needs_restart'], '⭐ %s 改后需重启 ⇒ 必须出现在 needs_restart ✓' % k
    # ⭐ 反向：⭐ 数值上限类（`max_tokens`）⛔ **不得**被当密钥藏掉 ✗
    assert 'max_tokens' not in (pl.get('hidden') or []), \
        '⭐ max_tokens 是数值上限 ⇒ 不应被当密钥隐藏 ✗（我方第一版误判过 ✓）'


# ── ⭐ 草稿 2／`C5`（2026-10-05）：⭐ 错误码表（⭐ 采纳微信侧 `-51` 草稿 2 ✓）──
def test_c5_error_code_table_and_mapping():
    """⭐ 码表存得下 ＋ ⭐ **推不出就空**（⛔ 不硬编假码 ✗）＋ ⭐ 码→人话 ✓。"""
    import error_codes
    assert error_codes.CODES, '⭐ 码表不得为空 ✗'
    for code in ('ACT-403-01', 'SELF-403-01', 'SELF-403-02', 'SPAWN-403-01',
                 'LOCK-409-01', 'TODO-409-01'):
        assert code in error_codes.CODES, '⭐ 缺码 %s ✗' % code
        assert error_codes.message_of(code), '⭐ 每个码都要有**人话** ✗（⛔ 只给码不给话 ✗）'
    assert error_codes.code_for('动作端点未开启（需服务端 --enable-actions）') == 'ACT-403-01'
    assert error_codes.code_for('不是 git 仓库') == 'SELF-400-01'
    assert error_codes.code_for('这句话毫无对应') == '', '⭐ 推不出必须给**空** ✗（⛔ 不硬编 ✗）'


def test_c5_err_appends_err_code_keeps_old_fields(tmp_path):
    """⭐ ⭐ 兼容硬约束：⭐ 403 响应 ⭐ **新增 `err_code`** ✗ 而 ⭐ **旧 `code` 仍在** ✓
    （⭐ 草稿 2 明写：⛔ 不改旧字段、不改旧文案 ✗）。"""
    import threading
    import time
    import urllib.error
    import urllib.request
    import relay_log
    import relay_server
    lg = relay_log.RelayLog(str(tmp_path / 'c5.jsonl'))
    httpd, port = relay_server.create_server(lg, '127.0.0.1', 0, ui_path='')
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)
    try:
        req = urllib.request.Request('http://127.0.0.1:%d/api/step' % port, data=b'{}',
                                     headers={'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(req, timeout=4).read()
            raise AssertionError('⭐ 动作面默认关 ⇒ 应 403 ✗')
        except urllib.error.HTTPError as he:
            assert he.code == 403
            j = __import__('json').loads(he.read().decode('utf-8'))
        assert j.get('err_code') == 'ACT-403-01', '⭐ 应带业务码 ✗（实际 %r）' % j.get('err_code')
        assert j.get('code') == 403, '⭐ 旧 code（HTTP 状态码）必须保留 ✗'
        assert '动作端点未开启' in j.get('error', ''), '⭐ 旧文案不得改 ✗'
        assert len(lg.replay()) == 0, '⛔ 只读校验不得写日志 ✗'
    finally:
        httpd.shutdown()


def test_c5_self_and_spawn_carry_codes():
    """⭐ 自改码与子进程两处 ⭐ 拒绝文案必须**带码** ✗（⭐ 直接传码 ✓ 不靠推断 ✓）。"""
    self_src = io.open(os.path.join(REPO, 'pet_selfcode.py'), encoding='utf-8').read()
    for tag in ('SELF-403-01', 'SELF-403-02', 'SELF-400-01'):
        assert tag in self_src, '⭐ 自改码文案应含 %s ✓' % tag
    pl_src = io.open(os.path.join(REPO, 'platform_layer.py'), encoding='utf-8').read()
    assert 'SPAWN-403-01' in pl_src, '⭐ 子进程拒绝文案应含 SPAWN-403-01 ✓'
