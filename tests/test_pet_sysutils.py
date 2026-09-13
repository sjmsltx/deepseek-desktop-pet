# -*- coding: utf-8 -*-
"""pet_sysutils 补充单测（2026-09-13，桌宠收尾批 2 / 任务 C5）

覆盖安全门之外的四个系统交互函数：剪贴板读写、run_ps、volume_ps、热键过滤器工厂。
全部打桩，不触碰真实剪贴板、不真的执行 PowerShell、不改系统音量。

用法：python tests/test_pet_sysutils.py
"""
import ctypes
import io
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pet_sysutils as ps  # noqa: E402

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((name, 'PASS', ''))
        print('  ✅ %s' % name)
    except Exception as e:
        RESULTS.append((name, 'FAIL', str(e)[:160]))
        print('  ❌ %s: %s' % (name, str(e)[:160]))


# ---------------- B. 基础工具 ----------------
def t_quote():
    assert ps.quote_ps_single("a'b") == "'a''b'"
    assert ps.quote_ps_single(123) == "'123'"


def t_procname():
    assert ps.is_safe_process_name('chrome.exe') is True
    assert ps.is_safe_process_name('a b-c_1.2') is True
    assert ps.is_safe_process_name('a"; del x') is False
    assert ps.is_safe_process_name('') is False


def t_open_url():
    # 非 http/https 一律拒绝（不真开浏览器）
    assert ps.open_url('file:///C:/x') is False
    assert ps.open_url('javascript:alert(1)') is False
    assert ps.open_url('') is False
    assert ps.open_url('ftp://x') is False


# ---------------- C. run_ps ----------------
class _FakeProc:
    def __init__(self, out='', err='', code=0):
        self.stdout, self.stderr, self.returncode = out, err, code


