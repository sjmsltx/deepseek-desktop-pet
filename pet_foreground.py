# -*- coding: utf-8 -*-
"""前台程序感知（v6.59，可选功能 · 默认关闭）

用途：让「主动关心」知道用户此刻在用什么程序，从而在明显忙碌时自动让路
——此前 judge_wakeup 的提示词里写着「用户明显在忙时不打扰」，但**根本没有
任何「忙不忙」的信号**，全靠模型猜。本模块补上这个信号。

========================= 隐私边界（硬约束，勿改） =========================
1. 只读取前台窗口所属**进程的可执行文件名**（例如 code.exe）。
2. **不读取窗口标题**、不读取页面内容、不截屏、不读剪贴板、不读输入内容。
3. **不联网**：本模块不 import 任何网络库，数据只在进程内传给提示词。
4. 只有在用户于「设置 → 通用 → 前台程序感知」**显式勾选**后才生效；默认关闭。
5. 返回值为程序名本身（如 code.exe），不含完整路径，避免泄露目录结构。

以上 1–5 条由 `tests/test_foreground_privacy.py` 做源码级护栏断言，改坏会红灯。
=========================================================================
"""
import ctypes
import os

__all__ = ['foreground_process_name', 'categorize', 'busy_level', 'is_busy',
           'busy_hint', 'privacy_note', 'category_label', 'LEVEL_HIGH', 'LEVEL_MID']

LEVEL_HIGH = 'high'   # 明显忙碌：会议 / 游戏 / 看视频 —— 建议不打扰
LEVEL_MID = 'mid'     # 专注但可打断：写代码 / 文档 —— 可以说话，但更短更轻
LEVEL_NONE = 'none'   # 不表态：浏览器 / 终端 / 未知 —— 维持原有判断逻辑

# 进程名（去 .exe、小写）→ 类别。数据驱动，新增程序只加一行。
_CATEGORIES = {
    'meeting': (
        'zoom', 'teams', 'ms-teams', 'wemeetapp', 'wemeet', 'tencentmeeting', 'txmeeting',
        'voov', 'dingtalk', 'feishu', 'lark', 'skype', 'slack', 'discord', 'webexmta',
        'bytedance', 'qqlive-meeting', 'screencast',
    ),
    'game': (
        'steam', 'steamwebhelper', 'genshinimpact', 'yuanshen', 'dota2', 'cs2', 'csgo',
        'leagueclient', 'league of legends', 'valorant', 'minecraft', 'javaw',
        'battle.net', 'epicgameslauncher', 'wegame', 'dnplayer', 'nox', 'gta5', 'rdr2',
    ),
    'video': (
        'potplayermini64', 'potplayer', 'vlc', 'mpv', 'mpc-hc64', 'mpc-be64', 'kmplayer',
        'bilibili', 'bilibili-recorder', 'youku', 'iqiyi', 'qqlive', 'tencentvideo',
        'pptv', 'kmp', 'obs64', 'obs32',
    ),
    'code': (
        'code', 'code-insiders', 'vscodium', 'cursor', 'trae', 'zed', 'devenv', 'pycharm64',
        'pycharm', 'idea64', 'idea', 'webstorm64', 'clion64', 'goland64', 'rider64',
        'sublime_text', 'notepad++', 'vim', 'nvim', 'emacs', 'spyder', 'jupyter-notebook',
        'rstudio', 'matlab', 'arcgispro', 'arcmap', 'blender', 'unity', 'unityhub', 'godot',
        'hbuilderx', 'eclipse', 'android studio64', 'ssms', 'datagrip64', 'navicat',
    ),
    'office': (
        'winword', 'excel', 'powerpnt', 'onenote', 'outlook', 'wps', 'et', 'wpp',
        'acrobat', 'acrord32', 'foxitreader', 'sumatrapdf', 'notepad', 'wordpad',
    ),
    'browser': (
        'chrome', 'msedge', 'firefox', '360se', '360chrome', 'qqbrowser', 'opera', 'brave',
        'vivaldi', 'safari', 'iexplore',
    ),
    'terminal': (
        'windowsterminal', 'wt', 'cmd', 'powershell', 'pwsh', 'conhost', 'mintty',
        'git-bash', 'bash', 'wsl',
    ),
}
_LABELS = {
    'meeting': '会议 / 通话', 'game': '游戏', 'video': '视频播放', 'code': '写代码 / 设计',
    'office': '文档 / 办公', 'browser': '浏览器', 'terminal': '终端',
}
_LEVELS = {'meeting': LEVEL_HIGH, 'game': LEVEL_HIGH, 'video': LEVEL_HIGH,
           'code': LEVEL_MID, 'office': LEVEL_MID}
