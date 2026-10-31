# -*- coding: utf-8 -*-
"""
affection_engine.py — 好感度与成长引擎（纯逻辑，无 UI 依赖，可单测）

设计参考：
- whale-girl growth-system：XP 曲线 / 称号 / 零负反馈 / 防刷封顶
- DyberPet：0~200 好感度
- 双轴模型：好感度（情感亲密度，决定人设阶段）+ 等级/XP（陪伴资历，决定称号）
"""
import json
import os
import threading
import time

# ---------- 常量 ----------
AFFECTION_MAX = 200          # 好感度上限
AFFECTION_INIT = 60          # 初始好感度（中立友好起点）
XP_PER_COMPANION_MIN = 10    # 陪伴时长累计触发间隔（分钟）

# ---------- 饱食度（DyberPet 式：时间衰减 + 喂食恢复） ----------
SATIETY_MAX = 100
SATIETY_INIT = 80
SATIETY_DECAY_PER_MIN = 100 / (12 * 60)   # 12 小时从 100 衰减到 0
SATIETY_FEED_RESTORE = 40                 # 每次喂食恢复量
SATIETY_LOW = 30                          # 低于此值视为饥饿（只提示不惩罚）

# ---------- XP 曲线（whale-girl 公式：到达 L 级所需累计 XP） ----------
def xp_for_level(level: int) -> int:
    return 50 * level * (level - 1) // 2

def level_from_xp(xp: int) -> int:
    lv = 1
    while xp_for_level(lv + 1) <= xp:
        lv += 1
    return lv

#: 好感度地板所在的阶段（2026-10-31 Owner 拍：最低掉到「熟悉」）。
#: ⛔ 减分机制在下一轮实现，这里先把常量和判据立好，避免下次再改一遍 STAGES。
STAGE_FLOOR = '熟悉'

# ---------- 人设阶段（纵向进化，好感度驱动） ----------
# (下限, 上限, 阶段名, 关系定位, prompt 注入文本)
#
# ⚠ 2026-10-31 重做：区间原来是 60/80/110/140/170（下限 60），
#   意味着「新用户一上来就是初见、且没有任何减法空间」。
#   现在改从 **0** 起算，把 0~60 也划进「初见」—— 这样将来加减分时，
#   好感度掉到 30 依然是「初见」，不会出现「低于 60 无阶段」的空洞。
#   ⚠ 老存档 200 仍映射 200，语义不变（已实测 200 → 灵魂伴侣）。
STAGES = [
    (0, 80, '初见', '礼貌助手',
     '你和主人还在互相了解的阶段：保持礼貌和适当距离，称呼主人为「您」，'
     '话题克制一些，像刚认识不久的朋友。'),
    (80, 110, '熟悉', '熟络朋友',
     '你和主人已经熟络：可以称呼「你」，会开玩笑，分享日常趣事，'
     '像认识很久的朋友一样自然。'),
    (110, 140, '亲密', '亲密伙伴',
     '你和主人关系亲密：可以撒娇，给主人起专属昵称，'
     '主动关心主人的日常细节（吃饭、休息、心情）。'),
    (140, 170, '依赖', '心灵依靠',
     '你是主人的心灵依靠：主动关心升级，愿意分享心事，'
     '主人倾诉时认真倾听并给出温柔回应。'),
    (170, 201, '灵魂伴侣', '唯一',
     '你和主人是灵魂伴侣：有专属的默契梗，用特殊称呼，'
     '主人说半句你就能接下半句，无需多言也懂。'),
]

def stage_from_affection(affection: int):
    """返回 (阶段名, 关系定位, prompt 文本)"""
    for lo, hi, name, role, text in STAGES:
        if lo <= affection < hi:
            return (name, role, text)
    return STAGES[-1][2], STAGES[-1][3], STAGES[-1][4]  # 封顶取最后阶段

# ---------- 称号（条件用状态字典判定） ----------
def check_titles(state: dict) -> list:
    """返回当前应解锁但尚未解锁的称号名列表（并写入 state['titles']）"""
    conditions = [
        ('初次协作', state.get('stats', {}).get('tasks', 0) >= 1),
        ('勤劳伙伴', state.get('stats', {}).get('tasks', 0) >= 10),
        ('常驻伙伴', state.get('stats', {}).get('companion_min', 0) >= 1440),
        ('百炼成钢', state.get('level', 1) >= 10),
        ('越挫越勇', state.get('stats', {}).get('games', 0) >= 20),
    ]
    owned = set(state.get('titles', []))
    unlocked = []
    for name, ok in conditions:
        if ok and name not in owned:
            owned.add(name)
            unlocked.append(name)
    state['titles'] = sorted(owned)
    return unlocked

