# -*- coding: utf-8 -*-
"""
pet_sysutils.py — 系统工具层（P1 模块化拆分）
==============================================
从 desktop_pet.py 拆出的无 UI 纯工具函数：
- 命令安全门（check_dangerous：只读白名单 + 硬拒绝 + 默认拒绝）
- 剪贴板读写（ctypes，worker 线程安全）
- PowerShell 执行（安全校验 + 超时 + UTF-8 + 截断）
- 音量控制（IAudioEndpointVolume C# 内嵌）
- 全局热键过滤器工厂

模块化说明：本模块不依赖任何 UI/主程序状态，可独立单测。
"""
import os as _os
import re as _re
import subprocess as _subprocess

# ============ 命令安全门（v6.50：黑名单 → 只读白名单） ============
# 背景（2026-09-12 安全审查）：旧实现是"危险关键词黑名单"，被实测绕过——
# Stop-Computer / rd /s /q / cmd /c del / icacls / taskkill /f 全部放行，
# 却把 Remove-Item -Recurse -Force 误拦。PowerShell 语法变体太多，黑名单
# 不可能穷举，因此改成"默认拒绝"的三层判定：
#   ① 破坏性语义硬拒绝（命中即拦，不要求写法精确）
#   ② 按语句拆解后逐条取命令名，不在【只读白名单】内 → 拦
#   ③ 拆解不出命令名的一律拦
# 被拦不代表功能消失：上层会把"被拦"转成"是否允许执行？"的询问，
# 用户确认后以 run_ps(cmd, skip_check=True) 执行。
#
# 维护须知：新增只读工具时，把命令名加进 _SAFE_CMD_RE；
# 绝不要为了让某条命令通过而放宽 _HARD_DENY_PATTERNS。

# ① 破坏性语义：命中即拦（避免用宽泛词，否则会误伤 Format-Table 等常用命令）
_HARD_DENY_PATTERNS = [
    # 关机 / 重启 / 注销
    r'\b(stop-computer|restart-computer|shutdown|logoff)\b',
    # 删除 / 格式化 / 分区
    r'\b(remove-item|rmdir|remove-partition|format-volume|diskpart|clear-disk|clear-recyclebin)\b',
    r'\b(rd|del|erase|rm)\s+',
    r'\bformat\s+[a-z]:',
    r'\bcipher\s+/w\b',
    # 写文件 / 覆盖 / 重定向
    r'\b(set-content|add-content|out-file|new-item|clear-content|export-csv|tee-object)\b',
    r'(?<![<>=])>{1,2}(?![=&\d])',
    # 权限 / 账户 / 注册表 / 服务 / 计划任务 / 引导
    r'\b(icacls|cacls|takeown|attrib)\b',
    r'\bnet\s+(user|localgroup|share)\b',
    r'\breg\s+(add|delete|import|copy|save|restore)\b',
    r'\b(set|new|remove|stop|restart|suspend)-service\b',
    r'\bschtasks\b', r'\bsc(\.exe)?\s+(delete|config|stop|start)\b', r'\bbcdedit\b',
    # 进程操控
    r'\b(stop-process|taskkill|kill)\b',
    # 执行 / 下载 / 编码执行 / 脚本宿主
    r'\b(invoke-expression|iex|invoke-webrequest|invoke-restmethod|invoke-command)\b',
    r'\b(start-process|start-job|register-scheduledjob)\b',
    r'\b(certutil|bitsadmin|mshta|wscript|cscript|rundll32|regsvr32|psexec|wmic)\b',
    r'\bcmd(\.exe)?\s*/[ck]\b',
    r'-enc(oded)?command\b',
    # 安全策略 / 防火墙 / 备份还原
    r'\b(set-executionpolicy|set-mppreference)\b',
    r'\bnetsh\s+(advfirewall|firewall)\b',
    r'\b(vssadmin|wbadmin|dism)\b',
]
_HARD_DENY_RE = [_re.compile(p, _re.IGNORECASE) for p in _HARD_DENY_PATTERNS]

