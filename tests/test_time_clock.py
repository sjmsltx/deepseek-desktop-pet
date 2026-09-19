# -*- coding: utf-8 -*-
"""时间源护栏：峰谷计价必须用「北京时间」，不能受用户时区/本机时钟影响（v6.62）

两个要防的场景：
① 外国用户（系统时区不是 Asia/Shanghai）→ 本机时间不等于北京时间
② 用户改过系统时间 / 时钟漂移 → 连日期都可能错，还会把节假日表选错年份

对策：UTC+8 固定换算（中国无夏令时）+ 用官方 API 响应头 `Date` 校正本机时钟（零成本）。

运行：python -m pytest tests/test_time_clock.py -q
"""
import datetime
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import server_clock as sc          # noqa: E402
from api_stats import ApiStats     # noqa: E402

ApiStats.HOLIDAYS_CACHE = os.path.join(BASE, 'holidays_cache.json')


def _epoch(s):
    """'2026-09-18T02:00:00Z' → epoch"""
    return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(
        tzinfo=datetime.timezone.utc).timestamp()


def test_parse_http_date():
    ep = sc.parse_http_date('Fri, 18 Sep 2026 02:00:00 GMT')
    assert ep == _epoch('2026-09-18T02:00:00Z')
    assert sc.parse_http_date('garbage') is None
    assert sc.parse_http_date(None) is None


def test_beijing_now_is_timezone_independent():
    """UTC+0 的机器在 02:00 UTC（= 北京 10:00）→ 必须算成北京的 10 点"""
    ts = _epoch('2026-09-18T02:00:00Z')      # 周五 02:00 UTC
    bj = sc.beijing_now(local_epoch=ts, offset=0)
    assert bj.hour == 10 and bj.minute == 0
    assert ApiStats.is_peak_now(bj) is True, '北京时间 10 点 = 高峰'


def test_wrong_local_clock_is_corrected():
    """本机时钟被改到 2027（实际 2026）→ 用服务器时间校正后仍按 2026 判定"""
    real_utc = _epoch('2026-01-04T01:00:00Z')     # 北京时间 2026-01-04 09:00（周日·调休补班日）
    wrong_local = _epoch('2027-01-04T01:00:00Z')  # 本机时钟快了整一年
    # 官方响应头给的是真实时间 → 记下偏差
    off = sc.note_server_http_date('Sun, 04 Jan 2026 01:00:00 GMT', local_epoch=wrong_local)
    assert off is not None and abs(off + 365 * 86400) < 2 * 86400
    bj = sc.beijing_now(local_epoch=wrong_local, offset=off)
    assert bj.year == 2026 and bj.hour == 9
    assert ApiStats.is_peak_now(bj) is False, '2026-01-04 是周日（补班日）→ 仍按空闲'
    # 对照：不校正就会落到 2027（表里没有 → 保守按高峰，且年份也不对）
    bad = sc.beijing_now(local_epoch=wrong_local, offset=0)
    assert bad.year == 2027 and ApiStats.is_peak_now(bad) is True


def test_offset_sanity_guard():
    """偏差超过 5 年视为异常（代理伪造 Date）→ 忽略，不动已有校正值"""
    sc.reset()
    assert sc.note_server_http_date('Fri, 18 Sep 2026 02:00:00 GMT',
                                    local_epoch=_epoch('2026-09-18T02:00:10Z')) is not None
    before = sc.offset_seconds()
    assert sc.note_server_http_date('Fri, 18 Sep 2099 02:00:00 GMT',
                                    local_epoch=_epoch('2026-09-18T02:00:00Z')) is None
    assert sc.offset_seconds() == before
    sc.reset()


def test_api_stats_uses_beijing_clock(monkeypatch):
    """is_peak_now() 默认必须走 server_clock 的北京时间，而不是本机时间"""
    fixed = datetime.datetime(2026, 9, 18, 10, 0, tzinfo=sc.CN_TZ)   # 周五 10:00 北京
    monkeypatch.setattr(sc, 'beijing_now', lambda *a, **k: fixed)
    assert ApiStats.is_peak_now() is True
    src = open(os.path.join(BASE, 'api_stats.py'), encoding='utf-8').read()
    assert 'server_clock' in src and 'beijing_now' in src, '计价判定必须用北京时间的来源'


def test_peak_ranges_local_text_for_other_timezones():
    """异时区用户的文案换算（北京 9-12 / 14-18 对应到本机）

    北京 09:00 = UTC 01:00；对 UTC+0 用户就是 01:00–04:00、06:00–10:00
    """
    assert sc.peak_ranges_in_local_text(local_offset_hours=0) == '01:00–04:00、06:00–10:00'
    assert sc.peak_ranges_in_local_text(local_offset_hours=8) == '09:00–12:00、14:00–18:00'
    # UTC-5（美东冬令时）→ 北京 9-12 对应前一天 20-23
    assert sc.peak_ranges_in_local_text(local_offset_hours=-5) == '20:00–23:00、01:00–05:00'


def test_skew_text():
    sc.reset()
    assert sc.skew_text() == '', '没偏差就不该提示'
    sc.note_server_http_date('Fri, 18 Sep 2026 04:00:00 GMT',
                             local_epoch=_epoch('2026-09-18T02:00:00Z'))   # 本机慢 2 小时
    assert '慢' in sc.skew_text() and '2 小时' in sc.skew_text()
    sc.reset()
    sc.note_server_http_date('Fri, 18 Sep 2026 02:00:00 GMT',
                             local_epoch=_epoch('2026-09-18T02:30:00Z'))   # 本机快 30 分
    assert '快' in sc.skew_text() and '30 分钟' in sc.skew_text()
    sc.reset()


def test_no_dst_assumption_needed():
    """中国无夏令时 → 固定 UTC+8；且不依赖 Windows 缺失的 tzdata"""
    assert sc.CN_TZ.utcoffset(None) == datetime.timedelta(hours=8)
    src = open(os.path.join(BASE, 'server_clock.py'), encoding='utf-8').read()
    assert 'from zoneinfo' not in src and 'import zoneinfo' not in src, \
        '不要依赖 ZoneInfo（Windows 无 tzdata 会抛错）'


def test_note_response_tolerates_bad_header():
    class _R:
        headers = {}
    assert sc.note_response(_R()) is None          # 没有 Date 头也不能炸


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))
