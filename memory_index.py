# -*- coding: utf-8 -*-
"""L3 索引层 —— 「去哪查」的地图

设计原文（通道 297 号件 §2.1，Owner 认可的分层）
------------------------------------------------------------
    L0 核心卡  身份事实（名字/称呼/职业…），不衰减
    L1 情节层  共同经历，半衰期 30 天
    L2 语义层  用户教过的事，半衰期 90 天
    L3 索引层  **不是记忆内容，是「去哪查」的地图**，永不写入业务数据

主线一句话：**能查的不进 L0~L2；L3 负责告诉它去哪查。**

为什么需要它
------------------------------------------------------------
记忆里的数字必然过期，接口里的不会。「这周花了多少」这种聚合问题，
记忆根本答不了，接口一行能算。

⛔ 本模块**只读**：不写 memories.json、不写 api_stats.json、不落任何业务数据。
   有测试（test_l3_is_read_only）盯着这条契约。

⛔ 索引里写的 source 会被 test_every_index_source_exists_on_host 逐段 getattr 验证 ——
   路标指错地方比没有路标更糟：模型会自信地去查一个不存在的东西。

用法
------------------------------------------------------------
    import memory_index
    blk = memory_index.build_l3_block(pet, user_text)   # 没命中返回 ''
    # 拼进 system prompt 的 relations 段之后
"""
import logging

_log = logging.getLogger('memory_index')

#: 预算：L3 是路标不是正文，别挤占人设与记忆的位置
BLOCK_BUDGET = 400

#: 索引表 —— 每条都是「问题类型 → 去哪查」。
#:
#:   key      内部标识（唯一）
#:   keywords 命中词（用户原话里出现任一即算命中；中文不做分词，用子串匹配）
#:   source   数据源路径，点分。**必须真实存在**（测试会逐段 getattr 验证）
#:   label    给人看的去处说明
#:   fmt      现算函数名（本模块内），返回一句话的值；None = 只给路标不给值
#:
#: ⚠ 2026-10-31 实测：api_stats 的 today / total / by_day / balance 全是 **property**，
#:   不是方法 —— 写成 `today()` 会 TypeError。加字段前先 dir() 一遍再用。
INDEX = [
    {
        'key': 'spend',
        'keywords': ('花了多少', '花费', '花了', '成本', '消费', '话费', '用了多少'),
        'source': 'api_stats.today',
        'label': '今天/累计的 API 花费与调用次数',
        'fmt': '_fmt_spend',
    },
    {
        'key': 'balance',
        'keywords': ('余额', '还剩多少', '还有多少钱', '充值'),
        'source': 'api_stats.balance',
        'label': '账户余额（实时接口值，不是记忆）',
        'fmt': '_fmt_balance',
    },
    {
        'key': 'todo',
        'keywords': ('待办', '要做', '没做完', 'todo'),
        'source': 'todos',
        'label': '待办清单',
        'fmt': '_fmt_todo',
    },
    {
        'key': 'affection',
        'keywords': ('好感', '关系', '亲密度', '认识多久'),
        'source': 'affection',
        'label': '好感度与关系阶段',
        'fmt': '_fmt_affection',
    },
    {
        'key': 'memory_count',
        'keywords': ('记得', '记忆', '回忆'),
        'source': 'memories',
        'label': '事件记忆条数（内容用 search 查，别背数字）',
        'fmt': '_fmt_memory_count',
    },
]


# ---------------- 现算函数 ----------------
# 约定：入参是宿主对象；取不到就返回 ''（不编数字、不抛异常）

def _fmt_spend(host):
    try:
        t = host.api_stats.today
        tot = host.api_stats.total
        return '今天 ¥%.4f / %d 次；累计 ¥%.4f / %d 次' % (
            float(t.get('cost') or 0), int(t.get('count') or 0),
            float(tot.get('cost') or 0), int(tot.get('count') or 0))
    except Exception as _exc:
        _log.warning('L3 现算花费失败：%s', _exc)
        return ''


def _fmt_balance(host):
    # 复用 ApiStats.balance_text()：它已处理「无缓存 / 接口不通 → 返回空串，绝不编数字」。
    # 以复用现有为荣，不自己拼数字。
    try:
        txt = host.api_stats.balance_text(with_detail=True)
        if not txt:
            return ''
        age = host.api_stats.balance_updated_text()
        return '%s（%s）' % (txt, age) if age else txt
    except Exception as _exc:
        _log.warning('L3 现算余额失败：%s', _exc)
        return ''


