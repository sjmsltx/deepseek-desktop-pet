# -*- coding: utf-8 -*-
"""governance.py — 治理三件：审计日志 / 出网白名单 / 额度限制（v6.69）
==============================================================================
为什么做这个（使用者的原话）：把"敢用"变成"敢放心用"。

三件事都在同一个模块里，因为它们共享一个事实来源 —— **审计日志**：

  ① 审计日志（audit）：每次技能/MCP 调用、安装、授权、拒绝都落一条 JSONL。
     文件：logs/audit_YYYY-MM-DD.jsonl（每天一个，默认留 30 天）
  ② 额度限制（quota）：**直接数当天日志**里的调用次数来判断，不另存计数器状态 ——
     好处是"日志里能看到的，就是限额算过的"，不会出现两套数据对不上的情况。
  ③ 出网白名单（net_allowlist）：技能包要联网必须走 pet_net 的受限入口
     （http_get / http_post_json / download），入口先查白名单；白名单是**域名模式**列表，
     例如 ["api.deepseek.com", "*.github.com"]。空列表 = 技能一律不许出网（默认最安全）。

设计取舍（诚实记录）：
  - 技能包代码与桌宠同进程，**无法在系统层面拦住**它自己 import urllib。
    所以采取"声明式约束"：v2 技能包若直接用 urllib/requests/socket，**安装时就拒绝**，
    要求改走 pet_net 入口；随程序自带的 builtin 包（我们自己发的）例外并在文档里写明。
  - 限额是"防跑飞"，不是精确计费器：按天/按分钟计数，超了直接拒绝并写审计。
"""
import datetime
import fnmatch
import json
import os
import threading
import time
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

KEEP_DAYS = 30
DEFAULT_LIMITS = {'per_minute': 20, 'per_day': 300}   # 单个技能/MCP server 的默认额度
_lock = threading.RLock()
_cache = {'mtime': None, 'day': None, 'counts': {}}


# ------------------------------------------------------------------ 配置

def _cfg():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cfg_value(key, value):
    """只改一个键（不整文件覆盖），原子写"""
    with _lock:
        cfg = _cfg()
        cfg[key] = value
        tmp = CONFIG_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)


def audit_enabled():
    return bool(_cfg().get('audit_log', True))


def limits_enabled():
    return bool(_cfg().get('tool_limits_enabled', True))


def limit_for(actor):
    """取某个 actor 的额度：config.tool_limits[actor] > config.tool_limits['*'] > 默认"""
    cfg = _cfg()
    table = cfg.get('tool_limits') or {}
    merged = dict(DEFAULT_LIMITS)
    for key in ('*', actor):
        item = table.get(key)
        if isinstance(item, dict):
            for k in ('per_minute', 'per_day'):
                if isinstance(item.get(k), (int, float)) and item[k] > 0:
                    merged[k] = int(item[k])
    return merged


def set_limit(actor, per_minute=None, per_day=None):
    cfg = _cfg()
    table = dict(cfg.get('tool_limits') or {})
    item = dict(table.get(actor) or {})
    if per_minute:
        item['per_minute'] = int(per_minute)
    if per_day:
        item['per_day'] = int(per_day)
    table[actor] = item
    _save_cfg_value('tool_limits', table)
    return item


# ------------------------------------------------------------------ 审计日志

def audit_path(day=None):
    day = day or time.strftime('%Y-%m-%d')
    return os.path.join(LOG_DIR, 'audit_%s.jsonl' % day)


