# -*- coding: utf-8 -*-
"""回归测试：~~删除线~~（Owner 2026-10-28 选 A 方案）

## 为什么做这个

Owner 2026-10-27 回忆「早期版本会把错误文本划一道横杠」。
查证后确认**桌宠任何历史版本都没这功能**（git grep 五关键词 0 命中、
`git log --all -S` 三个关键词全空、覆盖 539 提交/11 标签/4 分支）。
Owner 2026-10-28 选 A：加通用 markdown 删除线 `~~文字~~`。

## 关键技术事实（实测得出，写死在测试里防回退）

| 标签 | Qt fontStrikeOut | 用不用 |
|---|---|---|
| `<s>x</s>` | **True** | ✓ 用它 |
| `<del>x</del>` | True | 也可 |
| `<strike>x</strike>` | **False** | ✗ 不能用 |

## 三条不许破的保护

1. **代码块 / 行内代码里的 `~~` 不许被处理**（asr.py 注释里就有 `Speech~~~<语言>`）
2. **不跨行配对**（`~~第一行\n第二行~~` 不该变删除线）
3. **三个及以上波浪号不成对**（`~~~` 不能当成成对标签）
"""
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import chat_render  # noqa: E402


def _app():
    """拿一个 QApplication（照 `tests/test_asr.py:24-26` 的既有写法）

    ⚠ 必须有：`QTextDocument` 在没有 QApplication 的进程里会
      **Windows fatal exception: access violation**（进程直接崩）。
      纯字符串用例不需要它，但凡读 `charFormat()` 的用例都需要。
    """
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _ensure_qapp():
    """每个用例前确保 QApplication 存在（session 内只创建一次，重复调用无害）"""
    _app()
    yield


def md(text):
    return chat_render.md_to_html(text)


# ---------------- 基本功能 ----------------

def test_basic_strikethrough():
    assert md('这段话~~不要了~~保留') == '这段话<s>不要了</s>保留'


def test_multiple_strikethrough_in_one_line():
    out = md('~~A~~ 和 ~~B~~')
    assert out == '<s>A</s> 和 <s>B</s>'


def test_coexists_with_bold_and_italic():
    assert '<b>重点</b>' in md('**重点** 与 ~~删掉~~')
    assert '<s>删掉</s>' in md('**重点** 与 ~~删掉~~')
    assert '<i>强调</i>' in md('*强调* 与 ~~删掉~~')
    assert '<s>删掉</s>' in md('*强调* 与 ~~删掉~~')


# ---------------- 三条保护 ----------------

def test_no_cross_line_pairing():
    """`~~第一行\\n第二行~~` 不该被配成删除线（与粗体/斜体同一套不跨行规则）"""
    out = md('~~第一行\n第二行~~')
    assert '<s>' not in out, '跨行配对了：%r' % out


def test_code_block_tilde_untouched():
    """★ 代码块里的 `~~~` 必须原样保留（asr.py 注释里就有 `Speech~~~<语言>`）"""
    src = '```python\nx = "Speech~~~<语言>"\n```'
    out = md(src)
    assert '<s>' not in out, '代码块里的 ~~~ 被当成删除线了：%r' % out
    assert '~~~' in out, '代码块内容被破坏：%r' % out


def test_code_block_with_real_pair_untouched():
    """★ 真正的保护测试：代码块里放一对完整的 `~~文字~~`，不许被改成删除线

    原来那条 `Speech~~~<语言>` 只有 3 个波浪号、构不成配对，
    所以无论渲染顺序对错都不会被改写 —— **它验证不到保护**。
    这条补上：顺序若错（先处理再占位），代码块内容会被改成 `<s>`。
    """
    src = '```python\n# ~~这行不该被划掉~~\nx = 1\n```'
    out = md(src)
    assert '<s>' not in out, '代码块里的成对 ~~ 被改写了：%r' % out
    assert '~~这行不该被划掉~~' in out, '代码块内容被破坏：%r' % out


def test_qt_no_strike_inside_code_block_with_pair():
    """Qt 层：代码块里的 `~~文字~~` 不许真的被划掉"""
    struck = _struck_texts(md('```\n~~不该划~~\n```'))
    assert struck == [], '代码块内容被划掉了：%r' % struck


def test_inline_code_tilde_untouched():
    """★ 行内代码里的 `~~~` 也必须原样保留"""
    out = md('用法 `Speech~~~语言` 结束')
    assert '<s>' not in out, '行内代码里的 ~~~ 被处理了：%r' % out
    assert 'Speech~~~语言' in out


@pytest.mark.parametrize('src', [
    '标记 Speech~~~ 之后',   # 三个波浪号
    '价格 ~100 元',           # 单个
    '~~~~',                   # 四个
    '~~',                     # 只有两个
    '~~~a~~~',                # 两侧各三个
])
def test_tilde_edge_cases_dont_break(src):
    """这些都不该产生删除线，也不该抛异常"""
    out = md(src)
    assert '<s>' not in out, '%r 被误判成删除线：%r' % (src, out)


# ---------------- 表格内不生效（钉住既有行为，不是缺陷） ----------------

