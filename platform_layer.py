# -*- coding: utf-8 -*-
"""平台抽象层(P1,批次 1):把与操作系统耦合的能力收成一组接口,为跨平台打地基。

## 现状映射(2026-09-20 实测定位,不是推测)

| 能力 | 当前实现位置 | 本层状态 |
|---|---|---|
| 打开文件/目录 | `pet_sysutils.open_shell_target` | **已收编**(直接转发) |
| 打开 URL/搜索 | `pet_sysutils.open_url / open_search_url` | **已收编** |
| 剪贴板 | `pet_sysutils.read_clipboard_text / write_clipboard_text` | **已收编** |
| 前台窗口 | `pet_foreground.foreground_process_name / busy_hint` | **已收编** |
| OCR | `pet_docs.ocr_image(path, OCR_PS1)` | **已收编** |
| 朗读(TTS) | `voice_io.VoiceIO.speak / stop` | **已收编**(对象由宿主传入) |
| 语音输入(ASR) | `asr.AsrEngine`(WinRT) | **已收编**(只做能力探测) |
| 热键过滤 | `pet_sysutils.hotkey_filter_factory` + `user32.RegisterHotKey` | **已收编** |
| 开机自启 | **本层**（批次 2 从宿主收编；启动文件夹 `.lnk` 方案） | ✅ 本层实现 |
| 窗口特效 | **本层**（批次 2 收编；Qt 标志 + DWM 备用） | ✅ 本层实现 |

## 约定(跨平台的前提)

1. **导入期不得 import 平台专有模块**(`winreg` / `winsound` / `ctypes.windll`)-- 一律函数内延迟 import,
   否则非 Windows 上 `import platform_layer` 直接炸。
2. 能力缺失 / 非 Windows → 返回**降级值**(`False` / `''` / `0`)并让 `capabilities()` 如实报告,**不抛异常**。
3. 自启用**启动文件夹快捷方式**（`.lnk`），不是注册表 Run 项；改方案会让已开启的用户变两个入口。
   后续批次把实现搬进来,宿主方法改成调用本层(迁移顺序见 `docs/平台抽象层-20260920.md`)。
"""
import ctypes
import os
import sys

# ---- 热键修饰键(Win32 常量,纯数值,不依赖平台模块)----
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008



# ------------------------------------------------------------------ 基础

def platform_name():
    """'windows' / 'darwin' / 'linux' / 'other'(不 import platform,避免多余开销与差异)"""
    if os.name == 'nt':
        return 'windows'
    if sys.platform == 'darwin':
        return 'darwin'
    if sys.platform.startswith('linux'):
        return 'linux'
    return 'other'


def is_windows():
    return platform_name() == 'windows'


# ------------------------------------------------------------------ 能力探测

def _probe(module_name):
    """模块在本构建里存不存在 -- 用 `find_spec`:**只查不执行**。

    不用 __import__:那会把模块(以及它顶层的平台专有 import,如 pet_sysutils → winreg)
    真拉进 sys.modules,capabilities() 就不再是"轻量查询"了。
    """
    try:
        import importlib.util
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def capabilities():
    """返回 {能力: {'ok': bool, 'via': 'module'|'host'|'unavailable', 'note': str}}

    给设置界面 / 诊断用:一眼看出这台机器上哪些能力真的可用。
    只做**存在性查询**(find_spec),不 import 任何实现模块。
    """
    win = is_windows()
    out = {}

    def put(key, ok, via, note=''):
        out[key] = {'ok': bool(ok), 'via': via if ok else 'unavailable', 'note': note}

    sysutils_ok = win and _probe('pet_sysutils')
    fg_ok = _probe('pet_foreground')
    docs_ok = _probe('pet_docs')
    voice_ok = _probe('voice_io')
    asr_ok = _probe('asr')
    put('open_path', sysutils_ok, 'module' if sysutils_ok else 'unavailable',
        'ShellExecute 打开文件/目录/应用')
    put('open_url', sysutils_ok, 'module' if sysutils_ok else 'unavailable',
        '用默认浏览器打开链接/搜索')
    put('clipboard', sysutils_ok, 'module' if sysutils_ok else 'unavailable',
        '读写剪贴板(经 PowerShell)')
    put('foreground', fg_ok, 'module' if fg_ok else 'unavailable',
        '只读前台进程名(不含标题/内容)')
    put('ocr', docs_ok, 'module' if docs_ok else 'unavailable',
        '本地 OCR(Windows.Media.Ocr,经 ocr_helper.ps1)')
    put('tts', voice_ok, 'module' if voice_ok else 'unavailable',
        '朗读:在线神经声线 / 离线 WinRT / SAPI 三档')
    put('asr', asr_ok, 'module' if asr_ok else 'unavailable',
        '麦克风识别(WinRT,需系统语音隐私开关)')
    put('hotkey', win, 'module' if win else 'unavailable',
        '全局热键(RegisterHotKey + WM_HOTKEY 事件过滤器)')
    # -- 尚未收编:有待宿主绑定时才算"可用",否则明确报 unavailable(不假装支持)
    put('autostart', win, 'module' if win else 'unavailable',
        '启动文件夹快捷方式（.lnk，用户可见可改）')
    put('window_effects', win, 'module' if win else 'unavailable',
        '无边框/置顶/工具窗/去阴影（Qt 标志 + DWM 备用）')
    put('beep', win, 'module' if win else 'unavailable', '提示音(winsound.Beep)')
    put('lock_screen', win, 'module' if win else 'unavailable', '锁定工作站(LockWorkStation)')
    put('dpi_awareness', win, 'module' if win else 'unavailable', '声明进程 DPI 感知(SetProcessDPIAware)')
    return out


