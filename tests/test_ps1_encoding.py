# -*- coding: utf-8 -*-
"""回归：含中文的 .ps1 必须带 UTF-8 BOM

为什么要有这条（2026-10-21 收尾实测）：
    4 个 .ps1 都是 UTF-8 无 BOM，Windows PowerShell 5.1 会按 GBK 解析，
    实测后果：
        build_portable.ps1  语法失败 ⇒ 打包跑不了
        asr_helper.ps1      语法失败 ⇒ **语音输入功能不可用**（这就是 D11-7 的根因）
        tts_helper.ps1      中文提示乱码
    加 BOM 后全部正常。BOM 是 PS 5.1 识别 UTF-8 的唯一可靠手段。

⛔ 这条不是"风格检查"：没有 BOM 的后果是**功能直接失效**，而且失败信息是
   「The string is missing the terminator」这种与真实原因无关的解析错，极难定位。
"""
import io
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOM = b"\xef\xbb\xbf"
SKIP_DIRS = {"release_build", "__pycache__", ".git", "tests"}


def _ps1_files():
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn.lower().endswith(".ps1"):
                out.append(os.path.join(root, fn))
    return out


def test_all_cjk_ps1_have_bom():
    """含中文的 .ps1 必须带 UTF-8 BOM（否则 PS 5.1 下按 GBK 解析会出错）"""
    bad = []
    for p in _ps1_files():
        raw = io.open(p, "rb").read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            bad.append((os.path.basename(p), "不是合法 UTF-8"))
            continue
        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
        has_bom = raw.startswith(BOM)
        if has_cjk and not has_bom:
            bad.append((os.path.basename(p), "含中文但无 BOM"))
    assert not bad, "这些 .ps1 在 PowerShell 5.1 下会解析失败：%r" % (bad,)


def test_packaging_script_parses():
    """打包脚本必须能被 PowerShell 解析（收尾时它因缺 BOM 解析失败，直接导致打不了包）"""
    p = os.path.join(REPO, "tools", "build_portable.ps1")
    if not os.path.exists(p):
        pytest.skip("没有打包脚本")
    raw = io.open(p, "rb").read()
    assert raw.startswith(BOM), "build_portable.ps1 缺 BOM —— PowerShell 5.1 下会解析失败"


def test_asr_helper_check_runs():
    """语音识别辅助脚本 -Check 必须能跑通（D11-7 的根因就在这儿）

    只验「脚本能解析并给出 OK/ERR 结论」，不验麦克风（CI 环境没有）。
    """
    import subprocess
    import sys
    p = os.path.join(REPO, "asr_helper.ps1")
    if not os.path.exists(p):
        pytest.skip("没有 asr_helper.ps1")
    if sys.platform != "win32":
        pytest.skip("仅 Windows")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", p, "-Check"],
                           capture_output=True, timeout=60)
    except FileNotFoundError:
        pytest.skip("没有 powershell")
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    assert "The string is missing the terminator" not in out, \
        "脚本解析失败（编码问题又回来了）：%s" % out[:200]
    assert ("OK" in out) or ("ERR" in out), "脚本没给出结论：%s" % out[:200]
