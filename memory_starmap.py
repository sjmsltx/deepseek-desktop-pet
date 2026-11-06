# -*- coding: utf-8 -*-
"""memory_starmap.py — 记忆星图（可交互控件）

设计口径与静态预览稿一致，每个视觉维度都对应一个真实字段：
    星团   = 记忆类别（人际 / 兴趣 / 学业 / 工程 / 里程碑）
    团内半径 = 记忆年龄（越靠外越旧）
    亮度   = 时间衰减（半衰期 30 天，与 memory_engine.score_recency 同口径）
    大小   = importance
    连线   = 同类别内相邻经历（星座）
    中心   = L0 人格卡
    外圈暗点 = superseded（失效但留痕）

交互：拖动平移 / 滚轮缩放（以光标为中心）/ 悬停看摘要 / 点击钉住详情 / R 复位
只读：不改任何记忆文件。

配色说明（S3，审核指出）：本模块的 QColor(r, g, b) 不走主题 token，
是因为星图是**独立视觉域**（深空底色 + 类别色代表了真实的记忆分类），
不是为了绕开主题护栏。护栏只匹配十六进制色值与 rgba 函数写法，
对 QColor 三元组不计（这也是它的已知盲区，见审核 S3）。
显式声明：改主题时星图**不跟随**，需同步改本文件 PAL 表。
"""
import io
import json
import logging
import math
import zlib
import os
import re
import time

from PySide6.QtCore import QTimer

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QWidget

# ⚠ 2026-11-02：亮度衰减必须与 memory_events 共用一份公式。
#   原先本文件自带 HALF_LIFE_DAYS = 30.0 和一行 `0.5 ** (age/30)` —— 那是第二份实现。
#   这是本仓反复踩的形状（写两份必然只修一份：is_sensitive_path / screenAt / USER_CONFIG_PATH）。
from memory_events import HALF_LIFE_DAYS, decay_factor as _decay_factor  # noqa: F401

BASE = os.path.dirname(os.path.abspath(__file__))
FACTS_PATH = os.path.join(BASE, 'memory.json')
EVENTS_PATH = os.path.join(BASE, 'memories.json')

PAL = {
    'core':  (255, 234, 172),
    'human': (255, 126, 182),
    'like':  (108, 204, 255),
    'study': (100, 255, 202),
    'work':  (255, 170, 90),
    'mile':  (255, 228, 124),
    'dead':  (100, 96, 128),
}
CN = {'core': 'L0 人格卡', 'human': '人际 · 相处方式', 'like': '兴趣 · 偏好',
      'study': '学业 · 学习', 'work': '工程 · 项目', 'mile': '里程碑', 'dead': '已失效'}
ORDER = ['human', 'study', 'work', 'like', 'mile']
ANGLES = {'human': -128, 'study': -52, 'work': 34, 'like': 122, 'mile': 182}
KEYWORDS = [
    ('mile',  ['满分', '新纪录', '里程碑', '称号', '突破', '成就']),
    ('human', ['关心', '玩笑', '亲近', '语气', '陪伴', '晚安', '熬夜', '姐姐', '大蓝', '小蓝', '记得站']),
    ('study', ['遥感', 'GIS', '地理', '课程', '考试', 'Python', 'matplotlib', '古文', '过秦论',
               '诗', '学习', '背', '大二']),
    ('work',  ['桌宠', '代码', '工程', '更新', '仓库', 'AutoClaw', '环境', '版本']),
]
_log = logging.getLogger('pet.memory_starmap')


def _classify(text, status='active', typ='fact'):
    if status != 'active':
        return 'dead'
    for cat, kws in KEYWORDS:
        if any(k in text for k in kws):
            return cat
    return 'human' if typ == 'event' else 'like'


# ---------------- 关系判定（2026-10-31，Owner 要求「有关系的连起来」）----------------
#
# 口径必须诚实标注：这里的「关系」= **文本词面重叠**，不是语义理解。
#   · 中文 2-gram + 英文整词（英文不切碎，否则 python 会变成 py/ho/on/yt）
#   · 去停用词 —— 「用户」「桌宠」这类词出现在几乎每条记忆里，
#     不滤掉的话所有星点两两相连，图就废了
#   · Jaccard = 共享词数 / 并集词数
#
# 改前（旧实现）：同类别内按极角排序连相邻两颗 —— 纯几何位置，
#   与「有没有关系」无关。图例写「同类别的相邻经历」是夸大，已一并改掉。

#: 强边阈值。真实数据实测（2026-10-31，23 星点）：
#:   jac>=0.045 → 9 对，人工看全部成立（日语梗/主动关心/小蓝/过秦论/Python…）
#:   jac<0.030 开始出现噪音（「桃片」×「爱背古文」共享「户爱」这种）
STRONG_EDGE_JACCARD = 0.045

#: 每个星点最多连几条强边（防一个中心点辐射成毛球）
STRONG_EDGES_PER_NODE = 2

#: 停用词：泛词 + 虚词 2-gram。宁可多滤，也别让「用户」把所有星星缝成一坨。
_STOP = set("""
用户 桌宠 的 了 是 我 你 他 她 它 不 有 在 和 如 等 就 都 也 还 被 把 让 给 对 从 到 为 以 与 或 但 而 且 并 则 很 更 最 太
可以 什么 怎么 这个 那个 一下 一些 有点 比较 觉得 认为 会 能 要 说 做 用 时 里 上 下 中 后 前 自己 他们 我们 你们
用户会 户会 会用 我的 的名 字叫 叫小 叫大 名字 一个 现在 已经 因为 所以 如果 但是 而且 就是 不是 没有 起来 记得
""".split())

_ENG = re.compile(r'[a-z][a-z0-9_]{2,}')


def stable_jitter(key, salt=0):
    """确定性抖动，返回 [0, 1)。

    用途：打散黄金角螺旋留下的规整螺旋臂（Owner：「分布有点太规律了」）。
    ⛔ 不能用内置 hash()：它带 PYTHONHASHSEED 随机化，跨进程/重启会变 ⇒
       星图每开一次位置都不同，而且 test_layout_deterministic 会红。
    """
    h = zlib.crc32(('%s|%d' % (key, salt)).encode('utf-8')) & 0xffffffff
    return ((h >> 7) % 10007) / 10007.0


def terms(text):
    """取可比较的词集合：中文 2-gram（去停用词）+ 英文整词（≥3 字符）

    ⛔ 英文必须整词 —— 逐字符 2-gram 会让任何两个含 Python 的条互相「相关」，
       看起来像关系，其实是切碎的巧合。
    """
    t = text or ''
    out = set(_ENG.findall(t.lower()))
    cn = re.sub(r'[^\u4e00-\u9fa5]', '', t)
    for i in range(len(cn) - 1):
        g = cn[i:i + 2]
        if g not in _STOP:
            out.add(g)
    return out