_BY_NAME = {name: cat for cat, names in _CATEGORIES.items() for name in names}


def _basename(path):
    """从完整路径取文件名（小写、不含路径，避免泄露目录结构）"""
    if not path:
        return ''
    name = str(path).replace('\\', '/').split('/')[-1].strip().lower()
    return name


def foreground_process_name():
    """前台窗口所属进程的可执行文件名（如 'code.exe'）；取不到返回 ''。

    只调用 GetForegroundWindow / GetWindowThreadProcessId / QueryFullProcessImageNameW，
    **不调用任何取窗口标题的 API**（见模块头部隐私边界第 2 条）。
    """
    if os.name != 'nt':
        return ''
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ''
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ''
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ''
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(len(buf))
            ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            return _basename(buf.value) if ok else ''
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ''


def categorize(process):
    """进程名 → 类别（'meeting'/'game'/'video'/'code'/'office'/'browser'/'terminal'/'other'）"""
    name = _basename(process)
    if not name:
        return ''
    return _BY_NAME.get(name, _BY_NAME.get(name[:-4] if name.endswith('.exe') else name, 'other'))


def category_label(cat):
    """类别 → 中文标签（用于提示词与界面展示）"""
    return _LABELS.get(cat, '其他')


def busy_level(process):
    """忙碌等级：high（会议/游戏/视频）/ mid（写代码/办公）/ none（不表态）"""
    return _LEVELS.get(categorize(process), LEVEL_NONE)


def is_busy(process):
    """是否属于「明显忙碌」（high）——仅此等级才建议直接不打扰"""
    return busy_level(process) == LEVEL_HIGH


def busy_hint(process=None):
    """生成给唤醒判断用的一句话；无信号时返回 ''（不影响原有逻辑）。

    只包含①进程名②类别，不含路径、不含窗口标题。
    """
    name = _basename(process if process is not None else foreground_process_name())
    if not name:
        return ''
    cat = categorize(name)
    if cat in ('', 'other'):
        return '当前前台程序：%s。' % name
    return '当前前台程序：%s（%s）。' % (name, category_label(cat))


def privacy_note():
    """隐私说明（界面展示用，措辞与模块头部边界一致）"""
    return ('只读取当前前台程序的进程名（例如 code.exe）；不读取窗口标题、不读取页面内容、'
            '不截屏、不上传。仅用于在你开会/打游戏/看视频时让桌宠少打扰。')


def _demo():
    """自测：打印当前前台程序 + 几个样例的判定（不影响桌宠运行）"""
    print('可用性：', 'Windows' if os.name == 'nt' else '非 Windows（返回空）')
    print('隐私说明：', privacy_note())
    print()
    cur = foreground_process_name()
    print('当前前台程序：', repr(cur))
    print('类别 / 忙碌等级 / 提示：', categorize(cur), busy_level(cur), repr(busy_hint(cur)))
    print()
    print('%-24s %-10s %-6s %s' % ('样例进程', '类别', '等级', '生成提示'))
    for p in ('code.exe', 'pycharm64.exe', 'zoom.exe', 'genshinimpact.exe', 'potplayer.exe',
              'winword.exe', 'chrome.exe', 'windowsterminal.exe', 'unknownapp.exe', ''):
        print('%-24s %-10s %-6s %s' % (p or '(空)', categorize(p) or '-', busy_level(p),
                                       busy_hint(p) or '(无)'))


if __name__ == '__main__':
    _demo()