def report():
    """人类可读的能力报告(诊断/设置页展示用)"""
    lines = ['平台抽象层 · %s' % platform_name()]
    for key, info in capabilities().items():
        via = {'module': '模块', 'host': '宿主转发', 'unavailable': '不可用'}.get(info['via'], info['via'])
        lines.append('  [%s] %-16s %s%s' % ('✓' if info['ok'] else '×', key, via,
                                           (' - ' + info['note']) if info['note'] else ''))
    return '\n'.join(lines)


# ------------------------------------------------------------------ 已收编:直接转发

def open_path(target):
    """用系统默认方式打开文件 / 目录 / 应用(不过 cmd,无注入面)"""
    if not is_windows():
        return False
    try:
        from pet_sysutils import open_shell_target
        open_shell_target(str(target))
        return True
    except Exception:
        return False


def open_url(url):
    if not is_windows():
        return False
    try:
        from pet_sysutils import open_url as _open
        _open(str(url))
        return True
    except Exception:
        return False


def open_search(query, engine=None):
    if not is_windows():
        return False
    try:
        from pet_sysutils import open_search_url
        if engine:
            open_search_url(str(query), engine)
        else:
            open_search_url(str(query))
        return True
    except Exception:
        return False


def clipboard_get():
    if not is_windows():
        return ''
    try:
        from pet_sysutils import read_clipboard_text
        return read_clipboard_text() or ''
    except Exception:
        return ''


def clipboard_set(text):
    if not is_windows():
        return False
    try:
        from pet_sysutils import write_clipboard_text
        write_clipboard_text(str(text))
        return True
    except Exception:
        return False


def foreground_process():
    """前台进程名(小写,不含路径);拿不到返回 ''。隐私:只读进程名。"""
    try:
        from pet_foreground import foreground_process_name
        return foreground_process_name() or ''
    except Exception:
        return ''


def busy_hint(process=None):
    """前台忙碌提示(会议/游戏/视频 → 建议不打扰);不支持时返回 ''"""
    try:
        from pet_foreground import busy_hint as _bh
        return _bh(process) or ''
    except Exception:
        return ''


def ocr_image(path, ps1_path=None):
    """本地 OCR 一张图;失败返回 ''(调用方应自行降级提示)"""
    if not is_windows():
        return ''
    try:
        from pet_docs import ocr_image as _ocr
        return _ocr(path, ps1_path) or ''
    except Exception:
        return ''


def speak(voice_io, text, now=None, force=False):
    """朗读(委托给宿主持有的 VoiceIO 实例;本层不做引擎选择)"""
    if voice_io is None:
        return False, '没有语音实例'
    try:
        return voice_io.speak(text, now=now, force=force)
    except Exception as e:
        return False, '朗读失败:%s' % e


def stop_speech(voice_io):
    if voice_io is None:
        return False
    try:
        voice_io.stop()
        return True
    except Exception:
        return False


def asr_available():
    """麦克风识别是否可用(只探测,不启动)"""
    try:
        import asr  # noqa: F401
        return True
    except Exception:
        return False


def beep(kind='msg'):
    """提示音：'msg'（新消息）/ 'remind'（提醒）/ 其它 → 短促一声

    频率与宿主原实现逐字一致（等值搬迁）：msg=880+1320、remind=660+990、其它=660。
    兼容别名：ok→msg、err/notify→remind。
    """
    if not is_windows():
        return False
    kind = {'ok': 'msg', 'err': 'remind', 'notify': 'remind'}.get(kind, kind)
    seq = {'msg': [(880, 80), (1320, 80)], 'remind': [(660, 200), (990, 200)]}.get(kind, [(660, 100)])
    try:
        import winsound
        for freq, dur in seq:
            winsound.Beep(freq, dur)
        return True
    except Exception:
        return False


def lock_screen():
    """锁定工作站（Win+L 的效果）"""
    if not is_windows():
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.LockWorkStation())
    except Exception:
        return False