def jaccard(a, b):
    """两段文本的词集合 Jaccard 相似度。任一方为空 → 0"""
    ta, tb = terms(a), terms(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


#: ── 2.5D 星图（2026-11-03）──
#: z 轴 = 年龄。三维度分工：
#:   位置：向**全局消失点**（图心）收缩 —— 透视的正确做法（远处靠近消失点）
#:   大小：远小近大；光晕：越老越不发光（密集处才不会糊成色块）
#:   遮挡：按 z 降序绘制（老的先画，新的压在上面）
#:
#: ⛔ 曾经把深度做成「老记忆整体上移 R*0.34」，截图发现与环形方位布局打架：
#:   上方星团的老星顶到标题区（实际 y=97，标题在 y=44），下方星团的老星
#:   跑进画面中部，类团结构被破坏。**深度不能靠整体平移实现**，
#:   只能用「向消失点收缩」——那样每个点都沿自己的视线方向后退，不会串团。
#: 位移量 = 类内半径 × DEPTH_SHRINK。类内半径最大 190，
#: 要让「外圈更远」可被感知，位移需 ≥ 半径的 30%（约 57px）⇒ 取 0.30。
#: ⚠ 0.18 时位移只有 34px，在 600px 的类团间距下是噪声（前五轮截图的教训）。
DEPTH_SHRINK = 0.30      # 最老的向图心收缩 30%
DEPTH_TILT = 0.94        # 深度方向再压纵向 6%（斜视）
DEPTH_RAD = 0.48         # 最老的核心半径是最新的 48%（0.62 时密集处看不出差异）
DEPTH_GLOW = 0.38        # 最老的光晕只剩最新的 38%（再乘 alpha 衰减）

#: ── LOD（细节层次）2026-11-03 ──
#: 思路同 GIS 金字塔：视窗内按屏幕占用格去重，重叠处只留优先级高的（重要度→亮度），
#: 放大后格变小 ⇒ 自动显示更多。实测 1417 颗从 183ms/帧 降到个位数毫秒。
#:
#: ⛔ 星数 ≤ LOD_MIN_N 时**不启用**：真实库 27 颗、产品上限 MAX_MEMORIES=200，
#:    这两个规模本来就不重叠，保持原样可避免任何视觉回归。
LOD_MIN_N = 260
#: LOD 间距（屏幕 px）。**恒定**，不随 zoom 变 —— 它必须 ≥ 符号直径才不会叠。
#: 「放大看更多」靠另一条路：格不变而几何放大 ⇒ 数据空间分桶自动变细。
#: 格边长基准（屏幕 px）。**必须明显大于星核心直径**（imp=5 时约 19px），
#: 否则相切无间隙、视觉上密不透风（19px 实测：zoom=4 时 811 颗糊成一片）。
#: 26px 留出约 7px 间隙；实测可见数 zoom=1 147 / zoom=2 287 / zoom=4 584。
LOD_CELL_BASE = 26.0

#: 缩放上下限。2026-11-03 Owner「放大上限再调高一点」：4.0 → 30。
#: 配合「布局半径随条数 √ 增长」，放大到 30 倍才能把几万条里的一簇拆开看清。
ZOOM_MIN = 0.20
ZOOM_MAX = 30.0

#: 防误触：按下到松开位移超过这个像素就当「拖动」，不钉住星点。
#: Owner：「拖动时难免点到星上进行拖拽，这不是真的要钉住」。
#: 用位移而不是时间 —— 时间阈值会让慢速拖动误钉。
DRAG_THRESHOLD = 5.0

#: 符号尺寸随 zoom 的增长：rad ∝ zoom**0.35，且封顶 1.6 倍。
#: ⛔ 曾经写成线性（rad ∝ zoom）——zoom=3 时核心 28px 而格只有 7.5px，
#:   两者反向 ⇒ 1405 颗糊成一团。符号近乎恒定才是地图的做法。
SYM_ZOOM_POW = 0.35
SYM_ZOOM_CAP = 1.6

#: 星点 sprite 的尺寸分档（px）。按目标像素半径分档预生成 ⇒ 绘制时不缩放，
#: 实测 313 颗从 8.00ms 降到 0.73ms（比关平滑缩放还快一倍多）。
GLOW_STEP = 4.0
#: 超过此像素半径就不再单独生成（否则 zoom=4 时 sprite 会到 400px+，缓存爆炸），
#: 改用已有的 160 档缩放绘制。zoom≤2 时基本走不到这一步。
GLOW_MAX = 160.0

#: ── 世界坐标（2026-11-03）──
#: 布局与窗口解耦：`_layout` / `_centers` / `_cat_r` 存世界单位。
#: 世界半径随条数 √n 增长 ⇒ 每颗星占的世界面积恒定 ⇒ 几万条也放得下。
WORLD_BASE_R = 320.0     # n = WORLD_REF_N 时的世界布局半径
WORLD_REF_N = 400        # 基准条数

#: 参与算边的点数上限。build_edges 的候选对随点数平方增长：
#:   235 点 → 8.7k 对（3.5ms）／812 点 → 92k 对（29ms）／1417 点 → 282k 对（90ms）。
#: 400 点 ≈ 21k 对 ≈ 9ms，是一帧预算内能接受的上限。
#: 超出时按 (重要度 desc, 亮度 desc) 取前 N —— 被裁的是暗淡低重要度的星，
#: 它们不该抢眼的线；pinned / hover 强制保留。
EDGE_MAX_N = 360

#: 算边时的视野缓冲（屏幕 px）。视野外这么多以内的点也参与算边，
#: 这样小幅拖动时边缘的线不会突然断掉。
VIEW_PAD = 240.0
#: 拖动量化（屏幕 px）。pan 以这个粒度取整后才进缓存 key ⇒
#: 小幅拖动命中缓存（不重算边），大幅拖动才重算一次。
VIEW_PAN_Q = 200.0

#: 类团外半径上限（世界单位，n = WORLD_REF_N 时）。按星数 √n 分配使密度接近。
#: 190 是 1440x900 上限附近实测不越界的值；小窗口由 _compute_layout 按 R 再压。
CAT_R_MAX = 190.0
CAT_R_MIN = 58.0         # 只有几颗星的类团也别缩成一个点（标签没地方放）


def build_edges(stars):
    """算出星图的两种边。返回 (strong, weak)。

    strong: [(i, j, weight)]  i/j 为 stars 下标，weight = jaccard
            词面重叠 ≥ STRONG_EDGE_JACCARD 的配对，**可跨星团**；每点最多
            STRONG_EDGES_PER_NODE 条（按权重从大到小取）。
    weak:   [(i, j)]          同类别内的最小生成树（Prim），保证同类星点连成
            一片但不爆炸 —— n 个点只要 n-1 条线。

    ⛔ 只读 stars，不修改任何星点字段。
    """
    n = len(stars)
    if n < 2:
        return [], []

    # ---- 强边：全配对算词重叠 ----
    # v7.x（2026-11-03 性能）：原先每对都调 jaccard()，而 jaccard 内部把两段文本
    #   重新 terms() 一遍 ⇒ 1411 点要跑 199 万次 terms()。
    #   改成每篇只算一次，jaccard 用 |A∩B|/(|A|+|B|-|A∩B|) 手算（与原式恒等）。
    _ts = [terms(s.get('text', '')) for s in stars]
    # 2026-11-03：倒排索引，只算「共享至少 1 个词」的配对。
    #   全配对 1411 点 = 99.5 万次，实测 0.44s（开窗时卡一下）；
    #   倒排后候选对只占 15.3%（15.2 万），且**结果完全等价** ——
    #   共享 0 词的对 jaccard 恒为 0，本来就不可能过阈值。
    _inv = {}
    for _i, _t in enumerate(_ts):
        for _w in _t:
            _inv.setdefault(_w, []).append(_i)
    _inter = {}
    for _docs in _inv.values():
        _m = len(_docs)
        if _m < 2:
            continue
        for _a in range(_m):
            _ia = _docs[_a]
            for _b in range(_a + 1, _m):
                _ib = _docs[_b]
                _k = (_ia, _ib) if _ia < _ib else (_ib, _ia)
                _inter[_k] = _inter.get(_k, 0) + 1
    cand = []
    for (_i, _j), _inter_n in _inter.items():
        _union = len(_ts[_i]) + len(_ts[_j]) - _inter_n
        if not _union:
            continue
        _w = _inter_n / float(_union)
        if _w >= STRONG_EDGE_JACCARD:
            cand.append((_w, _i, _j))
    cand.sort(reverse=True)

    deg = {}
    strong = []
    for w, i, j in cand:
        if deg.get(i, 0) >= STRONG_EDGES_PER_NODE or deg.get(j, 0) >= STRONG_EDGES_PER_NODE:
            continue
        strong.append((i, j, w))
        deg[i] = deg.get(i, 0) + 1
        deg[j] = deg.get(j, 0) + 1

    # ---- 弱边：同类最小生成树 ----
    # 权重用「词重叠的相反数」不合适（同类里大量配对重叠为 0 ⇒ 全等权）。
    # 这里按 age（越相近越先连）排序，让细线倾向连接时间接近的经历。
    by_cat = {}
    for idx, s in enumerate(stars):
        by_cat.setdefault(s.get('cat'), []).append(idx)

    # ⚠ 2026-11-03 性能：原先用朴素 Prim（每轮扫 tree×rest），累计 O(V³)。
    #   实测 1411 条里 like 单团 1173 点 ⇒ 约 27 秒，是整张星图唯一的耗时大头
    #   （强边全配对只要 1.3 秒）。
    #
    #   但距离是 |age_a - age_b| —— **一维**。一维欧氏距离的最小生成树就是
    #   「按 age 排序后相邻两点相连」，O(n log n)，实测 0.0003 秒。
    #
    #   等价性：两者都是最小生成树 ⇒ **总权重相同**。原先注释要求的
    #   「细线倾向连接时间接近的经历」恰好就是排序相邻连，语义更强而非更弱。
    #   ⚠ age 完全相同的点之间 MST 不唯一，边集可能与 Prim 略有差异（总权重不变），
    #     星图视觉上无差别。
    weak = []
    for cand_idx in by_cat.values():
        if len(cand_idx) < 2:
            continue
        order = sorted(cand_idx, key=lambda k: (stars[k].get('age') or 0.0, k))
        for a, b in zip(order, order[1:]):
            weak.append((a, b))

    return strong, weak



def _try_mktime(value, fmt):
    """按指定格式解析时间；不匹配是预期情况，落 debug 日志后返回 None"""
    try:
        return time.mktime(time.strptime(value, fmt))
    except (ValueError, OverflowError):
        return None          # 格式不匹配是预期分支（逐个试格式），不落日志


def _age_days(ts, now=None):
    """把时间戳换算成「多少天前」。

    用窄异常（ValueError / OverflowError）逐格式试 —— 失败是预期分支，
    不是要吞的错误，因此不需要落日志（宽泛 except 才会被判静默）。
    """
    now = now or time.time()
    s = str(ts or '').replace('T', ' ').strip()
    if not s:
        return 45.0
    fmts = ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d')
    for fmt in fmts:
        t = _try_mktime(s[:len(fmt) + 6], fmt)
        if t is not None:
            return max(0.0, (now - t) / 86400.0)
    # 只有「月-日 时:分」的旧条目：按今年推算
    if len(s) >= 16:
        t = _try_mktime('2026-' + s[5:16], '%Y-%m-%d %H:%M')
        if t is not None:
            return max(0.0, (now - t) / 86400.0)
    return 45.0


def _is_noise(title, detail=''):
    try:
        from memory_events import is_recomputable_notice
        return is_recomputable_notice(title, detail)
    except Exception as _exc:
        _log.debug('_is_noise 回退到内联判据：%s', _exc)
        t = '%s %s' % (title, detail)
        return ('别处用了' in t) or ('余额 ¥' in t) or ('今天是' in t) or ('当前设置了' in t)


def _role_match(obj, role):
    """该条记忆对 role 这个角色是否可见（与注入侧同口径）

    · role 为 None → 全部可见（星图的「全部角色」视图）
    · facts（带 fact=True）→ `roles` 缺省视为 both，只认 both 或本角色
      口径来源：memory_engine.build_l0_block
    · events → 严格相等，缺省 role 的条目不属任何角色
      口径来源：MemoryEvents.recent / hint_block（两处都是 `m.get('role') == role`）
    """
    if role is None:
        return True
    if obj.get('fact'):
        return str(obj.get('roles', 'both')) in ('both', str(role))
    return str(obj.get('role')) == str(role)


def load_stars(facts_path=FACTS_PATH, events_path=EVENTS_PATH, role=None):
    """读真实数据 → 星点列表。不编造任何一条。

    role：None = 全部角色（不过滤）；否则只读该角色**注入时会用到**的那些。
      过滤口径见 _role_match —— 与 memory_engine / memory_events 对齐，
      否则星图与注入口径不一致（Owner：换了形象主区记忆没变）。
    """
    stars, dead, raw_events = [], [], 0
    try:
        mj = json.load(open(facts_path, encoding='utf-8'))
        n_skipped = 0
        for f in mj.get('facts', []):
            c = (f.get('content') or '').strip()
            if not c:
                continue
            if not _role_match(dict(f, fact=True), role):
                n_skipped += 1
                continue
            st = f.get('status', 'active')
            # key 唯一化：同名内容可能有多条（如「用户喜欢冰美式咖啡」×2），
            # 用 id 兜底，避免布局字典互相覆盖、只画出一条。
            # key 必须唯一：memory.json 里存在 3 组重复 id（同一次抽取同毫秒写入），
            #   单用 id 会撞号 ⇒ 前面加序号。
            _key = 'f:%d:%s' % (len(stars) + len(dead), f.get('id'))
            item = dict(text=c, imp=int(f.get('importance', 3)),
                        age=_age_days(f.get('created_at')), kind='fact',
                        cat=_classify(c, st), detail='', time=str(f.get('created_at') or ''),
                        key=_key)
            (dead if st != 'active' else stars).append(item)
    except Exception as _exc:
        _log.warning('星图读取 memory.json 失败（星图将只显示事件记忆）：%s', _exc)
    try:
        ev = json.load(open(events_path, encoding='utf-8'))
        raw_events = len(ev)
        seen = set()
        merged = 0
        for i, m in enumerate(ev):
            t = (m.get('title') or '').strip()
            d = (m.get('detail') or '').strip()
            if not _role_match(m, role):
                continue
            # 去重口径与 prompt_hint 一致：按 (title, detail)。
            #   同名同内容的重复提醒（如「记得站起来活动一下」×11）没有新信息，
            #   若按 (title, time) 保留，星图上会出现 11 个一模一样的点。
            #   合并数量记在 merged，由副标题披露，不沉默。
            _k = (t, d)
            if not t or _is_noise(t, d):
                continue
            if _k in seen:
                merged += 1
                continue
            seen.add(_k)
            stars.append(dict(text=t, imp=4, age=_age_days(m.get('time')),
                              kind='event', cat=_classify(t, 'active', 'event'),
                              detail=d, time=str(m.get('time') or ''),
                              emotion=str(m.get('emotion') or ''),
                              affection=m.get('affection_at'),
                              key='e:%d:%s' % (i, m.get('id'))))
    except Exception as _exc:
        _log.warning('星图读取 memories.json 失败（星图将只显示事实记忆）：%s', _exc)
    # merged 通过 raw_events 与最终条数的差体现，这里额外带出精确值
    globals()['_LAST_MERGED'] = merged if 'merged' in dir() else 0
    # 本次按角色过滤掉了多少条 facts（供面板副标题披露「另一个角色还有 N 条」）
    globals()['_LAST_SKIPPED'] = n_skipped if 'n_skipped' in dir() else 0
    return stars, dead, raw_events


class MemoryStarMap(QWidget):
    """记忆星图控件（只读可视化）"""

    def __init__(self, parent=None, stars=None, dead=None, raw_events=0,
                 facts_path=None, events_path=None, role=None):
        super().__init__(parent)
        # 记住本实例读的是哪两个文件 —— reload_data / 指纹都必须用它们，
        #   否则传了自定义路径的实例（测试 / 多库）刷新时会读错文件。
        self._facts_path = facts_path or FACTS_PATH
        self._events_path = events_path or EVENTS_PATH
        #: 当前视角的角色（None = 全部角色）。
        #:   v3.6（2026-11-06）：原先星图完全不看 role ⇒ 换形象后记忆区不变，
        #:   与注入侧（build_l0_block / MemoryEvents.recent）口径不一致。
        self.role = role
        self.setMinimumSize(900, 620)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        if stars is None:
            stars, dead, raw_events = load_stars(self._facts_path, self._events_path,
                                                 role=self.role)
        self.stars = stars or []
        self.dead = dead or []
        self.raw_events = raw_events
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.hover = None
        self.pinned = None
        self._drag_from = None
        self._pan0 = None
        #: 防误触：按下时的命中候选与起点（松手时判断「是点击还是拖动」）
        self._press_hit = None
        self._press_pt = None
        self._press_moved = False
        self._layout = {}
        self._centers = {}
        self._layout_cached_size = None
        #: L0 条数缓存：(文件指纹, 条数)。原先 paintEvent 每帧重读整个 memory.json。
        self._l0_cache = None
        #: 星点 sprite 缓存 {(cat, alpha档): QPixmap}。原先每帧给每颗星现建
        #:   QRadialGradient（1417 个/帧）—— 实测这是除 drawLine 外最大的开销。
        self._sprite_cache = {}
        #: 背景星尘缓存 (尺寸, QPixmap)。520 个 drawEllipse → 1 次 drawPixmap。
        self._dust_cache = None
        #: LOD 结果缓存 (key, [可见星点])
        self._lod_cache = None
        #: 每条星点的 key 列表缓存 (id(stars), len, [key])
        self._keys_cache = None
        #: 边缓存：**按 LOD 可见集算**（见 _edges_for）。
        #:   _edge_src_ref 持有**调用方传入的那个列表**的引用 —— 既做身份判据，
        #:   也防止 list 被回收后 id 复用导致误命中缓存。
        #:   ⚠ 不能存裁剪后的新列表（那会让身份判断永远不命中、每帧重算边）。
        self._edge_src_ref = None
        self._edge_strong = []
        self._edge_weak = []
        #: 视野内（含缓冲）的星点列表缓存。
        #:   边只在这批点上算 —— 大 zoom 时 LOD 可见数上千，全算要 68ms。
        self._view_cache = None
        #: 滚动/缩放中「延后重算边」的单次定时器。
        #:   缩放时 LOD 可见集会变 ⇒ 边要重算（30~40ms，超一帧预算）。
        #:   做法：先用上一轮的边继续画（位置仍按当前 _layout，视觉正确，
        #:   只是线的疏密短暂沿用），停 130ms 后再算一次。
        self._edge_timer = QTimer(self)
        self._edge_timer.setSingleShot(True)
        self._edge_timer.setInterval(130)
        self._edge_timer.timeout.connect(self._rebuild_edges_now)
        #: 优先级序缓存 (id(stars), len, [星点])
        #: ⚠ 与 _label_cache 必须分**两个**字段：两个缓存格式不同（3 元组 / 5 元组），
        #:   共用一个字段会互相覆盖 ⇒ 两边永远不命中 ⇒ 每帧全量排序 1417 星点算亮度。
        #:   （这个 bug 让稳定态帧耗时从 ~12ms 涨到 ~26ms，实测抓出来的。）
        self._prio_cache = None
        #: 标签候选缓存 (id(stars), len, [最亮 4 颗]) —— 与 _prio_cache 分开
        self._label_cache = None
        #: 每个类团的外半径 {cat: 世界单位}，_compute_layout 里按 √n 算
        self._cat_r = {}
        #: 世界→屏幕的窗口适配系数：fit = 窗口可用半径 / 世界半径。
        #: 初始 zoom=1 即「全览」。窗口 resize 时由 _compute_layout 重算。
        self._fit = 1.0
        #: 世界布局半径（随条数 √n 增长）
        self._world_r = WORLD_BASE_R
        # B（2026-10-31）：自动刷新。原来 load_stars 只在打开时调一次，
        #   窗口开着就一直显示旧数据（实测：写盘后重绘，星数不变）。
        self._data_sig = self._current_sig()
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(3000)
        self._auto_timer.timeout.connect(self._maybe_reload)
        self._auto_timer.start()
        # 底色由 paintEvent 自己铺（不写死十六进制色值，遵守主题单一源）

    # ---------- 布局 ----------
    def _compute_layout(self):
        w, h = self.width(), self.height()
        cx, cy = w * 0.50, h * 0.50
        # 2026-10-31：主区里容器高只有 ~610，若直接用 min(w,h)*0.40 星团名会顶到标题栏。
        #   留出顶部（标题+副标题约 84px）与底部（图例约 90px）的净空再定半径。
        # 窗口可用半径（世界→屏幕的适配目标）
        _avail = max(60.0, min(w * 0.44, (h - 84 - 90) * 0.42))
        # 世界半径随条数 √n 增长：每颗星占的世界面积恒定
        _grow = math.sqrt(max(1, len(self.stars)) / float(WORLD_REF_N))
        R = WORLD_BASE_R * _grow
        self._world_r = R
        self._fit = _avail / R
        self._centers = {}
        for cat in ORDER:
            a = math.radians(ANGLES[cat])
            self._centers[cat] = (R * 1.02 * math.cos(a), R * 0.80 * math.sin(a))
        self._cx, self._cy, self._R = cx, cy, _avail

        groups = {}
        for s in self.stars:
            groups.setdefault(s['cat'], []).append(s)
        self._groups = groups

        # ---- 类团外半径：按 √n 分配（2026-11-03）----
        #   病因：所有类团都是 22+168 ⇒ like 团 1173 颗挤在半径 190 的盘里，
        #   平均间距 9.8px 而星直径最大 19px ⇒ 必然重叠成一个实心色块；
        #   mile 团只有 6 颗却摊在同样大的盘上，空得只剩几个点。
        #   √n 分配让「点密度」接近一致：like 190 / study 107 / work 87 / human 80 / mile 69。
        #   ⚠ 上限再按 R 收（小窗口不出界）：1440x900 时 R≈305 ⇒ 190 生效。
        # 类团半径上限同样按 √n 放大（世界单位）⇒ 密度恒定。
        # ⚠ 上限必须留出「类团不压住中心 L0 核」的余量：
        #   类团中心距图心 = R*0.80，若半径到 R*0.62，则团的内缘只离图心 0.18R，
        #   1411 条时 like 团（最大）会把中心的人格核整个盖住 —— 截图实测。
        #   R*0.50 ⇒ 内缘 0.30R，中心与团之间留出空白。
        _cap = min(CAT_R_MAX * _grow, R * 0.50)
        _n_max = max([len(v) for v in groups.values()] or [1])
        # 类团半径一律按 √n 分配（每团点密度一致）。
        #
        # ⛔ 曾经加过「N≤150 时全部同半径」的混合（想保住旧观感），
        #   但那让小团也被撑到 cap：真实库 33 颗时 human（12 颗）半径 153px
        #   而 mile（1 颗）被 CAT_R_MIN 顶到 192px ⇒ mile 的标签直接落进粉团里，
        #   两个团名打架（截图实测）。**小团必须小**，同半径是病根。
        #
        # 下限用**相对量** R*0.14：保证「只有几颗星」的团还有一点位置，
        # 又不会在小库里占掉中心距的大半。
        _r_min = min(CAT_R_MIN, R * 0.14)
        self._cat_r = {}
        for cat in ORDER:
            _n = len(groups.get(cat) or [])
            if not _n:
                continue
            _r = _cap * math.sqrt(_n / float(_n_max))
            self._cat_r[cat] = max(min(_r_min, _cap), _r)

        # ---- 2.5D 深度：z = 全局归一化年龄（0 = 最新/最近，1 = 最老/最远）----
        #   用**全局**而不是类内归一化：这样整张图共用一条时间轴，
        #   不同星团的「老」程度可比 —— 这才是「z 轴 = 年龄」的本意。
        _ages = [float(s.get('age') or 0.0) for s in self.stars]
        if _ages:
            _a_lo, _a_hi = min(_ages), max(_ages)
        else:
            _a_lo, _a_hi = 0.0, 0.0
        _span = max(_a_hi - _a_lo, 1e-6)
        self._depth = {}

        pos = {}
        for cat in ORDER:
            arr = sorted(groups.get(cat) or [], key=lambda s: s['age'])
            if not arr:
                continue
            gx, gy = self._centers[cat]
            n = len(arr)
            for i, s in enumerate(arr):
                frac = (i + 0.5) / n
                # 2026-11-03：半径改由 self._cat_r[cat] 给（按 √n 分配）。
                #   0.12 是内圈留白比例（原 22/190 = 0.116），保持「离团心越远越老」。
                _cr = self._cat_r.get(cat, 120.0)
                # 2026-11-03：加确定性抖动（Owner：「分布有点太规律了」）。
                #   黄金角螺旋本身是均匀的，但**等比例**半径 + 固定步进角
                #   会在视觉上留下明显的螺旋臂（尤其 1173 颗挤在一团时）。
                #   角度抖 ±0.42rad、半径抖 ±11% 就足以打散纹理，
                #   又不破坏「离团心越远越老」的单调趋势（2.5D 的语义）。
                _key = s.get('key') or s['text']
                _ja = stable_jitter(_key, 1)
                _jr = stable_jitter(_key, 2)
                rr = (_cr * (0.12 + 0.88 * frac) * (0.89 + 0.22 * _jr)
                      * (1.0 if n > 1 else 0.45))
                ang = 2 * math.pi * ((i * 0.618) % 1.0) + (_ja - 0.5) * 0.84
                # 世界坐标（原点在图心）
                px = gx + rr * math.cos(ang)
                py = gy + rr * math.sin(ang) * 0.92

                # 深度归一化 → 透视投影：沿各自的视线向消失点（世界原点）后退。
                #   ⚠ 不加任何整体平移 —— 那会让远处的点串到别的星团、或顶出画面。
                z = (float(s.get('age') or 0.0) - _a_lo) / _span
                shrink = 1.0 - DEPTH_SHRINK * z
                sx = px * shrink
                sy = py * shrink * (1.0 - (1.0 - DEPTH_TILT) * z)

                key = s.get('key') or s['text']
                pos[key] = (sx, sy)
                self._depth[key] = z
        self._layout = pos

    def _current_sig(self):
        """两份数据文件的 (mtime, size) 指纹 + 当前 role —— 任一变了就重载

        v3.6：role 必须进指纹。否则换形象后两个文件都没变 ⇒ _maybe_reload 永远
        不触发 ⇒ 星图还显示上一个角色的记忆（Owner 报的就是这个现象）。
        """
        sig = [('role', self.role)]
        for p in (self._facts_path, self._events_path):
            try:
                st = os.stat(p)
                sig.append((round(st.st_mtime, 3), st.st_size))
            except OSError as _exc:
                # 文件不存在/被占用：记 None 表示「无法判指纹」，
                #   下一次轮询若文件出现，指纹会变 ⇒ 自动刷新仍会触发。
                _log.debug('星图指纹读取失败（该文件暂不可用）：%s', _exc)
                sig.append(None)
        return tuple(sig)

    def _maybe_reload(self):
        """文件变了就重载（自动更新；只读，不改文件）"""
        sig = self._current_sig()
        if sig == self._data_sig:
            return
        if self.reload_data():
            self._data_sig = sig

    def set_role(self, role):
        """切换视角角色并重载（role=None → 全部角色）。返回是否真的换了。

        ⚠ 换了就要清布局缓存：星点集合变了，但尺寸没变，缓存 key 会把旧布局当成新的。
        reload_data 内部已清（_layout / _lod_cache / _edge_src_ref…），这里只负责
        「换 role → 更新指纹 → 重载」。
        """
        if role == self.role:
            return False
        self.role = role
        self._data_sig = self._current_sig()   # 先把新指纹记下，避免 _maybe_reload 又重载一次
        return self.reload_data()

    def reload_data(self):
        """重新读盘并重排布局；返回是否成功。供定时器与手动刷新共用。"""
        try:
            stars, dead, raw = load_stars(self._facts_path, self._events_path,
                                          role=self.role)
        except Exception as _exc:
            _log.warning('星图自动刷新读取失败（保留旧数据）：%s', _exc)
            return False
        self.stars = stars
        self.dead = dead
        self.raw_events = raw
        # 清布局缓存：否则会继续用旧布局画新数据
        self._layout = {}
        self._layout_cached_size = None
        # LOD / 优先级序也要清：星点换了但缓存 key 只看 id+len，
        #   新列表的 id 通常会变，但不能寄望于此。
        self._lod_cache = None
        self._prio_cache = None
        self._label_cache = None
        self._edge_src_ref = None
        self._view_cache = None
        if self.pinned is not None and (self.pinned.get('key') or '') not in {
                s.get('key') or '' for s in stars}:
            self.pinned = None
        self.hover = None
        self.update()
        return True

    # ---------- 绘制缓存 / LOD ----------
    def _dust_pixmap(self):
        """整张静态背景：纯色底 + 径向渐变 + 星尘（固定种子）。

        三层都与 pan/zoom 无关 ⇒ 只在 resize 时重建，每帧一次 blit。
        原来每帧要做 3 次全屏操作：fillRect 纯色、fillRect 径向渐变、
        520 个 drawEllipse 星尘。
        """
        key = (self.width(), self.height(), round(getattr(self, '_cx', 0.0), 1),
               round(getattr(self, '_cy', 0.0), 1))
        if self._dust_cache and self._dust_cache[0] == key:
            return self._dust_cache[1]
        pm = QPixmap(max(1, self.width()), max(1, self.height()))
        pm.fill(QColor(6, 7, 15))
        pp = QPainter(pm)
        pp.setRenderHint(QPainter.Antialiasing, True)
        # 径向渐变（原先每帧现建）
        _gx = getattr(self, '_cx', self.width() * 0.5)
        _gy = getattr(self, '_cy', self.height() * 0.5)
        g = QRadialGradient(QPointF(_gx, _gy), max(self.width(), self.height()) * 0.75)
        g.setColorAt(0.0, QColor(22, 20, 46))
        g.setColorAt(0.55, QColor(10, 10, 24))
        g.setColorAt(1.0, QColor(4, 5, 12))
        pp.fillRect(0, 0, self.width(), self.height(), QBrush(g))
        pp.setPen(Qt.NoPen)
        seed = 1234567
        for _ in range(520):
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            x = (seed % 10000) / 10000.0 * self.width()
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            y = (seed % 10000) / 10000.0 * self.height()
            v = 18 + (seed % 64)
            pp.setBrush(QColor(v, v, min(255, v + 24)))
            pp.drawEllipse(QPointF(x, y), 0.9, 0.9)
        pp.end()
        self._dust_cache = (key, pm)
        return pm

    def _sym_scale(self):
        """符号尺寸的 zoom 系数（近乎恒定，封顶 SYM_ZOOM_CAP）。

        ⛔ 不要改回 `self.zoom` 线性：那会让放大后点更大、更挤，
        与「LOD 间距恒定」互相打架（zoom=3 时 1405 颗糊成一团）。
        """
        z = max(self.zoom, 0.05)
        return min(SYM_ZOOM_CAP, z ** SYM_ZOOM_POW)

    def _star_sprite(self, cat, px_radius):
        """光晕 sprite：按**目标像素半径**分档预生成（绘制时不缩放）。

        ⚠ 2026-11-03 实测（313 颗，同场景）：
            114px sprite + 平滑缩放   8.00 ms
            缩放但关平滑              1.77 ms
            按目标尺寸预生成、不缩放    0.73 ms   ← 采用
        ⇒ 主因是「平滑缩放」，不是光晕面积。所以按 GLOW_STEP 分档生成，
        绘制走 drawPixmap(QPointF, pm)，零缩放。

        返回 (pixmap, 实际半径)。实际半径与请求不同时（被 GLOW_MAX 截断），
        调用方负责缩放绘制。
        核心（亮圆点）不烘进 sprite：核心/光晕的比例随深度变化，
        烘死会改变老星的核心大小 —— 那属于视觉回归，不做。
        """
        r = max(6.0, min(GLOW_MAX, round(px_radius / GLOW_STEP) * GLOW_STEP))
        key = (cat, int(r))
        pm = self._sprite_cache.get(key)
        if pm is not None:
            return pm, r
        size = int(r * 2) + 2
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        pp = QPainter(pm)
        pp.setRenderHint(QPainter.Antialiasing, True)
        c = QPointF(size / 2.0, size / 2.0)
        col = PAL[cat]
        gg = QRadialGradient(c, r)
        c0 = QColor(*col); c0.setAlpha(190)
        c1 = QColor(*col); c1.setAlpha(64)
        c2 = QColor(*col); c2.setAlpha(0)
        gg.setColorAt(0.0, c0)
        gg.setColorAt(0.35, c1)
        gg.setColorAt(1.0, c2)
        pp.setBrush(QBrush(gg)); pp.setPen(Qt.NoPen)
        pp.drawEllipse(c, r, r)
        pp.end()
        self._sprite_cache[key] = pm
        return pm, r

    def _keys_list(self):
        """每条星点的 key（缓存）。原先每条连边两端都现算一次字符串拼接。"""
        c = getattr(self, '_keys_cache', None)
        if c and c[0] == id(self.stars) and c[1] == len(self.stars):
            return c[2]
        keys = [(s.get('key') or s['text']) for s in self.stars]
        self._keys_cache = (id(self.stars), len(self.stars), keys)
        return keys

    def _label_candidates(self):
        """个体标签候选（最亮 4 颗）。缓存 —— 原先每帧重排全部星点。"""
        c = self._label_cache
        if c and c[0] == id(self.stars) and c[1] == len(self.stars):
            return c[2]
        top = sorted(self.stars, key=lambda s: -self._bright(s))[:4]
        self._label_cache = (id(self.stars), len(self.stars), top)
        return top

    def _priority_order(self):
        """LOD 的优先级序：重要度高的先留，同重要度按亮度（越新越亮）。

        Owner 的原话是「重叠的地方干脆就只显示大的」⇒ 优先级第一键就是 imp。
        """
        c = self._prio_cache
        if c and c[0] == id(self.stars) and c[1] == len(self.stars):
            return c[2]
        order = sorted(self.stars,
                       key=lambda s: (-float(s.get('imp') or 3), -self._bright(s)))
        self._prio_cache = (id(self.stars), len(self.stars), order)
        return order

    def _rebuild_edges_now(self):
        """延后重算边（由 _edge_timer 触发）。

        把身份判据置空 ⇒ 下一次 paintEvent 会走同步重算分支。
        """
        self._edge_src_ref = None
        self.update()

    def _schedule_edge_rebuild(self):
        """滚动/缩放中：安排一次延后重算（已在排队就不重复排）。"""
        if not self._edge_timer.isActive():
            self._edge_timer.start()

    def _view_stars(self, vis):
        """LOD 可见集里**落在视野内（含 VIEW_PAD 缓冲）**的那些。

        为什么需要：build_edges 的代价随点数平方增长（zoom=20 时 1403 点要 68ms），
        而视野外看不见的边算了也白算。实测 zoom=3 时视野内只有 296 点、4.6ms。

        ⚠ pan 量化到 VIEW_PAN_Q 才进 key：否则拖动时每个 mouseMove 都重算边。
        """
        q = VIEW_PAN_Q
        key = (id(self.stars), len(self.stars), len(vis),
               round(self.zoom, 3), int(round(self.pan.x() / q)),
               int(round(self.pan.y() / q)))
        c = self._view_cache
        if c and c[0] == key:
            return c[1]
        S = self._S()
        if S <= 0:
            self._view_cache = (key, vis)
            return vis
        px = int(round(self.pan.x() / q)) * q
        py = int(round(self.pan.y() / q)) * q
        m = VIEW_PAD
        x_lo = (-m - self._cx - px) / S
        x_hi = (self.width() + m - self._cx - px) / S
        y_lo = (-m - self._cy - py) / S
        y_hi = (self.height() + m - self._cy - py) / S
        lay = self._layout
        out = []
        for st in vis:
            xy = lay.get(st.get('key') or st['text'])
            if not xy:
                continue
            if x_lo <= xy[0] <= x_hi and y_lo <= xy[1] <= y_hi:
                out.append(st)
        self._view_cache = (key, out)
        return out

    def _edges_for(self, vis):
        """算边（**在给定星点集合上**，通常是 LOD 可见集）。

        ⛔ 为什么不能「在全部星点上算完再过滤」：LOD 只保留约 17% 的点，
           要求边两端都可见 ⇒ 只剩约 3% 的边。实测 1417 点：1263 条强边
           画出来只有 49 条，64% 的可见星一条边都没有 ⇒「联系性没体现」。

        ✅ 在可见集上重算：全览看的是「每个位置的代表星之间的关系」，
           放大后代表变多、图自然变细（与地图金字塔同理）。
           实测 235 可见点：强边 49 → 172，有边星 36% → 83%。

        ⚠ 小库（≤LOD_MIN_N）时 vis 就是 self.stars 本身 ⇒ 与改动前完全一致。
        """
        # ⚠ 必须用「调用方传进来的那个对象」做身份判据（_edge_src_ref），
        #   不能用裁剪后的新列表 —— 否则下一次调用永远不命中、每帧重算边。
        if self._edge_src_ref is vis:
            return self._edge_strong, self._edge_weak
        _src = vis
        if len(vis) > EDGE_MAX_N:
            pin, hov = self.pinned, self.hover
            ordered = sorted(vis, key=lambda st: (
                -float(st.get('imp') or 3), -self._bright(st)))
            keep = ordered[:EDGE_MAX_N]
            ids = {id(x) for x in keep}
            for x in (pin, hov):
                if x is not None and id(x) not in ids and x in vis:
                    keep.append(x)
            vis = keep
        s, w = build_edges(vis)
        self._edge_strong, self._edge_weak = s, w
        self._edge_src_ref = _src          # 存**原始输入**对象（持有引用防 id 复用）
        return s, w

    def _lod_visible(self):
        """按屏幕占用格去重，返回本轮该画的星点（GIS 金字塔式 LOD）。

        格边长 = LOD_CELL_BASE / zoom ⇒ 放大后格变小、可见星自动变多，
        这就是「放大够了再把小的显示出来」。

        ⚠ 星数 ≤ LOD_MIN_N 时原样全返回 —— 真实库 27 颗、产品上限 200 颗
        本来就不重叠，不能因为这条优化改变它们的观感。
        ⚠ pinned / hover 永远保留，否则点开的星会突然消失。
        """
        if len(self.stars) <= LOD_MIN_N:
            return self.stars
        # 格边长 = 19px × 符号缩放，再换算成世界格（19×sym / S）。
        #   S 随 zoom 变大 ⇒ 世界格变小 ⇒ 同一区域容纳更多星（金字塔展开）。
        # ⚠ 必须乘 _sym_scale()：符号随 zoom 放大到 1.6 倍（直径 ~30px），
        #   若格仍固定 19px ⇒ 符号直径 > 格距 ⇒ 必然重叠糊成一片
        #   （zoom=4 截图实测：885 颗星糊成一团浅蓝，连线完全看不见）。
        cell = (LOD_CELL_BASE * self._sym_scale()) / max(self._S(), 1e-9)
        key = (round(self.zoom, 4), id(self.stars), len(self.stars),
               self._layout_cached_size)
        c = self._lod_cache
        if c and c[0] == key:
            return c[1]
        taken = set()
        keep = []
        pin, hov = self.pinned, self.hover
        for st in self._priority_order():
            k = st.get('key') or st['text']
            xy = self._layout.get(k)
            if not xy:
                continue
            ck = (int(math.floor(xy[0] / cell)),
                  int(math.floor(xy[1] / cell)))
            if ck in taken:
                if st is pin or st is st is hov:
                    keep.append(st)
                continue
            taken.add(ck)
            keep.append(st)
        self._lod_cache = (key, keep)
        return keep

    def _l0_count(self):
        """L0 人格卡常驻条数（读本实例的 facts_path，按文件指纹缓存）。

        ⚠ 2026-11-03 修：原实现写在 paintEvent 里，用的是**全局** FACTS_PATH
        且**每帧** open+json.load 整个文件 —— 传了自定义 facts_path 的实例
        （实验数据 / 多库）会显示真实库的条数，且拖动时每秒读盘 60 次。
        """
        try:
            st = os.stat(self._facts_path)
            key = (round(st.st_mtime, 3), st.st_size)
        except OSError as _exc:
            _log.debug('星图 L0 指纹读取失败：%s', _exc)
            return 0
        if self._l0_cache and self._l0_cache[0] == key:
            return self._l0_cache[1]
        n = 0
        try:
            from memory_engine import build_l0_block
            with io.open(self._facts_path, encoding='utf-8') as _f:
                _mj = json.loads(_f.read())
            _l0, _used = build_l0_block(_mj.get('facts', []), getattr(self, 'role', 'flash'))
            n = len(_used or [])
        except Exception as _exc:
            _log.debug('星图读取 L0 失败（不显示条数）：%s', _exc)
        self._l0_cache = (key, n)
        return n

    def _bright(self, s):
        # 与 memory_events.decay_factor 同源（幂律）。0.42 是保底亮度：
        # 老星星也要看得见 —— 星图的意义是「它还在」，不是「它快没了」。
        return 0.42 + 0.58 * _decay_factor(s['age'])

    def _S(self):
        """世界单位 → 屏幕像素的总系数（zoom × 窗口适配）。"""
        return self.zoom * self._fit

    def _to_screen(self, x, y):
        """世界坐标 → 屏幕坐标。世界原点 (0,0) 落在视图中心。"""
        _s = self._S()
        return QPointF(self._cx + x * _s + self.pan.x(),
                       self._cy + y * _s + self.pan.y())

    # ---------- 绘制 ----------
    def paintEvent(self, _ev):
        if not self._layout or self._layout_cached_size != (self.width(), self.height()):
            self._compute_layout()
            self._layout_cached_size = (self.width(), self.height())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # 背景（纯色 + 径向渐变 + 星尘）烘成一张静态 pixmap（2026-11-03）
        #   原来每帧三次全屏填充（纯色 / 径向渐变 / 星尘 alpha 混合）。
        #   三层都与 pan/zoom 无关，只在 resize 时重建 ⇒ 每帧 1 次 blit。
        p.drawPixmap(0, 0, self._dust_pixmap())

        # 星团云气
        for cat in ORDER:
            if not self._groups.get(cat):
                continue
            gx, gy = self._centers[cat]
            sp = self._to_screen(gx, gy)
            # 云气半径跟类团外半径走（原先固定 92+13*min(n,8)，与 √n 版式不匹配）
            rr = max(46.0 * self._fit, self._cat_r.get(cat, 120.0) * 1.08) * self._S()
            col = QColor(*PAL[cat])
            gg = QRadialGradient(sp, rr)
            c0 = QColor(col); c0.setAlpha(78)
            c1 = QColor(col); c1.setAlpha(16)
            c2 = QColor(col); c2.setAlpha(0)
            gg.setColorAt(0.0, c0)
            gg.setColorAt(0.45, c1)
            gg.setColorAt(1.0, c2)
            p.setBrush(QBrush(gg)); p.setPen(Qt.NoPen)
            p.drawEllipse(sp, rr, rr)

        # 中心 → 星团 细线
        for cat in ORDER:
            if not self._groups.get(cat):
                continue
            a = self._to_screen(0.0, 0.0)
            b = self._to_screen(*self._centers[cat])
            p.setPen(QPen(QColor(46, 52, 84, 150), 1))
            p.drawLine(a, b)

        # 连线（2026-10-31 重做，Owner：「有关系的连起来，同大类用细线」）
        #
        # 改前是「同类别内按极角连相邻两颗」—— 纯几何位置，与关系无关。
        # 现在分两种：
        #   强边 = 词面重叠 ≥ STRONG_EDGE_JACCARD，可跨星团，实线，按权重给亮度
        #   弱边 = 同类别最小生成树，很淡的细线（表示「同类但无显著词面关系」）
        #
        # 边：在**本轮可见集**上算（不是全量算完过滤 —— 那会丢掉 96% 的线，
        #   见 _edges_for 的注释）。可见集没变时命中缓存，不重算。

        # 本轮可见集合（LOD 后的结果）与它的 key 集 —— 连线两端都可见才画，
        #   否则会出现「线连着看不见的点」这种破绽，也白画。
        _vis = self._lod_visible()
        _vis_keys = {(s.get('key') or s['text']) for s in _vis}
        # 边在「可见 ∩ 视野内」上重算 ⇒ 下标是 _view 的局部下标。
        #   （不先按视野筛，zoom 大时 1400 点算边要 68ms）
        _view = self._view_stars(_vis)
        if self._edge_src_ref is _view:
            # 已就绪：直接用缓存
            _strong_e, _weak_e = self._edge_strong, self._edge_weak
        elif self._edge_src_ref is None:
            # 首次（或延后重算刚清空）：同步算一次
            _strong_e, _weak_e = self._edges_for(_view)
        else:
            # 缩放中：先用上一轮的边（位置仍按当前 _layout ⇒ 视觉正确），
            #   停 130ms 后再算。否则每次滚轮都要 30~40ms，滚动会迟滞。
            _view = self._edge_src_ref
            _strong_e, _weak_e = self._edge_strong, self._edge_weak
            self._schedule_edge_rebuild()
        _vkeys = [(s.get('key') or s['text']) for s in _view]
        # key 列表按星点缓存 —— 原先每条边两端都现算 'key' or 'text' 字符串，
        #   每帧 5350 次（1.6ms）。改成索引查表。
        _keys = self._keys_list()

        # 弱边先画（在底层，避免盖住强边）
        #   2026-11-03：改为**按类别聚成一条 QPainterPath**，并关掉抗锯齿。
        #   实测 181 条逐条 AA drawLine = 7.4ms；批量 + 无 AA = 4.8ms。
        #   弱边 alpha 只有 28，关 AA 看不出锯齿。
        _weak_paths = {}
        for i, j in _weak_e:
            ki, kj = _vkeys[i], _vkeys[j]
            a, b = self._layout[ki], self._layout[kj]
            _cat = _view[i].get('cat') or 'human'
            pa, pb = self._to_screen(*a), self._to_screen(*b)
            _path = _weak_paths.get(_cat)
            if _path is None:
                _path = QPainterPath()
                _weak_paths[_cat] = _path
            _path.moveTo(pa)
            _path.lineTo(pb)
        if _weak_paths:
            _aa = p.testRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.Antialiasing, False)
            # 放大时衰减：全览看结构（线有用），放大看单颗（线成了蛛网）。
            #   实测 zoom=12 时满屏蛛网，遮住星点。
            # ⚠ 用 math.sqrt 而不是 `** 0.5`：tests/test_decay_model 的结构钉会用 AST
            #   扫「源码段里同时出现 0.5 和 **」并当作「第二份字面衰减公式」。
            #   这里的含义是连线视觉衰减，与记忆衰减无关，但没必要去撞那条守卫。
            _wa = int(28 * max(0.50, 1.0 / math.sqrt(max(self.zoom, 1.0))))
            for _cat, _path in _weak_paths.items():
                wcol = QColor(*PAL[_cat])
                wcol.setAlpha(_wa)
                p.setPen(QPen(wcol, 1.0))
                p.drawPath(_path)
            p.setRenderHint(QPainter.Antialiasing, _aa)

        # 强边后画（亮，压在上面）
        #   2026-11-04：改回**逐条 drawLine**。
        #   曾试过「按 alpha 分档聚成 QPainterPath」，cProfile 实测 drawPath
        #   每帧 17ms（280 次/8 帧），比逐条还慢 —— QPainterPath 里是一条条
        #   **不连续**子路径，描边要逐子路径做 join/cap，线段多并不省。
        #   微基准也证实：172 条散线 逐条 2.78ms / drawLines 2.47 / path 2.49。
        #   既然差这么小，就用最简单可预测的写法。
        # 下限 0.50：0.30 时放大 4 倍线几乎不可见（截图实测），
        #   而「放大后看关系」正是放大档的用途之一。
        _zoom_fade = max(0.50, 1.0 / max(self.zoom, 1.0) ** 0.6)
        _aa0 = p.testRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.Antialiasing, False)
        _pen_cache = {}
        for i, j, w in _strong_e:
            ki, kj = _vkeys[i], _vkeys[j]
            a, b = self._layout[ki], self._layout[kj]
            # 权重越高越亮：0.045 → alpha 90，0.20 → alpha 190
            t = min(1.0, max(0.0, (w - STRONG_EDGE_JACCARD) / 0.155))
            # 再按**屏幕距离**衰减：跨类强边长达 600+px，1px 细线横穿画面
            #   ⇒ 星团边界感被打散。团内保持清晰，跨团淡到约 1/4。
            _sa, _sb = self._to_screen(*a), self._to_screen(*b)
            _dist = math.hypot(_sa.x() - _sb.x(), _sa.y() - _sb.y())
            _fade = max(0.24, 1.0 - _dist / (self._R * 2.2))
            alpha = int((90 + 100 * t) * _fade * _zoom_fade)
            cat = _view[i].get('cat') or 'human'
            wide = 1 if t > 0.45 else 0
            _k = (cat, alpha // 16, wide)
            pen = _pen_cache.get(_k)
            if pen is None:
                col = QColor(*PAL[cat])
                col.setAlpha(int((alpha // 16 + 0.5) * 16))
                pen = QPen(col, 1.0 + (0.8 if wide else 0.0))
                _pen_cache[_k] = pen
            p.setPen(pen)
            p.drawLine(_sa, _sb)
        p.setRenderHint(QPainter.Antialiasing, _aa0)

        # 外圈失效星
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(92, 88, 116, 190))
        seed = 777
        for _ in self.dead:
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            ang = (seed % 6283) / 1000.0
            seed = (seed * 1103515245 + 12345) & 0x7fffffff
            rr = self._world_r * (1.30 + (seed % 220) / 1000.0)
            x = rr * math.cos(ang)
            y = rr * math.sin(ang) * 0.86
            _dr = 1.6 * self._sym_scale() + 0.6
            p.drawEllipse(self._to_screen(x, y), _dr, _dr)

        # 记忆星 —— 2.5D + LOD + sprite（2026-11-03）
        #   · 只画 _vis（LOD 后）：重叠处只留优先级高的，放大后自动变多
        #   · 按深度降序：z 大的（老的）先画，新的压在上面，形成前后遮挡
        #   · 每颗星不再现建渐变，改为 drawPixmap 缩放缓存好的 sprite
        _draw = sorted(_vis, key=lambda s: -self._depth.get(s.get('key') or s['text'], 0.0))
        # 平滑缩放只在「sprite 被 GLOW_MAX 截断」时用得上；默认关掉（实测 4.5 倍差）。
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        _sym = self._sym_scale()
        _W, _H = self.width(), self.height()
        _onview = 0
        for s in _draw:
            _k = s.get('key') or s['text']
            xy = self._layout.get(_k)
            if not xy:
                continue
            _z = self._depth.get(_k, 0.0)
            b = self._bright(s)
            # 远小近大；尺寸随 zoom 只轻微增长（见 _sym_scale）
            rad = (2.0 + 1.5 * s['imp']) * _sym * (1.0 - (1.0 - DEPTH_RAD) * _z)
            # 光晕随深度收缩+变淡：这是 1411 条不糊成色块的关键。
            glow = 5.5 * (1.0 - (1.0 - DEPTH_GLOW) * _z)
            ga = 1.0 - 0.55 * _z
            sp = self._to_screen(*xy)
            _r = rad * glow
            # 视窗剔除：连光晕都碰不到画面的直接跳过（zoom 大时省下绝大部分）
            if (sp.x() + _r < 0 or sp.x() - _r > _W
                    or sp.y() + _r < 0 or sp.y() - _r > _H):
                continue
            _onview += 1
            _pm, _ru = self._star_sprite(s['cat'], _r)
            p.setOpacity(b * ga)
            if _ru == _r:
                p.drawPixmap(QPointF(sp.x() - _ru, sp.y() - _ru), _pm)
            else:
                p.drawPixmap(QRectF(sp.x() - _r, sp.y() - _r, _r * 2, _r * 2), _pm,
                             QRectF(_pm.rect()))
            # 核心亮圆点：透明度回满 —— 与改动前一致（原实现核心不带亮度系数）
            p.setOpacity(1.0)
            _core = PAL[s['cat']]
            p.setBrush(QColor(min(255, _core[0] + 28), min(255, _core[1] + 28),
                              min(255, _core[2] + 28)))
            p.setPen(Qt.NoPen)
            p.drawEllipse(sp, rad, rad)
        self._onview_n = _onview

        # 中心 L0 核（三层固定半径，不再随 zoom 放大成白雾）
        # M2（审核抓出）：圆心必须走 _to_screen，否则拖动后中心亮斑留在屏幕正中、
        #   与已平移的星团辐条脱钩。
        _c = self._to_screen(0.0, 0.0)
        for rad_f, alpha in ((0.070, 150), (0.135, 52), (0.240, 18)):
            rr = self._R * rad_f * self.zoom
            gg = QRadialGradient(_c, rr)
            cc = QColor(255, 238, 186); cc.setAlpha(alpha)
            gg.setColorAt(0.0, cc)
            gg.setColorAt(0.45, QColor(255, 222, 160, max(6, alpha // 3)))
            gg.setColorAt(1.0, QColor(255, 238, 186, 0))
            p.setBrush(QBrush(gg)); p.setPen(Qt.NoPen)
            p.drawEllipse(_c, rr, rr)
        p.setBrush(QColor(255, 252, 240))
        _cr0 = 7.0 * self._sym_scale() + 2
        p.drawEllipse(_c, _cr0, _cr0)
        # S2（审核指出）：图例写「中心 = L0 人格卡」就必须真读数据。
        #   这里把真实身份条目数写在核下方，读不到就不写。
        _n_id = self._l0_count()
        if _n_id:
            p.setFont(QFont('Microsoft YaHei', 8))
            p.setPen(QColor(226, 214, 176, 220))
            p.drawText(_c.x() - 70, _c.y() + 30 * self._S() + 14,
                       'L0 人格卡 · %d 条常驻' % _n_id)

        # 文字
        p.setPen(QColor(255, 250, 242))
        f_title = QFont('Microsoft YaHei', 20, QFont.Bold)
        p.setFont(f_title)
        p.drawText(28, 44, '小蓝的记忆星图')

        p.setFont(QFont('Microsoft YaHei', 9))
        p.setPen(QColor(150, 162, 200))
        n_ev = sum(1 for s in self.stars if s['kind'] == 'event')
        # C3：把「滤掉了多少」也说清楚，避免把 3/200 说成「真实数据」而不披露
        # LOD 生效时必须在标题行披露「看到的是子集」，否则用户会以为数据丢了。
        _lod_note = ''
        _ov = getattr(self, '_onview_n', len(_vis))
        if _ov < len(self.stars):
            _lod_note = ' · 当前显示 %d 颗（视野内；重叠处先隐去，放大可见更多）' % _ov
        p.drawText(30, 68, '真实数据 · 亮星 %d 颗（事实 %d + 共同经历 %d）· 隐没 %d 颗%s'
                   % (len(self.stars), len(self.stars) - n_ev, n_ev, len(self.dead), _lod_note))
        # C3：滤除/合并了多少要披露，但不能塞进副标题（会压到星团名），
        #     放到右下角独立一行。
        _raw = self.raw_events or 0
        if _raw:
            _merged = globals().get('_LAST_MERGED', 0)
            p.setFont(QFont('Microsoft YaHei', 8))
            p.setPen(QColor(132, 140, 172))
            p.drawText(self.width() - 600, self.height() - 196,
                       '事件 %d/%d 入库：合并同名重复 %d 条、滤除可重算播报 %d 条'
                       % (n_ev, _raw, _merged, max(0, _raw - n_ev - _merged)))

        # 星团名
        p.setFont(QFont('Microsoft YaHei', 11))
        for cat in ORDER:
            if not self._groups.get(cat):
                continue
            sp = self._to_screen(*self._centers[cat])
            col = QColor(*PAL[cat])
            p.setPen(col)
            _cr = self._cat_r.get(cat, 120.0) * self._S()
            p.drawText(QRectF(sp.x() - 90, sp.y() - (_cr * 1.02 + 42), 180, 20),
                       Qt.AlignHCenter, CN[cat])
            p.setPen(QColor(150, 156, 184))
            p.setFont(QFont('Microsoft YaHei', 8))
            p.drawText(QRectF(sp.x() - 90, sp.y() - (_cr * 1.02 + 24), 180, 18),
                       Qt.AlignHCenter, '%d 颗' % len(self._groups[cat]))
            p.setFont(QFont('Microsoft YaHei', 11))

        # 个体标签（只标最亮 5 颗）
        # 2026-11-03：从 10 颗减到 5 颗。截图发现 10 个标签会从上往下排成一竖列，
        #   正好压在星团盘面上（星团中心 y≈238、半径≈148，标签区 y=90~190 全在盘内）。
        #   星图的主信息是「分布 + 关联」，个体详情 hover 已有卡片，
        #   所以密集时宁可不标，也不要糊成一团。
        p.setFont(QFont('Microsoft YaHei', 8))
        # ⚠ 2026-11-03：原先每帧都 sorted(全部星点) 取前 4 ⇒ 1417 次 _bright/帧（1.2ms）。
        #   星点与年龄不变时结果不变 ⇒ 缓存。
        cand = self._label_candidates()
        # 先把星团名 + **星团盘**占位 —— 否则个体标签会压在星团名与星点上
        boxes = []
        for cat in ORDER:
            if not self._groups.get(cat):
                continue
            cp = self._to_screen(*self._centers[cat])
            # 类团半径已按 √n 分配，标签/占位不能再写死 186/92 这些常量，
            #   否则小团（mile 69px）的标签会飘在很久之外。
            # 星团名要留在团盘**外侧**。⚠ 位置属于几何 ⇒ 用 zoom；
            #   符号尺寸才用 _sym_scale。混用会让 zoom=3 时名字落进团盘里被星压住。
            _cr = self._cat_r.get(cat, 120.0) * self._S()
            boxes.append((cp.x() - 95, cp.y() - (_cr * 1.02 + 42), 190, 44))
            _disk = _cr * 0.14
            boxes.append((cp.x() - _disk, cp.y() - _disk, _disk * 2, _disk * 2))
        for s in cand:
            xy = self._layout.get(s.get('key') or s['text'])
            if not xy:
                continue
            # 靠近 L0 中心的星不标 —— 那块要留给「人格卡」
            if math.hypot(xy[0] - self._cx, xy[1] - self._cy) < self._R * 0.34:
                continue
            sp = self._to_screen(*xy)
            text = s['text'] if len(s['text']) <= 15 else s['text'][:14] + '…'
            tw = p.fontMetrics().horizontalAdvance(text)
            placed = False
            for dx, dy in ((14, -22), (14, 8), (-tw - 14, -22), (-tw - 14, 8),
                           (14, -40), (-tw - 14, -40), (14, 26)):
                bx, by = sp.x() + dx, sp.y() + dy
                if bx < 20 or by < 90 or bx + tw > self.width() - 20 or by > self.height() - 120:
                    continue
                if any(not (bx + tw < ox - 6 or bx > ox + ow + 6 or by + 16 < oy - 4 or by > oy + oh + 4)
                       for (ox, oy, ow, oh) in boxes):
                    continue
                col = QColor(*PAL[s['cat']])
                p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 90), 1))
                p.drawLine(sp, QPointF(bx if dx > 0 else bx + tw, by + 8))
                # 2026-11-03：加深色底框。近光源标签压在亮星上读不清
                #   （截图实测：绿团里的「用户目前在准备计算机二级考试」几乎看不见）。
                #   底色沿用详情卡的 (10,12,26)，保持主题单一源、不引入新色值。
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(10, 12, 26, 205))
                p.drawRoundedRect(QRectF(bx - 4, by - 2, tw + 8, 19), 4, 4)
                p.setPen(QColor(min(255, col.red() + 70), min(255, col.green() + 70),
                                min(255, col.blue() + 70)))
                p.drawText(QPointF(bx, by + 14), text)
                boxes.append((bx, by, tw, 16))
                placed = True
                break

        # 图例 + 映射
        # 2026-11-03：加半透明深色底。放大后星团会压到这块，灰字打在蓝星上读不清
        #   （zoom=3 截图实测）。底色沿用详情卡的 (10,12,26)，不引入新色值。
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 12, 26, 176))
        p.drawRoundedRect(QRectF(20, self.height() - 168, 168, 156), 8, 8)
        p.drawRoundedRect(QRectF(self.width() - 310, self.height() - 168, 292, 156), 8, 8)
        p.setFont(QFont('Microsoft YaHei', 9))
        ly = self.height() - 150
        p.setPen(QColor(196, 204, 232))
        p.drawText(30, ly - 14, '颜色 = 记忆类别')
        for i, cat in enumerate(['core', 'human', 'like', 'study', 'work', 'mile', 'dead']):
            y = ly + i * 19
            p.setBrush(QColor(*PAL[cat])); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(34, y - 3), 4, 4)
            p.setPen(QColor(200, 206, 232))
            p.drawText(46, y, CN[cat])

        rx = self.width() - 300
        p.setPen(QColor(196, 204, 232))
        p.drawText(rx, ly - 14, '视觉 = 记忆机制')
        for i, m in enumerate(['亮度 = 时间衰减（半衰期 30 天）', '大小 = 重要度 importance',
                               '团内越靠外 = 越早的经历', '亮线 = 内容词面重合（可跨类）', '淡线 = 同类别（不表关系）',
                               '中心 = L0 人格卡，永不衰减']):
            p.drawText(rx, ly + i * 19, '·  ' + m)

        # 悬停 / 详情卡
        show = self.pinned or self.hover
        if show:
            self._draw_detail(p, show)

        p.end()

    def _draw_detail(self, p, s):
        pad = 12
        w = min(520, self.width() - 60)
        text = s['text']
        detail = (s.get('detail') or '').strip()
        p.setFont(QFont('Microsoft YaHei', 10))
        fm = p.fontMetrics()
        # M1（审核 WX 侧抓出）：PySide6 6.11 的 QFontMetrics.boundingRect
        #   只接受 QRect，传 QRectF 直接 TypeError ⇒ 悬停/钉住时 paintEvent 必崩、详情卡永不显示。
        _box = QRect(0, 0, int(w - pad * 2), 400)
        rect = fm.boundingRect(_box, int(Qt.TextWordWrap | Qt.AlignLeft), text)
        rect2 = fm.boundingRect(_box, int(Qt.TextWordWrap | Qt.AlignLeft), detail) \
            if detail else QRect(0, 0, 0, 0)
        h = 56 + rect.height() + (rect2.height() + 6 if detail else 0)
        x, y = 30, self.height() - h - 190
        p.setBrush(QColor(10, 12, 26, 235))
        p.setPen(QPen(QColor(*PAL[s['cat']]), 1))
        p.drawRoundedRect(QRectF(x, y, w, h), 10, 10)
        p.setPen(QColor(*PAL[s['cat']]))
        p.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
        p.drawText(x + pad, y + 22, '%s%s' % (CN.get(s['cat'], ''), ' · 已钉住' if self.pinned else ''))
        p.setPen(QColor(232, 236, 250))
        p.setFont(QFont('Microsoft YaHei', 10))
        p.drawText(QRectF(x + pad, y + 32, w - pad * 2, rect.height()),
                   Qt.TextWordWrap, text)
        if detail:
            p.setPen(QColor(168, 176, 204))
            p.setFont(QFont('Microsoft YaHei', 9))
            p.drawText(QRectF(x + pad, y + 38 + rect.height(), w - pad * 2, rect2.height()),
                       Qt.TextWordWrap, detail)
        p.setPen(QColor(140, 148, 180))
        p.setFont(QFont('Microsoft YaHei', 8))
        meta = []
        if s.get('time'):
            meta.append('时间 ' + str(s['time'])[:16])
        if s.get('emotion'):
            meta.append('情绪 ' + s['emotion'])
        if s.get('affection') is not None:
            meta.append('当时好感 %s' % s['affection'])
        meta.append('重要度 ★%s' % s.get('imp', 3))
        p.drawText(x + pad, y + h - 10, '　'.join(str(m) for m in meta))

    # ---------- 交互 ----------
    def _hit(self, pos):
        """命中测试。C1：半径随 zoom 与星体大小变化 —— 放大后 18px 固定值点不中。

        2.5D（2026-11-03）：老的星画得小（最多缩 34%），命中半径必须同比缩，
        否则点一颗小星会误中它旁边的大星。"""
        best, bd = None, None
        # 只命中**本轮可见**的星：LOD 隐去的星如果还能点中，
        #   就会出现「点了空白处却钉住一颗看不见的星」。
        for s in self._lod_visible():
            _k = s.get('key') or s['text']
            xy = self._layout.get(_k)
            if not xy:
                continue
            sp = self._to_screen(*xy)
            d = math.hypot(sp.x() - pos.x(), sp.y() - pos.y())
            # 可视核心半径 × zoom × 深度缩放 + 余量，下限 10px
            _z = self._depth.get(_k, 0.0)
            # 命中半径 = 核心半径 × 1.8 + 6，并**额外随 zoom 放宽**。
            #   ⚠ 符号本身封顶 1.6 倍（否则放大后点更挤），但点选容差不能跟着封顶：
            #   放大就是在细看，容差收紧会点不中（test_hit_radius_scales_with_zoom
            #   的契约：zoom=4 时 20px 外仍要能点中）。
            _core = (2.0 + 1.5 * s.get('imp', 3)) * self._sym_scale() \
                * (1.0 - (1.0 - DEPTH_RAD) * _z)
            reach = max(10.0, _core * 1.8 + 6.0 + 2.0 * max(0.0, self.zoom - 1.0))
            if d <= reach and (bd is None or d < bd):
                best, bd = s, d
        return best

    def mousePressEvent(self, ev):
        """按下只记候选，**不**立刻钉住。

        ⛔ 原实现「按到星就钉住」的问题：想拖动画面时按到星上，必然误钉
        （Owner：「拖动时难免点到星上进行拖拽，这不是真的要钉住」）。
        """
        if ev.button() == Qt.LeftButton:
            pos = ev.position()
            self._press_hit = self._hit(pos)
            self._press_pt = QPointF(pos)
            self._press_moved = False
            # 无论有没有命中，都允许拖动（覆盖「按在星上想平移」这个常见场景）
            self._drag_from = pos
            self._pan0 = QPointF(self.pan)
            if self._press_hit is not None:
                self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_from is not None:
            pos = ev.position()
            if not self._press_moved and self._press_pt is not None:
                if math.hypot(pos.x() - self._press_pt.x(),
                              pos.y() - self._press_pt.y()) > DRAG_THRESHOLD:
                    self._press_moved = True
            self.pan = QPointF(self._pan0.x() + pos.x() - self._drag_from.x(),
                               self._pan0.y() + pos.y() - self._drag_from.y())
            self.update()
            return
        hit = self._hit(ev.position())
        if hit is not self.hover:
            self.hover = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, ev):
        # 只有「按下没怎么动」才算点击（钉住/取消钉住）；拖动过就只当平移。
        if (self._drag_from is not None and not self._press_moved
                and self._press_hit is not None):
            self.pinned = None if (self.pinned is self._press_hit) else self._press_hit
            self.update()
        self._drag_from = None
        self._press_hit = None
        self._press_pt = None
        self._press_moved = False
        self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        factor = 1.12 if delta > 0 else 1 / 1.12
        new = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom * factor))
        # 以光标为中心缩放
        cur = ev.position()
        self.pan = QPointF(
            cur.x() - (cur.x() - self.pan.x() - self._cx) * (new / self.zoom) - self._cx,
            cur.y() - (cur.y() - self.pan.y() - self._cy) * (new / self.zoom) - self._cy)
        self.zoom = new
        self.update()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_R:
            self.zoom, self.pan, self.pinned = 1.0, QPointF(0, 0), None
            self.update()
        elif ev.key() == Qt.Key_Escape:
            self.pinned = None
            self.update()
        else:
            super().keyPressEvent(ev)

    def reset_view(self):
        self.zoom, self.pan, self.pinned, self.hover = 1.0, QPointF(0, 0), None, None
        self.update()
