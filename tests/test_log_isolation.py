# -*- coding: utf-8 -*-
"""回归测试：module 级 fixture 构造 PetWidget 也不能漏日志到真 logs/pet.log

## 为什么要这条

2026-10-28 实测定位：5 个文件的 module 级 fixture 里构造 `PetWidget()`，
构造日志漏进真 `logs/pet.log`（每文件 1 条，「环境：python=」）。

两条原因叠加：
1. `_isolate_log_file` 是 function 级 autouse，但 **module 级 fixture 先初始化**
2. function 级 teardown 的 `pet_log.reset()` **回到真路径**，形成「用例间隙真路径窗口」；
   而 module 级 fixture 的初始化时机是「第一个用到它的用例」——
   若前几个用例不需要它，初始化就落在这个窗口里

## 为什么用子进程测

这是「跑一整个 pytest 进程」才知道的行为。在同一个进程内自测会污染当前会话的日志路径。
⇒ 起一个子进程跑最小用例集，比对真 `logs/pet.log` 里「环境：python=」的条数。

那句是**每进程只打一次**（`_env_logged` 类属性），所以：
- 子进程若突破隔离 ⇒ 真日志 +1
- 隔离正常 ⇒ 真日志 +0

## 局限（诚实说明）

- 如果真 `logs/pet.log` 正被在跑的桌宠**轮转**，条数可能变化 —— 极罕见，失败时先看这个
- 子进程约 2~4 秒
"""
import io
import os
import subprocess
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(BASE, 'logs', 'pet.log')
MARK = '环境：python='


def _count_mark():
    if not os.path.exists(LOG):
        return 0
    try:
        t = io.open(LOG, 'rb').read().decode('utf-8', 'replace')
    except PermissionError:
        pytest.skip('真 pet.log 被占用，无法比对')
    return sum(1 for l in t.splitlines() if MARK in l)


@pytest.mark.parametrize('target', [
    'tests/test_rich_copy.py',            # ★ 前 4 个用例不用 module fixture，第 5 个才初始化
    'tests/test_text_selection.py',       # 对照：第 1 个用例就用 module fixture
    'tests/test_md_markup_detect.py',
])
def test_module_scope_fixture_does_not_leak_to_real_log(target):
    """module 级 fixture 构造 PetWidget 时，日志必须已在 tmp 里"""
    if not os.path.exists(os.path.join(BASE, target)):
        pytest.skip('目标文件不存在：%s' % target)
    before = _count_mark()
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env.pop('PYTHONPATH', None)   # 不继承外层 PYTHONPATH（避免探针插件混入）
    r = subprocess.run([sys.executable, '-m', 'pytest', target, '-q', '--tb=no',
                        '-p', 'no:cacheprovider'],
                       cwd=BASE, capture_output=True, env=env, timeout=600)
    out = (r.stdout + r.stderr).decode('utf-8', 'replace')
    after = _count_mark()

    assert 'passed' in out or 'no tests ran' in out, '子进程没跑起来：\n%s' % out[-800:]
    assert after == before, (
        '真 logs/pet.log 的「%s」多了 %d 条 ⇒ module 级 fixture 构造突破了日志隔离。\n'
        '  检查：① conftest 的 `_isolate_log_file_module` 还在吗？\n'
        '        ② function 级 `_isolate_log_file` 的 teardown 是不是又改回 pet_log.reset() 了？\n'
        '          （reset 会回到真路径，形成「用例间隙真路径窗口」）'
        % (MARK, after - before))
