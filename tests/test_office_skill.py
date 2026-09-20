# -*- coding: utf-8 -*-
"""办公文档技能护栏（v6.66）

背景：使用者质疑"日常任务（WPS 表格/文档）行不行"。实测原先 29 个工具全是通用类，
没有任何能生成带格式表格的工具 —— 本模块补上，并锁住：
1. 数据归一（JSON 字符串 / 扁平数组 / 换行文本 / 日期 / 整数浮点）
2. 真机端到端：生成带样式报表 → 读回一致 → 导出 PDF（没有办公软件时给出可读错误）
3. 工具接线：在 core 工具集里、schema 合法、handler 映射正确、未知 action 有提示
4. 路径安全：AI 给的路径一律收敛到 输出/ 下（防穿越）

运行：python -m pytest tests/test_office_skill.py -q
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import office_skill as off      # noqa: E402


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------- 数据归一

def test_norm_rows_variants():
    assert off._norm_rows('[["a",1],["b",2]]') == [['a', 1], ['b', 2]]
    assert off._norm_rows('["项目","数值","说明"]') == [['项目', '数值', '说明']], '扁平数组=一行'
    assert off._norm_rows(['x', 'y']) == [['x', 'y']]
    assert off._norm_rows('a,b\nc,d') == [['a,b'], ['c,d']]
    assert off._norm_rows(None) == [] and off._norm_rows('') == []
    assert off._norm_rows([[None, 1], 2]) == [['', 1], [2]]


def test_norm_cell_dates_and_floats():
    import datetime
    assert off._norm_cell(datetime.datetime(2026, 9, 19)) == '2026-09-19'
    assert off._norm_cell(32.0) == 32 and off._norm_cell(0.4182) == 0.4182
    assert off._norm_cell(None) == '' and off._norm_cell('文本') == '文本'


def test_split_cell():
    assert off._split_cell('A1') == (1, 1)
    assert off._split_cell('C3') == (3, 3)
    assert off._split_cell('AA2') == (2, 27)
    assert off._split_cell('') == (1, 1)


# ---------------------------------------------------------------- 真机端到端

def _has_office():
    info, err = off.office_info()
    return bool(info), info, err


def test_office_info_returns_dict():
    info, err = off.office_info(refresh=True)
    assert isinstance(info, dict)
    if info:
        assert any(v.get('prog_id') for v in info.values())


def _run_in_child(impl_name):
    """把真正打 COM 的用例放进**子进程**跑（v6.70）。

    COM 在 RPC 服务器异常时抛 Windows 致命异常（0x800706be），Python 的 try/except
    **抓不住** —— 在主进程里会把整个 pytest 进程打崩（2026-09-20 实测）。
    隔离后：崩也只崩子进程，主进程能如实报“这一条失败”。
    """
    import subprocess
    child = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_office_child.py')
    r = subprocess.run([sys.executable, child, impl_name], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=300,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    out = (r.stdout or '')[-600:] + (r.stderr or '')[-600:]
    assert 'CHILD_OK' in (r.stdout or ''), f'子进程 {impl_name} 未成功（rc={r.returncode}）：{out}'


def test_report_roundtrip():
    """真机：生成带样式报表 → 读回校验（子进程隔离执行）"""
    _run_in_child('_impl_report_roundtrip')


def _impl_report_roundtrip():
    import tempfile
    tmp = tempfile.mkdtemp(prefix='pet_office_')
    ok, info, err = _has_office()
    if not ok:
        rows, rerr = off.sheet_read(os.path.join(tmp, 'x.xlsx'))
        assert rerr, '没有办公软件时要给出可读错误'
        return
    xlsx = os.path.join(tmp, '报表.xlsx')
    msg, good = off.make_report(xlsx, '单元测试报表', '["项目","数值"]',
                                '[["甲",1],["乙",2.5]]', footer='测试页脚')
    assert good and os.path.exists(xlsx), msg
    rows, rerr = off.sheet_read(xlsx)
    assert not rerr and rows, rerr
    assert rows[0][0] == '单元测试报表', '标题应在首行'
    assert rows[1][:2] == ['项目', '数值'], '表头应分行写入（曾因扁平数组归一错误挤成一格）'
    assert rows[2][:2] == ['甲', 1] and rows[3][:2] == ['乙', 2.5]
    assert any('测试页脚' in str(c) for r in rows for c in r), '页脚应写入'


def test_sheet_write_then_read():
    """真机：写表 → 读回（子进程隔离执行）"""
    _run_in_child('_impl_sheet_write_then_read')


def _impl_sheet_write_then_read():
    import tempfile
    tmp = tempfile.mkdtemp(prefix='pet_office_')
    ok, info, err = _has_office()
    if not ok:
        return
    xlsx = os.path.join(tmp, 'data.xlsx')
    msg, good = off.sheet_write(xlsx, '[["姓名","分数"],["小李",95]]', sheet='成绩')
    assert good and os.path.exists(xlsx), msg
    rows, rerr = off.sheet_read(xlsx, sheet='成绩')
    assert not rerr and rows[0][:2] == ['姓名', '分数'] and rows[1][:2] == ['小李', 95]


def test_export_pdf():
    """真机：导出 PDF（子进程隔离执行）"""
    _run_in_child('_impl_export_pdf')


def _impl_export_pdf():
    import tempfile
    tmp = tempfile.mkdtemp(prefix='pet_office_')
    ok, info, err = _has_office()
    if not ok:
        return
    xlsx = os.path.join(tmp, 'p.xlsx')
    off.make_report(xlsx, 'PDF 测试', '["列"]', '[["值"]]')
    pdf = os.path.join(tmp, 'p.pdf')
    msg, good = off.export_pdf(xlsx, pdf)
    if good:
        assert os.path.exists(pdf) and os.path.getsize(pdf) > 1024
    else:
        assert '不支持' in msg or '失败' in msg, '失败要说清原因与替代方案'


def test_missing_file_error():
    rows, err = off.sheet_read('不存在的文件.xlsx')
    assert rows == [] and '不存在' in err


# ---------------------------------------------------------------- 工具接线

def test_tool_registered_in_core_with_schema():
    import tools_registry as tr
    names = [t['function']['name'] for t in tr.AI_TOOLS]
    assert 'office_doc' in names and 'office_doc' in tr.CORE_TOOLS, '日常任务工具默认就该可用'
    tool = [t for t in tr.AI_TOOLS if t['function']['name'] == 'office_doc'][0]
    props = tool['function']['parameters']['properties']
    assert set(tool['function']['parameters']['required']) == {'action'}
    assert set(props['action']['enum']) == {'info', 'write_sheet', 'read_sheet', 'make_report',
                                            'export_pdf', 'write_doc', 'write_slides'}


def test_tool_handler_wiring_and_errors():
    _app()
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    assert p._TOOL_HANDLERS.get('office_doc') == '_tool_office_doc'
    out = p._execute_tool('office_doc', {'action': '乱写'})
    assert '未知 action' in out and 'info' in out
    out2 = p._execute_tool('office_doc', {'action': 'make_report'})
    assert '需要 path' in out2
    out3 = p._execute_tool('office_doc', {'action': 'info'})
    assert '办公接口' in out3 or '没有可用' in out3


def test_path_is_confined_to_output_dir():
    _app()
    import desktop_pet as dp
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    for raw in ('../../Windows/evil.xlsx', 'C:\\Windows\\System32\\x.xlsx', '报告'):
        got = p._office_resolve(raw)
        assert os.path.dirname(os.path.abspath(got)) == os.path.abspath(p.OFFICE_OUT_DIR), got
    assert p._office_resolve('a.txt').endswith('.xlsx'), '扩展名不对时补默认扩展名'


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))
