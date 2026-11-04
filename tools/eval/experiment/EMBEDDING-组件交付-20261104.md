# memory_embed 组件交付（2026-11-04）

> 生成时间：2026-11-04 11:24
> 依据：`EMBEDDING-检索实测-20261104.md`（实测通过，Owner 已授权「符合预期则按你建议」）
> 范围：**只建组件，不接产品检索**。接线会改注入行为，需单独一批 + 单独验证。

---

## 一、做了什么

| 文件 | 行数 | 作用 |
|---|---|---|
| `memory_embed.py` | 约 380 | 向量编码 + 缓存 + 检索 + 定义式提问守卫 |
| `tests/test_memory_embed.py` | 约 250 | 23 项测试（降级段 10 项恒可跑，能力段 13 项需模型） |

**产品代码零改动**：`memory_engine.py`、`desktop_pet.py` 一行没动。
检索仍走 BM25 + 闸门，现网行为不变。

---

## 二、接口（最小面）

```python
import memory_embed as mem

mem.get_embedder(model_dir=None)      # 单例；失败不抛，原因在 e.reason / mem.REASON
mem.status()                          # '向量检索可用' / '向量检索不可用：<具体原因>'
mem.is_definition_question('扫雷是什么')  # True → 本轮不注入

e = mem.get_embedder()
e.ok                                  # 能力标志
e.encode(texts)      -> (n,512) float32 | L2 归一化 | None
e.score(query, vecs) -> np.ndarray    | None
e.top_k(query, vecs, texts, k=3, threshold=0.51)    # 不判概念提问
e.search(query, vecs, texts, k=3, threshold=0.51)   # ★ 带守卫，业务侧用这个

c = mem.VectorCache(path, e.model_dir)
c.load()                  # 指纹不符/损坏 → False（会重算），原因在 c.load_error
c.sync(facts, e)          # 只编码新增/变更 → (vecs, texts) 逐行对齐 | (None,None)
c.save()                  # 失败不抛，原因在 c.save_error
```

---

## 三、四条设计约束（对着实测结论写的，不是凭感觉）

### 3.1 不许静默失败

项目对 Live2D 有过教训：三处 `except: return None` 把原因吞了，调用方只能给笼统话术。
所以这里**每个失败点都留原因**：

| 字段 | 内容 |
|---|---|
| `Embedder.reason` | 缺哪个依赖（numpy/onnxruntime/tokenizers）／缺哪个模型文件／加载异常原文 |
| `VectorCache.load_error` | 指纹变了（附新旧指纹前 24 字）／读取异常 |
| `VectorCache.save_error` | 写入路径 + 异常原文 |
| `mem.REASON` / `mem.status()` | 一句话，可直接显示在 UI 或日志 |

### 3.2 缓存按「id + 内容指纹」，不只按 id

`update_facts` 改写记忆时 **id 不变、内容变了**。只按 id 会拿旧向量当新内容用。
所以 key = `sha1(内容)[:16]`，id 与 key 都对上才复用。

### 3.3 模型指纹不符必须全量重算

指纹 = `模型标签 | sha256(model.onnx)[:8] | 维度 | 截断长度`。
换模型但沿用旧缓存 ⇒ 新旧向量不在同一空间，cosine 数值无意义（能算出 0.9 但毫无含义）。
指纹不符时 `load()` 返回 False 并把差异写进 `load_error`。

### 3.4 宁可整批回退，不给半套

`sync()` 里只要有一条编码不出来，返回 `(None, None)` ⇒ 调用方整体回退 BM25。
不给「一半有向量一半没有」的错位结果（错位比没有更危险）。

---

## 四、验证记录

### 4.1 单测

```
C:\Users\lby13\AppData\Local\Python\pythoncore-3.14-64\python.exe -m pytest tests\test_memory_embed.py -q
23 passed in 2.14s        （0 skipped —— 能力段真跑了模型）
```

降级段（不需要模型，恒可跑）10 项：不可用原因具体、返回 None 不抛、状态不静默、
守卫正反例、已知缺口、内容指纹、缓存指纹失配、缓存缺失安静。
能力段（需模型）13 项：形状与归一化、**语义方向**、留出集命中、守卫生效、
缓存往返与增量（断言「只编码 2 条」）、目录自动创建。

