# -*- coding: utf-8 -*-
"""结构完整性 ratchet：页面构建函数不得被「插入新方法」截断
（v3.6 重写判据，2026-10-24；起因 WX-111 §4）

事故经过（我 19:40 那次）：
    给 settings_ui 加 `_open_stats_window` 方法时，插入点选在了 `_page_usage`
    函数体**中间** → 后半段整段被吞进新方法 → 该页少一半控件
    → 全量跑到 test_settings_dialog_does_not_write_config 直接 0xC0000005。

## 为什么 v3.1f 的「语句数 ratchet」要重写

v3.1f 用「语句数跌破下限就红」，下限卡到实测值 -2。
WX-111 §4 指出这有两个毛病，**我实测确认，两点都成立**：

1. **没有安全区间**。实测（收件箱/02-加工/实验-三判据区分度.py）：

   | 情形 | 语句数变化 |
   |---|---|
   | 事故·插在 25% 处 | **-45** |
   | 事故·插在 50% 处 | **-22** |
   | 事故·插在 90% 处 | **-6** |
   | 正常重构·删 4 条 | -3 |

   ⇒ 事故的丢失量**从 6 到 45 不等，取决于插入位置**。
   而正常重构也能删 3~5 条 —— **两者重叠**，卡哪都有人误伤。

2. **余量 2 条会被正常重构撞红**，然后下一个人不看就调低下限
   （初版 -12% → 后来 -2%，反方向同样会发生）。

## v3.6 的判据：三条独立信号，任一跌破就红

| 判据 | 基线 | 灵敏度（实测） |
|---|---|---|
| 语句数 ≥ 基线 × 0.82 | 只挡「整段被删」这类大事故 | 事故 -22~-45 红；正常 -3 绿 |
| **函数跨度** ≥ 基线 − 12 行 | 事故的本质是「函数提前结束」 | 事故 -51~-77 红；正常 -4 绿 |
| **self 属性集合** 不得减少 | 事故的本质是「控件创建语句没了」 | 事故 -4~-8 红；正常 0 绿 |

跨度用 `end_lineno - lineno + 1`（函数**自身**尺寸），不用绝对 `end_lineno` ——
后者会随文件上方任何增删整体漂移，误报来源多一条。

⚠ 一处边界（我原来写错了，WX-112 §3.3 更正）：
    我曾在文档里写「插在 90% 处三条都不到线、抓不到」。**实测是能抓到的** ——
    按「第 61 条顶层语句前插入」的形态：语句 -7、**跨度 -17（85 < 门槛 90）→ 红**。
    我当初测出 -10 是因为插入位置选在候选行里、含了嵌套块内的行，基准不同。

    ⇒ 正确说法：**尾部形态靠跨度判据兜住，但余量只有 5 行**（85 vs 90）。
      余量小意味着：如果有人把 SPAN_SLACK 从 12 调大到 18，这条就漏了。
      调这个常量前先想清楚：它同时决定了「正常重构的容忍度」和「尾部事故的灵敏度」。

运行：python -m pytest tests/test_page_structure_ratchet.py -q
"""
import ast
import io
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 基线（2026-10-24 v3.6 实测）：(语句数, 函数跨度行数, self 属性集合)
#   self 属性集合是**精确集合**，新增控件要同步加进来（这是有意的：
#   新加控件时你会来看这个文件，正好看见这条注释）。
#
#   ⚠ **删掉废弃控件同样要同步移除**（WX-112 §3.4 指出原来只写了「新增」）：
#     删一个控件赋值 → self 属性少一个 → 本条**必红**。
#     那不是误报，是「基线没跟上真实改动」。第一次遇到的人容易把它当 bug 处理，
#     所以写在这儿：**改完控件，回来同步 BASELINE 的集合**。
# ⚠ 属性集合必须是**实测**值，不能凭猜（我第一版就凭猜写错了一整套名字：
#   猜的是 lb_cache/lb_peak/btn_stats，实际是 ck_cost/sp_bal/sp_rt_tok 等）。
BASELINE = {
    '_page_usage': (68, 102, {
        'ck_cost', 'ck_rt', 'lb_bal_shared', 'lb_care', 'lb_purposes',
        'lb_rt_note', 'lb_today_cost', 'sp_bal', 'sp_cost', 'sp_rt_cost', 'sp_rt_tok'}),
    '_page_model': (52, 86, {
        'cb_char', 'cb_effort', 'cb_temp', 'ck_pass_rsn', 'ck_reason',
        'ck_strict', 'ck_vfiles', 'ck_vision', 'lb_model', 'sp_row'}),
    '_page_voice': (48, 98, {
        'cb_voice_content', 'cb_voice_name', 'cb_voice_rate', 'ck_voice',
        'ck_voice_night', 'ed_voice_custom', 'ed_voice_local',
        'ed_voice_prompt', 'ed_voice_ref'}),
    '_page_general': (46, 65, {
        'cb_edge', 'cb_lang', 'ck_active', 'ck_adv', 'ck_bubble', 'ck_fg',
        'ck_probe', 'ed_city', 'lb_fg_note', 'lb_fg_now'}),
}

STMT_RATIO = 0.82     # 语句数只挡大事故（WX-111 §4.2 建议放宽，我实测后取 0.82）
SPAN_SLACK = 12       # 跨度允许少 12 行：正常重构删几条语句 + 连带空行远到不了