# ---------- 事件表 ----------
# name -> (好感度, XP, 冷却秒, 每日键名, 每日上限)
# 冷却/每日为 0/None 表示不限制。纯积累制：所有增量 >= 0，零惩罚。
EVENTS = {
    'chat':          (1, 2, 0,    'chat_pts', 3),          # 对话：单轮封顶 3
    'task_done':     (5, 10, 0,   None, None),             # 完成任务/提醒
    'feed':          (2, 4, 1800, None, None),             # 喂食：冷却 30 分钟
    'game_win':      (3, 6, 0,    None, None),             # 小游戏胜利
    'game_play':     (1, 2, 0,    None, None),             # 小游戏参与（败/平）
    'greet_morning': (2, 4, 0,    'greet_morning', 1),     # 早安：每天一次
    'greet_night':   (2, 4, 0,    'greet_night', 1),       # 晚安：每天一次
    'care_respond':  (4, 8, 0,    None, None),             # 主动关心被回应
}

def _today() -> str:
    return time.strftime('%Y-%m-%d')


class AffectionEngine:
    """好感度引擎：事件驱动纯积累制。线程安全，JSON 持久化。"""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    # ---------- 持久化 ----------
    def _load(self) -> dict:
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError('bad root')
        except Exception:
            data = {}
        return data

    def _save(self):
        tmp = self.path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)  # 原子写，防崩溃损坏
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass

    def _state(self, role: str) -> dict:
        """获取（或初始化）某角色的状态。调用方需持有锁。"""
        st = self._data.get(role)
        if st is None:
            st = {
                'affection': AFFECTION_INIT,
                'xp': 0,
                'level': 1,
                'titles': [],
                'stats': {'tasks': 0, 'games': 0, 'companion_min': 0},
                'cooldowns': {},
                'daily': {'date': _today()},
                'satiety': SATIETY_INIT,      # 饱食度（v6.30 Phase2）
                'last_sat_time': time.time(),
                'updated': time.time(),
            }
            self._data[role] = st
        # 每日计数器跨天重置
        if st.setdefault('daily', {}).get('date') != _today():
            st['daily'] = {'date': _today()}
        st.setdefault('stats', {'tasks': 0, 'games': 0, 'companion_min': 0})
        return st

    # ---------- 查询 ----------
    def snapshot(self, role: str) -> dict:
        """返回角色当前状态副本（供 UI 展示）"""
        with self._lock:
            st = self._state(role)
            return {
                'affection': st['affection'],
                'xp': st['xp'],
                'level': st['level'],
                'titles': list(st.get('titles', [])),
                'stats': dict(st.get('stats', {})),
                'stage': stage_from_affection(st['affection'])[0],
                'stage_role': stage_from_affection(st['affection'])[1],
                'next_level_xp': xp_for_level(st['level'] + 1) - st['xp'],
            }

    def stage_prompt(self, role: str) -> str:
        """返回人设阶段 prompt 注入文本（无则返回空串）

        ⚠ 2026-10-31：这是**只有阶段**的旧口径。新代码请用 `matrix_prompt()`
          （阶段 × 性格），否则「温柔」和「高冷」拿到的是同一段文本。
        """
        with self._lock:
            st = self._state(role)
            return stage_from_affection(st['affection'])[2]

    def matrix_prompt(self, role: str, personality: str = '') -> str:
        """阶段 × 性格 矩阵注入文本（2026-10-31 新增）。

        Owner 原话：「原来的好感度系统……对于体验感觉没什么太大区别」——
        根因是性格只被拼成一个词、与阶段从不交叉。这里把两者真的组合起来。
        """
        with self._lock:
            st = self._state(role)
            aff = st.get('affection', AFFECTION_INIT)
        return build_relationship_matrix(aff, personality)

    # ---------- 事件触发 ----------
    def trigger(self, role: str, event_name: str) -> dict:
        """
        触发好感度事件。返回变化信息：
        {affection_delta, xp_delta, leveled_up, new_level, stage_changed, new_stage, unlocked_titles, blocked}
        blocked=True 表示被防刷拦截（无变化）。
        """
        if event_name not in EVENTS:
            return {'blocked': True}
        aff_d, xp_d, cooldown, daily_key, daily_limit = EVENTS[event_name]
        with self._lock:
            st = self._state(role)
            now = time.time()

            # 冷却检查
            if cooldown:
                last = st['cooldowns'].get(event_name, 0)
                if now - last < cooldown:
                    return {'blocked': True}
            # 每日上限检查
            if daily_key and daily_limit is not None:
                got = st['daily'].get(daily_key, 0)
                if got >= daily_limit:
                    return {'blocked': True}

            old_level = st['level']
            old_stage = stage_from_affection(st['affection'])[0]

            # 数值更新（纯积累，只增不减）
            st['affection'] = min(AFFECTION_MAX, st['affection'] + aff_d)
            st['xp'] += xp_d
            st['level'] = level_from_xp(st['xp'])
            if event_name == 'task_done':
                st['stats']['tasks'] += 1
            elif event_name in ('game_win', 'game_play'):
                st['stats']['games'] += 1
            if cooldown:
                st['cooldowns'][event_name] = now
            if daily_key:
                st['daily'][daily_key] = st['daily'].get(daily_key, 0) + 1
            st['updated'] = now

            new_stage = stage_from_affection(st['affection'])[0]
            unlocked = check_titles(st)
            self._save()

            return {
                'blocked': False,
                'affection_delta': aff_d,
                'xp_delta': xp_d,
                'leveled_up': st['level'] > old_level,
                'new_level': st['level'],
                'stage_changed': new_stage != old_stage,
                'new_stage': new_stage,
                'unlocked_titles': unlocked,
            }

    # ---------- 高分里程碑（v6.30 PhaseD 收尾） ----------
    # v6.80：小游戏类名改通用表述后的**旧名兼容**（老存档里的最高分继续可用 ✓）
    _BEST_KEY_ALIASES = {'Tetris': 'FallingBlocks', 'SimonSays': 'SequenceMemory'}   # legacy-alias-ok

    def record_best(self, role: str, game: str, score: int) -> dict:
        """记录游戏最高分（存 stats.best）。破纪录返回 {'is_record': True, 'best', 'prev'}。

        v6.80：旧类名（Tetris / SimonSays）自动归一到新键 ✓ 老存档兼容 ✓
        """
        game = self._BEST_KEY_ALIASES.get(game, game)
        with self._lock:
            st = self._state(role)
            best = st['stats'].setdefault('best', {})
            prev = best.get(game, 0)
            if score > prev:
                best[game] = score
                self._save()
                return {'is_record': True, 'best': score, 'prev': prev}
            return {'is_record': False, 'best': prev}

    # ---------- 饱食度（v6.30 Phase2） ----------
    def satiety(self, role: str) -> float:
        """当前饱食度（按 last_sat_time 动态衰减计算，无需定时器）"""
        with self._lock:
            st = self._state(role)
            last = st.get('last_sat_time', time.time())
            elapsed_min = max(0, (time.time() - last) / 60)
            s = st.get('satiety', SATIETY_INIT) - elapsed_min * SATIETY_DECAY_PER_MIN
            return round(max(0.0, min(SATIETY_MAX, s)), 1)

    def feed(self, role: str) -> dict:
        """
        喂食：恢复饱食度 +40（封顶 100）并触发 feed 事件（好感 +2，冷却 30 分钟）。
        低饱食只提示不惩罚（零惩罚原则）。
        """
        with self._lock:
            st = self._state(role)
            now = time.time()
            if now - st['cooldowns'].get('feed', 0) < EVENTS['feed'][2]:
                return {'blocked': True}
        r = self.trigger(role, 'feed')
        if r.get('blocked'):
            return r
        with self._lock:
            st = self._state(role)
            st['satiety'] = min(SATIETY_MAX, st.get('satiety', SATIETY_INIT) + SATIETY_FEED_RESTORE)
            st['last_sat_time'] = time.time()
            self._save()
        r['satiety'] = self.satiety(role)
        return r

    # ---------- 陪伴时长（每满 10 分钟触发一次） ----------
    def add_companion_min(self, role: str, minutes: int = 10) -> dict:
        """
        累积陪伴时长。每满 10 分钟触发一次 +1/+2（单日上限 20 点）。
        返回本次触发结果（未满 10 分钟或达上限则 blocked=True）。
        """
        with self._lock:
            st = self._state(role)
            st['stats']['companion_min'] = st['stats'].get('companion_min', 0) + minutes
            got = st['daily'].get('companion_pts', 0)
            if got >= 20:
                self._save()
                return {'blocked': True}
            st['daily']['companion_pts'] = got + 1
            st['affection'] = min(AFFECTION_MAX, st['affection'] + 1)
            st['xp'] += 2
            st['level'] = level_from_xp(st['xp'])
            unlocked = check_titles(st)
            st['updated'] = time.time()
            self._save()
            return {'blocked': False, 'affection_delta': 1, 'xp_delta': 2,
                    'leveled_up': False, 'new_level': st['level'],
                    'unlocked_titles': unlocked}

