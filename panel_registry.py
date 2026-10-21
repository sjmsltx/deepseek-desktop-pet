# -*- coding: utf-8 -*-
"""面板注册表（3.0 大界面 · 批 2）

目的
----
让宿主**不认识任何具体面板**。宿主只做三件事：遍历注册表、建按钮、把控件装进内容区。
加一个新面板 = 在别处调一次 `register_panel(...)`，`desktop_pet.py` 一行都不用改。

这是验收判据 3 的落点：搬第 3 个面板时，diff 里不得出现主窗口文件改动。

面板契约（判据 4）
------------------
面板类必须：
  1. 构造签名 `(host_data, save_cb, labels=None, parent=None)` 或能被 factory 适配
  2. **不 import desktop_pet**，只吃注入的接口
  3. 提供 `refresh()`（可选）—— 有就调，没有就跳过

⛔ 本模块不 import desktop_pet / todo_panel / side_panel 中任何一个：
   它必须能在不启动主程序的情况下被导入，否则「可独立验收」就是空话。
"""

#: 面板规格：key 唯一；title 显示名；factory(host) → QWidget；order 决定按钮顺序
_PANELS = []


class PanelSpec:
    """一条注册记录。用普通类而不是 NamedTuple，是为了以后加字段不破坏已有调用。"""

    __slots__ = ('key', 'title', 'factory', 'order', 'hint')

    def __init__(self, key, title, factory, order=100, hint=''):
        self.key = str(key)
        self.title = str(title)
        self.factory = factory
        self.order = int(order)
        self.hint = str(hint)

    def __repr__(self):
        return 'PanelSpec(key=%r, title=%r, order=%d)' % (self.key, self.title, self.order)


def register_panel(key, title, factory, order=100, hint='', replace=False):
    """注册一个面板。返回 PanelSpec。

    replace=False 时 key 重复会抛 ValueError —— 宁可启动就报错，
    也不要出现「两个面板抢同一个按钮、后注册的静默覆盖」。
    """
    if not callable(factory):
        raise TypeError('factory 必须可调用：key=%r' % key)
    k = str(key or '').strip()
    if not k:
        raise ValueError('面板 key 不能为空')
    for i, spec in enumerate(_PANELS):
        if spec.key == k:
            if not replace:
                raise ValueError('面板 key 重复：%r（要覆盖请传 replace=True）' % k)
            _PANELS[i] = PanelSpec(k, title, factory, order, hint)
            return _PANELS[i]
    spec = PanelSpec(k, title, factory, order, hint)
    _PANELS.append(spec)
    return spec


def unregister_panel(key):
    """移除一个面板（测试与热插拔用）。返回是否真的移除了。"""
    k = str(key or '')
    for i, spec in enumerate(_PANELS):
        if spec.key == k:
            del _PANELS[i]
            return True
    return False


def clear_panels():
    """清空（测试用）。"""
    del _PANELS[:]


def panels():
    """按 order 升序返回全部注册面板（副本，外部改不到内部）。"""
    return sorted(list(_PANELS), key=lambda s: (s.order, s.key))


def panel_keys():
    return [s.key for s in panels()]


def count():
    return len(_PANELS)


def build(key, host):
    """按 key 建一个面板控件。找不到返回 None（不抛，让宿主少一个面板也能跑）。"""
    for spec in _PANELS:
        if spec.key == str(key):
            return spec.factory(host)
    return None
