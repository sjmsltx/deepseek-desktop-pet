#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify.py —— 一键自检（A 类·低风险·仅新增文件）

用途：把"全量测试 + 退出码 + 通过/跳过数"收成一条命令，避免"靠人记得跑"。
放置：`desktop-pet/tools/verify.py`（★ 不要放 tests/，否则会被 pytest 收集 ✗）

用法：
    python tools/verify.py              # 全量测试（默认）
    python tools/verify.py --quick      # 快速档（跳过最慢的一批）
    python tools/verify.py --with-ui    # 追加 golden_ui.py check（较慢，默认不跑）
    python tools/verify.py --list       # 干跑：只列步骤

退出码：0 = 全部通过；非 0 = 有步骤失败（可直接被别的脚本/人判读）
设计：**只做编排与判读**，检查逻辑属于 pytest/既有脚本 ✗
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# GUI 项目专用解释器（TOOLS.md：禁用 AutoClaw 捆绑 python，否则白框事故）
PY = os.environ.get("PET_PY") or r"C:\Users\lby13\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not os.path.exists(PY):
    PY = sys.executable
    print("⚠ 未找到独立 python，已回退当前解释器：", PY)

# 各自独立匹配（行内计数顺序不固定：可能夹 deselected / warnings / xfailed ✗）
RE_PASSED = re.compile(r"(\d+) passed", re.I)
RE_SKIPPED = re.compile(r"(\d+) skipped", re.I)
RE_XFAILED = re.compile(r"(\d+) xfailed", re.I)
RE_FAILED = re.compile(r"(\d+) (?:failed|error)", re.I)


def _g(rx, s, d="0"):
    m = rx.search(s)
    return m.group(1) if m else d


def run(name: str, argv: list[str]) -> tuple[int, str]:
    t0 = time.time()
    print(f"\n=== {name} ===", flush=True)
    print("  $ " + " ".join(argv), flush=True)
    p = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    dt = time.time() - t0
    out = p.stdout or ""
    lines = [l for l in out.splitlines() if l.strip()]
    last = lines[-1] if lines else ""
    print(f"  通过 = {_g(RE_PASSED, last, '?')} ｜ 跳过 = {_g(RE_SKIPPED, last)} ｜ xfailed = {_g(RE_XFAILED, last)}"
          f" ｜ 失败 = {_g(RE_FAILED, last)} ｜ 退出码 = {p.returncode} ｜ 耗时 = {dt:.1f}s", flush=True)
    print(f"  末行：{last[:150]}", flush=True)
    if p.returncode != 0:
        print("  ---- 失败摘要（最后 20 行）----", flush=True)
        for l in lines[-20:]:
            print("   ", l[:150], flush=True)
    return p.returncode, last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过最慢的一批（paint / office）")
    ap.add_argument("--with-ui", action="store_true", help="追加 UI 黄金基线检查")
    ap.add_argument("--list", action="store_true", help="干跑：只列步骤")
    a = ap.parse_args()

    steps = [("全量测试",
              [PY, "-m", "pytest", "tests", "-q", "--durations=5"])]
    if a.quick:
        steps = [("快速测试（-x，排除 paint / office）",
                  [PY, "-m", "pytest", "tests", "-q", "-x", "-k", "not paint and not office"])]

    # ── R1（2026-09-25）：**脚本式检查** ─────────────────────────────────
    # 这些不是 pytest 用例（见 conftest.collect_ignore）→ **在这里单独跑** ✓
    # 目的：避免“移出收集即丢失检查” ✗，同时不让它们再炸整套测试 ✗
    SCRIPT_CHECKS = [
        ("命令闸门", os.path.join("tests", "test_command_gate.py")),
        ("工具注册表", os.path.join("tests", "test_tool_registry.py")),
        ("自改代码安全", os.path.join("tests", "test_pet_selfcode.py")),
        ("系统小工具", os.path.join("tests", "test_pet_sysutils.py")),
        ("文档一致性", os.path.join("tests", "test_pet_docs.py")),
    ]
    steps += [(n, [PY, p]) for n, p in SCRIPT_CHECKS]

    if a.with_ui:
        steps.append(("UI 黄金基线", [PY, os.path.join("tests", "golden_ui.py"), "check"]))

    if a.list:
        for n, argv in steps:
            print("[步骤]", n, "\n      ", " ".join(argv))
        print("\n解释器：", PY)
        return 0

    print("verify.py 一键自检")
    print("项目根：", ROOT)
    print("解释器：", PY, "（★ 必须是独立 python）")
    total = 0
    for n, argv in steps:
        rc, _ = run(n, argv)
        total |= rc
    print("\n" + "=" * 60)
    print("总退出码 =", total, "→", "✅ 通过" if total == 0 else "❌ 失败")
    print("提示：改了 GUI/主题/设置相关代码时，请加 --with-ui 跑黄金基线；另需人工真机冒烟 4 步")
    return total


if __name__ == "__main__":
    sys.exit(main())