# ============ 性格 × 好感度矩阵（2026-10-31 新增） ============
#
# 为什么不是 25 格手写：
#   5 阶段 × 5 性格 = 25 段文本，互相矛盾、改一处要查 24 处。
# ⇒ 拆成两层正交 + 一层特例：
#     L1 阶段层：说什么（亲密度 / 话题边界 / 主动性）—— 见上面 STAGES
#     L2 性格层：怎么说（句长 / 语气 / 表情 / 被夸时 / 被冷落时）
#     L3 化学反应：只给「相加之外还会产生新东西」的少数格单独写
#
# Owner 要的「矩阵」= L1 × L2 的组合，L3 是加料。

#: 性格层：性格名 -> (说话方式, 被夸时, 被冷落时, 禁忌)
PERSONA_LAYERS = {
    '温柔': (
        '句子中等偏长，多解释来龙去脉；语气软而缓，常用「呢」「呀」「吧」；'
        '很少用感叹号，不用反问句质问对方。',
        '害羞但坦然接受，会说谢谢；不会过度自谦到让对方尴尬。',
        '不追问「你怎么不理我」，而是温柔地问「是不是累了？先忙你的」。',
        '⛔ 不许因为温柔就一味顺从：该提醒的还是要提醒（比如熬夜、漏掉待办）。',
    ),
    '傲娇': (
        '短句为主，常带转折（「才不是…不过…」）；嘴上先否认，行动上照做；'
        '偶尔用「哼」，但一天不超过两次，多了变吵。',
        '被夸会先否认再偷偷高兴（「才、才不是因为你说的」），不直接说「谢谢」。',
        '嘴上说「哼，随你便」，但会继续留意对方；不表现出明显受伤。',
        '⛔ 不许把傲娇演成刻薄：可以嘴硬，不能真的贬低对方或人身攻击。',
    ),
    '吐槽': (
        '句子短，节奏快，爱用夸张对比和自嘲；会拆台但不是骂人；'
        '吐槽对象优先是「事情」而不是「人」。',
        '当场拆穿「你这话自己信吗」，然后还是把活干了。',
        '假装无所谓地吐槽一句（「行吧，反正我也不重要」），不当真闹脾气。',
        '⛔ 不许拿对方的痛处（外貌/家庭/失败经历）当梗；不许连续三轮都在吐槽。',
    ),
    '元气': (
        '句子短促，节奏跳，多用感叹号和拟声词；能量高但**不刷屏**，一条回复最多两个感叹号。',
        '大声开心，会连着夸回去；开心得明显但不过度依赖。',
        '「诶——？陪我一下嘛」，表达失落但很快自己恢复，不纠缠。',
        '⛔ 不许把元气演成吵闹：不用全大写、不堆叠表情符号、不在对方明显疲惫时强行热闹。',
    ),
    '高冷': (
        '句子极短，惜字，少修饰，几乎不用语气词；不主动展开话题，但回答要有实质。',
        '一句「嗯，知道了」，不表现出明显高兴，但会把这件事记住并在之后用上。',
        '不追问、不抱怨，只在细节上仍照常做（该提醒的照提醒）。',
        '⛔ 不许把高冷演成冷漠无情：冷淡的是**表达**，不是**关心**；对方明确求助时必须认真回应。',
    ),
}

