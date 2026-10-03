# -*- coding: utf-8 -*-
"""D2-1 护栏：**静默失败 AST 扫描器 ＋ 基线冻结**（我方开工单 WX-桌宠-20261004-24 §五.1）

背景（`WX-桌宠-20261004-23` §D2-1）：本项目对"静默失败"做过**一次性整改**
（`desktop_pet.py` 原 93 处 `except ...: pass/continue` → 接入 `_silent_log`），
⭐ 但**没有结构性护栏** ✗ —— ①新写的 `except: pass` 不会被拦下 ②出现了**新形态静默**：
**抛错被上游宽泛 `try` 吞掉**（今晚 3 例：角色条 `roleHasAlpha` → 整条空白无报错 ／
闸门卡片 ／ DSH 确认框 `except Exception: result['ok']=False`）。

本文件做两件事：
  ① **检测器**（⭐ **AST 级** ✗ 不看关键词 ✗ —— 关键词会被注释／docstring 骗到 ✓）
     A. `except ...: pass` ／ `except ...: continue`（含裸 `except:`）—— 完全不落痕 ✗
     B. **宽泛 try**（`try` body 直接语句数 ≥ `BROAD_N`）**且 handler 不落 reason**
        （无 `raise` ／ 无日志调用 ／ 无 `_silent_log` ／ 无 `_notify`）✗
  ③ **惯用豁免**（⭐ 单列一类，仍计数、但不判红 ✓）：`except ImportError/ModuleNotFoundError: pass`
     ＝ 可选依赖探测 ✓（行内惯例 ✓，要求它落 reason 属矫枉过正 ✗）—— 单列是为了
     让收敛时**不被它涸没真信号** ✓
  ② **基线冻结**：现存残留记入 `tests/_silent_guard_baseline.json` ✓ ——
     ⭐ 护栏**只对"基线外新增"判红** ✓（不打破在跑的全量 rc0 ✓）；
     ⭐ 基线一路清到 0 是本条的**收敛目标** ✓（不是"冻结了就算完" ✗）。

口径（双方一致 ✓）：**一切"静默处数"由本脚本产出** ✗ —— ⛔ 不手数 ✗（手工会差 ✓）。
    `python tests/test_silent_guard.py --report`   # 打印 文件→行号 明细 ＋ 合计数
    `python tests/test_silent_guard.py --freeze`   # 重新冻结基线（⛔ 需在 PR 里说明理由 ✗）
"""
import ast
import hashlib
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '_silent_guard_baseline.json')

# ⭐ 宽泛 try 的"大段逻辑"阈值（直接语句数）——
#    ⭐ 取 4：**实测能抓全今晚三例** ✓（例 1 角色条 4 句 / 例 3 确认框 5 句 ✓）；
#    仍不误伤 `try: x = d['k'] except KeyError: return None`（1 句）这类**窄用法** ✓
BROAD_N = 4

# ⭐ "落了 reason"的判定线索：handler 里出现任一，就算**有痕** ✓（不算静默 ✗）
_LOG_NAMES = {
    '_silent_log', '_notify', '_notify_cost_blocked', 'print', 'write_log',
    'log', 'warning', 'warn', 'error', 'exception', 'critical', 'info', 'debug',
}
_SKIP_DIRS = {'tests', '__pycache__', '.git', 'dist', 'build', '.venv', 'venv',
              'node_modules', 'backup', '_backup', '_raw_backup'}


def _read(path):
    """按 utf-8-sig 读（⛔ 容 BOM ✗ —— 本项目有 PowerShell 写入带 BOM 的历史）"""
    with io.open(path, encoding='utf-8-sig') as f:
        return f.read()


def _unparse(node):
    try:
        return ast.unparse(node)          # 3.9+ ✓（规范化：注释/空白不影响 → 基线稳定 ✓）
    except Exception:
        return repr(node)


def _key_hash(node):
    return hashlib.sha1(_unparse(node).encode('utf-8')).hexdigest()[:10]


