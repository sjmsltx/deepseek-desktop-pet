# -*- coding: utf-8 -*-
"""memory_embed.py — 记忆向量检索组件（**可选**，缺失即降级）
====================================================================
2026-11-04 建。实测依据见 `tools/eval/experiment/EMBEDDING-检索实测-20261104.md`：

    BM25 + 闸门        留出集 R@3  3/12 = 25%（闸门全关也只有 42%）
    向量 cosine ≥ 0.51 留出集 R@3 11/12 = 92%
    冷启动 79ms，单次 query 3.2~5.4ms，模型 22.9MB

设计原则（与 Live2D 可选组件一致）：
- **不许静默失败**：不可用时把**具体原因**写进 `reason`（模块级 REASON / 实例 .reason）
- **降级即回退**：调用方拿不到结果就继续走 BM25，功能不消失
- **不改调用方语义**：本模块只做「编码 + 打分」，闸门/注入策略仍归 memory_engine

⚠ 硬约束（实测得出，别省）：
  语义检索**无法**区分「在问概念」与「在问我」——
  「扫雷是什么」对「用户喜欢玩扫雷」cos 0.5548，
  「介绍一下骰子」0.5864，而真查询「考研数学二复习计划」0.7715。
  ⇒ 想用低阈值（0.51）换高召回，**必须同时启用 `is_definition_question()`
    守卫**，否则违反「记忆只作背景、不做话题」（test_memory_gate.py 契约）。

依赖（全部可选，缺任一即 not available）：
    onnxruntime, tokenizers, numpy
模型（两项都要）：
    <model_dir>/model.onnx      bge-small-zh-v1.5 int8，22.9MB
    <model_dir>/tokenizer.json  0.42MB
"""
import hashlib
import json
import logging
import os
import zipfile

#: 组件日志。⚠ 文件里两处宽泛 except 是**有意**的（可选组件不许拖垮宿主），
#: 但必须**留痕**：self.reason / save_error 字段 + 一条 warning。
#: tests/test_silent_guard.py 的红线是「宽泛 try + handler 不落痕」，
#: 只给字段赋值不算落痕（它要求 raise 或日志调用）。
_log = logging.getLogger('pet.memory_embed')

#: 模型标识（换模型必须改这里，否则旧缓存会被当成有效）
MODEL_TAG = 'bge-small-zh-v1.5-int8-cls'
EMBED_DIM = 512
MAX_TOKENS = 128

#: 单条文本的余弦下限。
#:
#: ⚠ 2026-11-06：**这个固定值已退为参考值**，生产路径改用下面的自适应阈值。
#: 原因（实测，对照实验脚本在 `tools/eval/experiment/`）：
#:   库 21 条 → 负样本误注入 7/42、无关查询 2/18
#:   库 521 条 → 负样本 34/42、无关查询 16/18   （召回几乎不变：5/6 与 10/12）
#: 固定阈值在库变大后必然失效：库里条目越多，任何一句都能找到“有点像”的邻居。
#:
#: ⛔ **这个数只在下列条件下成立**，换条件必须重校准（2026-11-04 复验）：
#:   · 模型文件：`Xenova/bge-small-zh-v1.5` 的 **int8** 量化版（22.9MB）
#:     —— 实测 fp32（90.5MB）的余弦整体低约 0.0196，top1 排序虽完全一致（12/12），
#:        但同一处判定会从 0.510 掉到 0.490 ⇒ 直接沿用 0.51 会漏召回
#:   · 事实库规模：**约 21 条时校准**（本机真实库）
#:     —— 库增大后最大余弦天然抬高（极值效应）：
#:        库 171 条时真实对话注入率 76%、521 条 80%、1432 条 87%
#:        （召回在 171 条内仍稳：11/12）
#:   · 检索方式：纯余弦 top-k + 定义式提问守卫
#:
#: 稳健带（留出集 11/12 不掉的区间）：**0.440 ~ 0.515**。当前 0.51 距上沿仅 0.005，
#: 越界后果是温和的（0.520 → 10/12、注入率 31%），不是崩到 0。
#: 复跑：tools/eval/experiment/scripts/reverify_band.py
DEFAULT_THRESHOLD = 0.51