def enable_dpi_awareness():
    """声明本进程 DPI 感知（高 DPI 下窗口不糊/不错位）"""
    if not is_windows():
        return False
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False
def foreground_categorize(process=None):
    """前台进程 → 类别(meeting/game/video/dev/…)；拿不到返回 ''"""
    try:
        from pet_foreground import categorize
        return categorize(process if process is not None else foreground_process()) or ''
    except Exception:
        return ''


def foreground_busy_level(process=None):
    """忙闲级别: high / mid / none"""
    try:
        from pet_foreground import busy_level
        return busy_level(process if process is not None else foreground_process()) or 'none'
    except Exception:
        return 'none'


def foreground_label(cat):
    """类别 → 人类可读标签"""
    try:
        from pet_foreground import category_label
        return category_label(cat) or ''
    except Exception:
        return ''


def foreground_privacy_note():
    """前台感知的隐私边界说明(设置页展示用)"""
    try:
        from pet_foreground import privacy_note
        return privacy_note() or ''
    except Exception:
        return ''


def hotkey_filter(callbacks):
    """创建 WM_HOTKEY 事件过滤器(callbacks: {hotkey_id: callback});非 Windows 返回 None"""
    if not is_windows():
        return None
    try:
        from pet_sysutils import hotkey_filter_factory
        return hotkey_filter_factory(callbacks)
    except Exception:
        return None


def register_hotkey(hotkey_id, mods, vk):
    """注册全局热键(例如 mods=MOD_CONTROL|MOD_ALT, vk=0x50 → Ctrl+Alt+P)"""
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.user32.RegisterHotKey(None, int(hotkey_id), int(mods), int(vk)))
    except Exception:
        return False


def unregister_hotkey(hotkey_id):
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.user32.UnregisterHotKey(None, int(hotkey_id)))
    except Exception:
        return False


# ------------------------------------------------------------------ 已收编：开机自启
#
# 方案沿用现状：**启动文件夹快捷方式**（`.lnk`，用户可见可改）+ 清理旧版 `.bat/.cmd`
# 与旧注册表 Run 项。**不要换成注册表方案**（会让已开启的用户变两个入口）。
#
# v6.72 批次 2 顺带修一个真 bug：原实现在删完文件后写了 `if True: … else: …`，
# 导致「只想关」永远成立、**打开自启的代码是死代码** —— 现在改成显式的 set(on)。

AUTOSTART_LNK_NAME = 'DeepSeekPet.lnk'
AUTOSTART_LEGACY = ('DeepSeekPet.bat', 'DeepSeekPet.cmd')
AUTOSTART_RUN_VALUE = 'DeepSeekPet'


def startup_dir():
    """当前用户的启动文件夹（Windows）"""
    appdata = os.environ.get('APPDATA') or os.path.expanduser(r'~\AppData\Roaming')
    return os.path.join(appdata, r'Microsoft\Windows\Start Menu\Programs\Startup')


def autostart_path(startup_directory=None):
    return os.path.join(startup_directory or startup_dir(), AUTOSTART_LNK_NAME)


def autostart_enabled(startup_directory=None):
    """启动文件夹里有没有我们的快捷方式"""
    try:
        return os.path.exists(autostart_path(startup_directory))
    except Exception:
        return False


def autostart_pythonw():
    """定位 pythonw.exe（优先当前解释器同目录，再常见安装位置，最后 PATH）"""
    import shutil
    base = os.path.dirname(sys.executable)
    local = os.path.join(base, 'pythonw.exe')
    if os.path.exists(local):
        return local
    cand = [os.path.expanduser(r'~\AppData\Local\Programs\Python\Python314\pythonw.exe')]
    for p in cand:
        if os.path.exists(p):
            return p
    return shutil.which('pythonw.exe') or local


def _main_dir():
    """调用方主脚本所在目录（开发版用来找 启动桌宠.bat / desktop_pet.py）"""
    try:
        return os.path.dirname(os.path.abspath(sys.modules['__main__'].__file__))
    except Exception:
        return os.path.dirname(os.path.abspath(sys.argv[0] or '.'))


def autostart_target(base_dir=None, script_path=None):
    """(target, workdir)：打包版 → exe 本身；开发版 → 启动桌宠.bat（无则 pythonw + 脚本）

    与原宿主实现逐行对应（只把“当前文件”改成可传入，便于测试）。
    """
    if getattr(sys, 'frozen', False):
        return sys.executable, os.path.dirname(sys.executable)
    base = base_dir or _main_dir()
    bat = os.path.join(base, '启动桌宠.bat')
    if os.path.exists(bat):
        return bat, base
    script = script_path or os.path.join(base, os.path.basename(sys.argv[0] or 'desktop_pet.py'))
    return '"%s" "%s"' % (autostart_pythonw(), script), base


