# -*- coding: utf-8 -*-
"""
api_stats.py — API 用量自监控（P1 模块化拆分）
==============================================
从 desktop_pet.py 拆出的 ApiStats 类：
- 解析响应 usage（prompt/completion/cache）
- 按模型价格表计算费用（每百万 token 单价；价格来源：模型档案 models.json → config.json api_prices → 内置兵底表）
- 今日/累计统计 + 最近 200 条调用明细
- 价格表支持 config.json api_prices 覆盖

模块化说明：独立类，无 UI 依赖；config 路径与模型档案通过 __init__ 注入。
"""
import datetime
import json
import os
import threading

from model_registry import BUILTIN_PROFILES


class ApiStats:
    """API 调用自监控：解析响应 usage，统计模型/token/缓存/费用，持久化"""
    PRICES = {  # 每百万 token 单价（元）——内置兵底表
        # 模型价格的正经来源是模型档案（models.json 的 price 字段），这里只在本模块
        # 未注入 registry 时兵底。键名改为官方**当前规范 ID**：官方重命名后响应里的
        # model 与请求写的 ID 不同，旧键（deepseek-v4-flash）会静默落到 DEFAULT_PRICE。
        'deepseek-flash': {'input': 1.5, 'cache': 0.05, 'output': 4.5},
        'deepseek-v4-pro': {'input': 4.5, 'cache': 0.15, 'output': 13.5},
        'deepseek-v4-flash': {'input': 1.5, 'cache': 0.05, 'output': 4.5},  # 旧别名（官方已重命名）
    }
    DEFAULT_PRICES = {k: dict(v) for k, v in PRICES.items()}  # 出厂价格快照（api_prices 清空时恢复）
    DEFAULT_PRICE = {'input': 1.5, 'cache': 0.05, 'output': 4.5}

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
            if not overrides and self.registry is not None:
                # 空对象 = 恢复出厂价：把档案价格重置为内置默认
                for p in self.registry.profiles():
                    for b in BUILTIN_PROFILES:
                        if b['key'] == p.key:
                            p.price = dict(b['price'])
                            touched = True
                            break
                if touched:
                    self.registry.save()
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
        except Exception:
            pass

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
                today = datetime.date.today().isoformat()
                if data.get('date') == today:
                    self.today = data.get('today', self.today)
                else:
                    self.today['date'] = today
        except Exception:
            pass

    def _save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump({'date': datetime.date.today().isoformat(),
                           'today': self.today, 'total': self.total,
                           'calls': self.calls[-200:]}, f,
                          ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _price_for(self, model):
        """查价格：优先模型档案（模型身份的唯一来源），退回内置表。
        返回 (价格 dict|None, 是否未知)。
        注意：官方重命名后响应里的 model 与请求写的 ID 可能不同，故先经
        registry.canonical_model_id() 归一化再查，避免像旧版那样整张价格表失效。"""
        if self.registry is not None:
            p = self.registry.price_for(model)
            if p:
                return p, False
            return None, True   # 档案里也没这个模型的价格 → 未知，不静默套兜底价
        p = ApiStats.PRICES.get(model or '')
        if p:
            return p, False
        return ApiStats.DEFAULT_PRICE, True

    def _cost(self, model, prompt, completion, cache_hit, cache_miss):
        p, unknown = self._price_for(model)
        if p is None:
            p = ApiStats.DEFAULT_PRICE   # 仅用于给出粗估，条目会带 price_unknown 标记
        try:
            return (cache_miss / 1e6 * float(p['input'])
                    + cache_hit / 1e6 * float(p.get('cache', p['input']))
                    + (completion or 0) / 1e6 * float(p['output'])), unknown
        except Exception:
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
                              'cache_hit': 0, 'cache_miss': 0, 'date': today}
            for agg in (self.today, self.total):
                agg['count'] += 1
                agg['prompt'] += prompt
                agg['completion'] += completion
                agg['total'] += prompt + completion
                agg['cost'] += cost
                agg['cache_hit'] += cache_hit
                agg['cache_miss'] += cache_miss
            self.last = entry
            self.calls.append(entry)
        self._save()
        return cost  # v6.30 返回本次费用（余额气泡用）
