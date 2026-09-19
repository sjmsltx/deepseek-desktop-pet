# -*- coding: utf-8 -*-
"""price_check.py — 核对官方定价页（v6.62）
==========================================

背景
----
价格存在**模型档案**里（models.json，用户可改），出厂值是官方价 —— 不属于“写死”，
但官方调价后不会自动跟随。官方**没有机器可读的定价接口**，不过定价页是
服务端渲染的规整表格，可以直接抓下来解析（实测 2026-09-19 可稳定读到 6 组价格）。

本模块只做「**核对并如实展示差异**」：抓页面 → 解析 → 与本地档案比 → 返回差异清单。
**绝不自动改价**：是否应用由用户点击决定（避免“官方页脚注/排版一改，本地价格被写坏”）。

官方计价规则（同一页脚注）：高峰 = 周一至周五 9:00–12:00、14:00–18:00（不含法定节假日）；
空闲 = 其余全部，价格为高峰的一半 —— 与 cn_holidays / server_clock 的实现一致。
"""
import re
import urllib.request

from pet_log import get_logger

_log = get_logger('price_check')

PRICING_URL = 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing'
USER_AGENT = 'Mozilla/5.0 (desktop-pet price check)'

# 行标签 → 价格字段（base 为空闲价，_peak 为高峰价）
_FIELD_MAP = (('缓存命中', 'cache'), ('缓存未命中', 'input'), ('输出', 'output'))


def _cells(row_html):
    """把一个 <tr> 拆成清洗后的单元格文本"""
    raw = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.S)
    return [re.sub(r'<[^>]+>', '', c).replace('\xa0', ' ').strip() for c in raw]


def _num(text):
    m = re.search(r'(\d+(?:\.\d+)?)', str(text or ''))
    return float(m.group(1)) if m else None


def parse_pricing_html(html):
    """解析官方定价页 → ({模型ID: {字段: 价格}}, 错误)

    结构（实测）：表头行 ['模型', 'deepseek-flash(1)', 'deepseek-v4-pro']，
    价格行为 ['价格(2)', '百万tokens输入（缓存命中）', '空闲时段', '0.02元', '0.15元']，
    紧跟一行 ['高峰时段', '0.04元', '0.30元']（无字段名，沿用上一行）。
    """
    try:
        tables = re.findall(r'<table.*?</table>', html or '', re.S)
        table = next((t for t in tables if '元' in t), None)
        if not table:
            return {}, '页面里没找到含价格的表格（官方可能改版了）'
        rows = re.findall(r'<tr.*?</tr>', table, re.S)
        if not rows:
            return {}, '表格里没有行'
        # 表头 → 模型列（去掉脚注标记，如 deepseek-flash(1)）
        head = _cells(rows[0])
        models = []
        for c in head[1:]:
            mid = re.sub(r'\(\d+\)$', '', c).strip()
            if mid and 'deepseek' in mid:
                models.append(mid)
        if not models:
            return {}, '表头里没认出模型列'
        prices = {m: {} for m in models}
        field = None
        for r in rows[1:]:
            cells = _cells(r)
            text = ' '.join(cells)
            for kw, f in _FIELD_MAP:          # 该行是否声明了新的字段
                if kw in text and ('缓存' in text or '输出' in text):
                    field = f
                    break
            if field is None:
                continue
            tier = 'peak' if '高峰时段' in text else ('base' if '空闲时段' in text else None)
            if tier is None:
                continue
            nums = [_num(c) for c in cells if '元' in c]
            nums = [n for n in nums if n is not None]
            if len(nums) < len(models):
                continue                      # 数值列不足 → 不是价格行
            for m, v in zip(models, nums[:len(models)]):
                prices[m]['%s_peak' % field if tier == 'peak' else field] = v
        prices = {m: v for m, v in prices.items() if v.get('input') is not None}
        if not prices:
            return {}, '解析出来是空表（官方可能改版了）'
        return prices, None
    except Exception as e:
        return {}, '解析失败：%s: %s' % (type(e).__name__, str(e)[:120])


def fetch_official_prices(timeout=25):
    """抓官方定价页并解析，返回 ({模型: {字段: 价格}}, 错误)"""
    try:
        req = urllib.request.Request(PRICING_URL, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode('utf-8', 'ignore')
        return parse_pricing_html(html)
    except Exception as e:
        return {}, '抓取失败：%s: %s' % (type(e).__name__, str(e)[:120])


def compare_with_profiles(prices, profiles):
    """把官方价格与本地档案比一遍。

    只比「官方接口地址」的档案（第三方/中转的价目与官方无关）。
    返回 [{'key','model_id','field','local','official'}, ...]
    """
    from model_registry import is_official_endpoint
    diffs = []
    for p in (profiles or []):
        try:
            if not is_official_endpoint(p.endpoint):
                continue
            official = prices.get(p.model_id)
            if not official:
                continue
            for field, want in official.items():
                got = p.price.get(field)
                if got is None or abs(float(got) - float(want)) > 1e-9:
                    diffs.append({'key': p.key, 'model_id': p.model_id, 'field': field,
                                  'local': got, 'official': want})
        except Exception as e:
            _log.debug('比对档案 %s 失败：%s', getattr(p, 'key', '?'), e)
    return diffs


def apply_prices(registry, prices):
    """把官方价格写进档案（**只在用户明确同意后调用**）。返回 (更新的档案键列表, 错误列表)"""
    from model_registry import is_official_endpoint
    done, errs = [], []
    for p in registry.profiles():
        if not is_official_endpoint(p.endpoint):
            continue
        official = prices.get(p.model_id)
        if not official:
            continue
        if registry.set_price(p.key, dict(official)):
            done.append(p.key)
        else:
            errs.append(p.key)
    if done and not registry.save():
        errs.append('写入 models.json 失败：%s' % registry.last_error)
    return done, errs


def diff_text(diffs):
    """差异清单 → 人类可读的多行文本（给对话框用）"""
    names = {'input': '输入(未命中)', 'cache': '输入(缓存命中)', 'output': '输出',
             'input_peak': '输入(未命中)·高峰', 'cache_peak': '输入(缓存命中)·高峰',
             'output_peak': '输出·高峰'}
    lines = []
    for d in diffs:
        lines.append('· %s（%s）%s：本地 %s → 官方 %s'
                     % (d['key'], d['model_id'], names.get(d['field'], d['field']),
                        d['local'], d['official']))
    return '\n'.join(lines)
