# -*- coding: utf-8 -*-
"""memory_usage.py — 「注入了，但回复里没用上」埋点
==================================================
2026-11-06 建。Owner 把它列为记忆线第三件：**最少人做的那一层**。

## 为什么值得做

前两层（写入边界、检索阈值）解决「记什么 / 取什么」，
这一层回答的是：「**取出来的东西，真的被用上了吗**」。
没有这个数据，任何"提高相关性"的改动都只能拿 R@3 这类离线指标自证，
而 R@3 好 ≠ 用户感受到「她记得我」。

## 判定口径（诚实标注：这是词面代理，不是语义理解）

一条注入的记忆算「被引用」，当且仅当：

  1. 它里面有**可指认的针**（专名/数字/英文/书名号/非泛用的 2-gram）
  2. 回复里出现了至少一个针
  3. **该针不在用户这条消息里** —— 否则只是复述用户刚说的话，不算"记得"

⛔ 已知偏差（必须写在报告里，不许当成准确率）：
  · 同义改写会漏判（回复说「甜的那种糕点」，记忆写「桃片」→ 判为未引用）
  · 恰好同名会误判（回复提到 "Python" 只是在聊语法，也算引用了那条 Python 记忆）
  · 短记忆（只有 4~6 字、没有专名）几乎没有针 → 恒判未引用
    ⇒ 统计时要把「无针记忆」单列，不能混进分母拉低引用率

所以本模块输出的是**倾向与对比**（哪类记忆常被用上、哪类从不被用上），
不是"准确引用率"。

## 落点

每条注入写一行 `inject`，回复落地后写一行 `usage`（同一 turn_id 可关联），
都进 `memory_ledger`（logs/memory_ledger.jsonl）。分析脚本：
`tools/eval/memory_usage_report.py`。
"""
import datetime
import logging
import re
import uuid

import memory_ledger as ledger

_log = logging.getLogger('pet.memory_usage')

#: 泛用词：在人-宠物对话里几乎每条都有，不能当"针"
_STOP = set("""
用户 桌宠 的 了 是 我 你 他 她 它 会 在 和 与 如 等 对 向 把 被 让 给 从 到 为 以 或 但 而 且 并
有 没有 不 很 更 最 太 也 都 还 就 能 要 说 做 用 时 里 上 下 中 后 前 自己 他们 我们
这个 那个 一下 一些 有点 比较 觉得 认为 可以 什么 怎么 因为 所以 如果 但是 而且 就是 不是
起来 记得 知道 希望 需要 可能 应该 喜欢 一个 现在 已经
""".split())

#: 引号/书名号里的内容天然是"针"（专名、作品名）
_QUOTED_RE = re.compile(r'《([^》]{1,20})》|「([^」]{1,20})」|"([^"]{1,20})"')
#: 英文/数字（含小数点、加号、井号，如 Python3.14、C#、4.1）
_TOKEN_RE = re.compile(r'[A-Za-z][A-Za-z0-9.+#_-]{1,}|[0-9]+(?:\.[0-9]+)?')

#: 每条记忆最多取几个针（够用即可，多了会拖慢且提高误判）
MAX_NEEDLES = 10

#: 低信息字：由它们组成的 2-gram 不算"针"。
#: 判据来源（2026-11-06 两次误判的教训）：
#:   · 不滤 ⇒ 记忆「好的」碰到回复「好的」被判成"引用了"
#:   · 改成"要命中 2 个 2-gram" ⇒ 反而把「桃片」这种真名词判丢（只命中 1 个）
#:   ⇒ 正确的判据是**信息量**，不是命中个数。
_LOWINFO_CHARS = set('的了是我你他她它会和与就也都很不有没这那好要能可以说做用个一上下中里前后时到对把被让给从为以如等而且则着过来去那')

#: 弱针至少命中几个才算"用上"
#: （现在弱针已经过滤掉虚词组合，命中 1 个就够；保留常量便于以后收紧）
WEAK_MIN_HITS = 1


def _cjk_ngrams(text, n=2):
    """中文 n-gram（只取纯中文连续段）"""
    out = []
    for run in re.findall(r'[\u4e00-\u9fff]+', text or ''):
        for i in range(len(run) - n + 1):
            out.append(run[i:i + n])
    return out


def _distinctive(g):
    """这个 2-gram 是否有信息量（不含低信息字、且不在停用词表里）"""
    if not g or len(g) < 2 or g in _STOP:
        return False
    return not (g[0] in _LOWINFO_CHARS or g[1] in _LOWINFO_CHARS)


def needles(text):
    """从一条记忆里取"可指认的针"，分两档：

      强针  书名号/引号内容、英文词、数字 —— 几乎不会误判
      弱针  有信息量的中文 2-gram（「桃片」「日语」「满分」），命中 1 个即算

    返回 (strong, weak)，两个字符串列表（可能都为空 —— 那说明这条记忆太泛，
    机械判不了它有没有被引用，统计时要单列）。
    """
    t = str(text or '')
    strong = []
    for m in _QUOTED_RE.finditer(t):
        for g in m.groups():
            if g and g.strip():
                strong.append(g.strip())
    strong.extend(_TOKEN_RE.findall(t))
    weak = [g for g in _cjk_ngrams(t) if _distinctive(g)]

    def _uniq(seq):
        seen, out = set(), []
        for x in seq:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out[:MAX_NEEDLES]

    return _uniq(strong), _uniq(weak)


