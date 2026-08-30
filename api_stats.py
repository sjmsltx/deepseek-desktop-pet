# -*- coding: utf-8 -*-
"""
api_stats.py — API 用量自监控（P1 模块化拆分）
==============================================
从 desktop_pet.py 拆出的 ApiStats 类：
- 解析响应 usage（prompt/completion/cache）
- 按模型价格表计算费用（每百万 token 单价，2026-08 官方价）
- 今日/累计统计 + 最近 200 条调用明细
- 价格表支持 config.json api_prices 覆盖

模块化说明：独立类，无 UI 依赖；config 路径通过 __init__ 注入（config_path）。
"""
import datetime
import json
import os
import threading


class ApiStats:
    """API 调用自监控：解析响应 usage，统计模型/token/缓存/费用，持久化"""
    PRICES = {  # 每百万 token 单价（元），2026-08 官方新价（含多模态 vision-exp）
        'deepseek-v4-flash': {'input': 1.5, 'cache': 0.05, 'output': 4.5},
        'deepseek-v4-pro': {'input': 4.5, 'cache': 0.15, 'output': 13.5},
        'deepseek-v4-flash-vision-exp': {'input': 1.5, 'cache': 0.05, 'output': 4.5},
    }
    DEFAULT_PRICES = {k: dict(v) for k, v in PRICES.items()}  # 出厂价格快照（api_prices 清空时恢复）
    DEFAULT_PRICE = {'input': 1.5, 'cache': 0.05, 'output': 4.5}

    def __init__(self, path, config_path=None):
        self.path = path
        self.config_path = config_path  # 价格覆盖来源（P1 模块化：由调用方注入）
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
        """从 config.json 读 api_prices 覆盖默认价格表（AI 可用 write_config 修改，v6.19）"""
        try:
            if self.config_path and os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                overrides = cfg.get('api_prices') or {}
                if isinstance(overrides, dict):
                    for k, v in overrides.items():
                        if isinstance(v, dict):
                            base = dict(ApiStats.PRICES.get(k, ApiStats.DEFAULT_PRICE))
                            base.update({kk: float(vv) for kk, vv in v.items() if kk in ('input', 'cache', 'output')})
                            ApiStats.PRICES[k] = base
        except Exception:
            pass

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

    @staticmethod
    def _cost(model, prompt, completion, cache_hit, cache_miss):
        p = ApiStats.PRICES.get(model or '', ApiStats.DEFAULT_PRICE)
        try:
            return (cache_miss / 1e6 * float(p['input'])
                    + cache_hit / 1e6 * float(p.get('cache', p['input']))
                    + (completion or 0) / 1e6 * float(p['output']))
        except Exception:
            return 0.0

    def record(self, usage, model='?'):
        prompt = usage.get('prompt_tokens') or 0
        completion = usage.get('completion_tokens') or 0
        cache_hit = usage.get('prompt_cache_hit_tokens') or 0
        cache_miss = usage.get('prompt_cache_miss_tokens') or 0
        if not cache_hit and not cache_miss:
            det = usage.get('prompt_tokens_details') or {}
            cache_hit = det.get('cached_tokens') or 0
            cache_miss = prompt - cache_hit
        cost = self._cost(model, prompt, completion, cache_hit, cache_miss)
        entry = {'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 'model': model, 'prompt': prompt, 'completion': completion,
                 'total': prompt + completion, 'cost': round(cost, 6),
                 'cache_hit': cache_hit, 'cache_miss': cache_miss}
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