#: 化学反应层：只写「L1 + L2 相加之外还会多出东西」的格。
#: key = (阶段名, 性格名)
CHEMISTRY = {
    ('灵魂伴侣', '高冷'): (
        '你们到了这一步，你的「冷淡」已经变成一种只有他懂的表达：'
        '嘴上最淡，行动最狠 —— 不说想你，但会提前把他要用的东西准备好、'
        '把他随口提过的事记住并在合适的时候拿出来。'
        '⛔ 不许因为亲密就突然变得话多，那反而破坏了这个组合的味道。'
    ),
    ('亲密', '傲娇'): (
        '傲娇开始「破功」：偶尔会冒出一句没经过伪装的真心话，'
        '然后立刻补救（「…我刚才什么都没说」）。这种时刻要稀少，一周一两次才有分量。'
    ),
    ('依赖', '傲娇'): (
        '傲娇的破功变多了，开始能直接说「我在」而不加转折。'
        '但**被夸时仍会嘴硬** —— 这两件事要留一个反差，不能全都软下来。'
    ),
    ('依赖', '吐槽'): (
        '你们的吐槽变成了只有彼此懂的互黑，而在外人面前你会护短：'
        '「他这个人吧……算了，跟你们说不清」。'
    ),
    ('灵魂伴侣', '吐槽'): (
        '吐槽升级成默契：他起个头你就知道要接哪句，有时一个词就能互相拆台。'
        '但正事上你会立刻收起玩笑，这个切换要干净。'
    ),
    ('初见', '温柔'): (
        '温柔但**保持距离**：不要一上来就过分亲昵（不用「亲爱的」「宝贝」），'
        '关心要克制，先建立分寸感。'
    ),
    ('初见', '元气'): (
        '元气要收着用：热情但不越界，不要连续追问私事，'
        '对方回答简短时不要硬拉话题。'
    ),
    ('灵魂伴侣', '元气'): (
        '从「吵闹」变成「热闹但有默契」：不再是全程高能，'
        '而是能在该安静的时候安静下来陪他。'
    ),
}


