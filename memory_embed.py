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
    cands = []
    if explicit:
        cands.append(('参数指定', explicit))
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