⚠ 第一版跑出来是 `17 passed, 6 skipped` —— 6 个能力测试全 skip 却显示「通过」。
原因是 fixture 没把找到的模型目录传进去。**skip 也是没验证**，报绿前必须看 skipped 数。

### 4.2 端到端（用组件本身跑，不是只看单测）

```
21 条真实库，留出集 12 条：
BM25   3/12 = 25%
组件   11/12 = 92%
```

与实验脚本（`probe_vector_grid.py` 的 0.51 档：5/6 dev、11/12 hold）完全一致
⇒ 组件行为和已验证的实验行为对得上。

### 4.3 缓存效果

```
首次：21 条编码 45 ms → 写盘（tools/eval/experiment/_embed_probe/mem_vec.npz）
冷启动：280 ms（含全量 sha256 指纹 ~200ms）；之后 query 3.2~5.4 ms
```

### 4.4 全量（干净口径）

```
HEAD 跑前 f2481d9 → 跑后 f2481d9（树未变）

python -m pytest -q
2332 passed, 11 skipped in 603.51s (0:10:03)
```

对照本轮改动前的基线 `2305 passed / 11 skipped`：
**+27 全是我新增的组件测试（23 + 4 项校准），skipped 仍是 11 项 ⇒ 零回归。**

⚠ 中间有两轮不算数：
- `2 failed, 2326 passed, 11 skipped` —— 产品守卫 `test_silent_guard` 抓到我新写的
  宽泛 try（详见第五节），已按守卫要求改自己的代码
- `2328 passed` —— 那是加校准告警前的口径
上面这行 `2332` 才是最新干净口径。

---

## 五、阈值 0.51 已经过复验（2026-11-04）

Owner 要求「复验」后，对 0.51 做了四重检验，结果与修正见
`EMBEDDING-复验-20261104.md`。要点：

| 复验项 | 结果 |
|---|---|
| 样本精度 | 11/12 = 92%，95%CI **[65%, 99%]**（与 BM25 的 [9%, 53%] 不重叠）|
| 稳健带 | 0.440 ~ 0.515；**当前向上只余 0.005**（越界后果温和：0.52 → 10/12）|
| 换量化 | top1 排序 12/12 一致，但 fp32 余弦**一致低约 0.010**（幅度 0.003~0.028 不齐）|
| 库变大 | 171 条时召回仍 11/12，但**注入率 36% → 76%**；1432 条时 87%（极值效应）|

因此代码里把 `DEFAULT_THRESHOLD` 改成了**带条件的常量**，并新增运行期自检
`calibration_warning()`（模型文件大小与校准时差 >25% 就告警，`status()` 会带出）。

新增 4 项校准测试，其中 `test_calibration_band_is_documented` 断言
「当前阈值必须落在记录的稳健带内」，防止以后改阈值不同步改文档。

---

## 六、本轮修的四个真 bug（都是自己写的）

| # | 症状 | 根因 | 修法 |
|---|---|---|---|
| 1 | `save()` 返回 False | `np.savez_compressed('x.tmp', ...)` 会自动补 `.npz` ⇒ `os.replace('x.tmp', ...)` 找不到源文件 | 传文件句柄，绕开自动补后缀 |
| 2 | 上面那个「静默」 | `except Exception: return False` 把原因吞了 | 改 `save_error`，留原文 |
| 3 | `load()` 读不回来 | `dtype=object` 数组在 npz 里依赖 pickle，`allow_pickle=False` 必失败 | 改 JSON 字符串存 ids/keys |
| 4 | 全量红 2 项 | 产品守卫 `test_silent_guard` 抓到我 7 处宽泛 try（2 处 `broad-swallow` + 5 处 `silent-default`） | 见下 |

第 1、2 条正是项目反复批评的形状：**先让失败静默，再花时间猜原因**。
第 3 条说明「写进去」和「读出来」必须成对验证，只测 save 不算。