class _FakeSubprocess:
    CREATE_NO_WINDOW = 0x08000000

    class TimeoutExpired(Exception):
        pass

    def __init__(self, out='', err='', raise_exc=None):
        self.calls = []
        self.out, self.err, self.raise_exc = out, err, raise_exc

    def run(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.raise_exc:
            raise self.raise_exc
        return _FakeProc(self.out, self.err)


def _with_fake_subprocess(fake, fn):
    real = ps._subprocess
    ps._subprocess = fake
    try:
        return fn()
    finally:
        ps._subprocess = real


def t_runps_blocked_no_exec():
    fake = _FakeSubprocess(out='should not run')
    out = _with_fake_subprocess(fake, lambda: ps.run_ps('Remove-Item -Recurse -Force C:\\x'))
    assert '需要你确认' in out, out
    assert fake.calls == [], '安全门拦截时不应调用 subprocess，实际调用了 %d 次' % len(fake.calls)


def t_runps_params():
    fake = _FakeSubprocess(out='ok')
    out = _with_fake_subprocess(fake, lambda: ps.run_ps('Get-Date', timeout=7))
    assert out == 'ok', out
    cmd, kw = fake.calls[0]
    assert cmd[0] == 'powershell' and '-NoProfile' in cmd and '-NonInteractive' in cmd
    joined = ' '.join(cmd)
    assert 'OutputEncoding' in joined and 'Get-Date' in joined
    assert kw.get('encoding') == 'utf-8'
    assert kw.get('timeout') == 7
    assert kw.get('creationflags') == _FakeSubprocess.CREATE_NO_WINDOW


def t_runps_skip_check():
    fake = _FakeSubprocess(out='done')
    out = _with_fake_subprocess(fake, lambda: ps.run_ps('Remove-Item x', skip_check=True))
    assert out == 'done' and len(fake.calls) == 1


def t_runps_truncate():
    fake = _FakeSubprocess(out='x' * 2000)
    out = _with_fake_subprocess(fake, lambda: ps.run_ps('Get-Date'))
    assert len(out) <= 1500 + 20 and '输出过长已截断' in out, len(out)


def t_runps_err_and_empty():
    fake = _FakeSubprocess(out='', err='boom')
    out = _with_fake_subprocess(fake, lambda: ps.run_ps('Get-Date'))
    assert out.startswith('（错误）') and 'boom' in out, out
    fake2 = _FakeSubprocess(out='', err='')
    out2 = _with_fake_subprocess(fake2, lambda: ps.run_ps('Get-Date'))
    assert out2 == '（无输出，执行成功）', out2


def t_runps_timeout():
    # 用桩自己的 TimeoutExpired（真 subprocess 的那个需要 (cmd, timeout) 两个参数）
    fake = _FakeSubprocess(raise_exc=_FakeSubprocess.TimeoutExpired('t'))
    out = _with_fake_subprocess(fake, lambda: ps.run_ps('Get-Date', timeout=3))
    assert '超时' in out and '3' in out, out


# ---------------- D. volume_ps ----------------
def t_volume_ps():
    seen = {}
    real = ps.run_ps

    def fake_run_ps(cmd, timeout=15, skip_check=False):
        seen['cmd'], seen['timeout'], seen['skip'] = cmd, timeout, skip_check
        return '50'

    ps.run_ps = fake_run_ps
    try:
        out = ps.volume_ps('[Volume]::GetPercent()')
        assert out == '50'
        assert seen['skip'] is True and seen['timeout'] == 20
        assert 'Add-Type' in seen['cmd'] and '[Volume]::GetPercent()' in seen['cmd']
        assert 'class Volume' in seen['cmd']
    finally:
        ps.run_ps = real


# ---------------- E. 剪贴板（打桩 ctypes） ----------------
# 注意：产品代码会对这些方法设 restype/argtypes，因此必须用**函数对象**
# （类实例的绑定方法不允许赋属性，会抛 AttributeError 并被 except 吞掉）
def _mk_fakes(open_ok=True, fmt_available=True, handle=0x1000, text=None,
              alloc_ok=True, lock_ok=True):
    state = {'closed': 0, 'unlocked': 0, 'set_calls': [], 'data': None}
    u = types.SimpleNamespace()
    u.OpenClipboard = lambda h: 1 if open_ok else 0
    u.CloseClipboard = lambda: state.__setitem__('closed', state['closed'] + 1)
    u.IsClipboardFormatAvailable = lambda f: 1 if fmt_available else 0
    u.GetClipboardData = lambda f: (handle if handle else None)
    u.EmptyClipboard = lambda: 1
    u.SetClipboardData = lambda f, h: (state['set_calls'].append((f, h)), h)[1]
    k = types.SimpleNamespace()
    k.GlobalAlloc = lambda flags, size: (0x2000 if alloc_ok else 0)
    k.GlobalLock = lambda h: (0x3000 if lock_ok else 0)
    k.GlobalUnlock = lambda h: (state.__setitem__('unlocked', state['unlocked'] + 1), 1)[1]
    return u, k, state


def _with_fake_ctypes(user32, kernel32, text_holder, fn):
    fake = types.SimpleNamespace()
    fake.windll = types.SimpleNamespace(user32=user32, kernel32=kernel32)
    fake.c_void_p = ctypes.c_void_p
    fake.c_uint = ctypes.c_uint
    fake.c_size_t = ctypes.c_size_t
    fake.memmove = lambda p, d, n: text_holder.__setitem__('data', bytes(d[:n]))
    fake.c_wchar_p = lambda p: types.SimpleNamespace(value=text_holder.get('value'))
    real = sys.modules.get('ctypes')
    sys.modules['ctypes'] = fake
    try:
        return fn()
    finally:
        sys.modules['ctypes'] = real


def t_clip_read_ok():
    u, k, st = _mk_fakes(text='hello 中文')
    out = _with_fake_ctypes(u, k, {'value': 'hello 中文'}, ps.read_clipboard_text)
    assert out == 'hello 中文', out
    assert st['closed'] == 1 and st['unlocked'] == 1


def t_clip_read_denied():
    u, k, _ = _mk_fakes(open_ok=False)
    assert _with_fake_ctypes(u, k, {'value': 'x'}, ps.read_clipboard_text) is None
    u2, k2, _ = _mk_fakes(fmt_available=False)
    assert _with_fake_ctypes(u2, k2, {'value': 'x'}, ps.read_clipboard_text) is None
    u3, k3, _ = _mk_fakes(handle=0)
    assert _with_fake_ctypes(u3, k3, {'value': 'x'}, ps.read_clipboard_text) is None


def t_clip_write_ok():
    u, k, st = _mk_fakes()
    holder = {}
    ok = _with_fake_ctypes(u, k, holder, lambda: ps.write_clipboard_text('hi'))
    assert ok is True, ok
    assert st['set_calls'] and st['set_calls'][0][0] == 13
    assert holder.get('data', b'').endswith(b'\x00\x00')


def t_clip_write_alloc_fail():
    u, k, _ = _mk_fakes(alloc_ok=False)
    ok = _with_fake_ctypes(u, k, {}, lambda: ps.write_clipboard_text('hi'))
    assert ok is False
    u2, k2, _ = _mk_fakes(open_ok=False)
    assert _with_fake_ctypes(u2, k2, {}, lambda: ps.write_clipboard_text('hi')) is False


# ---------------- F. 热键过滤器 ----------------
def t_hotkey_filter():
    import ctypes.wintypes as wt
    called = []
    flt = ps.hotkey_filter_factory({1: lambda: called.append('a'), 2: lambda: called.append('b')})

    msg = wt.MSG()
    msg.message = 0x0312  # WM_HOTKEY
    msg.wParam = 1
    ret = flt.nativeEventFilter(b'windows_generic_MSG', ctypes.addressof(msg))
    assert called == ['a'], called
    assert ret[0] is True

    msg.wParam = 99  # 未注册的 id
    ret2 = flt.nativeEventFilter(b'windows_generic_MSG', ctypes.addressof(msg))
    assert ret2[0] is False and called == ['a']

    ret3 = flt.nativeEventFilter(b'something_else', ctypes.addressof(msg))
    assert ret3[0] is False


def main():
    print('===== pet_sysutils 补充单测 =====')
    print('A. 基础工具')
    check('quote_ps_single 单引号翻倍', t_quote)
    check('is_safe_process_name 注入字符拒绝', t_procname)
    check('open_url 只放行 http/https', t_open_url)

    print('B. run_ps')
    check('安全门拦截时不执行 subprocess', t_runps_blocked_no_exec)
    check('调用参数（powershell/编码/超时/无窗口）', t_runps_params)
    check('skip_check 绕过安全门', t_runps_skip_check)
    check('超长输出截断 1500', t_runps_truncate)
    check('stderr 透出与空输出兜底', t_runps_err_and_empty)
    check('超时提示', t_runps_timeout)

    print('C. volume_ps')
    check('跳过安全门 + timeout=20 + 内嵌 Add-Type', t_volume_ps)

    print('D. 剪贴板（打桩）')
    check('读：正常取值 + 资源释放', t_clip_read_ok)
    check('读：打不开/格式不可用/句柄空', t_clip_read_denied)
    check('写：写入成功且格式为 CF_UNICODETEXT', t_clip_write_ok)
    check('写：分配失败 / 打不开剪贴板', t_clip_write_alloc_fail)

    print('E. 热键过滤器')
    check('WM_HOTKEY 命中回调 / 未注册 id / 非目标事件', t_hotkey_filter)

    total = len(RESULTS)
    fail = [r for r in RESULTS if r[1] == 'FAIL']
    print('\npet_sysutils 单测：%d 组断言' % total)
    print('结果：%s' % ('全部通过 ✅' if not fail else '失败 %d 组 ❌' % len(fail)))
    for n, _, e in fail:
        print('   ❌ %s: %s' % (n, e))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
