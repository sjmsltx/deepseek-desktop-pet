# -*- coding: utf-8 -*-
"""v6.56 新增：自改代码【成功路径】回归测试

背景：tests/test_pet_selfcode.py 原有 12 组断言全是"拒绝分支"（非法文件/路径穿越/语法错误…），
成功路径 0 覆盖 —— 于是「CRLF 文件匹配必然失败 + 备份从来没写成」这类问题能一路绿灯。
本文件专门覆盖成功路径与本次修复的四个根因。
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pet_selfcode import edit_own_code  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sandbox(name):
    d = os.path.join(tempfile.gettempdir(), "selfcode_t_" + name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    subprocess.run(["git", "init", "-q"], cwd=d, capture_output=True)
    return d


def test_lf_oldtext_matches_crlf_file():
    """R1 核心修复：CRLF 文件 + LF 的 old_text 必须能匹配（此前必然失败）"""
    d = _sandbox("r1")
    p = os.path.join(d, "m.py")
    with open(p, "wb") as f:
        f.write(b"A = 1\r\nB = 2\r\nC = 3\r\n")
    r = edit_own_code("A = 1\nB = 2", "A = 111\nB = 222", file="m.py", base_dir=d)
    assert r.startswith("✅"), "LF old_text 仍无法匹配 CRLF 文件：%s" % r[:80]
    assert "A = 111" in open(p, encoding="utf-8").read()


def test_line_endings_preserved():
    """R2 修复：编辑后必须保留原文件行尾（此前 CRLF 会被整体改写成 LF）"""
    d = _sandbox("r2")
    p = os.path.join(d, "m.py")
    with open(p, "wb") as f:
        f.write(b"A = 1\r\nB = 2\r\nC = 3\r\n")
    edit_own_code("", "B = 22", start_line=2, end_line=2, file="m.py", base_dir=d)
    raw = open(p, "rb").read()
    assert raw.count(b"\r\n") == 3, "CRLF 被改写：现在有 %d 个 CRLF" % raw.count(b"\r\n")
    # LF 文件也不应被改成 CRLF
    p2 = os.path.join(d, "n.py")
    with open(p2, "wb") as f:
        f.write(b"A = 1\nB = 2\nC = 3\n")
    edit_own_code("", "B = 22", start_line=2, end_line=2, file="n.py", base_dir=d)
    raw2 = open(p2, "rb").read()
    assert raw2.count(b"\r\n") == 0 and raw2.count(b"\n") == 3, "LF 文件被污染"


def test_backup_really_created():
    """R3 修复：改前备份必须真的落盘（此前 datetime 未导入 → backup/ 一直是空的）"""
    d = _sandbox("r3")
    p = os.path.join(d, "m.py")
    open(p, "w", encoding="utf-8").write("A = 1\n")
    r = edit_own_code("A = 1", "A = 2", file="m.py", base_dir=d)
    assert r.startswith("✅")
    bdir = os.path.join(d, "backup")
    files = os.listdir(bdir) if os.path.isdir(bdir) else []
    assert files, "backup/ 仍为空（备份没写出）"
    assert "改前备份" in r, "成功消息未提到备份"
    # 备份内容应为改前版本
    assert open(os.path.join(bdir, files[0]), encoding="utf-8").read().strip() == "A = 1"


def test_trailing_space_tolerant():
    """行尾空格差异可容忍（AI 常把行尾空格丢掉）"""
    d = _sandbox("r4")
    p = os.path.join(d, "m.py")
    open(p, "w", encoding="utf-8").write("X = 1   \nY = 2\n")
    r = edit_own_code("X = 1\nY = 2", "X = 9\nY = 8", file="m.py", base_dir=d)
    assert r.startswith("✅"), "行尾空格差异导致匹配失败：%s" % r[:80]


def test_syntax_guard_still_blocks():
    """语法门必须仍在（这条此前是好的，防止修坏）"""
    d = _sandbox("r5")
    p = os.path.join(d, "m.py")
    open(p, "w", encoding="utf-8").write("A = 1\nB = 2\n")
    before = open(p, encoding="utf-8").read()
    r = edit_own_code("A = 1", "def broken(:", file="m.py", base_dir=d)
    assert "语法验证失败" in r, "语法门失效：%s" % r[:80]
    assert open(p, encoding="utf-8").read() == before, "非法改动竟然落盘了"


def test_multi_match_hint():
    """多处匹配要给出可操作建议（改用行号模式）"""
    d = _sandbox("r6")
    p = os.path.join(d, "m.py")
    open(p, "w", encoding="utf-8").write("A = 1\nA = 1\n")
    r = edit_own_code("A = 1", "A = 2", file="m.py", base_dir=d)
    assert "多处匹配" in r or "处匹配" in r
    assert "start_line" in r, "未提示改用行号模式"


def test_success_message_useful():
    """成功消息要能指导使用者：文件 + 位置 + 重启生效"""
    d = _sandbox("r7")
    p = os.path.join(d, "m.py")
    open(p, "w", encoding="utf-8").write("A = 1\n")
    r = edit_own_code("", "A = 2", start_line=1, end_line=1, file="m.py", base_dir=d)
    assert "m.py" in r and "第 1" in r and "重启" in r


def test_inline_fragment_fallback():
    """v6.56b：行内片段也要能匹配（模型常只给一句话中间的片段）"""
    d = _sandbox("r8")
    p = os.path.join(d, "m.py")
    open(p, "w", encoding="utf-8").write('DESC = "自动带 git 保护（改前提交基线，改后语法验证）"\n')
    r = edit_own_code("改前提交基线", "改前记录基线 hash", file="m.py", base_dir=d)
    assert r.startswith("✅"), "行内片段未能匹配：%s" % r[:90]
    assert "改前记录基线 hash" in open(p, encoding="utf-8").read()


def test_no_backup_on_failed_match():
    """v6.56b：匹配失败不应留下备份（避免 backup/ 噪音）"""
    d = _sandbox("r9")
    p = os.path.join(d, "m.py")
    open(p, "w", encoding="utf-8").write("A = 1\n")
    edit_own_code("这段根本不存在", "X", file="m.py", base_dir=d)
    bdir = os.path.join(d, "backup")
    assert not (os.path.isdir(bdir) and os.listdir(bdir)), "失败也写了备份"


def test_source_guards():
    """源码护栏：不许退回旧写法（sys.executable 校验 / datetime 未导入 / 静默 pass）"""
    src = open(os.path.join(ROOT, "pet_selfcode.py"), encoding="utf-8-sig").read()
    # 去掉模块 docstring 后再扫（docstring 里会描述“旧写法”，不应触发护栏）
    body = src.split('"""', 2)[2] if src.count('"""') >= 2 else src
    assert "import datetime as _dt" in src, "datetime 未导入（备份会再次静默失败）"
    assert "sys.executable" not in body, "语法校验又用回了 sys.executable（冻结版会失败）"
    assert "ast.parse(new_src)" in body, "缺少进程内语法校验"
    assert "_file_eol" in body and "_norm_lines" in body, "缺少行尾处理"
    # 各失败路径必须接日志（不再是静默 pass）
    for tag in ("'backup'", "'git_head'", "'search_code'", "'write_file_tool'", "'edit_own_code'"):
        assert "_log(" + tag in body, "失败路径 %s 未接日志" % tag
    # 只允许 _log() 自身保留静默兜底（日志助手不能拖垮调用方）
    assert body.count("except Exception:\n        pass") <= 1, "出现多处静默兜底"


if __name__ == "__main__":
    test_lf_oldtext_matches_crlf_file()
    test_line_endings_preserved()
    test_backup_really_created()
    test_trailing_space_tolerant()
    test_syntax_guard_still_blocks()
    test_multi_match_hint()
    test_success_message_useful()
    test_inline_fragment_fallback()
    test_no_backup_on_failed_match()
    test_source_guards()
    print("✅ 自改代码成功路径 10 项断言通过")
