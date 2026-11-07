# -*- coding: utf-8 -*-
"""facts 权重与淘汰的纯逻辑（2026-11-04）

## 为什么单独一个文件

`memory_engine.py` 已 460 行且是检索核心，把淘汰塞进去会让「检索」和「存储治理」
搅在一起。这里只放纯函数（不改全局状态、不落盘）、台账、以及可单测的判定。

## 背景：facts 一直是裸增长

实测（2026-11-04）：`memory.json` 的写入路径就是 `self.memory_facts.append(item)`，
**没有任何容量判断**。而 `memories.json`（事件层）有 `MAX_MEMORIES=200` 滚动淘汰。
⇒ 事实库用几年会无限长，且「忘了什么」无从追溯。

## 三条设计决策（都有理由，不是默认值）

### ① 上限限制的是「active 条数」，不是数组长度
淘汰用 `status='evicted'` 标记，**不物理删除**。
理由：「原件保留」是本项目既有纪律；且 JSON 体积不痛（2 万条约 5MB，
检索实测 5.42ms），物理删除只省磁盘却丢掉可恢复性。

### ② base 权重用 importance 兜底
facts 存量 **没有 weight 字段**（只有 importance 1~5）。
若直接复用 `effective_weight()`，所有人的 base 都是 `WEIGHT_NEW=0.55`
⇒ 淘汰退化成「换个名字的按时间淘汰」，白做。
`importance` 是用户/抽取器显式标注的重要度，归一化后正是「重要的事留下」的基准。

### ③ 身份条目与 pinned 永不淘汰
复用 `memory_events.is_identity_entry()`（判据同源，不另造）：
「我的名字叫小蓝」这类每轮必在的条目，不能因为重要性分数低就被挤掉。

## 衰减函数直接复用 memory_events

`decayed_weight` / `entry_age_days` 已经过测试（`test_memory_weight.py` 的
`test_decay_lowers_weight_with_age` 等锁着幂律参数）。这里不重新实现 —— 
两套衰减公式迟早会对不上。
"""
import hashlib
import json
import logging
import os
import time

import memory_events as _mev

_log = logging.getLogger('pet.fact_evict')

#: 事实库 active 上限。
#:
#: 取值依据（2026-11-04 精扫，`scripts/pick_facts_max.py` + 三种子复核）：
#:   以真实库 21 条为基底、按真实风格补无关记忆到 N 条，对 45 条真实对话算注入率：
#:
#:     库条数   200   240   260   280   300   320   360   400
#:     中位     42%   44%   47%   47%   47%   49%   49%   49%
#:     三种子极差 ±3~6 个百分点
#:
#:   ⇒ **400 条时中位 49%，刚好压在 Owner 定的 50% 目标线上**。
#:   ⚠ 口径限定：以上是**纯 BM25 + coverage 闸门**（产品现况）的数字。
#:       补的全是无关记忆 = 最坏情况（只增竞争、不增帮助），真实增长会更低。
#:
#: ⚠ **2026-11-06 向量检索已接进产品（默认并集），上面那条「接向量后上限约只能取 40 条」
#:   已作废** —— 它是按**固定余弦 0.51** 估的，而实际接的是**自适应 z 阈值**（按本库相似度
#:   分布定标，库越大门槛越高）。两者不是一回事，不能拿旧估计套新方案。
#:
#:   向量口径（cos≥0.51 固定）当初的精扫数字，留作对照：
#:       21 条 36%   /  50 条 **60%**  /  80 条 67%  /  171 条 73%  /  400 条 76%
#:
#:   接自适应阈值后的实测（6 条不该注入的问句）：
#:       库 18/21/50/100 → 并集 0~2 条注入；库 200/400 → 并集 1 条，**纯向量 0 条**
#:     ⇒ **没有观察到「向量在多带误注入」**，与自适应阈值的设计预期一致。
#:
#: ⛔ 但**这不等于 400 已被验证**：样本只有 6 条负样本、补库是合成的，按纪律只能算
#:   「没观察到恶化」。⇒ 400 现在的身份是**待观察值**，不是结论。
#:   要把它变成结论，需要：真实分布补库 + 负样本 ≥42 条 + 注入率按 45 条真实对话算。
#:
#: 历史修正留痕：
#:   · 原注释写「400 远低于 171 这个恶化规模」——400 > 171，方向写反（早前复核指出）
#:   · 又写「约 10 倍余量」——实际 21→400 是 19 倍
#:   · 随后我改成「171 条时注入率 76%，400 一定会越线」——**这句也是错的**：
#:     76% 是**向量**口径的数字，产品用的是 BM25，BM25 在 400 条时中位 49%。
#:     口径混用比方向写反更隐蔽，因为数字本身是真的，只是不是这个场景的。
FACTS_MAX = 400