def log_event(kind, actor, action, detail='', allowed=True, extra=None, ms=None):
    """写一条审计（kind: call/deny/install/uninstall/enable/grant/connect/error）

    参数摘要与结果摘要只存**截断后的文本**，避免日志被大内容撑爆。
    """
    if not audit_enabled():
        return None
    entry = {
        'ts': datetime.datetime.now().isoformat(timespec='seconds'),
        'kind': str(kind)[:24],
        'actor': str(actor)[:80],
        'action': str(action)[:80],
        'allowed': bool(allowed),
        'detail': str(detail or '')[:400],
    }
    if ms is not None:
        entry['ms'] = int(ms)
    if extra:
        entry['extra'] = {str(k)[:30]: str(v)[:200] for k, v in dict(extra).items()}
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with _lock:
            with open(audit_path(), 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        _cache['mtime'] = None            # 让计数缓存失效
    except Exception:
        pass
    return entry


def read_recent(limit=50, day=None):
    """读最近 N 条审计（新→旧）"""
    path = audit_path(day)
    if not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out[-limit:][::-1]


def _counts_today():
    """当天各 actor 的调用计数 + 最近一分钟计数（按日志现算）"""
    day = time.strftime('%Y-%m-%d')
    path = audit_path(day)
    mt = 0
    try:
        mt = os.path.getmtime(path)
    except Exception:
        mt = 0
    if _cache['mtime'] == mt and _cache['day'] == day:
        return _cache['counts']
    counts, recent = {}, {}
    now = time.time()
    for e in read_recent(limit=100000, day=day):
        if e.get('kind') != 'call':
            continue
        actor = e.get('actor') or '?'
        counts[actor] = counts.get(actor, 0) + 1
        try:
            ts = datetime.datetime.fromisoformat(e['ts']).timestamp()
        except Exception:
            ts = now
        if now - ts <= 60:
            recent[actor] = recent.get(actor, 0) + 1
    _cache.update({'mtime': mt, 'day': day, 'counts': {'day': counts, 'minute': recent}})
    return _cache['counts']


def check_quota(actor):
    """(ok, why, used) —— 判断这个 actor 还能不能调用"""
    if not limits_enabled():
        return True, '', 0
    lim = limit_for(actor)
    counts = _counts_today()
    day_used = (counts.get('day') or {}).get(actor, 0)
    min_used = (counts.get('minute') or {}).get(actor, 0)
    if day_used >= lim['per_day']:
        return False, '%s 今天已调用 %d 次（上限 %d）' % (actor, day_used, lim['per_day']), day_used
    if min_used >= lim['per_minute']:
        return False, '%s 一分钟内已调用 %d 次（上限 %d）' % (actor, min_used, lim['per_minute']), day_used
    return True, '', day_used


# ---------------------------------------------------------------- 成本限额（治理增强③）

def cost_limit_enabled():
    return bool(_cfg().get('cost_limit_enabled', True))


def cost_limit_daily():
    try:
        return float(_cfg().get('cost_limit_daily', 20) or 0)
    except Exception:
        return 20.0


def today_cost(path=None):
    """今日累计成本（元）——**直接读 API 统计的持久化文件**，不另立第二套计价

    口径与「用量与计费」页、费用气泡完全一致（都来自 api_stats.py 算好的 today.cost）。
    """
    p = path or os.path.join(BASE_DIR, 'api_stats.json')
    try:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        if data.get('date') != time.strftime('%Y-%m-%d'):
            return 0.0                      # 跨天自动归零（统计文件自己也会重置）
        return float((data.get('today') or {}).get('cost') or 0.0)
    except Exception:
        return 0.0


def check_cost(estimate=0.0):
    """(ok, why, used) —— 日成本是否还在限额内（含本次预估）；关上限或上限为 0 时一律放行"""
    if not cost_limit_enabled():
        return True, '', 0.0
    lim = cost_limit_daily()
    if lim <= 0:
        return True, '', 0.0
    used = today_cost()
    if used + max(0.0, float(estimate or 0.0)) > lim:
        return False, ('今日模型调用已花 ¥%.2f，达到你设的日上限 ¥%.2f；'
                       '可在「设置 → 用量与计费 → 日成本上限」调高或关掉') % (used, lim), used
    return True, '', used


def purge_old(days=KEEP_DAYS):
    """删掉超过保留期的审计文件（默认 30 天）"""
    removed = []
    if not os.path.isdir(LOG_DIR):
        return removed
    cutoff = time.time() - days * 86400
    for fn in os.listdir(LOG_DIR):
        if not (fn.startswith('audit_') and fn.endswith('.jsonl')):
            continue
        p = os.path.join(LOG_DIR, fn)
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
                removed.append(fn)
        except Exception:
            continue
    return removed


def audit_stats(day=None):
    """给界面用：条数、被拒次数、涉及对象"""
    items = read_recent(limit=100000, day=day)
    return {
        'total': len(items),
        'denied': sum(1 for e in items if not e.get('allowed', True)),
        'actors': sorted({e.get('actor', '?') for e in items}),
        'kinds': sorted({e.get('kind', '?') for e in items}),
        'path': audit_path(day),
    }


# ------------------------------------------------------------------ 出网白名单

def read_filtered(kind=None, actor=None, only_denied=False, limit=500, day=None):
    """按条件筛审计（新→旧）—— 供审计查看窗口用

    kind / actor 传 None 或 '全部' 表示不过滤；only_denied=True 时只留被拒（allowed=False）。
    """
    skip = (None, '', '全部', 'all', 'ALL')
    out = []
    for e in read_recent(limit=100000, day=day):
        if kind not in skip and e.get('kind') != kind:
            continue
        if actor not in skip and e.get('actor') != actor:
            continue
        if only_denied and e.get('allowed', True):
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out


def export_csv(path, day=None):
    """把当日审计导出为 CSV（utf-8-sig，Excel 双击不乱码）。返回 (ok, 条数或错误信息)"""
    import csv
    items = list(reversed(read_recent(limit=100000, day=day)))   # 时间正序，便于阅读
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['时间', '类型', '对象', '动作', '是否允许', '耗时ms', '详情', '附加'])
            for e in items:
                extra = e.get('extra')
                w.writerow([
                    e.get('ts', ''), e.get('kind', ''), e.get('actor', ''), e.get('action', ''),
                    '是' if e.get('allowed', True) else '否',
                    e.get('ms', ''), e.get('detail', ''),
                    json.dumps(extra, ensure_ascii=False) if extra else '',
                ])
        return True, len(items)
    except Exception as ex:
        return False, str(ex)


