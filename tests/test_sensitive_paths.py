# -*- coding: utf-8 -*-
"""敏感文件判据必须「一条判据、两个入口」（2026-11-01，WX-163 §二）

## 微信侧实测的事实（这份文件就是把它们钉住）
`read_own_file` 原来自带一份黑名单，但：
  · 漏了 `memory.json`（43 条 facts）和 `balance_history.json` ⇒ **能读全文**
  · shell 路径完全不知道黑名单 ⇒ `Get-Content config.json` 免确认，`.ssh/id_rsa` 也能读

⇒ 病根不是「没有黑名单」，是**黑名单只装在一扇门上**。
⇒ 修法是把判据提到 `pet_sysutils`，两个入口共用一份。

⛔ 本文件第 E 组专门挡「有人又在某个文件里自己写一份清单」——那是这个 bug 的唯一复发路径。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pet_docs  # noqa: E402
import pet_sysutils as ps  # noqa: E402


# ---------- A. 判据本身 ----------
def test_sensitive_parts_cover_all_known_files():
    """清单必须覆盖实盘里真实存在的那些敏感文件（不能凭印象列）"""
    must = ('config.json', 'api_stats.json', 'affection.json', 'memories.json',
            'memory.json', 'balance_history.json', 'chat_memory',
            'id_rsa', 'id_ed25519')
    for name in must:
        assert name in ps.SENSITIVE_NAME_PARTS, '清单漏了 %s' % name


def test_is_sensitive_path_basic():
    assert ps.is_sensitive_path(r'D:\x\config.json') is True
    assert ps.is_sensitive_path('D:/x/CONFIG.JSON') is True, '大小写不敏感'
    assert ps.is_sensitive_path(r'C:\Users\a\.ssh\id_rsa') is True
    assert ps.is_sensitive_path(r'D:\x\README.md') is False
    assert ps.is_sensitive_path('') is False
    assert ps.is_sensitive_path(None) is False


def test_backslash_and_slash_both_work():
    """Windows 路径可能是 \\ 也可能是 /，判据必须都认"""
    assert ps.is_sensitive_path('D:\\x\\memory.json') is True
    assert ps.is_sensitive_path('D:/x/memory.json') is True


# ---------- B. 命令层：WX 实测的那九条 ----------
def test_shell_cannot_read_sensitive_files_without_confirm():
    cmds = [
        'Get-Content {b}\\config.json',
        'Get-Content {b}\\memories.json',
        'Get-Content {b}\\memory.json',
        'Get-Content {b}\\balance_history.json',
        'Get-Content {b}\\api_stats.json',
        'Get-Content {b}\\affection.json',
        r'Get-Content C:\Users\a\.ssh\id_rsa',
        r'Get-Content C:\Users\a\.ssh\id_ed25519',
        'Select-String -Path {b}\\config.json -Pattern key',
    ]
    for c in cmds:
        cmd = c.format(b=BASE)
        r = ps.check_dangerous(cmd)
        assert r, '这条命令免确认就能执行（黑名单没生效）：%s' % cmd


def test_shell_still_free_for_harmless_reads():
    """不能过度拦截：普通只读命令必须仍然免确认（否则用户每次都被问）"""
    harmless = [
        'Get-Content ' + os.path.join(BASE, 'README.md'),
        'dir ' + os.path.join(BASE, 'tests'),
        'Get-Date',
        'whoami',
        'Get-ChildItem ' + os.path.join(BASE, 'assets'),
    ]
    for c in harmless:
        assert ps.check_dangerous(c) is None, '误拦了无害命令：%s' % c


def test_shell_mentioning_sensitive_name_anywhere_is_flagged():
    """即使只是拼路径里带了这个名字，也问一次（保守，多问一次不会出事）"""
    assert ps.check_dangerous('Copy-Item a.txt ' + os.path.join(BASE, 'config.json'))


# ---------- C. 文件工具层：补漏的两个 ----------
def test_read_own_file_blocks_the_two_that_leaked():
    for name in ('memory.json', 'balance_history.json'):
        out = str(pet_docs.read_own_file(name, BASE))
        assert '敏感文件拒绝读取' in out, (
            '%s 仍能被 read_file 读全文（WX-163 实测这条路漏了）' % name)


def test_read_own_file_still_allows_normal_files():
    out = str(pet_docs.read_own_file('README.md', BASE))
    assert '敏感文件拒绝读取' not in out
    assert len(out) > 0


# ---------- D. 两个入口必须同源 ----------
def test_both_entries_share_one_source():
    """文件工具层与命令层对同一个文件名的判定必须一致

    ⛔ 这是本 bug 的核心：两处各写一份清单，必然只修一份。
    """
    for name in ('config.json', 'memory.json', 'balance_history.json', 'README.md'):
        in_file_tool = '敏感文件拒绝读取' in str(pet_docs.read_own_file(name, BASE))
        in_shell = ps.is_sensitive_path(name)
        assert in_file_tool == in_shell, (
            '%s 在两层的判定不一致：文件工具=%s 命令层=%s（两份清单又分叉了）'
            % (name, in_file_tool, in_shell))


# ---------- E. 护栏：不许在别处再写一份清单 ----------
def test_no_second_hardcoded_blacklist():
    """结构钉：除了 pet_sysutils，别处不许再出现那份文件名清单

    ⚠ 用 ast 判、不 grep 文本 —— 注释里提到这些名字（比如本文件的说明）会误判。
       （这个坑我 2026-11-01 已经踩过四次。）
    """
    import ast
    targets = []
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs
                   if d not in ('.git', '__pycache__', 'assets', 'assets_3.0',
                                'release_build', 'backup', '_archive',
                                '_raw_backup', 'logs', '输出', 'tests')]
        for fn in files:
            if fn.endswith('.py') and fn != 'pet_sysutils.py':
                targets.append(os.path.join(root, fn))

    # 在**代码**（非注释/字符串）里找同时出现 3 个以上敏感名的元组/列表
    NAMES = set(ps.SENSITIVE_NAME_PARTS)
    offenders = []
    for path in targets:
        try:
            src = open(path, encoding='utf-8', errors='ignore').read()
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                continue
            vals = set()
            for el in node.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    vals.add(el.value.lower())
            if len(vals & NAMES) >= 3:
                offenders.append('%s:%d' % (os.path.basename(path), node.lineno))
    assert not offenders, (
        '又在别处写了一份敏感文件名清单：%r —— 两份必然只修一份（WX-163 §2.1 的原始病因）'
        % offenders)
