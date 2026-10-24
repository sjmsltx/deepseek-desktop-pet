# -*- coding: utf-8 -*-
"""结构完整性 ratchet：页面构建函数不得被「插入新方法」截断（v3.1f，2026-10-24）

事故经过（我 19:40 那次）：
    给 settings_ui 加 `_open_stats_window` 方法时，插入点选在了 `_page_usage`
    函数体**中间** → 后半段（server_clock / _hd_tip / 若干 f.addRow）
    整段被吞进新方法 → SettingsDialog 该页少一半控件
    → 全量跑到 test_settings_dialog_does_not_write_config 直接 0xC0000005。

为什么既有护栏没拦住：
    `compile()` 只验语法。这种「结构合法但语义截断」它看不出来。
    我当时补的自我校验是「三个字符串还在不在」—— **WX-109 §3.3 指出这不硬**：
    那三行被挪到别处仍在，断言照样过。

本文件改用 ast 数函数体语句（WX 的建议，我采纳）：
    截断会让语句数**骤降**，而正常改动不会。用 ratchet 锁下限。

运行：python -m pytest tests/test_page_structure_ratchet.py -q
"""
import ast
import io
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 基线（2026-10-24 实测）：语句数只许涨，不许跌破下限
#
# 下限为什么要卡这么紧（初版写 -12%，实测**漏掉**了真事故）：
#   按真实形态注入（插 def _oops 让后续行成为它的方法体）后，
#   _page_usage 语句数只从 68 → 61（少 7 条），初版下限 60 **没红**，
#   是「关键控件还在不在」那条抓到的。
#   ⇒ 收紧到当前值 -2：正常改页面不会连删 3 条语句，而真事故必然掉更多。
BASELINE = {
    '_page_usage': 66,      # 实测 68（这次事故就发生在这个函数）
    '_page_model': 50,      # 实测 52
    '_page_voice': 46,      # 实测 48
    '_page_general': 40,    # 实测 42
}


def _funcs(path):
    src = io.open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    return {n.name: (len(n.body), n.lineno, n.end_lineno)
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)}


def test_page_functions_not_truncated():
    """settings_ui 各页面构建函数的语句数不得跌破下限"""
    funcs = _funcs(os.path.join(BASE, 'settings_ui.py'))
    bad = []
    for name, floor in BASELINE.items():
        if name not in funcs:
            bad.append('%s 不见了（被改名/删除？）' % name)
            continue
        cnt = funcs[name][0]
        if cnt < floor:
            bad.append('%s 语句数 %d < 下限 %d' % (name, cnt, floor))
    assert not bad, ('页面构建函数疑似被截断（插入新方法时吞掉了后半段）：\n  '
                     + '\n  '.join(bad)
                     + '\n⚠ 这不是「代码变简洁」，是结构事故。'
                       '参考 2026-10-24 那次：68 → 少了半页控件 → 段错误。')


def test_page_usage_still_has_usage_widgets():
    """_page_usage 必须仍然包含它该有的控件（防「语句数够但内容被换掉」）"""
    funcs_src = io.open(os.path.join(BASE, 'settings_ui.py'), encoding='utf-8').read()
    tree = ast.parse(funcs_src)
    seg = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == '_page_usage':
            seg = ast.get_source_segment(funcs_src, n)
            break
    assert seg, '_page_usage 不见了'
    must = ['lb_bal_shared', 'lb_today_cost', 'lb_purposes', 'lb_care',
            '_hd_tip', 'server_clock']
    missing = [m for m in must if m not in seg]
    assert not missing, '_page_usage 里缺了：%s（该页控件被吞掉了）' % missing


def test_no_method_defined_inside_function_body():
    """不得把方法定义塞进**另一个函数体内部**（真嵌套形态）

    ⚠ 边界（实测得出的，别误以为它能抓所有截断）：
      2026-10-24 那次事故里，插入 `    def _oops(self):` 之后，
      `_page_usage` 在它之前就**结束了**，后续代码成为 `_oops` 的成员
      —— 那是「并列方法吃掉后续」，不是「嵌套函数」。
      实测：这种形态本条**抓不到**，由上面两条（语句数 ratchet + 关键控件）抓到。
      本条抓另一种：`def` 真的写在另一函数的缩进里（那样 ast 才会嵌套）。
    """
    path = os.path.join(BASE, 'settings_ui.py')
    src = io.open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    offenders = []
    for outer in ast.walk(tree):
        if not isinstance(outer, ast.FunctionDef):
            continue
        for inner in ast.walk(outer):
            if isinstance(inner, ast.FunctionDef) and inner is not outer:
                # 类里的方法不算嵌套；只看「函数套函数」
                offenders.append('%s 内定义了 %s（行 %d）'
                                 % (outer.name, inner.name, inner.lineno))
    assert not offenders, ('发现函数内嵌函数定义 —— 极可能是插入点选错、'
                           '把后续代码吞进了新函数：\n  ' + '\n  '.join(offenders))