# run_ps 自己拼的编码前缀（安全检查前先剥掉，否则会被当成未知语句拦下）
_PS_PREFIX_RE = _re.compile(
    r'^\s*\[Console\]::OutputEncoding\s*=\s*\[Text\.Encoding\]::UTF8\s*;\s*'
    r'\$OutputEncoding\s*=\s*\[Text\.Encoding\]::UTF8\s*;\s*', _re.IGNORECASE)

# ② 只读白名单：命令名（动词-名词）或常用别名；不在表内一律拦
_SAFE_CMD_RE = _re.compile(
    r'^(?:'
    r'get|test|select|sort|measure|where|group|compare|convertto|convertfrom|resolve'
    r')-[a-z]+$'
    r'|^convert-path$|^split-path$|^join-path$|^start-sleep$|^get-help$|^help$'
    r'|^format-(?:table|list|wide|custom|enum)$'
    r'|^out-(?:string|host|null|default|gridview)$'
    r'|^write-(?:output|host)$'
    # PowerShell 别名
    r'|^(?:dir|ls|gci|gc|cat|type|ps|gps|ft|fl|fw|oh|echo|sls|sleep|gm|cls|clear-host)$'
    # 只读的原生命令行工具（ping/ipconfig 等，工具说明里明确承诺支持）
    r'|^(?:ping|ipconfig|netstat|systeminfo|nslookup|tracert|whoami|hostname|ver|'
    r'tasklist|getmac|driverquery|pathping|findstr|more|tree|where|gpresult|vol|query)$',
    _re.IGNORECASE)