#: 每次被检索命中时的权重增量（与 events 的 WEIGHT_BUMP 同口径）
WEIGHT_BUMP = 0.06
WEIGHT_MAX = 1.0
WEIGHT_NEW = 0.55

#: 淘汰台账（与本模块同库文件同目录），追加式 JSONL
LEDGER_NAME = 'memory_evicted_facts.jsonl'
LEDGER_MAX_LINES = 5000


def fact_base_weight(f):
    """条目的基准权重（不含时间衰减）。

    优先用显式 `weight`（未来有了 bump 就靠它累积）；
    否则用 `importance / 5` 归一化 —— 这是存量 44 条唯一的「重要度」来源。
    两者都没有时退回 WEIGHT_NEW。
    """
    try:
        w = f.get('weight')
        if w is not None:
            return max(0.0, min(WEIGHT_MAX, float(w)))
    except (TypeError, ValueError) as exc:
        # 不是数字 ⇒ 往下走 importance 兜底（落痕，不静默跳过）
        _log.debug('weight 字段不可用（%r），改用 importance：%s', f.get('weight'), exc)
    try:
        imp = float(f.get('importance', 3))
    except (TypeError, ValueError):
        imp = 3.0
    # importance 理论范围 1~5；越界的按边界夹住（老数据可能有 0 或 6）
    return max(0.0, min(WEIGHT_MAX, imp / 5.0))


def fact_effective_weight(f, now=None):
    """有效权重 = base × 时间衰减；身份条目不衰减。

    身份豁免为什么重要：实测「我的名字叫小蓝」created_at 从没更新过，
    年龄 89.8 天时衰减后只有 0.069 —— 与「爱吃桃片」同档，
    但它每轮都必须在（`test_identity_entry_never_decays` 锁着这条）。
    """
    base = fact_base_weight(f)
    if _mev.is_identity_entry(f):
        return base
    return _mev.decayed_weight(base, _mev.entry_age_days(f, now))


#: 「失效代价高」关键词：这类条目丢了有**实际后果**，与它被用得多不多无关。
#:
#: ⛔ 为什么需要这一维（桌宠 2026-11-04 在 chat_memory_flash 里指出，我实测坐实）：
#:   淘汰按「有效权重」排序，而权重 = importance/5 × 时间衰减 + 命中次数加成。
#:   「命中次数」与「丢了会怎样」**完全无关** ⇒ 低频关键记忆被优先淘汰。
#:
#:   实测（`verify_lowfreq.py`）：
#:     过敏(imp=3, 0 命中)   有效 0.108  → **被淘汰**
#:     周杰伦(imp=3, 20 命中) 有效 1.000
#:     过敏(imp=5, 0 命中)   有效 0.180  → **即使标最高重要度仍被淘汰**
#:
#:   桌宠原话：「'低频但关键'和'高频但无害'在同一个池子里打分竞争……
#:   后者的失效代价是前者的一百倍。」
#:
#: ⚠ 词表刻意取窄：只收「丢了有实际后果」的类别。
#:   「什么记忆永远不能丢」是产品策略，扩词表前须 Owner 确认。
_CRITICAL_PATTERNS = (
    '过敏', '忌口', '禁用', '不能吃', '不能碰', '不可吃',
    '用药', '服药', '病历', '病史', '身份证', '密码', '紧急联系',
    # 2026-11-07 补：服药/用药的常见同义说法。
    # ⚠ 这 4 个词**只用于淘汰保护**，不用于写入侧分层 —— 实测（评审-186 §三）
    #   若在 classify 里按它返 fact，会把「助手建议我服用维生素」「用户怕打针」
    #   「用户觉得医院输液太贵」这类 6 条钉死在 facts 里，永不淘汰。
    #   淘汰保护侧的误保护代价只是「一条 event 不被挤掉」，远小于分层错的代价。
    '服用', '输液', '打针', '过敏源',
)