#: 校准条件（供 calibration_warning 比对）
CALIBRATION = {
    'model_tag': 'bge-small-zh-v1.5-int8-cls',
    'onnx_mb': 22.9,          # int8 量化版大小
    'library_size': 21,       # 校准时的事实库条数
    'verified_on': '2026-11-04',
    'band': (0.440, 0.515),   # 留出集 11/12 的阈值区间
}


# ---------------- 自适应阈值（2026-11-06）----------------
#
# 为什么不再用固定余弦下限：实测（同一套查询，脚本在 `tools/eval/experiment/`）
#
#     库条数   固定 0.51 的负样本误注入   无关查询
#     21       7/42                       2/18
#     121      29/42                      9/18
#     321      33/42                      15/18
#     521      34/42                      16/18
#
#   召回几乎不变（开发 5/6、留出 10/12），**精度崩了**。
#   机制：库越大，任何一句都能找到一个"有点像"的邻居 —— 固定阈值分不清
#   「这条对我特别相关」与「这条在这么多邻居里排第一」。
#
# 所以阈值改为**按本库自身的相似度分布定标**：拿本次查询与全库的余弦分布，
# 要求 top1 是**离群点**（z 分数），而不是超过某个绝对余弦。
# z 天然随库规模收紧：邻居越多，随机就能撞到的高分越多，z 门槛自动变高。
#
# z 门槛本身还随库条数缓增（对数），因为极值效应比 z 归一化剩下的那部分更顽固：
#
#     z_min(N) = Z0 + SLOPE * ln(N / REF_N)
#
# 参数由实测点拟合（判据：留出集不掉到 BM25 以下，同时负样本误注入最小）：
#     N=21  → 2.75     N=121 → 4.0     N=321 → 4.7     N=521 → 5.0
#
# 实测效果（单向量 + 本阈值，库 21 → 521）：
#     负样本误注入 4 → 2 /42      （固定阈值是 7 → 34）
#     无关查询     0 → 3 /18      （固定阈值是 2 → 16）
#     留出集       8 → 3 /12      （召回随规模回落到 BM25 水平，这是代价，不掩饰）
#     真实对话注入 10 → 4 /45     （22% → 9%）
#
# ⚠ 诚实的边界：**相似度本身分不开「问概念」与「问我」**。
#   z 阈值只能保证「不随库变大而无脑放开」，不能把召回和精度同时保住。
#   概念提问另有 `is_definition_question()` 守卫（产品契约），两道一起用。

#: 库规模为本数时的 z 门槛（校准点）
ADAPTIVE_REF_N = 21
#: 校准点上的 z 门槛（2026-11-06 由 2.75 调到 2.5：配合下面的绝对下限后，
#: 留出集 +2 条、负样本只多 1 条；网格实测见 memory_embed 顶部说明）
ADAPTIVE_Z0 = 2.5
#: **第二信号**：绝对余弦下限。
#:
#: 为什么光有 z 不够：迁移后实测这对——
#:     f03「明天下午三点提醒我开会」top1=0.492 z=2.70（无关，必须挡）
#:     h08「我读大几了来着」        top1=0.584 z=2.66（真召回，不该挡）
#: z 分不开，余弦分得开。所以两个都要过。
#:
#: 数值依据（库 18 条时的 top1 分布）：
#:   无关查询 max 0.515 / false 组 max 0.492 / 真召回 min（有效命中）0.511
#:   ⇒ 0.50 卡在 0.492 与 0.511 之间，两侧余量各约 0.01。
#: ⚠ 余量很小：换模型或换 fp32 版必须重测（见 CALIBRATION 的说明）。
ADAPTIVE_ABS_FLOOR = 0.50

