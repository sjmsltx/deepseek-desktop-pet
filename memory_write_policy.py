# -*- coding: utf-8 -*-
"""memory_write_policy.py — 记忆写入边界：这条该进 facts 还是 events
====================================================================
2026-11-06 建。起因：Owner 指出「库里混了『脱离语境无意义』的条目，
任何话题都能匹配到点什么 —— 调阈值治不好这个」。

本模块只做一件事：**在写入前判定这条记忆该落在哪一层**，把不该进 facts 的
挡在 facts 外面。检索侧（BM25 / 向量 / 闸门）概不负责分类错误。

## 为什么边界必须写在「写入」而不是「检索」

facts 是**常驻可检索池**（L0 人格卡 + 按问题检索），events 是**时间线**（按角色、
按时间、最近 N 条）。同一条内容放在两层，代价完全不同：

    「用户在 Python 基础关卡中 5 关全部满分」放 facts
        ⇒ 此后每一个带「Python / 练习 / 关卡」的提问都会把它抬出来，
          哪怕用户只是在问 list 和 tuple 的区别
    放 events
        ⇒ 它作为「某个时间点发生的事」存在，随时间和条数自然淡出

所以一条**一次性的事**写进 facts，等于给 facts 永久加了一个话题命中点。
库越大，这种永久命中点越多 —— 这正是「库大了以后什么都匹配得到」的机制。

## 判据来源（全部来自真实库，不是拍脑袋）

对真实库 21 条 active facts 逐条过（`记忆线-20261106/audit_facts.py`），
人工确认下列类别确实不该在 facts 里：

| 库内实例 | 问题 | 本模块判定 |
|---|---|---|
| 「用户在 Python 基础关卡中 5 关全部满分（100/100…），重视练习成绩」 | 一次性的里程碑 | event / milestone |
| 「用户在做重庆区县地理数据的分析…涉及 GIS 相关任务」 | 进行中的具体任务 | event |
| 「用户正在学习用 matplotlib…练习绘制抛体运动轨迹点」 | 一次练习会话 | event |
| 「…属于『规则会翻十倍』的重度用户类型，**适合分层治理而非单文件方案**」 | 混进了助手的主张 | drop / advice |
| 「…**实测视觉识别功能效果好**，习惯用『越具体越准』的提问方式」 | 混进了对系统的评测 | event / system_eval |

⚠ **近重复合并没有做**，而且是有依据的不做。实测（`dup_jaccard_exp.py`）：

    真重复  日语梗 ↔ 日语谐音梗                 原始 Jaccard 0.321 / 去泛用词 0.208
    假配对  日语梗 ↔ 主流 AI 模型（都提"开玩笑"）  原始 Jaccard 0.212 / 去泛用词 0.107
    假配对  我的名字 ↔ 姐姐的名字                 原始 Jaccard 0.176 / 去泛用词 0.188

去泛用词后真假间隔从 0.109 缩到 0.020，**判据分不开**。
按「以连续硬猜为耻」，这里不做词面阈值合并；
交给抽取提示词里的 `update_facts`（模型看着已有记忆判断），并在下轮复核。

## 设计约束

- **纯函数**：不读写文件、不抛异常、不依赖 Qt。可独立单测。
- **不静默**：每次判定都返回 reason 码，调用方必须落痕（写台账/日志）。
- **判据可解释**：全部是词表 + 长度/结构判据，不用模型、不用概率。
"""
import re

#: 判定目标
TARGET_FACT = 'fact'
TARGET_EVENT = 'event'
TARGET_DROP = 'drop'

#: reason 码 → 人话（台账/日志里直接可读）
REASON_TEXT = {
    'empty': '空或过短',
    'advice': '混入助手主张（建议/适合/优于…）',
    'system_eval': '混入对系统的评测（实测/效果好…）',
    'milestone': '一次性里程碑（满分/通关/第N次…）',
    'session': '进行中的具体任务（正在/在做…）',
    'contextless': '脱离语境无法读懂（指代无先行词且过短）',
    'fact': '稳定属性/偏好/身份',
}

# ---- 词表：全部来自真实库与抽取提示词的观察，逐条注明用法 ----

#: 助手主张：出现即说明这句话是「我给用户的建议」，不是「用户本身的事实」。
#: 「适合…而非…」这条来自库内实例「适合分层治理而非单文件方案」。
_ADVICE = ('建议', '应该', '应当', '适合', '而非', '优于', '推荐使用',
           '最好用', '不如', '更合理', '效果更好', '值得', '需要改')