def is_critical_text(text):
    """纯文本版 is_critical —— events 的 title/detail 没有 content 字段。
    2026-11-07 加：写入边界会把 critical 条目判进 events，而 events 层原本
    完全没有 critical 保护，进 events 就等于等着被 200 条滚动淘汰。
    """
    t = str(text or '')
    if not t:
        return False
    return any(p in t for p in _CRITICAL_PATTERNS)


def is_critical(f):
    """这条是否「失效代价高」（丢了后果严重，与使用频率无关）。"""
    text = (f.get('content') or '')
    if not text:
        return False
    return any(p in text for p in _CRITICAL_PATTERNS)


def protected(f):
    """这条是否受保护（不参与淘汰）。

    三种情况：pinned / 身份条目 / 失效代价高。
    前两者原有；第三者是 2026-11-05 补的（见 _CRITICAL_PATTERNS 注释）。
    """
    if f.get('pinned'):
        return True
    if _mev.is_identity_entry(f):
        return True
    return is_critical(f)


def bump_fact(f, now=None):
    """被检索命中：weight 上升、access_count 累加、last_access 更新。

    只对**真正返回给调用方**的条目调用（不撒胡椒面）。
    返回是否真的改了（pinned 的也照常 bump —— 它只是不被淘汰）。
    """
    if not isinstance(f, dict):
        return False
    changed = False
    # ⛔ 2026-11-04 修（评审-178 §一 指出的真缺陷）：
    #   原来这里写 `float(f.get('weight', WEIGHT_NEW))` —— 存量条目**都没有 weight 字段**
    #   ⇒ 任何条目被命中一次后 weight 都变成 0.55+0.06=0.61，**与它的 importance 无关**。
    #   实测后果（全部已复现）：
    #     · imp=5 从 1.00 掉到 0.61（降 39%）、imp=4 从 0.80 掉到 0.61（降 19%）
    #     · imp=5 与 imp=1 bump 后 weight 完全相同 ⇒ importance 区分度消失
    #     · 一年后「命中过一次」反而低于「从没命中」（0.0996 < 0.1462）⇒ **命中即降权**
    #     · cap=1 时淘汰了 imp=5 那条（只因它更旧）⇒ 与「重要的留下」完全相反
    #   为什么 31 项测试没抓到：`test_bump_accumulates` 用了 imp=3，
    #   而 imp=3 恰好是唯一「bump 后 base 仍上升」的档位（0.60→0.61）。
    #   现在统一走 fact_base_weight：有 weight 用它，没有则 importance/5。
    base = fact_base_weight(f)
    new_w = min(WEIGHT_MAX, base + WEIGHT_BUMP)
    if new_w != f.get('weight'):
        f['weight'] = round(new_w, 4)
        changed = True
    try:
        f['access_count'] = int(f.get('access_count') or 0) + 1
        changed = True
    except (TypeError, ValueError):
        f['access_count'] = 1
        changed = True
    f['last_access'] = time.strftime('%Y-%m-%dT%H:%M:%S') if now is None else now
    return changed


def _content_hash(text):
    return hashlib.sha1((text or '').strip().encode('utf-8')).hexdigest()[:16]


def plan_eviction(facts, cap=None, now=None):
    """算出该淘汰谁，**不改动入参**。

    返回 (evicted_list, kept_active_count)。
    规则：
      1. 只考虑 status == 'active' 的（superseded/evicted 本来就不占名额）
      2. 受保护条目（pinned / 身份）**不参与**排序，直接占名额
      3. 其余按 (有效权重 升序, 时间 升序) 淘汰 —— 权重相同就先走最旧的
      4. 若保护条目已超 cap，不再淘汰更多（宁可短暂超容，也不动核心事实）
    """
    cap = FACTS_MAX if cap is None else int(cap)
    active = [f for f in facts if f.get('status', 'active') == 'active']
    if len(active) <= cap:
        return [], len(active)
    guared = [f for f in active if protected(f)]
    normal = [f for f in active if not protected(f)]
    room = cap - len(guared)
    if room < 0:
        # 保护条目自己就超了上限：不动它们，也不额外淘汰（只记一笔）
        return [], len(active)
    if len(normal) <= room:
        return [], len(active)

    def key(f):
        return (fact_effective_weight(f, now), str(f.get('time') or
                                                     f.get('created_at') or ''))

    ordered = sorted(normal, key=key)          # 低权重、旧的在前 = 先淘汰
    n_evict = len(normal) - room
    return ordered[:n_evict], cap