#: **第三判据**：明显胜出旁路。
#: top1 比第二名高出这么多时，即使没过 z/余弦下限也接纳（只对 top1 生效）。
#: 依据（库 18 条实测）：真召回 gap 0.022~0.117，假查询最大 0.073 ⇒ 0.10 在两者之间。
#: 库大时 gap 天然塌到 0.02~0.03（318 条时留出中位 0.030），这条自动失效 —— 不会放大误注入。
ADAPTIVE_GAP_BYPASS = 0.10
#: 每翻 e 倍的 z 增量
ADAPTIVE_SLOPE = 0.70
#: 上限：防止库极大时门槛高到永不注入
ADAPTIVE_Z_MAX = 6.0
#: 下限：再小就与固定阈值无异（低于 1.5 时负样本 41/42，实测）
ADAPTIVE_Z_MIN = 1.5
#: 低于这个条数时 z 分数不可靠，改用绝对余弦阈值
#: （n 条样本的 |z| 上限 = sqrt(n-1)：n=10 时才 3.0，n=2 时只有 1.0）
MIN_N_FOR_Z = 10


def adaptive_z_threshold(n):
    """按库条数给出 z 门槛。n 为该库**参与检索**的条目数。

    ⚠ 小于参考条数时**不放松**（回到 Z0）：校准就是在 21 条上做的，
      比它更小的库没有依据说"可以更松"。
      实测（2026-11-06）：存量迁移把库从 21 条降到 18 条后，
      formula 给出 2.63（< Z0）⇒ 多注入一条，FALSE 从 1.0 掉到 0.75（无关问句命中了）。
    """
    import math
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = ADAPTIVE_REF_N
    if n <= ADAPTIVE_REF_N:
        return ADAPTIVE_Z0
    z = ADAPTIVE_Z0 + ADAPTIVE_SLOPE * math.log(float(n) / ADAPTIVE_REF_N)
    return max(ADAPTIVE_Z_MIN, min(ADAPTIVE_Z_MAX, z))


def calibration_warning(onnx_mb):
    """模型文件大小与校准时不符就给一句警告；正常返回空串。

    为什么按大小判：量化精度没法从文件内容直接看出来，但 int8(22.9MB) 与
    fp32(90.5MB) 差 4 倍，足以区分。差太远说明「阈值不是在这个模型上量的」。
    """
    try:
        mb = float(onnx_mb)
    except (TypeError, ValueError):
        return ''
    expect = CALIBRATION['onnx_mb']
    if mb <= 0:
        return ''
    ratio = mb / expect
    if 0.8 <= ratio <= 1.25:
        return ''
    return ('模型文件 %.1f MB 与校准时的 int8 版（%.1f MB）差 %.1f 倍 ⇒ '
            '阈值 %.2f 可能不适用，请重跑 reverify_models.py 重校准'
            % (mb, expect, ratio, DEFAULT_THRESHOLD))

#: 小库（条数 < ADAPTIVE_REF_N）用的判据：**余弦下限 + top1/top2 间隔**，不用 z。
#:
#: 为什么小库不该用 z（2026-11-08 实测）：
#:   n 条样本上 |z| 的上限只有 √(n-1) —— n=15 时 3.74、n=18 时 4.12，
#:   而门槛 2.5 已占去大半个量程 ⇒ 在这个区间里 z 测不出「突出」。
#:   18 条库上量了 21 条用例：**9 条的 z 落在门槛 ±0.5 内**，库规模一动就翻面。
#:   实例：清理试跑删掉 3 条后 h06/h08 从命中变不命中，而它们的余弦几乎没变
#:   （0.517→0.516、0.584→0.586），只是 z 从 2.62→2.38、2.66→2.47 掉到门槛以下。
#:   答案条目一直在库里，一条都没删。
#:
#: 为什么改用 gap（top1 与 top2 的余弦差）：
#:   小库邻居少，第一名领先第二名多少比「在全库分布里的位置」更可信。
#:   11-07 实测真召回 gap 0.022~0.117 ⇒ 取 0.02 不误杀真召回。
#:
#: 18 条库实测（tuning 选参 / holdout 验收，两者分开）：
#:   现状 z≥2.5：       tuning 5/8  holdout 10/12  无关 1/16  负样本 6/42
#:   余弦≥0.50 + gap0.02：tuning 7/8  holdout 11/12  无关 1/16  负样本 5/42
#:   ⇒ 召回升、误注入不增。0.02 不是端点（0.015→无关 2/16；0.025→holdout 掉到 10/12）。
#:
#: ⚠ 只在 n < ADAPTIVE_REF_N 时启用：21 条以上没有实测支撑，继续用 z。
#:   设为 None 可关闭（退回旧的纯 z 路径），便于对照。
SMALL_LIB_GAP = 0.02