def test_table_cell_strikethrough_not_applied():
    """★ 表格单元格内的 `~~x~~` **不**转成删除线（2026-10-28 现状，已知限制）

    为什么不修（实测依据，不是偷懒）：

    | 样式 | 表格内 | 普通段落 |
    |---|---|---|
    | 粗体 `**B**` | ✗ | ✓ |
    | 斜体 `*I*` | ✗ | ✓ |
    | 删除线 `~~S~~` | ✗ | ✓ |
    | 链接 `[l](u)` | ✗ | ✓ |
    | 行内代码 | ✓ | ✓ |

    表格在 `md_to_html` 里被整体占位成 HTML，所有行内样式规则都跑不到单元格内部；
    只有行内代码例外（它的占位早于表格）。

    ⇒ 删除线跟粗体/斜体/链接同命，**不是异类**。
    ⇒ 单独把删除线规则提到表格之前，会让它成为唯一能在表格内生效的行内样式，
      反而制造不一致。要统一修就是重构渲染管线，不属于最小修复。

    这条测试的作用：把这个限制**钉死**，免得以后被当成 bug 反复"修"。
    （与 `test_lone_trailing_angle_kept` 同一思路）
    """
    out = md('| A | B |\n|---|---|\n| ~~旧~~ | 新 |')
    assert '<s>' not in out, '表格内出现了删除线 —— 行为变了，需同步更新本文档的取舍说明：%r' % out
    assert '~~旧~~' in out, '单元格内容被破坏：%r' % out


def test_table_cell_other_inline_styles_also_not_applied():
    """对照组：粗体/斜体/链接在表格内同样不生效 —— 证明删除线不是异类

    这一条是「为什么钉住而不是修」的**证据**。若哪天有人把删除线单独修好，
    这条会红，提醒他「其它样式仍不生效，你制造了不一致」。
    """
    out = md('| A | B |\n|---|---|\n| **粗** | *斜* |')
    assert '<b>' not in out, '表格内粗体生效了（与删除线取舍的前提变了）'
    assert '<i>' not in out, '表格内斜体生效了（与删除线取舍的前提变了）'
    out2 = md('| A |\n|---|\n| [文字](http://x) |')
    assert '<a ' not in out2, '表格内链接生效了（与删除线取舍的前提变了）'


def test_inline_code_in_table_does_work():
    """记录既有不一致：行内代码在表格内**能**生效（因占位顺序早于表格）

    ⛔ 不是本次引入，也不修（修 = 重构渲染管线）。
    写出来是为了让下一个人知道「表格内并非全部样式都失效」，别拿它当反例推翻上一条。
    """
    out = md('| A |\n|---|\n| `code` |')
    assert '<code' in out, '行内代码在表格内失效了（占位顺序可能被改了）'


# ---------------- Qt 真渲染（不是看字符串） ----------------

def _struck_texts(html):
    """逐字符读 charFormat().fontStrikeOut()，返回被划掉的连续片段

    ⚠ 不用 `QTextBlock.iterator`：实测在含 `<pre>` 的文档上会
      **Windows fatal exception: access violation**（进程直接崩，不是断言失败）。
      `QTextCursor` 是稳定路径。
    ⚠ `clearSelection()` 已把光标落在选中字符之后，**不要再 movePosition** ——
      多移一次就是每两个字只读一个（我第一版这么错过）。
    """
    _app()   # 保险：无 QApplication 时 QTextDocument 会 access violation
    from PySide6.QtGui import QTextCursor, QTextDocument
    doc = QTextDocument()
    doc.setHtml('<html><body>%s</body></html>' % html)
    out, run = [], []
    cur = QTextCursor(doc)
    cur.movePosition(QTextCursor.Start)
    while not cur.atEnd():
        cur.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor, 1)
        txt = cur.selectedText()
        struck = cur.charFormat().fontStrikeOut()
        cur.clearSelection()
        if txt and txt not in ('\u2029', '\n'):
            if struck:
                run.append(txt)
            elif run:
                out.append(''.join(run))
                run = []
        elif run:
            out.append(''.join(run))
            run = []
    if run:
        out.append(''.join(run))
    return out


def test_qt_actually_renders_strike():
    """★ 关键：Qt 必须真的把这段文字标记为删除线

    只断言 `<s>` 字符串存在是不够的 —— `<strike>` 也存在但不生效。
    这里读 `charFormat().fontStrikeOut()`，是渲染层真判据。
    """
    struck = _struck_texts(md('这段话~~不要了~~保留'))
    assert struck == ['不要了'], 'Qt 没有把该段标成删除线：%r' % struck


def test_qt_does_not_strike_code():
    """代码块里的 `~~~` 不能被 Qt 标成删除线"""
    struck = _struck_texts(md('```\nSpeech~~~\n```'))
    assert struck == [], '代码块被划掉了：%r' % struck


def test_qt_strikes_multiple_segments():
    """多段删除线都要被 Qt 认到"""
    struck = _struck_texts(md('~~A~~ 和 ~~B~~'))
    assert struck == ['A', 'B'], '多段没全划：%r' % struck


def test_qt_no_strike_when_cross_line():
    """跨行的 `~~` 不该被划"""
    struck = _struck_texts(md('~~第一行\n第二行~~'))
    assert struck == [], '跨行被划了：%r' % struck


def test_uses_s_not_strike_tag():
    """⛔ 不许用 `<strike>`（实测 Qt 下 fontStrikeOut=False，等于没效果）"""
    out = md('~~要删的~~')
    assert '<strike>' not in out, '用了不生效的 <strike> 标签'
    assert '<s>' in out
