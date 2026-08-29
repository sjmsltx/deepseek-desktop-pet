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

# ---------- 人设阶段（纵向进化，好感度驱动） ----------
# (下限, 上限, 阶段名, 关系定位, prompt 注入文本)
STAGES = [
    (60, 80, '初见', '礼貌助手',
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
    (170, 200, '灵魂伴侣', '唯一',
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
        """返回人设阶段 prompt 注入文本（无则返回空串）"""
        with self._lock:
            st = self._state(role)
            return stage_from_affection(st['affection'])[2]

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
    def record_best(self, role: str, game: str, score: int) -> dict:
        """记录游戏最高分。破纪录返回 {'is_record': True, 'best', 'prev'}，否则 {'is_record': False, 'best'}。"""
        with self._lock:
            st = self._state(role)
            best = st.setdefault('best', {})
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
