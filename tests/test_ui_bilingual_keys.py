# -*- coding: utf-8 -*-
"""双语键一致性（2026-11-06 补）

## 为什么有这条

README 对外写着「中英双语 146 = 146 条，键集合完全一致（零缺失）」。
在全仓测试里搜 `UI_ZH|UI_EN|双语|零缺失`，此前**一条断言都没有** ——
那句「零缺失」从写进去到被发现不成立，中间没被任何测试验过。

而且它被写错过两次：
  · 最初「114 = 114」（实际 115/115，差 1，近似）
  · 改成「49 = 49」（实际 147/146，错 3 倍，且「零缺失」是假话）
    ⇒ 49 的来源：扫描脚本的正则只匹配 **4 空格缩进** 的键，而这两个字典内部
      混着 8 空格缩进的段，53 个键漏在外面。**探针本身造出了那个数。**

本测试用运行时字典比对，不用任何正则。
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import desktop_pet as dp  # noqa: E402


def test_ui_zh_en_keys_match():
    """双语键必须一一对应 —— README 宣称「零缺失」由这条锁住"""
    zh, en = set(dp.UI_ZH), set(dp.UI_EN)
    only_zh = sorted(zh - en)
    only_en = sorted(en - zh)
    assert zh == en, '只在中文：%r；只在英文：%r' % (only_zh, only_en)


def test_ui_dicts_have_no_duplicate_literal_keys():
    """字典里不许有重复字面键（重复会让「数了多少个键」失真）

    `mem_time` 曾在 UI_ZH/UI_EN 各出现两次（工具栏与列头，值相同）：运行时 len
    看不出问题（后者覆盖前者），但用 ast 数字面键会多出 1，正是「简单计数 vs 真实结构」的差。
    """
    import ast
    import io
    src = io.open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    bad = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in ('UI_ZH', 'UI_EN'):
                    keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
                    seen, dup = set(), set()
                    for k in keys:
                        if k in seen:
                            dup.add(k)
                        seen.add(k)
                    if dup:
                        bad[t.id] = sorted(dup)
    assert not bad, '有重复字面键：%r' % bad


def test_both_dicts_nonempty():
    """防空测试：两边都有条目，且数量相当（防哪天被清空还绿）"""
    assert len(dp.UI_ZH) > 100, '中文条数异常：%d' % len(dp.UI_ZH)
    assert len(dp.UI_EN) > 100, '英文条数异常：%d' % len(dp.UI_EN)
    assert abs(len(dp.UI_ZH) - len(dp.UI_EN)) == 0, (
        '两边条数不一致：%d vs %d' % (len(dp.UI_ZH), len(dp.UI_EN)))
