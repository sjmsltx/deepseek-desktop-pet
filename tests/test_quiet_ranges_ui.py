# -*- coding: utf-8 -*-
"""夜间静音「多时段」编辑区 —— 2026-10-30（Owner 要求可调、可多段）

三条最要紧的判据（都是实测踩出来的坑，不是想象）：
  1 界面**铺进去**的时段数必须等于配置里的段数
     —— 曾经因为把内部分钟格式又当外部字符串 parse 一遍，三段只剩一段
  2 界面改一下时间，**必须真的写进配置**
     —— 曾经因为 setter 用 parse 处理分钟格式，改完什么都不保存、还不报错
  3 坏值不许污染配置
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTime                      # noqa: E402
from PySide6.QtWidgets import QApplication            # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def host():
    """真 PetWidget，但把 _save_cfg_value 换成记录版（⛔ 不写真 config.json）"""
    import desktop_pet as dp
    p = dp.PetWidget()
    rec = {'saved': [], 'notes': []}
    p._save_cfg_value = lambda k, v: (rec['saved'].append((k, v)) or True)
    p._notify = lambda m: rec['notes'].append(m)
    p.voice_quiet_ranges = [(23 * 60, 8 * 60), (12 * 60, 13 * 60 + 30)]
    p._rec = rec
    yield p
    p.deleteLater()


@pytest.fixture()
def dlg(host):
    from settings_ui import SettingsDialog
    d = SettingsDialog(host)
    i = [k for k in range(d.nav.count()) if d.nav.item(k).text() == '语音'][0]
    d.nav.setCurrentRow(i)
    QApplication.processEvents()
    yield d
    d.deleteLater()


def test_editor_shows_all_configured_ranges(dlg):
    """配了几段就显示几行（这条曾经红过：三段只剩一段）"""
    rows = dlg._quiet_rows
    assert len(rows) == 2, '配置 2 段，界面显示 %d 行' % len(rows)
    assert rows[0][1].time().toString('HH:mm') == '23:00'
    assert rows[1][2].time().toString('HH:mm') == '13:30'


def test_checkbox_label_no_longer_hardcodes_times(dlg):
    """勾选框不再写死「23:00–08:00」（时段已经可配了）"""
    txt = dlg.ck_voice_night.text()
    assert '23:00' not in txt and '08:00' not in txt, txt


def test_changing_time_writes_config(dlg, host):
    """改一下时间必须真的落盘（这条曾经红过：改了什么都没保存）"""
    host._rec['saved'].clear()
    dlg._quiet_rows[0][1].setTime(QTime(22, 30))
    QApplication.processEvents()
    saved = host._rec['saved']
    assert saved, '改时间后没有任何保存调用'
    key, val = saved[-1]
    assert key == 'voice_quiet_ranges'
    assert val == [['12:00', '13:30'], ['22:30', '08:00']], val


def test_add_and_delete_rows(dlg, host):
    n0 = len(dlg._quiet_rows)
    dlg._add_quiet_row(9 * 60, 10 * 60)
    assert len(dlg._quiet_rows) == n0 + 1
    host._rec['saved'].clear()
    dlg._apply_quiet_rows()
    assert len(host._rec['saved'][-1][1]) == n0 + 1
    dlg._del_quiet_row(dlg._quiet_rows[-1][0])
    assert len(dlg._quiet_rows) == n0


def test_cannot_delete_last_row(dlg, host):
    """删到只剩一行就不许再删（全删光用户会看着空界面不知所措）"""
    while len(dlg._quiet_rows) > 1:
        dlg._del_quiet_row(dlg._quiet_rows[-1][0])
    host._rec['notes'].clear()
    dlg._del_quiet_row(dlg._quiet_rows[0][0])
    assert len(dlg._quiet_rows) == 1
    assert host._rec['notes'], '删最后一行时没有给任何提示'


def test_no_writeback_while_building(dlg, host):
    """构建/刷新期间不许回写（否则会把用户配置冲成界面默认值）"""
    dlg._building = True
    host._rec['saved'].clear()
    assert dlg._apply_quiet_rows() is None
    assert host._rec['saved'] == []
    dlg._building = False


def test_setter_rejects_bad_values(host):
    """坏值不许写进配置（点一下保存就把原时段清空 = 数据丢失）"""
    host._rec['saved'].clear()
    assert host._set_voice_quiet_ranges([['25:99', 'x'], 'oops']) is None
    assert host._rec['saved'] == []


def test_setter_accepts_internal_and_external(host):
    """内部分钟格式与外部字符串格式都要认"""
    got = host._set_voice_quiet_ranges([(1350, 480)])
    assert got == [(1350, 480)], got
    got2 = host._set_voice_quiet_ranges([['23:00', '07:00']])
    assert got2 == [(1380, 420)], got2


def test_setter_pushes_to_voice_engine(host):
    """setter 必须把新时段推给 VoiceIO，否则要重启才生效"""
    v = getattr(host, 'voice', None)
    if v is None:
        pytest.skip('本环境没有 VoiceIO 实例')
    host._set_voice_quiet_ranges([['13:00', '14:00']])
    assert v.quiet_ranges == [(780, 840)], v.quiet_ranges