def _call_name(node):
    f = getattr(node, 'func', None)
    if f is None:
        return ''
    return getattr(f, 'id', None) or getattr(f, 'attr', None) or ''


def _handler_logs_reason(handler):
    """handler 是否**落痕** ✓：`raise` ／ 日志调用 ／ `_silent_log` ／ `_notify` 任一即算 ✓"""
    for n in ast.walk(handler):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Call) and _call_name(n) in _LOG_NAMES:
            return True
    return False


def _is_pass_only(handler):
    """`except ...: pass` ／ `except ...: continue`（含裸 `except:`）＝ 完全不落痕 ✗"""
    body = [n for n in handler.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    return len(body) == 1 and isinstance(body[0], (ast.Pass, ast.Continue))


_TOLERATED_EXC = {'ImportError', 'ModuleNotFoundError'}


def _is_optional_import(handler):
    """⭐ **惯用豁免**：`except ImportError/ModuleNotFoundError: pass` ＝ 可选依赖探测 ✓
    （⛔ 属行内惯例，不应要求落 reason ✗；但**仍计数** ✓ —— 只是单列一类，便于收敛时不被它淹没 ✓）"""
    names = set()
    for t in handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]:
        nm = getattr(t, 'id', None) or getattr(t, 'attr', None)
        if nm:
            names.add(nm)
    return bool(names) and names <= _TOLERATED_EXC


def scan_source(src, fname):
    """返回该文件的静默点列表：[{file,line,kind,snippet,key}] ✓"""
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:                      # ⭐ 解析失败必须明说 ✗ 不静默 ✗
        out.append({'file': fname, 'line': getattr(exc, 'lineno', 0) or 0,
                    'kind': 'parse-error', 'snippet': repr(exc), 'key': 'parse-error'})
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            if _is_pass_only(h):
                kind = 'optional-import' if _is_optional_import(h) else 'except-pass'
                out.append({'file': fname, 'line': h.lineno, 'kind': kind,
                            'snippet': _unparse(node)[:160], 'key': _key_hash(node)})
            elif len(node.body) >= BROAD_N and not _handler_logs_reason(h):
                out.append({'file': fname, 'line': h.lineno, 'kind': 'broad-swallow',
                            'snippet': _unparse(node)[:160], 'key': _key_hash(node)})
    return out


def _iter_py_files(root=REPO):
    """产品代码扫描面：仓库根 `*.py` ＋ `collab/*.py` ✓（⛔ **不含 `tests/`** ✗ —— 测试里的
    try/except 是夹具行为，纳入会淹没真信号 ✗；⛔ 不含依赖/产物目录 ✗）"""
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if os.path.isfile(p) and name.endswith('.py'):
            yield p
    cdir = os.path.join(root, 'collab')
    if os.path.isdir(cdir):
        for name in sorted(os.listdir(cdir)):
            p = os.path.join(cdir, name)
            if os.path.isfile(p) and name.endswith('.py'):
                yield p


def scan_repo(root=REPO, include_tests=False):
    issues = []
    files = list(_iter_py_files(root))
    if include_tests:
        tdir = os.path.join(root, 'tests')
        if os.path.isdir(tdir):
            for name in sorted(os.listdir(tdir)):
                if name.endswith('.py'):
                    files.append(os.path.join(tdir, name))
    for p in files:
        rel = os.path.relpath(p, root).replace('\\', '/')
        try:
            src = _read(p)
        except Exception as exc:                    # ⭐ 读失败必须明说 ✗
            issues.append({'file': rel, 'line': 0, 'kind': 'read-error',
                           'snippet': repr(exc), 'key': 'read-error'})
            continue
        issues.extend(scan_source(src, rel))
    return issues


def _key(issue):
    return '%s|%s|%s' % (issue['file'], issue['kind'], issue['key'])


def load_baseline(path=BASELINE):
    if not os.path.exists(path):
        return None
    with io.open(path, encoding='utf-8') as f:
        return set(json.load(f).get('keys', []))