def _fmt_todo(host):
    try:
        items = host.todos or []
        left = [x for x in items if not x.get('done')]
        if not left:
            return '没有未完成项'
        names = '、'.join(str(x.get('text') or x.get('title') or '?')[:12] for x in left[:3])
        more = ' 等 %d 项' % len(left) if len(left) > 3 else ''
        return '%d 项未完成：%s%s' % (len(left), names, more)
    except Exception as _exc:
        _log.warning('L3 现算待办失败：%s', _exc)
        return ''


def _fmt_affection(host):
    try:
        s = host.affection.snapshot(getattr(host, 'current', 'flash'))
        return '%s · 好感 %s' % (s.get('stage'), s.get('affection'))
    except Exception as _exc:
        _log.warning('L3 现算好感失败：%s', _exc)
        return ''


def _fmt_memory_count(host):
    try:
        n = len(host.memories.all(getattr(host, 'current', 'flash')))
        return '事件记忆 %d 条' % n
    except Exception as _exc:
        _log.warning('L3 现算记忆条数失败：%s', _exc)
        return ''


_FMT = {
    '_fmt_spend': _fmt_spend,
    '_fmt_balance': _fmt_balance,
    '_fmt_todo': _fmt_todo,
    '_fmt_affection': _fmt_affection,
    '_fmt_memory_count': _fmt_memory_count,
}


# ---------------- 对外 ----------------

def _source_exists(host, source):
    """逐段 getattr 判断数据源是否存在。

    这是「路标不许指向不存在的地方」的唯一判据；
    test_every_index_source_exists_on_host 用的是同一套逻辑。
    """
    obj = host
    for part in source.split('.'):
        # ⚠ 不能只靠 hasattr：hasattr 只吞 AttributeError，
        #   数据源的 property 内部抛 RuntimeError（接口挂了/配置坏了）会穿透上来，
        #   把整块 L3 打掉。每段都显式 try。
        try:
            if not hasattr(obj, part):
                return False
            obj = getattr(obj, part)
        except Exception as _exc:
            _log.warning('L3 探测数据源 %s 失败：%s', source, _exc)
            return False
    return True


def match(query):
    """按关键词子串匹配索引项。未命中返回 []（宁可不给，不瞎塞）"""
    if not query or not isinstance(query, str):
        return []
    q = query.lower()
    hit = []
    for item in INDEX:
        if any(kw.lower() in q for kw in item['keywords']):
            hit.append(item)
    return hit


def build_l3_block(host, query, budget=BLOCK_BUDGET):
    """生成「去哪查」提示段。没命中或全取不到值时返回空字符串。

    Args:
        host: 桌宠对象（只读它的属性）
        query: 用户这句话
        budget: 字数上限

    Returns:
        str，形如：
            【这些事别背，去查（L3 索引）】
            · 今天/累计的 API 花费：去 api_stats 查 → 今天 ¥0.0737 / 12 次
    """
    items = match(query)
    if not items:
        return ''

    lines = []
    for item in items:
        fn = _FMT.get(item.get('fmt') or '')
        val = ''
        if fn is not None:
            try:
                val = fn(host) or ''
            except Exception as _exc:
                # 现算函数内部已 try，这里再兜一层：坏一个不影响其他项
                _log.warning('L3 条目 %s 现算失败：%s', item.get('key'), _exc)
                val = ''
        where = item['source'].split('.')[0]
        # 先确认这个数据源真的存在再给路标：
        # 宿主根本没有该属性时还写「去 X 查」，等于指错路 —— 比不给更糟。
        if not _source_exists(host, item['source']):
            continue
        if val:
            lines.append('· %s：去 %s 查 → %s' % (item['label'], where, val))
        else:
            # 属性在、只是这次没取到值 ⇒ 路标仍有用：模型可以再让工具现查
            lines.append('· %s：去 %s 查（现在没取到，需要时让工具现查）' % (item['label'], where))

    if not lines:
        return ''

    body = '\n'.join(lines)
    head = '【这些事别凭记忆答，去查（L3 索引）】'
    txt = head + '\n' + body
    if len(txt) > budget:
        # 截断到条目边界，不切半句
        cut = txt[:budget]
        cut = cut[:cut.rfind('\n')] if '\n' in cut else cut
        txt = cut
    return txt