### 5.1 被守卫抓到之后怎么改的（没有动守卫）

守卫的红线是：**宽泛 try（try 体 ≥4 句或宽泛异常）＋ handler 不落痕**。
「落痕」的判据是 handler 里出现 `raise` 或 `_silent_log` / `log` / `warning` 等调用 ——
**只给字段赋值不算**（我原来写 `self.reason = …` 就撞在这条上）。

处置原则：**改自己的代码，不放宽守卫**（项目规矩）。

| 位置 | 捕获的失败类型 | 改法 |
|---|---|---|
| numpy / onnxruntime / tokenizers 导入 | 找不到模块 / dll 损坏 | 窄化 `(ImportError, OSError)` |
| 模型指纹计算 | 文件读不了 | 窄化 `OSError` |
| 缓存读取（npz 是 zip 包） | 文件/格式/键缺失/截断/坏包 | 窄化 `(OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile)` |
| **模型加载** | 不可枚举（tokenizer 解析、onnx 图优化、provider 初始化…） | 保留 `Exception`，**加 `_log.warning` 落痕** |
| **缓存写入** | 不可枚举（磁盘满、权限、序列化…） | 保留 `Exception`，**加 `_log.warning` 落痕** |

**为什么两处仍保留宽泛**：这是可选组件，加载失败必须降级而不是把宿主带崩；
但「不抛」不等于「不吭声」—— 所以同时写 `reason` 字段和一条 warning 日志。

改完自证：用守卫自己的扫描器（`scan_source`）扫 `memory_embed.py` ⇒ **0 处静默点**，
不是靠 `--freeze` 掩盖，也不是加一句假日志。

```
memory_embed.py 静默点 0 处
判定： ✓ 干净
```

---

## 七、还没做（明确边界）

| 项 | 为什么不在这批做 |
|---|---|
| **接进 `memory_engine.search_memory_for_injection`** | 会改注入行为 ⇒ 影响 2305 项测试基线 + 真实对话体验。必须单独一批、单独验证 |
| 接进星图 `build_edges` | 同上；且星图是观感，优先级低于检索 |
| 模型随包分发 | 涉及打包脚本与发行策略，要 Owner 定（+23MB / +41.9MB 依赖） |
| 指纹计算的耗时优化 | 现在算全量 sha256 约 200ms（冷启动 280ms 里占大头）。可用 size+mtime+首段哈希降到 ~30ms，但会降低严格性，需权衡 |
| `requirements.txt` 未加可选依赖说明 | onnxruntime / tokenizers 目前只写在 `memory_embed.py` 的 docstring 里。要不要登记到 requirements 注释区，随接线那批一起定 |
| 阈值 0.51 的上线确认 | 它是**陡坡上的点**（0.50→47% 注入、0.52→83% 召回）。接线时必须先拿真实对话复验 |
| RRF 与 BM25 加权融合 | 本轮只测了「OR」与「纯向量」，没试分数融合 |

---

## 八、接线时的第一批检查项（写下来，免得到时忘）

1. 注入点必须同时有「阈值 + 定义式守卫」，**只改阈值不上守卫 = 违反 `test_memory_gate.py` 契约**
2. 不可用时必须原地回退，不能因为没模型就少注入或抛错
3. 缓存路径不能放在会被 git 跟踪的地方（`_embed_probe/` 已 gitignore）
4. 桌宠启动路径加 280ms（或优化后 ~100ms），需要确认是否可接受
5. `test_memory_gate.py` 的 6 项契约测试必须全绿，特别是 `test_weak_query_is_gated_out`
6. **先定「库变大怎么办」** —— 固定阈值在 171 条时注入率 76%，这是绝对判据的结构性缺陷，
   不是调参能修的（见复验报告 §5 与 §7.3）
7. 启动时读一次 `status()`，把校准告警写进日志（换模型后不能静默沿用旧阈值）

---

> 时间戳校正（2026-11-04 18:36 实测）：本文原写「2026-11-04 03:40」，那是估算值；
> 按文件实际写盘时间（mtime）校正为「2026-11-04 11:24」。规矩是写件前先读真时钟，我这次没读。
