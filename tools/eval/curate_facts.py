# -*- coding: utf-8 -*-
"""存量清理：把伪影 facts 降级到 events（2026-11-08）

## 为什么做

库内 18 条 active facts 里，「桌宠/模型」话题占 12 条 = 67%，
而真实对话记录里同话题只占 33%（52 条实测）。偏斜约 2 倍。

原因不是阈值，是**抽取把「我们一起在做的事」记成了「用户是什么样的人」**。
那类条目进了 facts 就成了常驻命中点，此后每个相关提问都会被抬出来。

## 判据（三条，先定后用）

1. **归属**：这句话描述的是「用户这个人的稳定属性」，还是「我们这段时间在做什么」？
   后者不进 facts。
2. **成分**：句子里有没有「助手主张 / 对系统的评测 / 互动方式」这类不属于用户属性的成分？
   有则剥掉该成分，剥完剩不到 6 字则整条降级。
3. **可回滚**：任何降级都保留原文（status 改 `moved_to_events` + 写 `moved_reason`），
   绝不物理删除。

⚠ 「这条该不该留」最终是人的判断，不是脚本判断。本脚本只把判定与依据摊开，
   `--dry` 默认输出，确认后才 `--apply`。

## ⛔ 2026-11-08：试跑过，但**已回滚，不执行**

试跑结果（`--apply` 已跑、已按快照回滚）：

```
清理前 18 条：A 类 4 条 = 22%
清理后 15 条：A 类 0 条 = 0%
```

伪影清干净了，但**召回掉了**：

```
留出集 H_R@3：10/12 → 8/12
掉的是 h06「我放松的时候打什么游戏」与 h08「我读大几了来着」
```

关键证据（这两条的答案条目都还在库里，一条都没删）：

```
h06  top1 就是「战争雷霆」那条，余弦 0.517→0.516（几乎没变），z 2.62→2.38（门槛 2.50）
h08  top1 就是「大二学生」那条，余弦 0.584→0.586，z 2.66→2.47（门槛 2.50）
```

⇒ **不是清理判错了，是 z 判据在这个库规模上处在临界点**：答案排第一、余弦 0.58，
   却因为「不够离群」被判不注入。库一动（删几条），一批用例随机翻面。

**回滚理由**：基线规矩是「只许上调，不许为了变绿往下改」。
   这次清理让召回真实下降 2 条，而根因（z 临界）没解决 —— 此时下调基线等于掩盖问题。
   **所以先修 z，再回来跑这个脚本。**

复现：`python tools/eval/curate_facts.py`（dry-run，判定与依据全部打印）。
清理后的库快照留在 `logs/memory.json.snapshot-curated-*`，需要对比可直接用。

## 用法

    python tools/eval/curate_facts.py            # 只打印判定（默认，安全）
    python tools/eval/curate_facts.py --apply    # 真改（先自动备份到 logs/）

## 产物落哪

备份与报告都落 `logs/`（.gitignore 已排除）—— 里面含真实记忆原文，不能进公开仓库。
"""
import argparse
import io
import json
import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MEMORY = os.path.join(ROOT, 'memory.json')
LOGS = os.path.join(ROOT, 'logs')

#: 逐条判定。结构：fact id → (动作, 理由码, 说明, 新内容或 None)
#:   动作：keep 原样保留 / trim 剥成分后保留 / move 降级到 events
#: ⚠ 这里写死 id 是有意的：存量清理是一次性动作，不做通用规则。
#:   通用规则已经在 memory_write_policy 里（管今后写入），两边职责不同。
DECISIONS = {
    # ── 保留：稳定的用户属性 ───────────────────────────────
    'f1785689490646': ('keep', '', '稳定偏好（爱吃桃片），含地域与口味细节', None),
    'f1785689595993': ('keep', '', '角色身份（桌宠自己的名字），产品必需', None),
    'f1785689596033': ('keep', '', '角色身份（姐姐的名字），产品必需', None),
    'f1787068645500': ('keep', '', '稳定兴趣（galgame / ACG）', None),
    'f1788143335570': ('keep', '', '身份（大二学生）', None),
    'f1789640343829': ('keep', '', '稳定习惯（解压时玩战争雷霆）', None),
    'f1789917675229': ('keep', '', '稳定兴趣（古典诗词），含具体作品', None),
    'f1791697950926': ('keep', '', '长期技能（学 Python），含具体知识点', None),
    'f1792904556928': ('keep', '', '稳定互动习惯（日语梗开玩笑）', None),
    'f1793010722059': ('keep', '', '稳定兴趣（背古文、考据作者）', None),

    # ── 剥成分后保留 ────────────────────────────────────
    'f1789824394827': ('trim', 'system_eval',
                       '前半是使用习惯（发截图让识别），后半「实测视觉识别功能效果好」是对系统的评测，'
                       '不属于用户属性', '用户经常发教材插图/截图让桌宠识别（如摄影测量原理图），'
                       '习惯用「越具体越准」的提问方式'),
    'f1785732107832': ('trim', 'project',
                       '「通过 AutoClaw 来强化桌宠」是我们在做的事；「称其为小龙虾」是用户的命名习惯，'
                       '属于用户属性；但剥时必须保住「桌面 AI 协作平台」这个描述词 —— '
                       '只留命名习惯会让「那个帮我管事的桌面平台」这类问句召回不到（实测过）',
                       '用户把 AutoClaw（桌面 AI 协作平台）称作「小龙虾」'),

    # ── 降级到 events ───────────────────────────────────
    'f1786722588650': ('move', 'advice',
                       '整条都是「我们在用分层体系做治理」＋末尾「适合分层治理而非单文件方案」是助手主张，'
                       '剥完剩不下用户属性', None),
    'f1793377316145': ('move', 'greeting',
                       '源自一句「感谢天气提醒，早上好，注意身体健康哟」—— 一句寒暄被记成了稳定人格',
                       None),
    'f1793453924641': ('move', 'project',
                       '源自我们讨论记忆机制的对话，把「我们在改的东西」记成了用户的关注点',
                       None),
}