#: 对系统的评测：描述的是产品表现，不是用户属性。
#: 「实测」「效果好」来自库内实例「实测视觉识别功能效果好」。
_SYS_EVAL = ('实测', '效果好', '效果不错', '识别效果', '性能', '功能正常',
             '可用', '响应速度', '没报错', '能正常')

#: 稳定习惯词：命中它说明这句话在描述「一直如此」，不是一次性的评测/事件。
#: ⚠ 2026-11-06 dry-run 实测：库内「用户经常发教材插图…实测视觉识别功能效果好…
#:   习惯用『越具体越准』」同时命中「实测」与「经常/习惯」—— 若让评测词无条件优先，
#:   会把一条真实习惯判成 events（漏拓 recall）。所以习惯优先。
_HABIT = ('经常', '常常', '总是', '习惯', '喜欢', '爱吃', '爱', '每天', '每周',
          '平时', '一向', '历来')

#: 一次性里程碑：这条一旦进 facts 会永久成为命中点。
#: 「满分」「通关」来自库内实例；时间词来自抽取文本的常见开头。
#: ⚠ 不放裸「记录」——「有做题耗时与评测次数记录」只是描述，不算里程碑；
#:   库里那条已被「满分/全部通过」命中，不需要它（dry-run 实测）。
_MILESTONE = ('今天', '昨天', '刚才', '刚刚', '这次', '那次', '上次',
              '第一次', '满分', '通关', '全部通过', '已完成', '完成了',
              '拿到了', '得了', '破纪录', '新纪录')

#: 进行中的具体任务：状态会过期，属于时间线而不是属性。
#: 「正在学习用 matplotlib…练习绘制…」是库内实例。
#: ⚠ **不收裸「在学」**：dry-run 实测「用户在学习/练习 Python」（长期技能）会被误判，
#:   而那条正是 h05/h10「我在练哪门编程」的唯一答案源。进行时靠「正在」就够。
_SESSION = ('正在', '在做', '在写', '在弄', '这几天', '最近在',
            '目前在', '本周在', '这周在')

#: 「第 N 次」形式（正则，词表覆盖不到任意数字）
_ORDINAL_RE = re.compile(r'第\s*[0-9一二三四五六七八九十]+\s*[次轮关遍]')

#: 指代词
_PRONOUN = ('它', '他', '她', '这个', '那个', '这些', '那些', '该', '此')

#: 具体实体：专名/数字/英文/书名号 —— 有它说明这句话能脱离语境站得住
_ENTITY_RE = re.compile(
    r'[0-9]'
    r'|[A-Za-z]{2,}'
    r'|《[^》]+》'
    # 专名后缀：行政区划/机构/产品类别 —— 都是机械可判的
    r'|[\u4e00-\u9fff]{2,}(?:大学|学院|中学|公司|系统|平台|软件|语言|课程|专业|城市|区|县|省|市|镇|路|街)'
)

#: 过短阈值：低于这个长度又没有实体，基本是半句话
_MIN_SELF_CONTAINED = 12


def _hit(text, words):
    """返回命中的词列表（保持词表顺序，便于台账复现）"""
    return [w for w in words if w in text]


def has_entity(text):
    """这句话里有没有能独立指认的东西（数字/英文/书名号/专有名词后缀）"""
    return bool(_ENTITY_RE.search(text or ''))