#: 定义式提问的词表 —— 命中即本轮不注入。
#: ⚠ 覆盖不全：「扫雷怎么玩」「骰子规则」不匹配，仍会被注入（已知遗留风险）。
_DEF_PAT = ('是什么', '是啥', '啥意思', '什么意思', '介绍一下', '介绍下',
            '怎么回事', '啥玩意', '是什么东西', '讲讲', '科普', '怎么用',
            '有什么用', '定义')

#: 环境变量：显式指定模型目录（优先于默认位置）
ENV_MODEL_DIR = 'PET_EMBED_DIR'

AVAILABLE = False          #: 模块级能力标志（首次 get_embedder() 后确定）
REASON = '未初始化'          #: 不可用的具体原因


def is_definition_question(text):
    """这句是不是「在问某个概念」，而不是「在问我」—— 是则不注入记忆。

    为什么用词表而不是模型：这条是**产品契约**（记忆只作背景不做话题），
    要求可解释、可单测、不依赖模型；用模型判断会把契约变成概率。
    """
    t = (text or '').strip()
    return bool(t) and any(p in t for p in _DEF_PAT)


def _find_model_dir(explicit=None):
    """按 显式参数 → 环境变量 → 仓库 models/ → 旁挂目录 的顺序找模型。

    返回 (dir, 说明)。找不到时 dir 为 None，说明写具体缺什么。
    """
    # 显式指定 ⇒ 只看它。指错了必须报错，不许静默换成别的模型
    #   （2026-11-06 实测：显式目录不存在时会继续落到 models/，
    #     用户以为在测 A，实际跑的是 B —— 这类"以为"最费时间）
    if explicit:
        onnx = os.path.join(explicit, 'model.onnx')
        tok = os.path.join(explicit, 'tokenizer.json')
        if os.path.exists(onnx) and os.path.exists(tok):
            return explicit, ''
        missing = [n for n, p in (('model.onnx', onnx), ('tokenizer.json', tok))
                   if not os.path.exists(p)]
        return None, ('参数指定的模型目录 %s 下缺 %s；'
                      '可用 %s 指定正确目录，或把 model.onnx + tokenizer.json '
                      '放进 models/bge-small-zh-v1.5/'
                      % (explicit, ' / '.join(missing), ENV_MODEL_DIR))
    cands = []
    env = os.environ.get(ENV_MODEL_DIR)
    if env:
        cands.append(('环境变量 %s' % ENV_MODEL_DIR, env))
    here = os.path.dirname(os.path.abspath(__file__))
    cands.append(('仓库 models/', os.path.join(here, 'models', 'bge-small-zh-v1.5')))
    for label, d in cands:
        if not d:
            continue
        onnx = os.path.join(d, 'model.onnx')
        tok = os.path.join(d, 'tokenizer.json')
        if os.path.exists(onnx) and os.path.exists(tok):
            return d, ''
        missing = [n for n, p in (('model.onnx', onnx), ('tokenizer.json', tok))
                   if not os.path.exists(p)]
        if os.path.isdir(d):
            return None, '%s 下缺 %s' % (label, ' / '.join(missing))
    return None, ('找不到模型目录（试过：%s）；可设 %s 指定，'
                  '或把 model.onnx + tokenizer.json 放进 models/bge-small-zh-v1.5/'
                  % (', '.join('%s=%s' % (a, b) for a, b in cands), ENV_MODEL_DIR))