def _split_statements(cmd):
    """按 ; | && || 换行 拆句；引号/括号/花括号/here-string 内部不拆"""
    out, buf, i, n = [], [], 0, len(cmd)
    depth, quote = 0, None
    while i < n:
        ch = cmd[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                if i + 1 < n and cmd[i + 1] == quote:   # '' / "" 转义
                    buf.append(cmd[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if ch in '"\'"':
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch in '({[':
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch in ')}]':
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
            continue
        if depth == 0 and ch in ';|\n\r':
            out.append(''.join(buf))
            buf = []
            i += 1
            continue
        if depth == 0 and ch == '&':
            out.append(''.join(buf))
            buf = ['&']   # 保留调用运算符：& "程序.exe" 不能被当成纯字符串语句放行
            i += 2 if cmd[i + 1:i + 2] == '&' else 1
            continue
        buf.append(ch)
        i += 1
    out.append(''.join(buf))
    return [s.strip() for s in out if s.strip()]


def _statement_is_safe(stmt):
    """单条语句是否属于"只读可放行"；解析不出的按危险处理"""
    s = stmt.strip()
    if not s:
        return True
    m = _re.match(r'^\$[\w:]*\s*=\s*(.+)$', s, _re.S)   # 赋值语句 → 只看右值
    if m:
        s = m.group(1).strip()
    if not s:
        return True
    if _re.fullmatch(r'"[^"]*"', s) or _re.fullmatch(r"'[^']*'", s):
        return True                                     # 纯字符串输出（如 "已设置音量 50%"）
    if _re.fullmatch(r'[-\d.]+', s):
        return True                                     # 纯数字输出
    if _re.match(r'^\[[\w.]+\]::', s):                  # 静态调用：[math]::Max(...)
        bad = _re.search(r'\.(set|write|delete|remove|save|create|kill|start|stop|add|new)\w*\s*\(', s, _re.I)
        return not bad and '=' not in s
    head = _re.match(r'^&?\s*([A-Za-z][\w-]*)', s)      # 命令名
    if not head:
        return False                                    # 解析不出 → 默认拒绝
    return bool(_SAFE_CMD_RE.match(head.group(1)))


def check_dangerous(cmd):
    """返回拦截提示，可放行返回 None（run_ps 与上层确认流程共用）"""
    text = str(cmd or '')
    if not text.strip():
        return None
    body = _PS_PREFIX_RE.sub('', text)
    for rx in _HARD_DENY_RE:
        m = rx.search(body)
        if m:
            return f'该命令含破坏性操作（命中"{m.group(0)}"），需要你确认后才执行。'
    for stmt in _split_statements(body):
        if not _statement_is_safe(stmt):
            return f'该命令不在只读白名单内（"{stmt[:50]}"），需要你确认后才执行。'
    return None


def quote_ps_single(value):
    """把值包成 PowerShell 单引号字符串（内部单引号翻倍），拼接命令时防注入"""
    return "'" + str(value).replace("'", "''") + "'"


def open_shell_target(target):
    """用 ShellExecute 打开应用/文件/文件夹（os.startfile 不过 cmd，& | > 无注入面）"""
    try:
        t = str(target or '').strip()
        if not t:
            return False
        _os.startfile(t)
        return True
    except Exception:
        return False


def open_url(url):
    """用默认浏览器打开链接（只允许 http/https，替代 os.system('start ...')）"""
    try:
        u = str(url or '').strip()
        if not _re.match(r'^https?://', u, _re.IGNORECASE):
            return False
        import webbrowser
        return bool(webbrowser.open(u))
    except Exception:
        return False


def open_search_url(query, engine='https://www.bing.com/search?q='):
    """用浏览器搜索（query 先做 URL 编码，防参数注入）"""
    import urllib.parse as _up
    return open_url(engine + _up.quote(str(query or '')))


def is_safe_process_name(name):
    """进程名校验：仅字母数字与 . _ - 空格，防止拼进 PowerShell 时注入"""
    return bool(_re.fullmatch(r'[A-Za-z0-9_.\- ]{1,80}', str(name or '')))


def read_clipboard_text():
    """读取剪贴板文本（纯 ctypes，worker 线程安全）"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        # 64 位下句柄/指针必须显式声明 restype + argtypes，否则默认 32 位 c_int 截断
        user32.GetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        if not user32.OpenClipboard(0):
            return None
        try:
            if not user32.IsClipboardFormatAvailable(13):  # CF_UNICODETEXT
                return None
            h = user32.GetClipboardData(13)
            if not h:
                return None
            p = kernel32.GlobalLock(h)
            try:
                return ctypes.c_wchar_p(p).value or ''
            finally:
                kernel32.GlobalUnlock(h)
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def write_clipboard_text(text):
    """写入剪贴板文本（纯 ctypes，worker 线程安全）"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        if not user32.OpenClipboard(0):
            return False
        try:
            user32.EmptyClipboard()
            data = str(text).encode('utf-16-le') + b'\x00\x00'
            h = kernel32.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
            if not h:
                return False
            p = kernel32.GlobalLock(h)
            if not p:
                return False
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            user32.SetClipboardData(13, h)
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def run_ps(command, timeout=15, skip_check=False):
    """执行 PowerShell 命令：安全校验 + 超时 + UTF-8 + 输出截断"""
    if not skip_check:
        blocked = check_dangerous(command)
        if blocked:
            return blocked
    try:
        full = f'[Console]::OutputEncoding=[Text.Encoding]::UTF8; $OutputEncoding=[Text.Encoding]::UTF8; {command}'
        p = _subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', full],
            capture_output=True, text=True, timeout=timeout,
            encoding='utf-8', errors='replace', creationflags=_subprocess.CREATE_NO_WINDOW,
        )
        out = (p.stdout or '').strip()
        err = (p.stderr or '').strip()
        if not out and err:
            out = f'（错误）{err}'
        if not out:
            out = '（无输出，执行成功）'
        return out if len(out) <= 1500 else out[:1500] + '\n…（输出过长已截断）'
    except _subprocess.TimeoutExpired:
        return f'（超时：命令超过 {timeout} 秒未完成，已终止）'
    except Exception as e:
        return f'（执行失败：{e}）'


# ============ 精确音量控制（v6.1，IAudioEndpointVolume API） ============
_VOLUME_CS = r'''using System;
using System.Runtime.InteropServices;

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumeratorComObject { }

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDevice device);
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    int Activate(ref Guid iid, int clsCtx, IntPtr pActivationParams, out IAudioEndpointVolume volume);
}

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr pNotify);
    int UnregisterControlChangeNotify(IntPtr pNotify);
    int GetChannelCount(out int count);
    int SetMasterVolumeLevel(float level, Guid ctx);
    int SetMasterVolumeLevelScalar(float level, Guid ctx);
    int GetMasterVolumeLevel(out float level);
    int GetMasterVolumeLevelScalar(out float level);
    int SetChannelVolumeLevel(uint index, float level, Guid ctx);
    int SetChannelVolumeLevelScalar(uint index, float level, Guid ctx);
    int GetChannelVolumeLevel(uint index, out float level);
    int GetChannelVolumeLevelScalar(uint index, out float level);
    int SetMute(bool mute, Guid ctx);
    int GetMute(out bool mute);
}

public static class Volume {
    static IAudioEndpointVolume GetVolume() {
        IMMDeviceEnumerator enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
        IMMDevice device;
        enumerator.GetDefaultAudioEndpoint(0, 1, out device);
        Guid iid = new Guid("5CDF2C82-841E-4546-9722-0CF74078229A");
        IAudioEndpointVolume volume;
        device.Activate(ref iid, 23, IntPtr.Zero, out volume);
        return volume;
    }
    public static float GetPercent() {
        float level;
        GetVolume().GetMasterVolumeLevelScalar(out level);
        return (float)Math.Round(level * 100f);
    }
    public static void SetPercent(float percent) {
        float v = Math.Max(0f, Math.Min(100f, percent)) / 100f;
        GetVolume().SetMasterVolumeLevelScalar(v, Guid.Empty);
    }
    public static bool GetMuted() {
        bool m;
        GetVolume().GetMute(out m);
        return m;
    }
    public static void SetMuted(bool mute) {
        GetVolume().SetMute(mute, Guid.Empty);
    }
}
'''


def volume_ps(script):
    """执行带 Volume 类的 PowerShell 脚本

    skip_check 说明：script 只由本模块内部用「已夹紧的整数」拼出
    （见 desktop_pet._execute_tool 的 control_volume），不含 AI 原始输入；
    且 [Volume]::SetPercent 这类写操作本就不在只读白名单内，故这里跳过安全门。
    新增调用方时必须保证 script 里不含未校验的外部字符串。
    """
    ps = f'[Console]::OutputEncoding=[Text.Encoding]::UTF8; Add-Type -TypeDefinition @"\n{_VOLUME_CS}\n"@; {script}'
    return run_ps(ps, timeout=20, skip_check=True)


def hotkey_filter_factory(callbacks):
    """创建全局热键过滤器（WM_HOTKEY）。callbacks: {hotkey_id: callback}"""
    import ctypes.wintypes  # 必须显式导入（Python 3.14 中 ctypes.wintypes 不随 ctypes 自动加载）
    from PySide6.QtCore import QAbstractNativeEventFilter

    class _HotkeyFilter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, eventType, message):
            try:
                # PySide6 的 eventType 是 QByteArray（不是 str/bytes），message 是 VoidPtr
                et = bytes(eventType) if hasattr(eventType, '__bytes__') else str(eventType).encode('utf-8', 'ignore')
                if b'windows_generic_MSG' in et:
                    msg = ctypes.wintypes.MSG.from_address(int(message))
                    if msg.message == 0x0312:  # WM_HOTKEY
                        cb = callbacks.get(msg.wParam)
                        if cb:
                            cb()
                            return True, 0
            except Exception:
                pass
            return False, 0

    return _HotkeyFilter()