def apply_eviction(facts, evicted, reason='overflow', now=None):
    """把 plan 的结果标成 status='evicted'（**不物理删除**）。返回被标记的条目。"""
    ids = {id(f) for f in evicted}
    stamp = time.strftime('%Y-%m-%dT%H:%M:%S') if now is None else now
    done = []
    for f in facts:
        if id(f) in ids:
            f['status'] = 'evicted'
            f['evicted_at'] = stamp
            f['evicted_reason'] = reason
            done.append(f)
    return done


def ledger_rows(evicted, kept, reason='overflow', now=None, active_before=None):
    """台账行（字段与 events 台账对齐，便于同一套脚本对账）。

    `active_before` = 淘汰**前**的 active 条数。
    为什么必须记：容量预算要用「库在多大时开始需要淘汰」，
    只记淘汰后的 `kept` 回答不了这个问题。
    """
    stamp = time.strftime('%Y-%m-%dT%H:%M:%S') if now is None else now
    rows = []
    for f in evicted:
        rows.append({
            'v': 2,
            't': stamp,
            'reason': reason,
            'kept': kept,
            'active_before': active_before,
            'id': f.get('id'),
            'title': (f.get('content') or '')[:120],
            'content_hash': _content_hash(f.get('content')),
            'weight': f.get('weight'),
            'importance': f.get('importance'),
            'access_count': f.get('access_count'),
            'status': f.get('status'),
        })
    return rows


def append_ledger(path, rows):
    """追加写台账。**先记账、再改库** —— 顺序不许反。

    写失败不阻断淘汰（否则库会无限长），但必须落痕。
    """
    if not rows:
        return False
    try:
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        _rotate_if_needed(path)
        with open(path, 'a', encoding='utf-8', newline='\n') as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + '\n')
        return True
    except OSError as exc:
        _log.warning('事实淘汰台账写入失败 path=%s: %s', path, exc)
        return False


def _rotate_if_needed(path):
    """超 LEDGER_MAX_LINES 就把现文件挪成 .1（只留一代，防台账自己无限长）。"""
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding='utf-8', errors='ignore') as fh:
            n = sum(1 for _ in fh)
    except OSError:
        return
    if n < LEDGER_MAX_LINES:
        return
    try:
        os.replace(path, path + '.1')
    except OSError as exc:
        _log.warning('事实淘汰台账轮转失败 path=%s: %s', path, exc)


#: 记忆密度阈值：平均「每件事有几条记忆」达到此值，多维聚合才开始有收益。
#:
#: 依据（2026-11-04 实测，`probe_structure_premise.py`）：
#:   · 真实库 21 条 → 21 个实体，密度 1.00，100% 自成一件事
#:     ⇒ 聚合等于原样输出（2-gram 留存 1.00），没有压缩
#:     ⚠ 2026-11-04 原报「21 条 / 18 实体 / 1.17 / 83%」**是错的**：那 21 条里有 3 组
#:       共用同一个 id（撞号缺陷，2026-11-05 已修），**两条内容各不相同**，却被当成
#:       同一实体并了组。id 修好后是 21 条 / 21 实体。
#:     ⚠ 另一个坑：一度写成「18 条**唯一**记忆」—— 那是把 **id 数量当成了记忆数量**
#:       （3 条不同记忆因共用 id 被误当重复项扔掉）。密度 1.00 两版都成立，条数不是。
#:       （评审-181 §四 更正）
#:       详见 tools/eval/experiment/勘误-真实库密度-20261105.md
#:   · 合成库 1411 条 → 239 实体，密度 5.9（**人为造的高密度**）
#:     ⇒ 聚合能省上下文，但那是造出来的场景
#: 所以：密度低时不要做多维聚合；等真实使用把密度推上去再谈。
DENSITY_STRUCTURE_MIN = 2.0
#: 归一实体键时要剥掉的标点（含全角）。用 chr() 拼装是为了避免源码里的引号冲突
_PUNCT = (chr(32), chr(0x3000), chr(0xFF0C), chr(0x3002), chr(0x3001), chr(0xFF1B),
          chr(0xFF1A), chr(0xFF01), chr(0xFF1F), chr(0x2C), chr(0x2E), chr(0x3B),
          chr(0x3A), chr(0x21), chr(0x3F), chr(0xFF08), chr(0xFF09), chr(0x28),
          chr(0x29), chr(0x300C), chr(0x300D), chr(0x22), chr(0x27), chr(0xB7))


