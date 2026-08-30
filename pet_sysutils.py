# -*- coding: utf-8 -*-
"""
pet_sysutils.py — 系统工具层（P1 模块化拆分）
==============================================
从 desktop_pet.py 拆出的无 UI 纯工具函数：
- 危险命令检测（check_dangerous）
- 剪贴板读写（ctypes，worker 线程安全）
- PowerShell 执行（安全校验 + 超时 + UTF-8 + 截断）
- 音量控制（IAudioEndpointVolume C# 内嵌）
- 全局热键过滤器工厂

模块化说明：本模块不依赖任何 UI/主程序状态，可独立单测。
"""
import re as _re
import subprocess as _subprocess

# 危险命令检测（精确匹配，避免误杀 Format-Table 等常用命令）
DANGEROUS_PATTERNS = [
    r'\bshutdown\b', r'\brestart\b', r'\breboot\b', r'\bformat\s+[a-zA-Z]:', r'\bdiskpart\b',
    r'\bremove-item\b', r'\brm\s+-r', r'\brmdir\s+/s', r'\bdel\s+/s', r'\breg\s+delete\b',
    r'\bnet\s+user\b', r'\bclear-recyclebin\b', r'\bformat-volume\b',
    r'set-content\b', r'add-content\b', r'out-file\b', r'new-item\b',
    r'stop-process\s+-force', r'\brmdir\b.*-recurse',
]
DANGEROUS_RE = [_re.compile(p, _re.IGNORECASE) for p in DANGEROUS_PATTERNS]


def check_dangerous(cmd):
    """返回拦截提示，无危险返回 None"""
    for rx in DANGEROUS_RE:
        if rx.search(cmd):
            return f'危险操作已拦截（匹配 {rx.pattern}）：删除/关机/格式化/写文件/强制结束等操作我不执行，请手动操作。'
    return None


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
    """执行带 Volume 类的 PowerShell 脚本"""
    ps = f'[Console]::OutputEncoding=[Text.Encoding]::UTF8; Add-Type -TypeDefinition @"\n{_VOLUME_CS}\n"@; {script}'
    return run_ps(ps, timeout=20)


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