SKIP_SPAN = {         # 这几个函数下面紧跟别的定义，跨度会被重构影响，不锁跨度
}


def _parse():
    path = os.path.join(BASE, 'settings_ui.py')
    src = io.open(path, encoding='utf-8').read()
    return src, ast.parse(src)


def _measure(src):
    """返回 {函数名: {stmt, span, attrs}}"""
    tree = ast.parse(src)
    out = {}
    for n in ast.walk(tree):
        if not isinstance(n, ast.FunctionDef):
            continue
        attrs = set()
        for sub in ast.walk(n):
            if isinstance(sub, ast.Assign):
                for t in sub.targets:
                    if isinstance(t, ast.Attribute) and \
                            isinstance(t.value, ast.Name) and t.value.id == 'self':
                        attrs.add(t.attr)
        out[n.name] = {
            'stmt': len(n.body),
            'span': n.end_lineno - n.lineno + 1,
            'attrs': attrs,
            'lineno': n.lineno,
            'end': n.end_lineno,
        }
    return out


def test_page_functions_not_truncated():
    """三条判据任一条跌破 → 判为截断

    报错信息里带上「哪条判据、实测值、基线」，避免下一个看的人
    只看到「红了」就去调低基线。
    """
    src, _ = _parse()
    funcs = _measure(src)
    bad = []

    for name, (base_stmt, base_span, base_attrs) in BASELINE.items():
        if name not in funcs:
            bad.append('%s **整个函数不见了**（被改名/删除？）' % name)
            continue
        f = funcs[name]

        # ① 语句数（粗筛，只挡整段被删）
        floor = int(base_stmt * STMT_RATIO)
        if f['stmt'] < floor:
            bad.append('%s 语句数 %d < %d（基线 %d × %.0f%%）'
                       % (name, f['stmt'], floor, base_stmt, STMT_RATIO * 100))

        # ② 函数跨度（事故本质：函数提前结束）
        if name not in SKIP_SPAN:
            span_floor = base_span - SPAN_SLACK
            if f['span'] < span_floor:
                bad.append('%s 跨度 %d 行 < %d（基线 %d，少 %d 行）'
                           % (name, f['span'], span_floor, base_span,
                              base_span - f['span']))

        # ③ self 属性集合（精确，最贴近事故本质）
        if base_attrs is not None:
            missing = base_attrs - f['attrs']
            if missing:
                bad.append('%s 少了 self 属性：%s'
                           % (name, '、'.join(sorted(missing))))

    assert not bad, (
        '页面构建函数疑似被截断（插入新方法时吞掉了后半段）：\n  '
        + '\n  '.join(bad)
        + '\n\n⚠ 这不是「代码变简洁」，是结构事故。\n'
          '  参考 2026-10-24 那次：68 条语句 → 少半页控件 → 段错误 0xC0000005。\n'
          '  若确实是**有意重构**：同步改 BASELINE，并在提交说明里写清删了什么、为什么。'
    )


def test_page_usage_still_has_usage_widgets():
    """_page_usage 必须仍然包含它该有的控件（防「语句数够但内容被换掉」）

    这条是 v3.1f 那次**真正抓到事故**的判据（不是语句数 ratchet）。
    它也兜住「插在 90% 处、三条 ratchet 都不到线」的轻微形态。
    """
    src, tree = _parse()
    seg = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == '_page_usage':
            seg = ast.get_source_segment(src, n)
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
      实测：这种形态本条**抓不到**，由上面两条抓到。
      本条抓另一种：`def` 真的写在另一函数的缩进里（那样 ast 才会嵌套）。
    """
    _, tree = _parse()
    offenders = []
    for outer in ast.walk(tree):
        if not isinstance(outer, ast.FunctionDef):
            continue
        for inner in ast.walk(outer):
            if isinstance(inner, ast.FunctionDef) and inner is not outer:
                offenders.append('%s 内定义了 %s（行 %d）'
                                 % (outer.name, inner.name, inner.lineno))
    assert not offenders, ('发现函数内嵌函数定义 —— 极可能是插入点选错、'
                           '把后续代码吞进了新函数：\n  ' + '\n  '.join(offenders))


def test_baseline_matches_reality():
    """基线本身不得与实测脱节（防「基线写的是三年前的数字」）

    WX-111 §3 报过同类问题：源护栏下限写 55，实测 124，防护力≈0。
    这条保证 BASELINE 与真实值不会漂太远。
    """
    src, _ = _parse()
    funcs = _measure(src)
    drift = []
    for name, (base_stmt, base_span, _attrs) in BASELINE.items():
        if name not in funcs:
            drift.append('%s 不存在' % name)
            continue
        f = funcs[name]
        if f['stmt'] > base_stmt * 1.6:
            drift.append('%s 实际语句 %d 已远超基线 %d（基线上调？）'
                         % (name, f['stmt'], base_stmt))
        if f['span'] > base_span * 1.8:
            drift.append('%s 实际跨度 %d 已远超基线 %d（基线上调？）'
                         % (name, f['span'], base_span))
    assert not drift, ('ratchet 基线与实际脱节，护栏正在自我安慰：\n  '
                       + '\n  '.join(drift))
