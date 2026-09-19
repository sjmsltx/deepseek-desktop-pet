# -*- coding: utf-8 -*-
"""
api_stats.py — API 用量自监控（P1 模块化拆分）
==============================================
从 desktop_pet.py 拆出的 ApiStats 类：
- 解析响应 usage（prompt/completion/cache）
- 按模型价格表计算费用（每百万 token 单价；价格来源：模型档案 models.json → config.json api_prices → 内置兜底表）
- 今日/累计统计 + 最近 200 条调用明细
- 价格表支持 config.json api_prices 覆盖

模块化说明：独立类，无 UI 依赖；config 路径与模型档案通过 __init__ 注入。
"""
import datetime
import json
import os
import threading
import urllib.request

from pet_log import get_logger

_log = get_logger('api_stats')


class ApiStats:
    """API 调用自监控：解析响应 usage，统计模型/token/缓存/费用，持久化"""
    PRICES = {  # 每百万 token 单价（元，**空闲时段价**）——内置兜底表
        # 模型价格的正经来源是模型档案（models.json 的 price 字段），这里只在本模块
        # 未注入 registry 时兜底。键名改为官方**当前规范 ID**：官方重命名后响应里的
        # model 与请求写的 ID 不同，旧键（deepseek-v4-flash）会静默落到 DEFAULT_PRICE。
        # v6.62 按官方定价页（api-docs.deepseek.com/zh-cn/quick_start/pricing，
        # 2026-09-19 核对）校正：deepseek-flash 空闲 1/0.02/4 元、高峰 2/0.04/8 元；
        # deepseek-v4-pro 空闲 4.5/0.15/13.5 元、高峰 9/0.3/27 元。
        'deepseek-flash': {'input': 1.0, 'cache': 0.02, 'output': 4.0,
                           'input_peak': 2.0, 'cache_peak': 0.04, 'output_peak': 8.0},
        'deepseek-v4-pro': {'input': 4.5, 'cache': 0.15, 'output': 13.5,
                            'input_peak': 9.0, 'cache_peak': 0.30, 'output_peak': 27.0},
        'deepseek-v4-flash': {'input': 1.0, 'cache': 0.02, 'output': 4.0,
                              'input_peak': 2.0, 'cache_peak': 0.04, 'output_peak': 8.0},
    }
    DEFAULT_PRICES = {k: dict(v) for k, v in PRICES.items()}  # 出厂价格快照（api_prices 清空时恢复）
    DEFAULT_PRICE = {'input': 1.0, 'cache': 0.02, 'output': 4.0}

    # ---- v6.61：余额查询（官方 GET /user/balance） ----
    BALANCE_TIMEOUT = 15
    BALANCE_DEFAULT_BASE = 'https://api.deepseek.com'

    @staticmethod
    @staticmethod
    def normalize_base(base_url):
        """把「完整接口地址」或「基础地址」归一成基础地址（v6.62 修 404）

        背景：档案里存的是**完整 endpoint**（…/chat/completions），旧实现直接拼
        `/user/balance` → `…/chat/completions/user/balance` → HTTP 404。
        实测：余额接口本身没问题，是拼地址错了（裸基础地址一直能通）。
        """
        s = str(base_url or '').strip().rstrip('/')
        if not s:
            return ApiStats.BALANCE_DEFAULT_BASE
        for suf in ('/chat/completions', '/completions', '/responses'):
            if s.endswith(suf):
                s = s[:-len(suf)].rstrip('/')
                break
        if s.endswith('/v1') or s.endswith('/beta'):
            s = s.rsplit('/', 1)[0].rstrip('/')
        return s or ApiStats.BALANCE_DEFAULT_BASE

    def query_balance(api_key, base_url='', timeout=None):
        """查询 DeepSeek 账户余额（v6.61；v6.62 修 404：先归一基础地址）

        官方接口：GET {base}/user/balance（Authorization: Bearer key），实测返回：
            {"is_available": true,
             "balance_infos": [{"currency": "CNY", "total_balance": "70.68",
                                "granted_balance": "0.00", "topped_up_balance": "70.68"}]}

        返回：{'ok': True, total, granted, topped_up, currency, is_available, at}
              {'ok': False, 'error': '...'}
        **失败时绝不编数字**——调用方只把 error 显示出来。
        """
        key = (api_key or '').strip()
        if not key:
            return {'ok': False, 'error': '未配置 API Key'}
        base = ApiStats.normalize_base(base_url)
        url = base + '/user/balance'
        req = urllib.request.Request(url, headers={
            'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout or ApiStats.BALANCE_TIMEOUT) as r:
                data = json.loads(r.read().decode('utf-8'))
        except Exception as e:
            code = getattr(e, 'code', '')
            host = base.split('//')[-1].split('/')[0]
            tip = '' if 'api.deepseek.com' in host else '（当前接口地址非官方，可能是中转，不支持余额接口）'
            msg = ('HTTP %s' % code) if code else str(e)[:100]
            return {'ok': False, 'error': '%s%s' % (msg, tip)}
        infos = data.get('balance_infos') if isinstance(data, dict) else None
        if not infos:
            return {'ok': False, 'error': '响应缺少 balance_infos 字段'}
        info = infos[0] or {}

        def _num(v):
            try:
                return float(v)
            except Exception:
                return None

        total = _num(info.get('total_balance'))
        if total is None:
            return {'ok': False, 'error': '响应里的 total_balance 不是数字'}
        return {'ok': True,
                'total': total,
                'granted': _num(info.get('granted_balance')),
                'topped_up': _num(info.get('topped_up_balance')),
                'currency': info.get('currency') or 'CNY',
                'is_available': bool(data.get('is_available', True)),
                'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

    def __init__(self, path, config_path=None, registry=None):
        self.path = path
        self.config_path = config_path  # 价格覆盖来源（P1 模块化：由调用方注入）
        self.registry = registry        # 模型档案（价格首选来源；None 时退回内置表）
        self.lock = threading.Lock()
        self.today = {'count': 0, 'prompt': 0, 'completion': 0, 'total': 0, 'cost': 0.0,
                      'cache_hit': 0, 'cache_miss': 0, 'date': ''}
        self.total = {'count': 0, 'prompt': 0, 'completion': 0, 'total': 0, 'cost': 0.0,
                      'cache_hit': 0, 'cache_miss': 0, 'date': ''}
        self.last = None
        self.calls = []  # 最近调用明细（上限 200）
        self.by_model = {}  # 按模型累计（终身口径：次数/token/费用/价格未知次数）
        self.balance = None  # v6.61：最近一次余额查询结果（缓存，落盘）
        self._load()
        self._load_price_overrides()

    def _load_price_overrides(self):
        """从 config.json 读 api_prices 覆盖价格（AI 可用 write_config 修改，v6.19）。

        注入了模型档案时，覆盖写进**档案**并落盘——保持「档案是模型身份唯一来源」，
        不让 config.json 与 models.json 各存一份价（那正是本次要治的双头状态）。
        """
        try:
            if not (self.config_path and os.path.exists(self.config_path)):
                return
            with open(self.config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            overrides = cfg.get('api_prices')
            if isinstance(overrides, str):        # 旧配置里可能是 JSON 字符串
                try:
                    overrides = json.loads(overrides)
                except Exception:
                    overrides = {}
            if not isinstance(overrides, dict):
                return
            touched = False
            if not overrides:
                # 空 api_prices = 用户没设任何覆盖 → 完全不动档案里的价格。
                # 档案是价格的唯一来源，启动流程绝不能清掉用户对 models.json 的改动；
                # 「恢复出厂价」应由设置界面显式触发，而不是靠「配置为空」隐式推断。
                ApiStats.PRICES.clear()
                ApiStats.PRICES.update({k: dict(v) for k, v in ApiStats.DEFAULT_PRICES.items()})
                return
            for k, v in overrides.items():
                if not isinstance(v, dict):
                    continue
                patch = {kk: float(vv) for kk, vv in v.items() if kk in ('input', 'cache', 'output')}
                if not patch:
                    continue
                prof = None
                if self.registry is not None:
                    for p in self.registry.profiles():
                        if k in (p.model_id, p.key) or k in p.aliases:
                            prof = p
                            break
                if prof is not None:
                    merged = dict(prof.price)
                    merged.update(patch)
                    self.registry.set_price(prof.key, merged)
                    touched = True
                else:
                    base = dict(ApiStats.PRICES.get(k, ApiStats.DEFAULT_PRICE))
                    base.update(patch)
                    ApiStats.PRICES[k] = base
            if touched:
                self.registry.save()
        except Exception as e:
            _log.warning('价格表同步/保存失败：%s', e)

    def reload_prices(self):
        """重新应用 config.json 的 api_prices（write_config 改价后热加载）"""
        ApiStats.PRICES.clear()
        ApiStats.PRICES.update({k: dict(v) for k, v in ApiStats.DEFAULT_PRICES.items()})
        self._load_price_overrides()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.total = data.get('total', self.total)
                self.calls = data.get('calls', [])[-200:]
                self.by_model = data.get('by_model', {})
                self.balance = data.get('balance') or None   # v6.61
                today = datetime.date.today().isoformat()
                if data.get('date') == today:
                    self.today = data.get('today', self.today)
                else:
                    self.today['date'] = today
        except Exception as e:
            _log.warning('用量统计文件读取失败，本次从零开始：%s', e)

    def _save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump({'date': datetime.date.today().isoformat(),
                           'today': self.today, 'total': self.total,
                           'by_model': self.by_model,
                           'balance': self.balance,
                           'calls': self.calls[-200:]}, f,
                          ensure_ascii=False, indent=2)
        except Exception as e:
            _log.error('用量统计保存失败：%s', e)

    def _price_for(self, model, now=None):
        """查价格：优先模型档案（模型身份的唯一来源），退回内置表。
        返回 (价格 dict|None, 是否未知)。
        注意：官方重命名后响应里的 model 与请求写的 ID 可能不同，故先经
        registry.canonical_model_id() 归一化再查，避免像旧版那样整张价格表失效。
        v6.62：官方价格分高峰/空闲两档（空闲为高峰一半），这里按时段返回生效价。"""
        if self.registry is not None:
            p = self.registry.price_for(model)
            if p:
                # v6.62：只有「官方峰谷计价」的档案才套峰谷规则；
                # 第三方/中转档案（pricing_mode=flat，或非官方 endpoint）按固定价算。
                if self.registry.uses_peak_pricing(model):
                    p = self._peak_adjusted(p, now)
                return p, False
            return None, True   # 档案里也没这个模型的价格 → 未知，不静默套兜底价
        p = ApiStats.PRICES.get(model or '')
        if p:
            return self._peak_adjusted(p, now), False
        return None, True       # v6.62：没有 registry 又查不到 → 未知（不再拿 DEFAULT_PRICE 当已知价）

    # 官方高峰时段（北京时间，周一至周五；不含法定节假日）
    PEAK_HOURS = ((9, 12), (14, 18))
    # 节假日缓存文件路径（由宿主注入；不注入就只用内置表）
    HOLIDAYS_CACHE = None

    @staticmethod
    def is_peak_now(now=None):
        """当前是否官方高峰时段（v6.62）

        官方口径（中文定价页脚注）：高峰 = **周一至周五** 9:00–12:00、14:00–18:00，
        **不含中国法定节假日**；其余全部（周末 + 法定节假日全天）为空闲。
        关键细节：判定只看“是不是周末 / 是不是节假日”，**不看是否调休补班** ——
        所以调休补班的**周末仍按空闲**。
        `now=None` 时用 `server_clock.beijing_now()`（UTC+8 + 服务器时间校正）：
        即使用户在外国时区、或把系统时间改过，也能得到真实的北京时间。
        局限：节假日表来自国务院安排，本机无法预知未来年份；表里没有的年份会
        保守按高峰计（只会多算，不会少算）。
        """
        try:
            if now is None:               # v6.62：不再用本机当地时间，改用北京时间（时区无关 + 时钟校正）
                try:
                    from server_clock import beijing_now as _bj_now
                    now = _bj_now()
                except Exception:
                    now = datetime.datetime.now()
            if now.weekday() >= 5:          # 周末全天空闲（含调休补班的周末）
                return False
            try:                            # 法定节假日 → 全天空闲
                from cn_holidays import is_holiday
                if is_holiday(now.date(), ApiStats.HOLIDAYS_CACHE):
                    return False
            except Exception:
                pass
            h = now.hour + now.minute / 60.0
            return any(a <= h < b for a, b in ApiStats.PEAK_HOURS)
        except Exception:
            return False

    @staticmethod
    def _peak_adjusted(p, now=None):
        """空闲价 → 高峰价（v6.62）：有 *_peak 用显式值，没有就按官方“高峰=空闲×2”"""
        if not ApiStats.is_peak_now(now):
            return p
        out = dict(p)
        for k, kp in (('input', 'input_peak'), ('cache', 'cache_peak'), ('output', 'output_peak')):
            v = p.get(kp)
            if v is None and p.get(k) is not None:
                try:
                    v = float(p[k]) * 2
                except (TypeError, ValueError):
                    v = None
            if v is not None:
                out[k] = v
        return out

    def _cost(self, model, prompt, completion, cache_hit, cache_miss, now=None):
        p, unknown = self._price_for(model, now)
        if p is None:
            # v6.62：价格未知 —— 不再拿兜底价算出一个“看着像真的”的数字。
            # 记 0 并标记，统计里单列“未计入”的调用次数，引导用户去模型管理填价格。
            return 0.0, True
        try:
            return (cache_miss / 1e6 * float(p['input'])
                    + cache_hit / 1e6 * float(p.get('cache', p['input']))
                    + (completion or 0) / 1e6 * float(p['output'])), unknown
        except Exception as e:
            _log.debug('费用计算失败（按 0 计并标记未知价）：%s', e)
            return 0.0, True

    def record(self, usage, model='?'):
        prompt = usage.get('prompt_tokens') or 0
        completion = usage.get('completion_tokens') or 0
        cache_hit = usage.get('prompt_cache_hit_tokens') or 0
        cache_miss = usage.get('prompt_cache_miss_tokens') or 0
        if not cache_hit and not cache_miss:
            det = usage.get('prompt_tokens_details') or {}
            cache_hit = det.get('cached_tokens') or 0
            cache_miss = prompt - cache_hit
        if self.registry is not None:
            model = self.registry.canonical_model_id(model) or model
        cost, price_unknown = self._cost(model, prompt, completion, cache_hit, cache_miss)
        entry = {'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 'model': model, 'prompt': prompt, 'completion': completion,
                 'total': prompt + completion, 'cost': round(cost, 6),
                 'cache_hit': cache_hit, 'cache_miss': cache_miss}
        if price_unknown:
            entry['price_unknown'] = True
        with self.lock:
            today = datetime.date.today().isoformat()
            if self.today.get('date') != today:
                self.today = {'count': 0, 'prompt': 0, 'completion': 0, 'total': 0, 'cost': 0.0,
                              'cache_hit': 0, 'cache_miss': 0, 'date': today, 'unknown': 0}
            for agg in (self.today, self.total):
                agg['count'] += 1
                agg['prompt'] += prompt
                agg['completion'] += completion
                agg['total'] += prompt + completion
                agg['cost'] += cost
                agg['cache_hit'] += cache_hit
                agg['cache_miss'] += cache_miss
                if price_unknown:      # v6.62：未配置价格的调用单列计数（界面据此提示）
                    agg['unknown'] = agg.get('unknown', 0) + 1
            self.last = entry
            self.calls.append(entry)
            # 按模型累计（终身口径）：看哪个模型花了多少、有没有价格未知的
            bkey = model or '?'
            mb = self.by_model.get(bkey)
            if not isinstance(mb, dict):
                mb = {'count': 0, 'prompt': 0, 'completion': 0, 'cost': 0.0, 'unknown': 0}
                self.by_model[bkey] = mb
            mb['count'] += 1
            mb['prompt'] += prompt
            mb['completion'] += completion
            mb['cost'] += cost
            if entry.get('price_unknown'):
                mb['unknown'] = mb.get('unknown', 0) + 1
        self._save()
        return cost  # v6.30 返回本次费用（余额气泡用）

    def model_breakdown(self):
        """按模型汇总（终身口径）：次数 / token / 费用 / 价格未知次数。费用从高到低。"""
        with self.lock:
            rows = [dict(model=k, **v) for k, v in self.by_model.items()]
        rows.sort(key=lambda r: -float(r.get('cost') or 0))
        return rows

    # ---- v6.61：余额缓存与文案 ----

    def set_balance(self, info):
        """缓存一次余额结果并落盘（info=None 表示查询失败，不覆盖旧的成功缓存）"""
        if not info or not info.get('ok'):
            return
        with self.lock:
            self.balance = dict(info)
            self.balance.pop('_manual', None)
        self._save()

    def balance_age_seconds(self):
        """距上次成功查询的秒数（无缓存 / 时间戳不可解析 → None）"""
        at = (self.balance or {}).get('at')
        if not at:
            return None
        try:
            t = datetime.datetime.strptime(at, '%Y-%m-%d %H:%M:%S')
        except Exception:
            return None
        return max(0.0, (datetime.datetime.now() - t).total_seconds())

    def balance_stale(self, minutes=10):
        """缓存是否过期（无缓存也算过期，用于「对话后静默刷新」判定）"""
        age = self.balance_age_seconds()
        if age is None:
            return True
        try:
            return age > max(1, int(minutes)) * 60
        except Exception:
            return True

    def balance_text(self, with_detail=False):
        """余额一句话文案；无成功缓存时返回 ''（绝不编数字）"""
        b = self.balance or {}
        if not b.get('ok') or b.get('total') is None:
            return ''
        cur = '¥' if (b.get('currency') or 'CNY') == 'CNY' else ((b.get('currency') or '') + ' ')
        s = '%s%.2f' % (cur, float(b['total']))
        if with_detail:
            s += '（赠金 %s%.2f / 充值 %s%.2f）' % (cur, float(b.get('granted') or 0),
                                                   cur, float(b.get('topped_up') or 0))
        return s

    def balance_updated_text(self):
        """「多久之前更新」文案（给悬浮窗用）"""
        age = self.balance_age_seconds()
        if age is None:
            return '未查询'
        if age < 60:
            return '%d 秒前更新' % int(age)
        if age < 3600:
            return '%d 分钟前更新' % int(age // 60)
        return '%d 小时前更新' % int(age // 3600)