def classify(text, existing_facts=None):
    """判定一条待写入记忆该去哪一层。

    Args:
        text: 抽取出来的内容（facts 的 content / events 的 title+detail）
        existing_facts: 现有 facts（用于识别「已存在」），可为 None

    Returns:
        dict:
          target   'fact' | 'event' | 'drop'
          reason   REASON_TEXT 的键
          text     去空白后的原文
          title    目标为 event 时的标题（取首句，≤28 字）
          hits     命中的词（可复现判据，写台账用）
          existing 已存在的同内容 fact（dict）或 None

    判定顺序即优先级：先判「不该进 facts」的强信号，再落到 fact。
    """
    raw = (text or '').strip()
    out = {'target': TARGET_FACT, 'reason': 'fact', 'text': raw,
           'title': '', 'hits': [], 'existing': None, 'trimmed': []}

    if len(raw) < 4:
        out.update(target=TARGET_DROP, reason='empty')
        return out

    # ① 助手主张：不是"关于用户"，是"关于我给的建议"。
    #   先尝试**剥掉主张子句**（保留同一句里真正的用户属性）；剥完不到 6 字才算整条主张。
    hits = _hit(raw, _ADVICE)
    if hits:
        kept, dropped = _strip_advice(raw)
        if len(kept) >= 6 and not _hit(kept, _ADVICE):
            out['text'] = kept
            out['trimmed'] = dropped
            raw = kept
        else:
            out.update(target=TARGET_DROP, reason='advice', hits=hits)
            return out

    # ② 对系统的评测：信息有用，但它是"某次观察"，不是用户属性。
    #   例外：同时命中稳定习惯词 ⇒ 这条在描述「一直如此」，留在 facts
    #   （dry-run 实测「经常发截图…实测效果好…习惯用…」不该被拓去 events）。
    hits = _hit(raw, _SYS_EVAL)
    if hits and not _hit(raw, _HABIT):
        out.update(target=TARGET_EVENT, reason='system_eval', hits=hits,
                   title=_title(raw))
        return out

    # ③ 一次性里程碑
    hits = _hit(raw, _MILESTONE)
    m = _ORDINAL_RE.search(raw)
    if m:
        hits = hits + [m.group(0)]
    if hits:
        out.update(target=TARGET_EVENT, reason='milestone', hits=hits,
                   title=_title(raw))
        return out

    # ④ 进行中的具体任务（状态会过期）
    hits = _hit(raw, _SESSION)
    if hits:
        out.update(target=TARGET_EVENT, reason='session', hits=hits,
                   title=_title(raw))
        return out

    # ⑤ 脱离语境读不懂：短 + 指代 + 无实体
    if (len(raw) < _MIN_SELF_CONTAINED and _hit(raw, _PRONOUN)
            and not has_entity(raw)):
        out.update(target=TARGET_DROP, reason='contextless',
                   hits=_hit(raw, _PRONOUN))
        return out

    # ⑥ 其余：稳定属性 → facts
    for f in (existing_facts or []):
        if f.get('status') != 'active':
            continue
        c = (f.get('content') or '').strip()
        if not c:
            continue
        # 与 memory_store.remember_fact 同一口径（相等/包含），避免两处判断不一致
        if c == raw or raw in c or c in raw:
            out['existing'] = f
            break
    return out


def _strip_advice(text):
    """把句子里的「助手主张」子句剥掉，留下关于用户的部分。

    为什么不是整条丢弃：库内实例
      「用户是 AI Agent 治理体系的重度用户：…，属于…类型，**适合分层治理而非单文件方案**」
    后半句是助手的主张，前半句是真的用户属性。整条丢 = 把真记忆也删了。

    切分符：，；;、。（保留句号内部不切，避免把「例如」切碎）
    返回 (剩余文本, 被剥掉的子句列表)。
    """
    parts = re.split(r'[，；;、]', text or '')
    keep, dropped = [], []
    for p in parts:
        if _hit(p, _ADVICE):
            dropped.append(p.strip())
        elif p.strip():
            keep.append(p.strip())
    return '，'.join(keep), dropped


def _title(text, limit=28):
    """event 标题：取第一个分句，去掉换行，超长截断加省略号"""
    s = re.split(r'[\n。；;]', (text or '').strip())[0].strip()
    if len(s) > limit:
        s = s[:limit] + '…'
    return s or (text or '')[:limit]


def event_payload(decision):
    """把 event 判定转成 memory_events.add 需要的字段

    返回 {'title','detail','type'}：
      · type 用 milestone（events 允许的四种之一）还是 event
      · detail 保留全文，便于「点开看当时到底发生了什么」
    """
    text = decision.get('text') or ''
    typ = 'milestone' if decision.get('reason') == 'milestone' else 'event'
    return {'title': decision.get('title') or _title(text),
            'detail': text, 'type': typ}


def bump_evidence(fact):
    """已存在时累加证据计数（原地改，返回新值）。

    为什么需要它：抽取出来的是「某一次观察」还是「反复成立的属性」，
    目前两者在库里长得一样。记下 evidence 才有后续判据可用
    （本模块**不**用它做硬判定，避免引入未实测的排序变化）。
    """
    try:
        cur = int(fact.get('evidence', 1) or 1)
    except (TypeError, ValueError):
        cur = 1
    fact['evidence'] = cur + 1
    return fact['evidence']