def clear_day(day=None, keep_backup=True):
    """清空当日审计。默认**先改名备份**（audit_<day>.jsonl.bak-HHMMSS）而不是直接删，
    并补写一条自身的审计（说明是谁在什么时候清的）。返回 (ok, 说明)"""
    path = audit_path(day)
    if not os.path.isfile(path):
        return False, '当前没有审计文件'
    bak = ''
    try:
        if keep_backup:
            bak = path + '.bak-' + time.strftime('%H%M%S')
            os.replace(path, bak)
        else:
            os.remove(path)
        _cache['mtime'] = None            # 计数缓存失效
        log_event('deny', 'audit', '清空当日日志',
                  detail='备份为 %s' % (os.path.basename(bak) if bak else '（未备份，已直接删除）'),
                  allowed=True)
        return True, ('已清空。原日志已备份为 %s' % os.path.basename(bak)) if bak else '已清空（未备份）'
    except Exception as ex:
        return False, str(ex)


def net_allowlist():
    return [str(x).strip() for x in (_cfg().get('net_allowlist') or []) if str(x).strip()]


def set_net_allowlist(items):
    _save_cfg_value('net_allowlist', [str(x).strip() for x in (items or []) if str(x).strip()])
    return net_allowlist()


def add_net_rule(pattern):
    items = net_allowlist()
    p = str(pattern or '').strip()
    if p and p not in items:
        items.append(p)
        set_net_allowlist(items)
    return items


def host_of(url):
    try:
        u = urlparse(str(url))
        host = (u.hostname or '').lower()
        return host
    except Exception:
        return ''


def net_explain(url):
    """试算用：返回 (ok, why, rule, host) —— rule 是命中的那条规则（未命中为 None）

    与 net_allowed 是**同一套判定**（net_allowed 直接调本函数），不写第二遍逻辑。
    """
    host = host_of(url)
    if not host:
        return False, '看不懂的地址（要给完整 http(s):// 地址）', None, ''
    rules = net_allowlist()
    if not rules:
        return False, '出网白名单是空的（默认禁止技能出网；可在需要时添加域名）', None, host
    for rule in rules:
        r = rule.lower()
        if r in ('*', '*.*'):
            return True, '白名单全放行', rule, host
        if fnmatch.fnmatch(host, r):
            return True, '命中白名单（%s）' % rule, rule, host
    return False, '域名 %s 不在出网白名单里' % host, None, host


def net_allowed(url):
    """(ok, why)：域名是否在白名单里。支持 *.example.com 这种通配

    判定统一走 net_explain（保证「试算」与「真实拦截」永远一致）
    """
    ok, why, _rule, _host = net_explain(url)
    return ok, why


def http_get(url, timeout=15, max_bytes=4 * 1024 * 1024):
    """受限 HTTP GET：先过白名单，再限大小（给技能包用的统一入口）"""
    ok, why = net_allowed(url)
    if not ok:
        log_event('net', 'pet_net', 'GET', '%s → %s' % (url, why), allowed=False)
        return None, why
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'pet-skill/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(max_bytes + 1)
        if len(data) > max_bytes:
            return None, '响应超过 %d KB 上限' % (max_bytes // 1024)
        log_event('net', 'pet_net', 'GET', url, allowed=True)
        return data, ''
    except Exception as e:
        log_event('net', 'pet_net', 'GET', '%s → %s' % (url, e), allowed=True)
        return None, '请求失败：%s' % e


def http_post_json(url, payload, timeout=20, max_bytes=4 * 1024 * 1024):
    """受限 HTTP POST（JSON）：同样先过白名单"""
    ok, why = net_allowed(url)
    if not ok:
        log_event('net', 'pet_net', 'POST', '%s → %s' % (url, why), allowed=False)
        return None, why
    try:
        import urllib.request
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=body,
                                     headers={'Content-Type': 'application/json',
                                              'User-Agent': 'pet-skill/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(max_bytes + 1)
        log_event('net', 'pet_net', 'POST', url, allowed=True)
        return data, ''
    except Exception as e:
        log_event('net', 'pet_net', 'POST', '%s → %s' % (url, e), allowed=True)
        return None, '请求失败：%s' % e
