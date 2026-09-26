# -*- coding: utf-8 -*-
"""任务队列护栏（v6.79 · 缺陷 76）

背景（实测 ✓）：
  `self._task_queue` 在 `__init__` 链路里**从未初始化** ✗ →
  `_enqueue_task` 直接抛 AttributeError（未被捕获 ✗）、
  `_next_task` / `_refresh_task_sidebar` 每次**静默**失败 ✗ →
  任务队列（FCFS 排队 / 自动续跑 / 侧栏「任务」页）**整体失效** ✗。

发现路径 ✓：从 `logs\\pet.log` 的 `pet.silent` 行抓到 `_next_task:812 AttributeError`
**反复出现**（15:13 / 15:27 / 15:36 / 15:38 ✓）—— 用户侧完全看不到 ✗。
定位依据 ✓：全仓搜 `_task_queue =` 只有「拖拽重排时赋值」与「测试里手动赋值」✗。

运行：python -m pytest tests/test_task_queue.py -q
"""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _pet():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    return p


def test_task_queue_is_initialized():
    p = _pet()
    assert hasattr(p, '_task_queue'), 'PetWidget 缺 _task_queue（缺陷 76 复发）'
    assert isinstance(p._task_queue, list) and p._task_queue == [], \
        '_task_queue 应初始化为空列表，实际 %r' % (p._task_queue,)


def test_enqueue_adds_to_queue():
    p = _pet()
    p._enqueue_task('排队任务 A')          # 原先这里抛 AttributeError
    assert len(p._task_queue) == 1, '入队后队列长度应为 1，实际 %d' % len(p._task_queue)
    assert p._task_queue[0]['text'] == '排队任务 A'


def test_next_task_advances_queue(monkeypatch):
    p = _pet()
    p._enqueue_task('任务 A')
    p._enqueue_task('任务 B')
    ran = []
    monkeypatch.setattr(p, '_run_task', lambda t, i=None: ran.append(t))
    p._next_task()
    assert ran == ['任务 A'], '应先来先到取出队首，实际 %r' % ran
    assert [t['text'] for t in p._task_queue] == ['任务 B']


def test_next_task_does_not_silently_fail_on_empty_queue():
    """空队列时 `_next_task` 必须能正常跑完（原先 AttributeError 被 _silent_log 吞掉 ✗）"""
    p = _pet()
    assert p._next_task() is None


def test_task_queue_init_lives_in_init_chain():
    """源码护栏：初始化必须写在初始化链路里（而不是只在拖拽重排时赋值）"""
    src = Path(os.path.join(BASE, 'desktop_pet.py')).read_text(encoding='utf-8')
    body = src.split('def _init_services_and_data(self):', 1)[1].split('\n    def ', 1)[0]
    assert 'self._task_queue = []' in body, \
        '_task_queue 未在初始化链路（_init_services_and_data）里赋初值 —— 缺陷 76 复发'