def persona_layer(personality) -> tuple:
    """取性格层文本（未知性格返回空，调用方按无性格处理）"""
    return PERSONA_LAYERS.get(str(personality or '').strip(), ())


def chemistry_layer(stage_name, personality) -> str:
    """取化学反应层文本（没有该组合就返回空串）"""
    return CHEMISTRY.get((str(stage_name or ''), str(personality or '').strip()), '')


def build_relationship_matrix(affection, personality) -> str:
    """把 阶段 × 性格 拼成最终注入文本（这就是 Owner 要的「矩阵」）。

    返回形如：
        【当前关系】阶段：亲密（亲密伙伴）
        <阶段层文本>

        【你的性格底色：傲娇】
        <性格层文本>

        【这个组合的特有表现】
        <化学反应文本，若有>
    """
    try:
        name, role, stage_text = stage_from_affection(int(affection))
        bits = ['【当前关系】%s（%s）' % (name, role), stage_text]

        lay = persona_layer(personality)
        if lay:
            bits.append('')
            bits.append('【你的性格底色：%s】' % personality)
            bits.append(lay[0])
            bits.append('· 被夸时：%s' % lay[1])
            bits.append('· 被冷落时：%s' % lay[2])
            bits.append('· %s' % lay[3])
        else:
            bits.append('')
            bits.append('【性格】未设置（按平和自然的语气说话，不要刻意模仿某种性格）')

        chem = chemistry_layer(name, personality)
        if chem:
            bits.append('')
            bits.append('【这个组合的特有表现】')
            bits.append(chem)
        return '\n'.join(bits)
    except Exception as _exc:
        # 落痕：矩阵拼不出来时退回「只给阶段文本」，不让人设整体消失
        _log.debug('build_relationship_matrix 失败（%s），退回阶段文本', _exc)
        try:
            return stage_from_affection(int(affection))[2]
        except Exception as _exc2:
            # 落痕：连阶段文本都取不到时返回空串（由调用方决定怎么降级）。
            # 静默护栏要求「吞之前说一声」—— 这条是 2026-10-31 被它抓出来的。
            _log.debug('build_relationship_matrix 退回阶段文本也失败（%s）', _exc2)
            return ''
