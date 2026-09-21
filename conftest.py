# -*- coding: utf-8 -*-
"""pytest 收集配置。

regression_test.py 是**手动回归器脚本**（其 `def test(name, fn)` 需要外部传入 name），
不是 pytest 测试模块；被收集会报 "fixture 'name' not found"，
导致用例其实全绿、但全量退出码为 1（任何按退出码判成败的 CI 都会误判）。
这里显式不收集它。
"""
collect_ignore = ['regression_test.py']