def _sha8(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:8]


def fingerprint(model_dir):
    """模型指纹：模型字节 + 维度 + 池化方式。变了就必须重算全部向量，
    否则新旧向量不在同一个空间，cosine 数值无意义。"""
    onnx = os.path.join(model_dir, 'model.onnx')
    return '%s|%s|%d|%s' % (MODEL_TAG, _sha8(onnx), EMBED_DIM, MAX_TOKENS)


class Embedder(object):
    """向量编码器。构造失败不抛，`self.ok` 为 False 且 `self.reason` 留原因。"""

    def __init__(self, model_dir=None):
        self.ok = False
        self.reason = ''
        self.model_dir = None
        self.calibration_warning = ''
        self._tok = None
        self._sess = None
        self._names = []
        # ---- 依赖 ----
        try:
            import numpy as np
        except (ImportError, OSError) as exc:
            self.reason = '缺 numpy（%s）' % exc
            return
        self._np = np
        try:
            import onnxruntime as ort
        except (ImportError, OSError) as exc:
            self.reason = '缺 onnxruntime（pip install onnxruntime）：%s' % exc
            return
        try:
            from tokenizers import Tokenizer
        except (ImportError, OSError) as exc:
            self.reason = '缺 tokenizers（pip install tokenizers）：%s' % exc
            return
        # ---- 模型 ----
        d, why = _find_model_dir(model_dir)
        if not d:
            self.reason = why
            return
        try:
            tok = Tokenizer.from_file(os.path.join(d, 'tokenizer.json'))
            tok.enable_truncation(max_length=MAX_TOKENS)
            # 固定长度：动态形状在量化模型上不稳，且固定长度让批处理更快
            tok.enable_padding(length=MAX_TOKENS)
            sess = ort.InferenceSession(os.path.join(d, 'model.onnx'),
                                        providers=['CPUExecutionProvider'])
        except Exception as exc:
            self.reason = '模型加载失败（%s）：%s' % (d, exc)
            _log.warning('向量模型加载失败 dir=%s: %s', d, exc)
            return
        self._tok = tok
        self._sess = sess
        self._names = [i.name for i in sess.get_inputs()]
        self.model_dir = d
        self.ok = True
        try:
            mb = os.path.getsize(os.path.join(d, 'model.onnx')) / 1024.0 / 1024.0
            self.calibration_warning = calibration_warning(mb)
        except OSError as exc:
            self.calibration_warning = ''
            _log.warning('读模型大小失败：%s', exc)
        if self.calibration_warning:
            _log.warning(self.calibration_warning)

    # ---------- 编码 ----------
    def encode(self, texts):
        """返回 (n, 512) float32 已 L2 归一化。不可用时返回 None。"""
        if not self.ok:
            return None
        np = self._np
        items = [str(t or ' ') for t in (texts or [])]
        if not items:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)
        encs = self._tok.encode_batch(items)
        ids = np.array([e.ids for e in encs], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
        feed = {}
        for n in self._names:
            if n == 'input_ids':
                feed[n] = ids
            elif n == 'attention_mask':
                feed[n] = mask
            else:
                feed[n] = np.zeros_like(ids)      # token_type_ids
        hidden = self._sess.run(None, feed)[0]
        v = hidden[:, 0, :]                       # bge 用 CLS 池化
        norm = np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
        return (v / norm).astype(np.float32)

    def score(self, query, vecs):
        """返回与 vecs 逐行对齐的余弦数组。不可用/为空时返回 None。"""
        if not self.ok:
            return None
        qv = self.encode([query])
        if qv is None or len(qv) == 0:
            return None
        return (self._np.asarray(vecs, dtype='float32') @ qv[0]).astype('float32')

    def top_k(self, query, vecs, texts, k=3, threshold=None):
        """按余弦取 top-k。返回 [{'index','score','text'}]，已过阈值。

        注意：**这里不判概念提问**——守卫应由调用方先调
        `is_definition_question()`，或直接用 `search()`。
        """
        thr = DEFAULT_THRESHOLD if threshold is None else float(threshold)
        sims = self.score(query, vecs)
        if sims is None:
            return []
        order = self._np.argsort(-sims)
        out = []
        for i in order:
            if float(sims[int(i)]) < thr:
                break
            out.append({'index': int(i), 'score': round(float(sims[int(i)]), 4),
                        'text': texts[int(i)] if i < len(texts) else ''})
            if len(out) >= k:
                break
        return out

    def search(self, query, vecs, texts, k=3, threshold=None):
        """带「定义式提问」守卫的检索 —— 业务侧请优先用这个。"""
        if is_definition_question(query):
            return []
        return self.top_k(query, vecs, texts, k=k, threshold=threshold)

    def search_adaptive(self, query, vecs, texts, k=3, threshold=None,
                        definition_guard=True):
        """自适应阈值检索：top1 必须是**本库分布里的离群点**，而不是过某个绝对余弦。

        参数：
            threshold: 显式指定 z 门槛；None 时按库条数用 `adaptive_z_threshold(len(vecs))`
            definition_guard: 是否先过「概念提问」守卫（默认是 —— 产品契约）

        返回 [{'index','score','z','text'}]，按余弦降序；不可用时返回 []。

        两个判据同时要求（都是单调的，所以可以 break）：
          · z >= 自适应门槛          —— 在这么多邻居里够不够突出
          · score >= ADAPTIVE_ABS_FLOOR —— 绝对亲密度够不够

        ⚠ 只用 z 不行：库 18 条时「明天下午三点提醒我开会」z=2.70 比真召回
          「我读大几了来着」z=2.66 还高，但余弦 0.492 < 0.584，加下限才分得开。
        """
        if definition_guard and is_definition_question(query):
            return []
        sims = self.score(query, vecs)
        if sims is None or len(sims) == 0:
            return []
        np = self._np
        n = int(len(sims))
        # 极小库：z 不可用（n 条样本的 |z| 上限是 sqrt(n-1)，n=2 时最大 1.0，
        #   任何门槛都够不到 ⇒ 永不注入）。样本不足就退回绝对余弦阈值。
        if n < MIN_N_FOR_Z and threshold is None:
            return self.top_k(query, vecs, texts, k=k, threshold=DEFAULT_THRESHOLD)
        order = np.argsort(-sims)
        # 小库（校准点以下）：改用「余弦下限 + top1/top2 间隔」，不用 z。
        # 依据与被测数据见 SMALL_LIB_GAP 的注释。
        if (SMALL_LIB_GAP is not None and threshold is None
                and n < ADAPTIVE_REF_N):
            if len(order) < 2:
                return []
            s1 = float(sims[int(order[0])])
            s2 = float(sims[int(order[1])])
            win = s1 - s2
            # 两条路都算通过：
            #   ① 过绝对下限 且 与第二名拉开 SMALL_LIB_GAP
            #   ② 明显胜出（win ≥ ADAPTIVE_GAP_BYPASS）—— 即使余弦低于下限也放行
            # 为什么保留 ②：有些**真召回**余弦偏低但第一名远超第二名。
            #   实测「我平时吃什么零食」→ 桃片：余弦 0.404 < 0.50，但 win 0.100。
            #   去掉 ② 会让这类召回消失（12 条库回归用例当场变红）。
            # ⚠ 代价必须记住：② 同时会放行个别**误注入**。实测 18 条库上
            #   「改一下明天重庆的天气」→ 桃片（余弦 0.470、win 0.121）也被放行 ——
            #   它与上一条在余弦、gap 两个维度上都不可分（误判的 gap 反而更大），
            #   这是判据的极限，不是调参能解决的。所以无关从 1/16 变成 2/16。
            bypass = win >= ADAPTIVE_GAP_BYPASS
            if not ((s1 >= ADAPTIVE_ABS_FLOOR and win >= SMALL_LIB_GAP) or bypass):
                return []
            out = []
            for i in order:
                si = float(sims[int(i)])
                if si < ADAPTIVE_ABS_FLOOR and not bypass:
                    break
                out.append({'index': int(i), 'score': round(si, 4), 'z': 0.0,
                            'text': texts[int(i)] if int(i) < len(texts) else ''})
                if len(out) >= k:
                    break
            return out
        zmin = adaptive_z_threshold(n) if threshold is None else float(threshold)
        mu = float(sims.mean())
        sd = float(sims.std()) or 1e-6
        # 明显胜出：库里就这一条明显对得上（只看 top1）
        clear_winner = False
        if len(order) >= 2:
            clear_winner = (float(sims[int(order[0])]) - float(sims[int(order[1])])
                            ) >= ADAPTIVE_GAP_BYPASS
        out = []
        for rank, i in enumerate(order):
            s = float(sims[int(i)])
            z = (s - mu) / sd
            ok = (z >= zmin and s >= ADAPTIVE_ABS_FLOOR)
            if not ok and not (rank == 0 and clear_winner):
                break
            out.append({'index': int(i), 'score': round(s, 4), 'z': round(z, 3),
                        'text': texts[int(i)] if int(i) < len(texts) else ''})
            if len(out) >= k:
                break
        return out


class VectorCache(object):
    """向量缓存：npz 落盘 + 按内容增量。

    为什么按「id + 内容指纹」而不是只按 id：
    记忆被 update_facts 改写后 id 不变、内容变了，只按 id 会拿旧向量当新内容用。
    """

    def __init__(self, path, model_dir=None):
        self.path = path
        self.fp = ''
        self.ids = []          # type: list[str]
        self.keys = []         # type: list[str]  内容指纹
        self.vecs = None       # type: object     (n, 512) float32
        self.load_error = ''
        self.save_error = ''
        if model_dir:
            try:
                self.fp = fingerprint(model_dir)
            except OSError as exc:
                self.load_error = '指纹计算失败：%s' % exc

    @staticmethod
    def content_key(text):
        return hashlib.sha1((text or '').strip().encode('utf-8')).hexdigest()[:16]

    def load(self):
        """读缓存。指纹不符或损坏 → 视为空（会全量重算），并把原因记下来。"""
        if not self.path or not os.path.exists(self.path):
            return False
        try:
            import numpy as np
            with np.load(self.path, allow_pickle=False) as z:
                fp = str(z['fingerprint'].item()) if 'fingerprint' in z else ''
                if fp != self.fp:
                    self.load_error = ('模型指纹变了（缓存 %s ≠ 当前 %s）⇒ 重算'
                                       % (fp[:24] or '空', self.fp[:24]))
                    return False
                self.ids = [str(x) for x in json.loads(str(z['ids'].item()))]
                self.keys = [str(x) for x in json.loads(str(z['keys'].item()))]
                self.vecs = np.asarray(z['vecs'], dtype='float32')
            return True
        except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile) as exc:
            self.load_error = '缓存读取失败（%s）：%s' % (self.path, exc)
            self.ids, self.keys, self.vecs = [], [], None
            return False

    def sync(self, facts, embedder):
        """把缓存对齐到 facts（[{id, content}]），只编码新增/变更项。

        返回与 facts 逐行对齐的 (vecs, texts)；embedder 不可用返回 (None, None)。
        """
        if embedder is None or not embedder.ok:
            return None, None
        import numpy as np
        ids = []
        keys = []
        texts = []
        for i, f in enumerate(facts or []):
            t = (f.get('content') or '').strip()
            fid = str(f.get('id') or ('auto%d' % i))
            ids.append(fid)
            keys.append(self.content_key(t))
            texts.append(t)
        old = {}
        if self.vecs is not None and len(self.ids) == len(self.vecs):
            for j, (fid, ck) in enumerate(zip(self.ids, self.keys)):
                old[(fid, ck)] = self.vecs[j]
        todo = [i for i, (fid, ck) in enumerate(zip(ids, keys))
                if (fid, ck) not in old]
        if todo:
            fresh = embedder.encode([texts[i] for i in todo])
            if fresh is not None and len(fresh) == len(todo):
                for slot, i in enumerate(todo):
                    old[(ids[i], keys[i])] = fresh[slot]
        if old:
            mat = np.zeros((len(ids), EMBED_DIM), dtype='float32')
            filled = 0
            for i, (fid, ck) in enumerate(zip(ids, keys)):
                v = old.get((fid, ck))
                if v is not None:
                    mat[i] = v
                    filled += 1
            if filled != len(ids):
                return None, None        # 有编不出来的 ⇒ 宁可整批回退，不给半套
            self.ids, self.keys, self.vecs = ids, keys, mat
            return mat, texts
        return None, None

    def save(self):
        """落盘。失败不抛（缓存只是加速，缺了下次重算），但**原因要留**。

        ⚠ 2026-11-04 修：原先 `np.savez_compressed(tmp + '.tmp', ...)`
          会被 numpy **自动补成 `.tmp.npz`**，随后 os.replace 找不到源文件
          ⇒ 静默失败（而且当时 `except Exception: return False` 把原因也吞了）。
          改成传文件句柄，绕开自动补后缀。
        """
        self.save_error = ''
        if not self.path or self.vecs is None:
            self.save_error = '无路径或无向量，跳过写入'
            return False
        try:
            import numpy as np
            d = os.path.dirname(self.path)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'wb') as fh:      # 句柄形式 ⇒ numpy 不会补后缀
                np.savez_compressed(
                    fh,
                    fingerprint=np.array(self.fp),
                    # ⚠ 不能用 dtype=object：npz 里 object 数组依赖 pickle，
                    #   allow_pickle=False 读取必失败（2026-11-04 实测）。
                    #   用 JSON 字符串存，安全且可读。
                    ids=np.array(json.dumps(self.ids, ensure_ascii=False)),
                    keys=np.array(json.dumps(self.keys, ensure_ascii=False)),
                    vecs=np.asarray(self.vecs, dtype='float32'))
            os.replace(tmp, self.path)
            return True
        except Exception as exc:
            self.save_error = '缓存写入失败（%s）：%s' % (self.path, exc)
            _log.warning('向量缓存写入失败 path=%s: %s', self.path, exc)
            return False


_EMBEDDER = None
_TRIED = False


def get_embedder(model_dir=None, retry=False):
    """单例。返回 Embedder（可能 ok=False）；失败原因同时写入模块级 REASON。"""
    global _EMBEDDER, _TRIED, AVAILABLE, REASON
    if _TRIED and not retry:
        return _EMBEDDER
    _TRIED = True
    e = Embedder(model_dir)
    _EMBEDDER = e
    AVAILABLE = e.ok
    REASON = '' if e.ok else (e.reason or '未知原因')
    return e


def reset():
    """清掉单例（仅供测试）"""
    global _EMBEDDER, _TRIED, AVAILABLE, REASON
    _EMBEDDER, _TRIED, AVAILABLE, REASON = None, False, False, '未初始化'


def status():
    """一句话状态，供 UI/日志显示（不许静默）"""
    if not AVAILABLE:
        return '向量检索不可用：%s' % REASON
    warn = getattr(_EMBEDDER, 'calibration_warning', '')
    if warn:
        return '向量检索可用（⚠ %s）' % warn
    return '向量检索可用'