def memory_density(facts):
    """记忆密度 = active 条数 / 实体数（实体键同 memory_embed 的口径：object 优先）。

    为什么单独一个指标：多维节点（一个实体挂多个面向）只有在**同一件事有多条记忆**
    时才有价值。密度 1.00 意味着**每一条都自成一件事**，聚合是白做。
    """
    active = [f for f in (facts or []) if f.get('status', 'active') == 'active']
    if not active:
        return 0.0, 0, 0
    keys = set()
    unlabeled = 0
    for f in active:
        obj = (f.get('object') or '').strip().lower()
        top = (f.get('topic') or '').strip().lower()
        for ch in _PUNCT:
            obj = obj.replace(ch, '')
            top = top.replace(ch, '')
        if not obj and not top:
            # 没有标签的条目不参与实体计数 —— 否则它们全落到空键上，
            # 密度会被算成「条数/1」，得出「密度很高、值得结构化」的假结论。
            # （2026-11-04 实测：真实库 21 条全无标签时算出 density=21.0）
            unlabeled += 1
            keys.add('U:%d' % unlabeled)
            continue
        keys.add(('O:' + obj) if obj else ('T:' + top))
    return round(len(active) / float(len(keys)), 2), len(active), len(keys)


def capacity_status(facts, cap=None):
    """当前容量状态（观测用，不改任何行为）。

    返回 {'active', 'cap', 'free', 'ratio', 'need_evict', 'density', 'entities',
          'structure_worth'}

    `density` = 平均每件事几条记忆；`structure_worth` = 是否值得做多维聚合。
    两者都只是**观测**，不影响淘汰与注入。
    """
    cap = FACTS_MAX if cap is None else int(cap)
    active = len([f for f in (facts or []) if f.get('status', 'active') == 'active'])
    free = cap - active
    dens, n_a, n_e = memory_density(facts)
    labeled = sum(1 for f in (facts or [])
                  if f.get('status', 'active') == 'active'
                  and ((f.get('object') or '').strip() or (f.get('topic') or '').strip()))
    # 标签覆盖率不足时，密度不可判定（不能拿「全部落空键」算出的数下结论）
    decidable = labeled >= 0.8 * max(active, 1)
    return {
        'active': active,
        'cap': cap,
        'free': free,
        'ratio': round(active / float(cap), 4) if cap else 0.0,
        'need_evict': free < 0,
        'labeled': labeled,
        'density': dens if decidable else None,
        'entities': n_e if decidable else None,
        'structure_worth': (dens >= DENSITY_STRUCTURE_MIN) if decidable else None,
        'density_note': ('' if decidable else
                         '标签覆盖 %d/%d 不足 80%%，密度不可判定'
                         % (labeled, active)),
    }


def evict_facts(facts, cap=None, now=None, ledger_path=None, reason='overflow'):
    """一站式：算 → 记账 → 标记。返回 (evicted_count, kept_active)。

    调用方负责随后落盘（本函数不写 memory.json）。
    """
    active_before = len([f for f in (facts or [])
                         if f.get('status', 'active') == 'active'])
    evicted, kept = plan_eviction(facts, cap=cap, now=now)
    if not evicted:
        return 0, kept
    if ledger_path:
        rows = ledger_rows(evicted, kept, reason=reason, now=now,
                           active_before=active_before)
        append_ledger(ledger_path, rows)
    done = apply_eviction(facts, evicted, reason=reason, now=now)
    return len(done), kept
