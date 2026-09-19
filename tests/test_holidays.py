# -*- coding: utf-8 -*-
"""法定节假日与峰谷计价护栏（v6.62）

官方口径（中文定价页脚注）：
- 高峰 = 周一至周五 9:00–12:00、14:00–18:00，**不含中国法定节假日**
- 其余全部（周末 + 法定节假日全天）为空闲
- 判定只看「周末 / 节假日」，**不看是否调休补班** → 补班的周末仍按空闲

运行：python -m pytest tests/test_holidays.py -q
"""
import datetime
import json
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import cn_holidays as ch          # noqa: E402
from api_stats import ApiStats    # noqa: E402

ApiStats.HOLIDAYS_CACHE = os.path.join(BASE, 'holidays_cache.json')


def _peak(y, m, d, hh, mm=0):
    return ApiStats.is_peak_now(datetime.datetime(y, m, d, hh, mm))


def test_holidays_are_off_peak():
    """法定节假日全天空闲（含调休放假的工作日）"""
    assert _peak(2026, 10, 1, 10) is False, '国庆节（周四）应空闲'
    assert _peak(2026, 10, 1, 15) is False
    assert _peak(2026, 9, 25, 10) is False, '中秋节（周五）应空闲'
    assert _peak(2026, 2, 16, 10) is False, '春节（周一）应空闲'
    assert _peak(2026, 2, 23, 10) is False, '春节最后一天应空闲'


def test_normal_workdays_are_peak_in_hours():
    assert _peak(2026, 9, 18, 10) is True
    assert _peak(2026, 9, 18, 15, 30) is True
    assert _peak(2026, 2, 24, 10) is True, '春节后首个工作日恢复高峰'
    assert _peak(2026, 9, 18, 20) is False, '工作日晚上算空闲'
    assert _peak(2026, 9, 18, 12, 30) is False, '午休时段是空闲'


def test_swapped_weekend_still_off_peak():
    """调休补班的周末：官方只看星期几 → 仍按空闲（使用者从官方群确认）"""
    for y, m, d in ((2026, 1, 4), (2026, 2, 14), (2026, 2, 28),
                    (2026, 5, 9), (2026, 9, 20), (2026, 10, 10)):
        assert _peak(y, m, d, 10) is False, '%04d-%02d-%02d 补班日仍应空闲' % (y, m, d)


def test_weekend_always_off_peak():
    assert _peak(2026, 9, 19, 10) is False, '周六'
    assert _peak(2026, 9, 20, 15) is False, '周日（且是补班日）'


def test_unknown_year_is_conservative_peak():
    """表里没有的年份 → 保守按高峰（只多算不少算）"""
    assert ch.has_year(2027, ApiStats.HOLIDAYS_CACHE) is False
    assert _peak(2027, 1, 4, 10) is True


def test_builtin_table_shape():
    assert len(ch.off_days(2026)) == 33
    assert len(ch.off_days(2025)) == 28
    assert ch.is_holiday(datetime.date(2026, 10, 1)) is True
    assert ch.is_holiday(datetime.date(2026, 9, 19)) is False
    assert ch.holiday_name(datetime.date(2026, 10, 1)) == '国庆节'
    assert ch.holiday_name(datetime.date(2026, 9, 19)) == ''


def test_parse_remote_payload():
    payload = {'days': [{'name': '元旦', 'date': '2027-01-01', 'isOffDay': True},
                        {'name': '元旦', 'date': '2027-01-02', 'isOffDay': False}]}
    off, names = ch.parse_remote(payload, 2027)
    assert off == ['2027-01-01'] and names == {'2027-01-01': '元旦'}


def test_cache_roundtrip_extends_table(tmp_path):
    """缓存能补齐内置表没有的年份（自动/手动更新走这条）"""
    cache = tmp_path / 'holidays_cache.json'
    cache.write_text(json.dumps({'version': 1, 'off_days': {'2027': ['2027-01-01']},
                                 'names': {'2027-01-01': '元旦'}}, ensure_ascii=False), encoding='utf-8')
    ch._off_days = None      # 清掉运行时合并结果
    assert ch.has_year(2027, str(cache)) is True
    assert ch.is_holiday(datetime.date(2027, 1, 1), str(cache)) is True
    ch._off_days = None
    old = ApiStats.HOLIDAYS_CACHE
    try:
        ApiStats.HOLIDAYS_CACHE = str(cache)      # 让计价逻辑读这份缓存
        assert _peak(2027, 1, 1, 10) is False, '缓存里有 2027 → 元旦应判定为空闲'
    finally:
        ApiStats.HOLIDAYS_CACHE = old
        ch._off_days = None


def test_no_search_api_used():
    """护栏：节假日表只走公共静态 JSON，绝不碰搜索 API（省额度）"""
    src = open(os.path.join(BASE, 'cn_holidays.py'), encoding='utf-8').read()
    # 看实际调用/导入，不看注释里对搜索 API 的说明
    for bad in ('api.tavily.com', 'import tavily', 'search_api_key', 'tavily.com/search'):
        assert bad not in src, '节假日模块不得使用搜索 API（会消耗额度）：%s' % bad
    assert 'holiday-cn' in src, '应来自公共静态数据源'
    pet = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert 'ApiStats.HOLIDAYS_CACHE' in pet, '宿主必须把缓存路径注入计价逻辑'


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))