def needles_flat(text):
    """所有针拍平（给需要"有哪些针"的调用方用）"""
    s, w = needles(text)
    return s + [x for x in w if x not in s]


def judge(fact_text, reply, user_text=''):
    """这条记忆是否被回复"用上"了。

    判定：
      · 强针（专名/英文/数字）命中 1 个即算
      · 弱针（2-gram）需同时命中 WEAK_MIN_HITS 个 —— 单个 2-gram 太容易碰巧命中
      · 命中项必须在回复里且**不在用户消息里**（否则只是复述用户的话）

    Returns:
        dict: referenced(bool) needles(list) hit(list) echoed_only(bool) why(str)
    """
    strong, weak = needles(fact_text)
    nd = strong + weak
    if not nd:
        return {'referenced': False, 'needles': [], 'hit': [],
                'echoed_only': False, 'why': 'no_needle'}
    r = str(reply or '')
    u = str(user_text or '')
    sh = [x for x in strong if x and x in r]
    wh = [x for x in weak if x and x in r and x not in sh]
    if not sh and len(wh) < WEAK_MIN_HITS:
        near = sh + wh
        if near:
            return {'referenced': False, 'needles': nd, 'hit': near,
                    'echoed_only': not [x for x in near if x not in u],
                    'why': 'weak_only'}
        return {'referenced': False, 'needles': nd, 'hit': [],
                'echoed_only': False, 'why': 'not_in_reply'}
    fresh_s = [x for x in sh if x not in u]
    fresh_w = [x for x in wh if x not in u]
    if not fresh_s and not fresh_w:
        return {'referenced': False, 'needles': nd, 'hit': sh + wh,
                'echoed_only': True, 'why': 'echo_user'}
    return {'referenced': True, 'needles': nd, 'hit': (fresh_s + fresh_w)[:6],
            'echoed_only': False, 'why': 'hit'}


def record_injection(facts, user_text, role='', extra=None):
    """记一条「本轮注入了哪些记忆」，返回 turn 记录（供回复落地时回填）。

    facts: search_memory_for_injection 的返回（含 id/text/via/score）

    ⚠ 内部吞掉所有异常（只记日志）：埋点是观测设施，绝不能因为台账写不进去
      而把一轮对话弄输。调用方再包一层 try 也无妨（双保险）。
    """
    try:
        turn = {
            'turn': uuid.uuid4().hex[:12],
            'role': role,
            'user': str(user_text or '')[:200],
            'facts': [{'id': str(f.get('id') or ''), 'text': str(f.get('text') or '')[:200],
                       'via': f.get('via') or 'bm25',
                       'score': f.get('score')} for f in (facts or [])],
        }
        ledger.append('inject', turn, n=len(turn['facts']),
                      ts_ms=datetime.datetime.now().isoformat(timespec='seconds'))
        return turn
    except Exception as exc:
        _log.warning('注入埋点失败（不影响对话）：%s', exc)
        return None


def record_reply(turn, reply):
    """回复落地：算引用情况并落一行 usage。

    返回 {'turn','n','referenced','no_needle'}；turn 为空时返回 None（未注入）。
    内部同样吞掉异常（理由同 record_injection）。
    """
    if not turn:
        return None
    try:
        items = []
        n_ref = n_no_needle = 0
        for f in turn.get('facts', []):
            v = judge(f.get('text', ''), reply, turn.get('user', ''))
            if v['why'] == 'no_needle':
                n_no_needle += 1
            if v['referenced']:
                n_ref += 1
            items.append({'id': f.get('id'), 'referenced': v['referenced'],
                          'why': v['why'], 'hit': v['hit'][:4],
                          'needles': len(v['needles'])})
        out = {'turn': turn.get('turn'), 'role': turn.get('role'),
               'n': len(items), 'referenced': n_ref, 'no_needle': n_no_needle,
               'items': items}
        ledger.append('usage', out, reply_len=len(str(reply or '')))
        return out
    except Exception as exc:
        _log.warning('引用判定失败（不影响对话）：%s', exc)
        return None


def stats(rows=None):
    """把 ledger 里的 inject/usage 汇总成几个数（报告脚本与测试共用）

    返回 dict:
      turns_injected / turns_with_use / rate / facts_injected / facts_used /
      fact_rate / no_needle / by_why
    """
    rows = ledger.read_all() if rows is None else rows
    inj = [r for r in rows if r.get('kind') == 'inject']
    use = [r for r in rows if r.get('kind') == 'usage']
    n_turn = len(inj)
    turns_used = sum(1 for r in use if r.get('referenced'))
    n_fact = sum(int(r.get('n') or 0) for r in inj)
    n_used = sum(int(r.get('referenced') or 0) for r in use)
    n_no = sum(int(r.get('no_needle') or 0) for r in use)
    by_why = {}
    for r in use:
        for it in r.get('items', []):
            by_why[it.get('why')] = by_why.get(it.get('why'), 0) + 1
    return {
        'turns_injected': n_turn,
        'turns_with_use': turns_used,
        'rate': (float(turns_used) / n_turn) if n_turn else None,
        'facts_injected': n_fact,
        'facts_used': n_used,
        'fact_rate': (float(n_used) / n_fact) if n_fact else None,
        'no_needle': n_no,
        'by_why': by_why,
    }
