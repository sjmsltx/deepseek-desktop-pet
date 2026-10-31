# -*- coding: utf-8 -*-
"""测试不得污染真实 logs/（WX-154 的防回归）

根因（2026-10-31 实测定位）：
    test_failure_audit.py 曾用「裸赋值 gov.log_event + importlib.reload(gov) 恢复」。
    **reload 会重新执行 governance 模块** ⇒ LOG_DIR 被重置成真实 logs 路径，
    从那之后同一次 pytest 会话里所有测试文件都往真实审计日志写（实测 +8 行/轮）。

    隐蔽性：逐个文件单独跑 21 个全部 +0 —— 只有一起跑才暴露。

本文件锁四件事：
A. 会话内 LOG_DIR 指向临时目录（隔离生效）
B. **真实验证第二道防线**：故意把 LOG_DIR 改回真实路径，
   下一个测试开始时必须已被拉回（用两条串联测试实现，不真 reload ——
   真 reload 本身就是污染源，测污染的手段不能变成污染源）
C. 源码里不再出现「裸赋值模块属性」
D. 源码里不再出现 reload(governance)
"""
import ast
import io
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _real_logs():
    return os.path.abspath(os.path.join(BASE, 'logs'))


# ---------- A. 隔离生效 ----------
def test_log_dir_is_isolated():
    import governance as gov
    assert os.path.abspath(gov.LOG_DIR) != _real_logs(), \
        'LOG_DIR 指向真实 logs（隔离失效）：%s' % gov.LOG_DIR


def test_audit_path_not_in_real_logs():
    import governance as gov
    p = os.path.abspath(gov.audit_path())
    assert not p.startswith(_real_logs() + os.sep), '审计文件仍落在真实 logs：%s' % p


# ---------- B. 防线真有效（两条串联）----------
def test_zz1_deliberately_break_isolation():
    """故意把 LOG_DIR 改回真实路径，模拟 reload 的后果

    本测试自己不写任何日志，所以即使防线失效也不会污染 —— 只留一个坏状态给下一条。
    """
    import governance as gov
    gov.LOG_DIR = _real_logs()
    assert os.path.abspath(gov.LOG_DIR) == _real_logs()


def test_zz2_guard_restored_isolation():
    """上一条故意破坏后，本测试开始时必须已被防线拉回临时目录"""
    import governance as gov
    assert os.path.abspath(gov.LOG_DIR) != _real_logs(), (
        '第二道防线失效：上一条把 LOG_DIR 改成真实路径后，下一条开始时仍指向 %s'
        % gov.LOG_DIR)


# ---------- C/D. 源码防复发（用 ast，不受注释干扰）----------
def _iter_test_sources():
    """遍历 tests/ 下的测试源码

    用 encoding='utf-8-sig' 读：仓库里有两个旧测试文件带 BOM，
    用 utf-8 读出来首字符是 U+FEFF，ast.parse 会报「非打印字符」——
    那是读取方式的问题，不是文件本身的错。
    """
    tests_dir = os.path.join(BASE, 'tests')
    for fn in sorted(os.listdir(tests_dir)):
        if fn.startswith('test_') and fn.endswith('.py'):
            yield fn, io.open(os.path.join(tests_dir, fn), encoding='utf-8-sig').read()

def _dotted(node):
    """把 a.b.c 形式的表达式还原成 'a.b.c'；不是这种形式返回 ''"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return '.'.join(reversed(parts))
    return ''


def test_source_has_no_bare_log_event_assignment():
    """裸赋值模块属性会让状态无法自动恢复（当初就是这么漏的）

    ⛔ 用 ast 判，不用 grep —— 注释里提到这行写法不该算违规。
    """
    bad = []
    for fn, src in _iter_test_sources():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            for t in targets:
                if _dotted(t) in ('gov.log_event', 'governance.log_event'):
                    bad.append('%s:%d' % (fn, node.lineno))
    assert not bad, ('发现裸赋值模块属性（应改用 monkeypatch.setattr）：%s'
                     % ', '.join(bad))


def test_source_has_no_reload_of_governance():
    """reload 会重置 LOG_DIR 等模块级状态，测试里一律不许用

    ⛔ 同样用 ast 判：注释与 docstring 里写 reload(gov) 不算违规。
    """
    bad = []
    for fn, src in _iter_test_sources():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = _dotted(f)
            # importlib.reload(gov) / reload(gov)
            is_reload = name in ('importlib.reload', 'reload')
            if not is_reload or not node.args:
                continue
            arg = _dotted(node.args[0])
            if arg in ('gov', 'governance'):
                bad.append('%s:%d' % (fn, node.lineno))
    assert not bad, ('发现 reload(governance)（会重置 LOG_DIR）：%s' % ', '.join(bad))
