# -*- coding: utf-8 -*-
"""cn_holidays.py — 中国法定节假日表（峰谷计价判定用，v6.62）
=============================================================

为什么需要它
------------
官方峰谷计价的规则（api-docs.deepseek.com/zh-cn/quick_start/pricing 脚注）是：

- **高峰**：北京时间**周一至周五** 9:00–12:00、14:00–18:00，**不含中国法定节假日**
- **空闲**：其余全部时段 —— 含**周末**、**法定节假日**全天
- 空闲价 = 高峰价的一半

关键推论（常被搞错）：判定只看「是不是周末 / 是不是法定节假日」，**不看**“这天是不是调休补班”。
所以调休补班的周一至周五算高峰、调休补班的**周末仍算空闲**（使用者从官方群确认过这一点，
与官方定价页口径一致）。因此我们只需要「**放假日**日期表」，**不需要**补班日期表。

数据来源与成本
--------------
- 内置表：下方 `BUILT_OFF_DAYS`（按国务院办公厅年度节假日安排整理，经 holiday-cn 校对）
- 自动更新：`update_from_remote()` 拉 `NateScarlet/holiday-cn` 的静态 JSON
  （**静态文件、无 API key、无调用额度**，单年 < 2KB）；一年最多拉一次，失败静默
- **不使用**搜索 API（Tavily 每次调用都吃额度，且返回非结构化结果，查这个纯属浪费）

本模块不依赖 PySide6，纯函数 + 一份缓存文件，便于单测。
"""
import datetime
import json
import os

from pet_log import get_logger

_log = get_logger('cn_holidays')

REMOTE_URL = 'https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/%d.json'
CACHE_NAME = 'holidays_cache.json'
CACHE_VERSION = 1

# ---- 内置放假日（国务院办公厅年度安排；holiday-cn 校对，2026-09-19 更新）----
BUILT_OFF_DAYS = {
    2025: ['2025-01-01',
           '2025-01-28', '2025-01-29', '2025-01-30', '2025-01-31', '2025-02-01',
           '2025-02-02', '2025-02-03', '2025-02-04',
           '2025-04-04', '2025-04-05', '2025-04-06',
           '2025-05-01', '2025-05-02', '2025-05-03', '2025-05-04', '2025-05-05',
           '2025-05-31', '2025-06-01', '2025-06-02',
           '2025-10-01', '2025-10-02', '2025-10-03', '2025-10-04', '2025-10-05',
           '2025-10-06', '2025-10-07', '2025-10-08'],
    2026: ['2026-01-01', '2026-01-02', '2026-01-03',
           '2026-02-15', '2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19',
           '2026-02-20', '2026-02-21', '2026-02-22', '2026-02-23',
           '2026-04-04', '2026-04-05', '2026-04-06',
           '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04', '2026-05-05',
           '2026-06-19', '2026-06-20', '2026-06-21',
           '2026-09-25', '2026-09-26', '2026-09-27',
           '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05',
           '2026-10-06', '2026-10-07'],
}

# 节日名（给提示文案用；日期 → 名称）
BUILT_NAMES = {
    '2025-01-01': '元旦', '2025-01-28': '春节', '2025-04-04': '清明节',
    '2025-05-01': '劳动节', '2025-05-31': '端午节', '2025-10-01': '国庆节·中秋节',
    '2026-01-01': '元旦', '2026-02-15': '春节', '2026-04-04': '清明节',
    '2026-05-01': '劳动节', '2026-06-19': '端午节', '2026-09-25': '中秋节',
    '2026-10-01': '国庆节',
}

_off_days = None      # 运行时合并表（内置 + 缓存）
_names = None