#: 同 id 的两组（历史撞号），逐条按内容判，不按 id 判
#: 说明：库里存在同 id 不同内容的条目（f1793010722059 有两条、f1793377316145 有两条），
#:   是 11-05 修过的撞号缺陷留下的存量。本脚本按 (id, content) 判定，避免误伤。
CONTENT_DECISIONS = {
    '用户的古典文学兴趣不限于诗词，也涉及秦汉政论文（如《过秦论》）':
        ('keep', '', '与上一条「爱背古文」相关但角度不同（兴趣范围 vs 习惯），暂留', None),
    '用户了解市面上的主流 AI 模型（如 Claude、GPT），会拿它们和桌宠开玩笑、做比较':
        ('keep', '', '含真实信息（了解主流模型）；后半是互动方式，但不足以单独否认这条', None),
}


def decide(fact):
    """返回 (动作, 理由码, 说明, 新内容)"""
    content = str(fact.get('content') or '').strip()
    if content in CONTENT_DECISIONS:
        return CONTENT_DECISIONS[content]
    d = DECISIONS.get(str(fact.get('id')))
    if d is None:
        return ('keep', 'unreviewed', '本脚本没覆盖到这条，按保留处理（不擅自删）', None)
    return d


#: ── 指标口径（2026-11-08 修正，这条比脚本本身重要）─────────────────
#:
#: 我原先用「含桌宠/模型词」占比当偏斜指标：库内 67% vs 对话 33%。
#: 那个口径**不能用** —— 它把三类合理条目一起算进去了：
#:   · 角色身份（桌宠自己叫什么）—— 产品必需
#:   · 与桌宠的互动习惯（用日语梗逗它玩）—— 这是真实的用户属性
#:   · 只是句子里提到了「桌宠」二字
#:
#: 真正的偏斜是「把我们一起在做的事记成用户属性」，也就是 **A 类**。
#: 同口径实测（2026-11-08）：
#:   库内 A 类 4 / 18 = 22%
#:   真实对话里含项目/技术特征 2 / 52 = 4%（用户消息单独算 0 / 17 = 0%）
#: ⇒ 偏斜约 5 倍，且清理目标应该是「A 类降到 0~1」，不是「含词比例降下来」。
_PET_WORD = ('桌宠', '小蓝', '大蓝', '模型', 'autoclaw', '记忆', 'flash', 'pro 版')
_PROJECT = re.compile(r'(强化|搭建|治理体系|技术实现|记忆机制|实测.{0,6}效果'
                      r'|governance|template)')
_IDENTITY = re.compile(r'(名字叫|叫大蓝|叫小蓝|姐姐)')
_INTERACT = re.compile(r'(开玩笑|逗它|亲近|和桌宠|让桌宠|向桌宠)')


def category(text):
    """四类：A 项目/技术记录 / B 角色身份 / C 互动习惯 / C2 含桌宠词其他 / D 无关桌宠"""
    t = str(text or '')
    tl = t.lower()
    if _PROJECT.search(t):
        return 'A_项目技术'
    if _IDENTITY.search(t):
        return 'B_角色身份'
    has_pet = any(k in tl for k in _PET_WORD)
    if has_pet and _INTERACT.search(t):
        return 'C_互动习惯'
    if has_pet:
        return 'C2_含词其他'
    return 'D_无关桌宠'


def is_pet_topic(text):
    """⚠ 保留是为了兼容旧调用；**不要再用它当偏斜指标**（理由见上面口径说明）。"""
    keys = _PET_WORD
    t = str(text or '').lower()
    return any(k.lower() in t for k in keys)