def _run_ps(script, timeout=20):
    """跑一段 PowerShell（-EncodedCommand，避开引号/中文路径/分号转义）"""
    import base64
    import subprocess
    enc = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                           '-EncodedCommand', enc], capture_output=True, timeout=timeout)


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def create_autostart_lnk(path, target, workdir):
    """用 WScript.Shell 建快捷方式"""
    if not is_windows():
        return False
    ps = ('$ws = New-Object -ComObject WScript.Shell; '
          '$s = $ws.CreateShortcut(%s); '
          "$s.TargetPath = %s; $s.WorkingDirectory = %s; "
          "$s.Description = 'DeepSeek Pet'; $s.Save()" % (_quote(path), _quote(target), _quote(workdir)))
    try:
        _run_ps(ps)
    except Exception:
        return False
    return os.path.exists(path)


def _cleanup_legacy(startup_directory=None):
    """清理旧版启动项（.bat/.cmd 残留 + 旧注册表 Run 项），防止开机双启动"""
    removed = []
    d = startup_directory or startup_dir()
    for old in AUTOSTART_LEGACY:
        p = os.path.join(d, old)
        if os.path.exists(p):
            try:
                os.remove(p)
                removed.append(old)
            except Exception:
                pass
    if is_windows():
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r'Software\Microsoft\Windows\CurrentVersion\Run', 0,
                                 winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(key, AUTOSTART_RUN_VALUE)
                removed.append('Run:%s' % AUTOSTART_RUN_VALUE)
            except FileNotFoundError:
                pass
            finally:
                winreg.CloseKey(key)
        except Exception:
            pass
    return removed


def autostart_enable(startup_directory=None, target=None, workdir=None):
    """开启开机自启 → (ok, msg)"""
    if not is_windows():
        return False, '非 Windows 平台暂不支持'
    path = autostart_path(startup_directory)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        return False, '启动文件夹不可写'
    if target is None:
        target, workdir = autostart_target()
    _cleanup_legacy(startup_directory)          # 先清旧版，防双启动
    if not create_autostart_lnk(path, target, workdir or os.path.dirname(path)):
        return False, '自启写入失败（快捷方式没建起来）'
    return True, '开机自启已开启（启动文件夹快捷方式）'


def autostart_disable(startup_directory=None):
    """关闭开机自启 → (ok, msg)"""
    path = autostart_path(startup_directory)
    existed = os.path.exists(path)
    try:
        if existed:
            os.remove(path)
    except Exception as e:
        return False, '删除自启文件失败：%s' % e
    _cleanup_legacy(startup_directory)
    return True, ('开机自启已关闭（下次开机需手动启动桌宠）' if existed else '开机自启本来就是关的')


def autostart_set(on, startup_directory=None):
    """显式开关（取代原来那个“永远只会关”的 toggle）"""
    return autostart_enable(startup_directory) if on else autostart_disable(startup_directory)


def autostart_toggle(startup_directory=None):
    """翻转 → (新状态, ok, msg)"""
    want = not autostart_enabled(startup_directory)
    ok, msg = autostart_set(want, startup_directory)
    return (bool(want) if ok else not want), ok, msg


# ------------------------------------------------------------------ 已收编：窗口特效

def apply_pet_window(widget):
    """主窗/立绘窗标配：无边框 + 置顶 + 工具窗（不进任务栏）+ 无系统阴影 + 透明背景

    Qt 只在**调用时** import（保持“导入期不拉重依赖”的约定）。
    """
    try:
        from PySide6.QtCore import Qt
        widget.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                              Qt.Tool | Qt.NoDropShadowWindowHint)
        widget.setAttribute(Qt.WA_TranslucentBackground)
        return True
    except Exception:
        return False


def set_topmost(widget, on=True):
    """运行时切置顶（不重建窗口标志集）"""
    try:
        from PySide6.QtCore import Qt
        widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        return True
    except Exception:
        return False


# Windows DWM 常量（备用：需要手工去阴影/改客户区时用）
DWMWA_NCRENDERING_POLICY = 2
DWMNCRP_DISABLED = 1
WS_EX_TOOLWINDOW = 0x80
WS_EX_TOOLWINDOW_FLAG = 0x00000080


def clear_dwm_shadow(hwnd):
    """手工去掉 DWM 阴影/边框（目前主窗靠 Qt 标志就够，此函数备用）"""
    if not is_windows() or not hwnd:
        return False
    try:
        import ctypes
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(int(hwnd), ctypes.byref(ctypes.c_int(-1)))
        policy = ctypes.c_int(DWMNCRP_DISABLED)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(hwnd), DWMWA_NCRENDERING_POLICY,
                                                   ctypes.byref(policy), ctypes.sizeof(policy))
        return True
    except Exception:
        return False