def split_new(issues, base):
    """基线外**新增**＝判红对象 ✓；基线内 ＝ 已知残留（记录但不红 ✓）"""
    if base is None:
        return list(issues), []
    new = [i for i in issues if _key(i) not in base]
    known = [i for i in issues if _key(i) in base]
    return new, known


def summarize(issues):
    by_kind = {}
    for i in issues:
        by_kind[i['kind']] = by_kind.get(i['kind'], 0) + 1
    by_file = {}
    for i in issues:
        by_file[i['file']] = by_file.get(i['file'], 0) + 1
    return by_kind, by_file


# ─────────────────────────── 用例 ───────────────────────────
def test_no_new_silent_spots():
    """⭐ 主护栏：不得**新增**静默点 ✓（基线内的已知残留不在此判红 ✓；`optional-import` 豁免 ✓）"""
    issues = scan_repo()
    base = load_baseline()
    assert base is not None, '⛔ 缺基线 %s ✗（先 `--freeze` ✓）' % os.path.basename(BASELINE)
    new, known = split_new(issues, base)
    new = [i for i in new if i['kind'] != 'optional-import']      # ⭐ 惯用豁免 ✓ 不判红
    detail = '\n'.join('  %s:%s [%s]' % (i['file'], i['line'], i['kind']) for i in new)
    assert not new, ('⛔ 新增静默失败点 %d 处 ✗（基线内已知 %d 处 ✓）：\n%s\n'
                     '⭐ 处置：落 reason（`_silent_log` / `raise` / 日志）✓，'
                     '⛔ 不许直接 `--freeze` ✗（须在 PR 说明为何无法落痕 ✗）'
                     % (len(new), len(known), detail))


def test_no_new_broad_swallow():
    """⭐ 分项护栏：**宽泛 try 吞异常**不得新增 ✓（今晚三例的形态 ✓）"""
    issues = [i for i in scan_repo() if i['kind'] == 'broad-swallow']
    base = load_baseline() or set()
    new = [i for i in issues if _key(i) not in base]
    detail = '\n'.join('  %s:%s' % (i['file'], i['line']) for i in new)
    assert not new, '⛔ 新增"宽泛 try 吞异常" %d 处 ✗：\n%s' % (len(new), detail)


def test_detector_has_teeth_on_tonight_three():
    """⭐ **有牙证明** ✓：今晚**真实发生过的 3 例**必须**都能判红** ✗
    （⛔ 语料按真实代码形状写 ✗，不是"为了过而编的简单例子" ✗）"""
    cases = {
        # 例 1：角色条 —— `roleHasAlpha()` 抛错被上游宽泛 try 吞掉 → 整条空白且无报错 ✗
        'role_bar': (
            'def _render_role_bar(self):\n'
            '    items = []\n'
            '    try:\n'
            '        rows = self._role_rows()\n'
            '        for r in rows:\n'
            '            items.append(self._role_chip(r))\n'
            '        html = self._join(items)\n'
            '        self.role_box.setHtml(html)\n'
            '    except Exception:\n'
            '        return\n'),
        # 例 2：闸门卡片 —— 构造卡片时抛错被吞 → 卡片消失且无痕 ✗
        'gate_card': (
            'def _notify_cost_blocked(self, why):\n'
            '    try:\n'
            '        card = self._build_gate_card(why)\n'
            '        self._append_display(card)\n'
            '        self._flush_display()\n'
            '        self._touch_status_bar(card["title"])\n'
            '        self._mark_once_per_day()\n'
            '        self._log_gate(why)\n'
            '    except Exception:\n'
            '        pass\n'),
        # 例 3：DSH 后台确认框 —— `except Exception: result['ok']=False` ＝ 静默拒绝 ✗
        'dsh_confirm': (
            'def _request_confirm(self, ask):\n'
            '    result = {"ok": False}\n'
            '    try:\n'
            '        evt = threading.Event()\n'
            '        self.confirm_signal.emit(self._make_ask(ask, evt, result))\n'
            '        evt.wait(timeout=120)\n'
            '        self._after_confirm(result)\n'
            '        self._touch_status_bar(ask)\n'
            '    except Exception:\n'
            '        result["ok"] = False\n'
            '    return result\n'),
    }
    missed = []
    for name, src in cases.items():
        kinds = [i['kind'] for i in scan_source(src, name + '.py')]
        if 'except-pass' not in kinds and 'broad-swallow' not in kinds:
            missed.append('%s（检出：%s）' % (name, kinds or '无 ✗'))
    assert not missed, '⛔ 护栏对今晚真实例**未判红** ✗ ＝ 空扫 ✗：\n  ' + '\n  '.join(missed)


