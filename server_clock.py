# -*- coding: utf-8 -*-
"""server_clock.py — 与用户机器「时区/时钟设置」无关的北京时间（v6.62）
=============================================================

为什么需要它
------------
峰谷计价按**北京时间**判定（高峰 = 周一至周五 9:00–12:00、14:00–18:00，不含法定节假日），
但原先实现直接用 `datetime.datetime.now()`，有两个坑：

1. **时区**：外国用户（或把系统时区设成非 Asia/Shanghai 的人）拿到的是当地时间 → 判错。
2. **时钟**：用户手动改过系统时间 / 长期漂移 → 不只小时错，连**日期**都可能错，
   会连带把节假日表选错年份（比如本机显示 2027 年，但实际是 2026 年）。

本模块的两条对策
----------------
- **换算**：一律走 UTC + 固定 +08:00 → 北京时间。中国不实行夏令时，固定偏移完全等价，
  且不依赖 Windows 缺失的 tzdata（`ZoneInfo('Asia/Shanghai')` 在 Windows 上会报错）。
- **校正**：用官方 API 响应头 `Date`（标准 RFC 1123、GMT）反推本机时钟偏差。
  这是**零成本**的 —— 每次调用 API 都顺带校正一次，不额外发请求、不消耗任何额度。
  没有校正数据时退回本机 UTC（仍是时区无关的）。

不依赖 PySide6，纯函数 + 一份内存状态，便于单测。
"""
import datetime
import email.utils
import threading

from pet_log import get_logger

_log = get_logger('server_clock')

# 中国标准时间：UTC+8，无夏令时 → 固定偏移即可
CN_TZ = datetime.timezone(datetime.timedelta(hours=8))

# 官方高峰时段（北京时间），与 api_stats.PEAK_HOURS 保持一致
PEAK_HOURS = ((9, 12), (14, 18))

MAX_SANE_SKEW = 5 * 365 * 86400      # 偏差超过 5 年视为异常（代理伪造 Date / 解析错），忽略

_lock = threading.Lock()
_state = {'offset': 0.0, 'known': False, 'at': None}


def parse_http_date(value):
    """RFC 1123 日期串（如 'Sat, 19 Sep 2026 12:34:56 GMT'）→ epoch 秒；失败返回 None"""
    try:
        dt = email.utils.parsedate_to_datetime(str(value or ''))
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def note_server_http_date(value, local_epoch=None):
    """记一次服务器时间（来自官方响应头 Date），据此更新本机时钟偏差。返回偏差秒数或 None"""
    ep = parse_http_date(value)
    if ep is None:
        return None
    base = local_epoch if local_epoch is not None else datetime.datetime.now().timestamp()
    off = ep - base
    if abs(off) > MAX_SANE_SKEW:
        _log.debug('忽略异常的服务器时间偏差：%.0f 秒', off)
        return None
    with _lock:
        _state['offset'] = off
        _state['known'] = True
        _state['at'] = base
    return off


def note_response(resp):
    """从 urllib 响应对象抓 Date 头（网络层每次成功请求都调一下）"""
    try:
        return note_server_http_date(resp.headers.get('Date'))
    except Exception:
        return None


def offset_seconds():
    """本机时钟与官方服务器的时间差（服务器 - 本机），单位秒"""
    with _lock:
        return float(_state['offset'] or 0.0)


def has_server_time():
    """是否已经拿到过服务器时间（用于界面提示“已自动校正”）"""
    with _lock:
        return bool(_state['known'])


def now_utc(local_epoch=None, offset=None):
    """当前 UTC（已用服务器时间校正，与用户时区无关）"""
    base = local_epoch if local_epoch is not None else datetime.datetime.now().timestamp()
    off = offset if offset is not None else offset_seconds()
    return datetime.datetime.fromtimestamp(base + off, datetime.timezone.utc)


def beijing_now(local_epoch=None, offset=None):
    """当前北京时间（与用户时区/时钟设置无关）"""
    return now_utc(local_epoch, offset).astimezone(CN_TZ)


def local_now():
    """本机本地时间（仅供展示/记录，计价判定不要用它）"""
    return datetime.datetime.now()


def skew_seconds(local_epoch=None):
    """本机时钟偏差（正数 = 本机慢）"""
    return offset_seconds()


def skew_text(local_epoch=None):
    """偏差文案（给界面用）：偏差在 60 秒内视为正常，返回 ''"""
    try:
        off = offset_seconds()
    except Exception:
        return ''
    if abs(off) < 60:
        return ''
    n = abs(int(off))
    if n >= 86400:
        amt = '%d 天' % (n // 86400)
    elif n >= 3600:
        amt = '%d 小时' % (n // 3600)
    else:
        amt = '%d 分钟' % (n // 60)
    return '本机时钟比官方服务器%s %s（已自动校正）' % ('慢' if off > 0 else '快', amt)


def is_peak_hour_beijing(dt):
    """给定北京时间，是否落在高峰小时区间（不含节假日/周末判定 —— 那是 cn_holidays 的事）"""
    try:
        h = dt.hour + dt.minute / 60.0
        return any(a <= h < b for a, b in PEAK_HOURS)
    except Exception:
        return False


def peak_ranges_in_local_text(local_epoch=None, local_offset_hours=None):
    """高峰时段换算成本地时间的文案（给外国人/异时区用户看）

    例：本机 UTC+0 → "03:00–06:00、08:00–12:00"；本机 UTC+8 → 与北京一致
    local_offset_hours：测试用，显式指定本机时区偏移（不传则用系统时区）
    """
    try:
        base = local_epoch if local_epoch is not None else datetime.datetime.now().timestamp()
        if local_offset_hours is None:
            local_offset = datetime.datetime.fromtimestamp(base).astimezone().utcoffset()
            delta_h = (local_offset or datetime.timedelta(0)).total_seconds() / 3600.0 - 8.0
        else:
            delta_h = float(local_offset_hours) - 8.0
        parts = []
        for a, b in PEAK_HOURS:
            sa = (a + delta_h) % 24
            sb = (b + delta_h) % 24
            parts.append('%02d:%02d–%02d:%02d' % (int(sa), int(round((sa % 1) * 60)),
                                                  int(sb), int(round((sb % 1) * 60))))
        return '、'.join(parts)
    except Exception:
        return ''


def beijing_now_text():
    """'YYYY-MM-DD HH:MM（北京时间）'，给悬浮窗/状态条用"""
    try:
        return beijing_now().strftime('%Y-%m-%d %H:%M') + '（北京时间）'
    except Exception:
        return ''


def reset():
    """测试用：清空已记录的偏差"""
    with _lock:
        _state['offset'] = 0.0
        _state['known'] = False
        _state['at'] = None
