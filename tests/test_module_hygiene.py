# -*- coding: utf-8 -*-
"""v6.55 新增：模块卫生护栏（防宿主类再膨胀）

背景：PetWidget.__init__ 曾长到 312 行（一个方法里塞了状态、配置、信号、服务、
数据加载、UI 构树、收尾七件事）。本版等价拆为 5 个初始化方法，__init__ 只剩 7 行。
本测试锁住这个结果，防止后续改动又把东西堆回 __init__。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _main_src():
    return open(os.path.join(ROOT, 'desktop_pet.py'), encoding='utf-8-sig').read().split('\n')


def test_init_is_thin():
    lines = _main_src()
    start = None
    cls = None
    for i, l in enumerate(lines):
        m = re.match(r"^class (\w+)", l)
        if m:
            cls = m.group(1)
        if cls == 'PetWidget' and re.match(r"^    def __init__\(self", l):
            start = i
            break
    assert start is not None, '找不到 PetWidget.__init__'
    end = next(j for j in range(start + 1, len(lines)) if re.match(r"^    def ", lines[j]))
    body = [l for l in lines[start + 1:end] if l.strip()]
    assert len(body) <= 20, 'PetWidget.__init__ 又膨胀到 %d 行（应 ≤20）' % len(body)


def test_split_methods_exist():
    lines = _main_src()
    src = "\n".join(lines)
    for name in ('_init_state_and_config', '_init_signals_and_hotkeys',
                 '_init_services_and_data', '_init_ui_tree', '_init_finish'):
        assert re.search(r"def %s\(self\):" % name, src), '缺少初始化方法 %s' % name
        assert 'self.%s()' % name in src, '初始化方法 %s 未被调用' % name
    # 调用顺序必须保持（构造依赖顺序敏感）
    order = [src.index('self.%s()' % n) for n in
             ('_init_state_and_config', '_init_signals_and_hotkeys', '_init_services_and_data',
              '_init_ui_tree', '_init_finish')]
    assert order == sorted(order), '初始化方法调用顺序被改动'


def test_ui_construction_not_inlined_in_init():
    """UI 构树必须留在 _init_ui_tree 里（防止再次内联回 __init__）"""
    lines = _main_src()
    start = next(i for i, l in enumerate(lines) if l.strip() == 'def _init_ui_tree(self):')
    end = next(j for j in range(start + 1, len(lines)) if re.match(r"^    def ", lines[j]))
    block = "\n".join(lines[start:end])
    assert 'QtWidgets' in block or 'QLabel' in block or 'QVBoxLayout' in block, 'UI 构树不在 _init_ui_tree'
    assert len(lines[start:end]) >= 80, '_init_ui_tree 过短，疑似 UI 被搬走'


if __name__ == '__main__':
    test_init_is_thin()
    test_split_methods_exist()
    test_ui_construction_not_inlined_in_init()
    print('✅ 模块卫生 3 项断言通过')