def main(argv=None):
    ap = argparse.ArgumentParser(description='存量 facts 清理（默认 dry-run）')
    ap.add_argument('--apply', action='store_true', help='真改（先自动备份到 logs/）')
    args = ap.parse_args(argv)

    if not os.path.exists(MEMORY):
        raise SystemExit('memory.json 不存在：%s' % MEMORY)

    data = json.load(io.open(MEMORY, encoding='utf-8'))
    facts = data.get('facts', [])
    active = [f for f in facts if f.get('status') == 'active']

    print('库：%s' % MEMORY)
    print('facts 总 %d 条，active %d 条' % (len(facts), len(active)))
    print()
    print('=' * 100)
    print('逐条判定（动作 / 理由 / 依据）')
    print('=' * 100)

    tally = {'keep': 0, 'trim': 0, 'move': 0, 'unreviewed': 0}
    for i, f in enumerate(active, 1):
        act, reason, why, new = decide(f)
        key = 'unreviewed' if reason == 'unreviewed' else act
        tally[key] = tally.get(key, 0) + 1
        mark = {'keep': '留', 'trim': '剥', 'move': '↓'}[act]
        print('%2d. [%s] %s' % (i, mark, str(f.get('content'))[:88]))
        if act != 'keep':
            print('      动作=%s 理由=%s' % (act, reason or '-'))
            print('      依据：%s' % why)
            if new:
                print('      剥后：%s' % new[:80])
    print()
    print('=' * 100)
    print('影响预估')
    print('=' * 100)
    kept, moved = [], []
    for f in active:
        act, _r, _w, new_text = decide(f)
        if act == 'move':
            moved.append(f)
        else:
            # ⚠ 估算必须用**剥后**的文本：用原文会把「已剥掉的项目描述」仍算成 A 类，
            #   导致预估偏高（2026-11-08 踩到：预估 2 条 A 类，实际应为 0）
            kept.append(dict(f, content=(new_text if (act == 'trim' and new_text)
                                         else f.get('content'))))
    print('  保留（含剥后保留）：%d 条' % len(kept))
    print('  降级到 events：    %d 条' % len(moved))
    print()
    from collections import Counter
    for label, pool in (('清理前', active), ('清理后（预估）', kept)):
        c = Counter(category(f.get('content')) for f in pool)
        n_a = c.get('A_项目技术', 0)
        print('  %s：%d 条' % (label, len(pool)))
        for k in sorted(c):
            print('      %-14s %2d 条 = %3.0f%%' % (k, c[k], 100.0 * c[k] / max(len(pool), 1)))
        print('      ⇒ **A 类（真偏斜）%d 条 = %.0f%%**' % (n_a, 100.0 * n_a / max(len(pool), 1)))
    print()
    print('  同口径对照：真实对话里含项目/技术特征 2 / 52 = 4%（用户消息 0 / 17 = 0%）')
    print('  ⚠ 不要用「含桌宠词」比例当指标 —— 它把角色身份与互动习惯也算成偏斜了')

    if not args.apply:
        print()
        print('（dry-run，未改动任何文件。确认无误后加 --apply）')
        return 0

    # ---- 真改：先备份 ----
    os.makedirs(LOGS, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    bak = os.path.join(LOGS, 'memory.json.bak-curate-%s' % stamp)
    shutil.copy2(MEMORY, bak)
    print()
    print('已备份：%s' % os.path.relpath(bak, ROOT))

    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    changed = 0
    for f in facts:
        if f.get('status') != 'active':
            continue
        act, reason, why, new = decide(f)
        if act == 'trim' and new:
            # ⛔ 剥之前必须留原文：只改 content 会把原件冲掉，
            #    违反「原件保留、加工另存」。2026-11-08 第一版就是这么干的，
            #    靠整库备份才捞回来。
            if not f.get('original_content'):
                f['original_content'] = f.get('content')
            f['content'] = new
            f['curated_at'] = now
            f['curated_reason'] = reason
            changed += 1
        elif act == 'move':
            f['status'] = 'moved_to_events'
            f['moved_at'] = now
            f['moved_reason'] = reason or 'curated'
            f['curated_note'] = why
            changed += 1

    data['facts'] = facts
    data['updated_at'] = now
    with io.open(MEMORY, 'w', encoding='utf-8', newline='') as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2))

    print('已改 %d 条' % changed)
    print()
    # 复核
    after = [f for f in data['facts'] if f.get('status') == 'active']
    n_pet = sum(1 for f in after if is_pet_topic(f.get('content')))
    print('清理后 active：%d 条，桌宠/模型话题 %d 条 = %.0f%%'
          % (len(after), n_pet, 100.0 * n_pet / max(len(after), 1)))
    print('回滚：把 %s 覆盖回 memory.json 即可' % os.path.basename(bak))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
