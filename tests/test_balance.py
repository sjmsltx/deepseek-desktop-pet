# -*- coding: utf-8 -*-
"""余额查询：接口解析 / 缓存 / 触发 / 低余额提醒（v6.61）

使用者诉求（2026-09-19）：「光检测扣费用处不大，能拿到余额数据更好」。
本组测试锁住：
- 官方 GET /user/balance 的解析（含失败路径：**绝不编数字**）
- 余额缓存落盘 / 过期判定（对话后按 10 分钟静默刷新）
- 手动查询走状态条、失败时说清原因
- 低余额提醒：低于阈值提醒一次，每天最多一次，阈值 0 = 关闭

运行：python -m pytest tests/test_balance.py -q
"""
import datetime
import json
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

OFFICIAL = {'is_available': True,
            'balance_infos': [{'currency': 'CNY', 'total_balance': '70.68',
                               'granted_balance': '0.00', 'topped_up_balance': '70.68'}]}


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status = 200

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(monkeypatch, payload=None, exc=None):
    import urllib.request

    def fake(req, timeout=None):
        if exc is not None:
            raise exc
        return _Resp(json.dumps(payload).encode('utf-8'))
    monkeypatch.setattr(urllib.request, 'urlopen', fake)
    return fake


def _pet(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    import desktop_pet as dp
    import api_stats as _as
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    # 换成临时统计文件，避免污染使用者真实 api_stats.json
    p.api_stats = _as.ApiStats(str(tmp_path / 'api_stats.json'),
                               registry=dp.MODEL_REGISTRY)
    p._balance_alerted = ''
    return p


# ---------- 1. 接口解析 ----------

def test_query_balance_parses_official(monkeypatch):
    import api_stats as _as
    _patch_urlopen(monkeypatch, OFFICIAL)
    info = _as.ApiStats.query_balance('sk-test-123', 'https://api.deepseek.com')
    assert info['ok'] is True
    assert abs(info['total'] - 70.68) < 1e-9
    assert abs(info['topped_up'] - 70.68) < 1e-9
    assert info['currency'] == 'CNY' and info['is_available'] is True
    assert info.get('at'), '应带查询时间戳'


def test_query_balance_v1_base_stripped(monkeypatch):
    """/v1 结尾的地址也能用（拼成 {base}/user/balance）"""
    import api_stats as _as
    seen = {}

    def fake(req, timeout=None):
        seen['url'] = req.full_url
        return _Resp(json.dumps(OFFICIAL).encode('utf-8'))
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', fake)
    _as.ApiStats.query_balance('sk-x', 'https://api.deepseek.com/v1')
    assert seen['url'] == 'https://api.deepseek.com/user/balance'


def test_query_balance_http_error_never_fabricates(monkeypatch):
    import api_stats as _as
    err = Exception('boom')
    err.code = 401
    _patch_urlopen(monkeypatch, exc=err)
    info = _as.ApiStats.query_balance('sk-bad', 'https://api.deepseek.com')
    assert info['ok'] is False
    assert '401' in info['error']
    assert 'total' not in info, '失败时不得给出任何金额'


def test_query_balance_non_official_host_hint(monkeypatch):
    """中转地址：失败时明确提示「非官方地址不支持余额」"""
    import api_stats as _as
    err = Exception('conn refused')
    _patch_urlopen(monkeypatch, exc=err)
    info = _as.ApiStats.query_balance('sk-x', 'https://my-relay.example.com')
    assert info['ok'] is False and '非官方' in info['error']


def test_query_balance_missing_infos(monkeypatch):
    import api_stats as _as
    _patch_urlopen(monkeypatch, {'is_available': True})
    info = _as.ApiStats.query_balance('sk-x')
    assert info['ok'] is False and 'balance_infos' in info['error']


def test_query_balance_no_key():
    import api_stats as _as
    info = _as.ApiStats.query_balance('')
    assert info['ok'] is False and 'Key' in info['error']


# ---------- 2. 缓存 ----------

def test_balance_cache_persists_and_text(tmp_path):
    import api_stats as _as
    path = str(tmp_path / 'api_stats.json')
    st = _as.ApiStats(path)
    assert st.balance_text() == '', '无缓存时文案必须为空（不编数字）'
    st.set_balance(dict(OFFICIAL, ok=True, total=70.68, granted=0.0, topped_up=70.68,
                        currency='CNY', at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    assert st.balance_text() == '¥70.68'
    assert '赠金 ¥0.00' in st.balance_text(True)
    st2 = _as.ApiStats(path)          # 重新加载：缓存应落盘
    assert st2.balance_text() == '¥70.68'


def test_failed_query_does_not_overwrite_cache(tmp_path):
    import api_stats as _as
    st = _as.ApiStats(str(tmp_path / 'api_stats.json'))
    st.set_balance({'ok': True, 'total': 70.68, 'granted': 0.0, 'topped_up': 70.68,
                    'currency': 'CNY', 'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    st.set_balance({'ok': False, 'error': 'HTTP 500'})
    assert st.balance_text() == '¥70.68', '失败不得清掉上一次成功缓存'


def test_balance_stale_semantics(tmp_path):
    import api_stats as _as
    st = _as.ApiStats(str(tmp_path / 'api_stats.json'))
    assert st.balance_stale(10) is True, '从未查过 → 视为过期'
    st.set_balance({'ok': True, 'total': 10.0, 'currency': 'CNY',
                    'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    assert st.balance_stale(10) is False
    old = (datetime.datetime.now() - datetime.timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    st.set_balance({'ok': True, 'total': 10.0, 'currency': 'CNY', 'at': old})
    assert st.balance_stale(10) is True, '超过 10 分钟应判过期（触发对话后刷新）'


# ---------- 3. 主线程回调 / 提醒 ----------

def test_manual_query_result_shows_status_bar(tmp_path, monkeypatch):
    p = _pet(tmp_path, monkeypatch)
    p._on_balance_result({'ok': True, 'total': 70.68, 'granted': 0.0, 'topped_up': 70.68,
                          'currency': 'CNY', 'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                          '_manual': True})
    assert '余额' in p.status_bar.text() and '70.68' in p.status_bar.text()
    assert p._balance_busy is False


def test_manual_query_failure_explains(tmp_path, monkeypatch):
    p = _pet(tmp_path, monkeypatch)
    p._on_balance_result({'ok': False, 'error': 'HTTP 401', '_manual': True})
    assert '余额查询失败' in p.status_bar.text() and '401' in p.status_bar.text()
    assert p.api_stats.balance_text() == '', '失败不得写入缓存'


def test_auto_query_is_silent(tmp_path, monkeypatch):
    """对话后自动刷新：成功也不弹状态条（只更新缓存）"""
    p = _pet(tmp_path, monkeypatch)
    p._notify('占位提示')
    p._on_balance_result({'ok': True, 'total': 12.5, 'currency': 'CNY',
                          'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                          '_manual': False})
    assert p.status_bar.text() == '占位提示', '自动刷新不应覆盖/弹出提示'
    assert p.api_stats.balance_text() == '¥12.50'


def test_low_balance_alert_once_per_day(tmp_path, monkeypatch):
    p = _pet(tmp_path, monkeypatch)
    p.balance_low_threshold = 5.0
    at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    p._on_balance_result({'ok': True, 'total': 3.2, 'granted': 0.0, 'topped_up': 3.2,
                          'currency': 'CNY', 'at': at, '_manual': False})
    first = p.status_bar.text()
    assert '余额偏低' in first and '3.20' in first
    p._notify('别的消息')
    p._on_balance_result({'ok': True, 'total': 3.2, 'granted': 0.0, 'topped_up': 3.2,
                          'currency': 'CNY', 'at': at, '_manual': False})
    assert p.status_bar.text() == '别的消息', '同一天不得重复提醒'


def test_low_balance_threshold_zero_disables(tmp_path, monkeypatch):
    p = _pet(tmp_path, monkeypatch)
    p._notify('占位')
    p.balance_low_threshold = 0
    at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    p._on_balance_result({'ok': True, 'total': 0.5, 'currency': 'CNY', 'at': at, '_manual': False})
    assert p.status_bar.text() == '占位', '阈值 0 = 关闭提醒'


def test_cost_notify_includes_balance_when_cached(tmp_path, monkeypatch):
    p = _pet(tmp_path, monkeypatch)
    p.api_stats.set_balance({'ok': True, 'total': 70.68, 'granted': 0.0, 'topped_up': 70.68,
                             'currency': 'CNY', 'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    p._on_cost_bubble(0.0032)
    txt = p.status_bar.text()
    assert '本次' in txt and '余额 ¥70.68' in txt, '费用提示应带上余额：%r' % txt


def test_set_balance_low_persists_and_clamps(tmp_path, monkeypatch):
    p = _pet(tmp_path, monkeypatch)
    saved = {}
    p._save_cfg_value = lambda k, v: (saved.__setitem__(k, v), True)[1]
    assert p.set_balance_low('8.5') is True
    assert abs(p.balance_low_threshold - 8.5) < 1e-9
    assert saved['balance_low_threshold'] == 8.5
    assert p.set_balance_low(-3) is True and p.balance_low_threshold == 0.0, '负数夹到 0'
    assert p.set_balance_low('abc') is False, '非数字应拒绝'


# ---------- 4. 源码护栏 ----------

def test_source_guard_balance_wired():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    for token in ('balance_signal', '_on_balance_result', '_query_balance_async',
                  '_maybe_low_balance_alert', 'BALANCE_LOW_DEFAULT', 'balance_stale',
                  "'balance_low_threshold'"):
        assert token in src, '余额功能未接线：%s' % token
    assert "umenu.addAction('💰 查询余额')" in src, '缺少右键菜单入口'
    st = open(os.path.join(BASE, 'api_stats.py'), encoding='utf-8').read()
    assert '/user/balance' in st and 'def query_balance' in st
    sui = open(os.path.join(BASE, 'settings_ui.py'), encoding='utf-8').read()
    assert 'sp_bal' in sui and '_apply_balance_low' in sui, '设置里应有低余额阈值入口'


def test_normalize_base_fixes_404():
    """v6.62 修 404：档案里存的是完整 endpoint，拼 /user/balance 前必须先归一

    旧实现 base + '/user/balance' 在 base='.../chat/completions' 时得到
    '.../chat/completions/user/balance' → HTTP 404（使用者实际碰到的）。
    """
    from api_stats import ApiStats
    cases = {
        'https://api.deepseek.com/chat/completions': 'https://api.deepseek.com',
        'https://api.deepseek.com/v1/chat/completions': 'https://api.deepseek.com',
        'https://api.deepseek.com/': 'https://api.deepseek.com',
        'https://api.deepseek.com': 'https://api.deepseek.com',
        'https://api.deepseek.com/beta': 'https://api.deepseek.com',
        'https://api.deepseek.com/v1': 'https://api.deepseek.com',
        '': 'https://api.deepseek.com',
        None: 'https://api.deepseek.com',
        # 中转网关：保留自定义前缀
        'https://gw.example.com/deepseek/v1': 'https://gw.example.com/deepseek',
    }
    for raw, want in cases.items():
        assert ApiStats.normalize_base(raw) == want, '归一错误：%r → %r' % (raw, want)


def test_source_guard_normalize_base_used():
    """护栏：query_balance 必须走 normalize_base（否则又会拼出 404 地址）"""
    st = open(os.path.join(BASE, 'api_stats.py'), encoding='utf-8').read()
    assert 'base = ApiStats.normalize_base(base_url)' in st
    assert "base + '/user/balance'" in st
