# tests/test_structural_defaults.py
# -*- coding: utf-8 -*-
"""
结构钉：`if self.X:` 读到的属性，必须在**构造期必定执行到**的位置被赋值过。

## 为什么这么判（三条被否决的写法，实测过）

1. **全类赋值集合** → 放行 `tray`。因为 `self.tray = QSystemTrayIcon(...)` 确实写在
   `_ensure_tray()` 里 ⇒ 正好漏掉它本来要防的那一例。
2. **只认 `__init__` 字面赋值** → 报 23 条全误报。本仓 `__init__` 是 5 行分发，字面赋值 0 个。
3. **顶层语句就算，遇 return 不停** → 报 7 条，`tray` 被放行（错）。
   `_ensure_tray()` 顶层有赋值，但它前面有 `if not self._tray_allowed(): return None`。

## 采用的规则

1. 从 `__init__` 出发，只看函数体**顶层语句**（不递归进 if/try/for/while/with）
2. **遇顶层 `return` / `raise` 即停**
3. 顶层 `self.m(...)` 调用递归进 `m`
4. 读点 = `if/while` 条件里的 `self.X` / `not self.X`

## 当前 8 条报警的处置

其中 5 条（tray / _guide_inbox / drag_to_bin / screenshot_timer / balance_watch）
的默认值都写在 `_load_ai_config()` 里，而该函数体被一个 259 行的大 `try` 包住、
`except` 用 `_silent_log` 吞掉一切 ⇒ **碰巧安全，不是结构安全**。
把它们移出 try（`_init_state_and_config` 里 `_load_ai_config()` 之前）即可消除。

⛔ 不许因为报得多就放宽成「全类赋值」——那样就抓不到 tray 了。
"""
import ast
import os

KNOWN_SAFE = {}          # 属性名 -> 理由。留空 = 全部报红，这是故意的
BRANCH = (ast.If, ast.Try, ast.For, ast.While, ast.With, ast.AsyncWith)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _targets(node):
    return node.targets if isinstance(node, ast.Assign) else [node.target]


def _attr(t):
    if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self':
        return t.attr
    return None


def guaranteed_assignments(funcs, entry='__init__'):
    out, seen = set(), set()

    def walk(method):
        f = funcs.get(method)
        if f is None or method in seen:
            return
        seen.add(method)
        for s in f.body:
            if isinstance(s, (ast.Return, ast.Raise)):
                break                      # 后面不一定执行
            if isinstance(s, BRANCH):
                continue                   # 分支里不算
            if isinstance(s, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for t in _targets(s):
                    a = _attr(t)
                    if a:
                        out.add(a)
            for n in ast.walk(s):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == 'self':
                    walk(n.func.attr)

    walk(entry)
    return out


def conditional_reads(funcs):
    out = {}
    for name, f in funcs.items():
        for n in ast.walk(f):
            if not isinstance(n, (ast.If, ast.While)):
                continue
            t = n.test
            a = None
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self':
                a = t.attr
            elif isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not):
                o = t.operand
                if isinstance(o, ast.Attribute) and isinstance(o.value, ast.Name) and o.value.id == 'self':
                    a = o.attr
            if a:
                out.setdefault(a, []).append((name, n.lineno))
    return out


def _analyse():
    src = open(os.path.join(ROOT, 'desktop_pet.py'), encoding='utf-8', errors='replace').read()
    tree = ast.parse(src)
    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == 'PetWidget'), None)
    assert cls is not None, '没找到 PetWidget'
    funcs = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    g = guaranteed_assignments(funcs)
    reads = conditional_reads(funcs)
    return g, reads


def test_no_attribute_guarded_by_if_without_guaranteed_init():
    g, reads = _analyse()
    alarms = {a: v for a, v in reads.items() if a not in g and a not in KNOWN_SAFE}
    msgs = ['self.%s 被 `if self.%s:` 当一定存在，但不在构造期必定赋值里（读点 %s）'
            % (a, a, ', '.join('%s:L%d' % (m, ln) for m, ln in sites))
            for a, sites in sorted(alarms.items())]
    assert not msgs, (
        '结构性默认值缺失 %d 处（一处根因可引发多个测试崩）:\n  ' % len(msgs)
        + '\n  '.join(msgs)
    )


def test_check_itself_is_not_degenerate():
    """自检：判据别退化成「什么都有」或「什么都没有」"""
    g, reads = _analyse()
    assert len(g) > 100, '构造期必定赋值属性过少（%d），判据可能失效' % len(g)
    assert len(reads) > 5, '条件读点过少（%d），判据可能失效' % len(reads)
