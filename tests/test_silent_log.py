# -*- coding: utf-8 -*-
"""v6.54 新增：静默异常接入日志（用户可感知失败路径）回归测试

背景：体检发现 desktop_pet.py 有 93 处 `except ...: pass/continue`，
出问题时"它怎么不记得了 / 怎么不动了"完全无痕。本版把其中 50 处
（AI 任务链 / 数据落盘 / 记忆提取 / 工具执行 / 用量统计 / 系统集成）接入统一日志出口。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_silent_log_callable():
    """统一出口本身必须不抛异常（否则会把主程序拖垮）"""
    import desktop_pet as dp
    dp._silent_log('unittest', ValueError('故意触发'))
    dp._silent_log('unittest', None)          # 连 None 也不能崩
    assert callable(dp._silent_log)


def test_silent_log_writes_through_pet_log(tmp_path=None):
    """日志必须真的落到 logs/pet.log（走 pet_log，INFO 级）"""
    import time
    import desktop_pet as dp
    log = os.path.join(ROOT, 'logs', 'pet.log')
    marker = 'SILENT-UNIT-%d' % int(time.time() * 1000 % 1e9)
    dp._silent_log(marker, RuntimeError('单测写入'))
    time.sleep(0.2)
    txt = open(log, encoding='utf-8').read() if os.path.exists(log) else ''
    assert marker in txt, '未写入 logs/pet.log'
    assert 'RuntimeError' in txt.split(marker)[1][:200], '缺少异常类型'


def test_high_value_paths_are_instrumented():
    """源码护栏：高价值路径不得再静默吞异常"""
    src = open(os.path.join(ROOT, 'desktop_pet.py'), encoding='utf-8-sig').read()
    assert 'def _silent_log(where, exc):' in src, '缺少统一出口'
    assert src.count("_silent_log('") >= 45, '接入点不足 45 处（实际 %d）' % src.count("_silent_log('")
    for fn in ('_post_stream', '_extract_worker', '_smart_open', '_next_task'):
        seg = src.split('def %s' % fn, 1)
        assert len(seg) == 2, '函数 %s 不存在' % fn
        body = seg[1][:6000]
        assert '_silent_log(' in body, '%s 仍未接入日志' % fn


def test_pyproject_has_no_bom():
    """护栏：pyproject.toml 不得带 BOM（PowerShell 写入会带入，TOML 解析会失败）"""
    raw = open(os.path.join(ROOT, 'pyproject.toml'), 'rb').read()
    assert not raw.startswith(b'\xef\xbb\xbf'), 'pyproject.toml 带 BOM，TOML 会解析失败'


if __name__ == '__main__':
    test_silent_log_callable()
    test_silent_log_writes_through_pet_log()
    test_high_value_paths_are_instrumented()
    test_pyproject_has_no_bom()
    print('✅ 静默异常接入 4 项断言通过')