def _merge_from_cache(cache_path):
    """把本地缓存的年度表并进内置表（缓存里的年份优先，方便自动更新后生效）"""
    global _off_days, _names
    if _off_days is None:
        _off_days = {y: set(v) for y, v in BUILT_OFF_DAYS.items()}
        _names = dict(BUILT_NAMES)
    try:
        if cache_path and os.path.exists(cache_path):
            with open(cache_path, encoding='utf-8') as f:
                data = json.load(f)
            for y, days in (data.get('off_days') or {}).items():
                _off_days[int(y)] = set(days)
            for d, n in (data.get('names') or {}).items():
                _names[d] = n
    except Exception as e:
        _log.debug('节假日缓存读取失败（用内置表）：%s', e)
    return _off_days


def off_days(year, cache_path=None):
    """某年的放假日集合（ISO 字符串）"""
    _merge_from_cache(cache_path)
    return set(_off_days.get(int(year)) or ())


def has_year(year, cache_path=None):
    """内置/缓存里有没有这一年的数据（没有就该更新了）"""
    return bool(off_days(year, cache_path))


def is_holiday(date_obj, cache_path=None):
    """是否法定放假日（含调休放假的工作日；不含调休补班的周末）"""
    try:
        d = date_obj.strftime('%Y-%m-%d') if hasattr(date_obj, 'strftime') else str(date_obj)
        _merge_from_cache(cache_path)
        return d in (_off_days.get(int(d[:4])) or set())
    except Exception:
        return False


def holiday_name(date_obj, cache_path=None):
    """这一天的节日名（不是节假日则返回 ''）"""
    try:
        d = date_obj.strftime('%Y-%m-%d') if hasattr(date_obj, 'strftime') else str(date_obj)
        if not is_holiday(d, cache_path):
            return ''
        _merge_from_cache(cache_path)
        nm = _names.get(d, '')
        if nm:
            return nm
        # 表里没有名称时，按同名的相邻日期兜底（同一节日的连续几天）
        for k, v in _names.items():
            if k[:7] == d[:7] and v:
                return v
        return '法定节假日'
    except Exception:
        return ''


def parse_remote(payload, year):
    """解析 holiday-cn 的年度 JSON → (放假日列表, 日期→节日名)"""
    days = (payload or {}).get('days') or []
    off, names = [], {}
    for x in days:
        if not x.get('isOffDay'):
            continue
        d = str(x.get('date') or '')
        if not d:
            continue
        off.append(d)
        if x.get('name'):
            names[d] = str(x['name'])
    return sorted(off), names


def fetch_year(year, timeout=20):
    """拉取某年的公共节假日 JSON（静态文件，无 key 无额度）。返回 (放假日, 名称, 错误)"""
    import urllib.request
    try:
        req = urllib.request.Request(REMOTE_URL % int(year),
                                     headers={'User-Agent': 'desktop-pet-holidays/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode('utf-8'))
        off, names = parse_remote(payload, year)
        if not off:
            return [], {}, '当年安排尚未发布'
        return off, names, None
    except Exception as e:
        return [], {}, '%s: %s' % (type(e).__name__, str(e)[:120])


def update_from_remote(years, cache_path, timeout=20, merge=True):
    """更新若干年份并写入缓存。返回 (更新成功的年份列表, 错误列表)

    - 静态 JSON、无 key、无额度消耗；一年拉一次即可
    - 失败不抛异常、不动已有数据（宁可沿用内置表）
    """
    ok, errs = [], []
    data = {'version': CACHE_VERSION, 'off_days': {}, 'names': {}}
    if merge and cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding='utf-8') as f:
                old = json.load(f)
            data['off_days'] = dict(old.get('off_days') or {})
            data['names'] = dict(old.get('names') or {})
        except Exception:
            pass
    for y in years:
        off, names, err = fetch_year(y, timeout=timeout)
        if err:
            errs.append('%s：%s' % (y, err))
            continue
        data['off_days'][str(int(y))] = off
        data['names'].update(names)
        ok.append(int(y))
    if ok:
        try:
            tmp = cache_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, cache_path)
        except Exception as e:
            errs.append('缓存写入失败：%s' % e)
        global _off_days
        _off_days = None        # 下次访问重新合并
    return ok, errs