def test_detector_is_ast_not_keyword():
    """⭐ 反面证明：**注释／docstring 里的 `except: pass` 不得被算成违规** ✓
    （⛔ 关键词扫描会误报 ✗ —— 我方此前就被自己的 docstring 骗过 ✓）"""
    src = ('# 说明：这里以前是 except Exception: pass ✗\n'
           'MSG = """历史写法：\n'
           '    except Exception:\n'
           '        pass\n'
           '"""\n'
           'def ok():\n'
           '    return 1\n')
    assert not scan_source(src, 'docstring.py'), '⛔ 扫到了注释/docstring ✗ ＝ 不是 AST 级 ✗'


def test_report_caliber():
    """⭐ 口径自检：本脚本必须能报出**明细**（文件→行号）＋ 合计 ✓
    —— 双方一律引用本脚本合计数 ✗（⛔ 不手数 ✗）"""
    issues = scan_repo()
    by_kind, by_file = summarize(issues)
    assert isinstance(by_kind, dict) and isinstance(by_file, dict)
    for i in issues:
        assert i['file'] and i['kind'], '明细缺字段：%r' % (i,)


# ─────────────────────────── CLI ───────────────────────────
def _report(include_tests=False):
    issues = scan_repo(include_tests=include_tests)
    base = load_baseline()
    new, known = split_new(issues, base)
    by_kind, by_file = summarize(issues)
    print('== 静默失败扫描（口径：tests/test_silent_guard.py）==')
    print('扫描面：仓库根 *.py ＋ collab/*.py%s'
          % (' ＋ tests/*.py' if include_tests else '（不含 tests/ ✓）'))
    uniq = len({_key(i) for i in issues})
    print('合计：%d 处（唯一指纹 %d）｜ 基线内（已知残留）：%d 处 ｜ 基线外（新增 ✗）：%d 处'
          % (len(issues), uniq, len(known), len(new)))
    print('按类：%s' % (by_kind or '（无）'))
    print('按文件：')
    for f in sorted(by_file, key=lambda k: -by_file[k]):
        print('  %-28s %d' % (f, by_file[f]))
    print('明细（文件:行 [类]）：')
    for i in sorted(issues, key=lambda x: (x['file'], x['line'])):
        flag = '新增✗' if i in new else '  '
        print('  %s %s:%s [%s]' % (flag, i['file'], i['line'], i['kind']))
    return issues


def _freeze():
    issues = scan_repo()
    keys = sorted({_key(i) for i in issues})
    with io.open(BASELINE, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'note': 'D2-1 静默护栏基线：基线内＝已知残留，只判新增✗（optional-import 惯用豁免不判红）；收敛目标是清零',
                   'kinds': ['except-pass', 'broad-swallow', 'optional-import'],
                   'count': len(keys), 'keys': keys}, f, ensure_ascii=False, indent=1)
    print('已冻结基线：%d 处（唯一指纹 %d）→ %s' % (len(issues), len(keys), BASELINE))


if __name__ == '__main__':
    import tempfile
    if '--report' in sys.argv:
        _report(include_tests='--with-tests' in sys.argv)
    elif '--freeze' in sys.argv:
        _freeze()
    else:
        test_no_new_silent_spots()
        test_no_new_broad_swallow()
        test_detector_has_teeth_on_tonight_three()
        test_detector_is_ast_not_keyword()
        test_report_caliber()
        print('✅ 静默护栏 5 项断言通过')
