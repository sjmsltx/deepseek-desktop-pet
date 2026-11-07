# tools/eval/ — 记忆检索的评测与判据工具

这里的脚本**不是产品依赖**，是「结论怎么来的」那部分：判据来源、评测集、以及可复跑的实验。

跑法都在仓库根：`python tools/eval/<脚本>.py`。

| 文件 | 作用 |
|---|---|
| `cases.json` | 评测用例：开发集 `recall`（选参时看）+ 留出集 `holdout`（选完才验收）+ `false`/`noise`/`superseded` 反例。**留出集不许参与调参** |
| `negatives.json` | 不该注入的记忆/问句（42 条，分类别） |
| `realdist.json` | 45 条真实对话样本，用来算「真实对话注入率」 |
| `audit_facts.py` | facts 库体检：自足性 / 一次性 / 可检索性三类客观标记，输出候选清单（不替代人判断） |
| `dup_jaccard_exp.py` | 近重复判据实验：原始 Jaccard vs 去泛用词 Jaccard，看真假配对分不分得开 |
| `memory_usage_report.py` | 「注入但未引用」统计（需要先攒真实使用数据；口径见 `memory_usage.py` 头部偏差清单） |

## 两条纪律

1. **开发集与留出集分离**：选参只能看开发集。历史上吃过「拿同一批用例既调参又评分」的亏（过拟合 58 个百分点）。
2. **报数字必附口径**：分母是什么、库有几条、跑的是哪条路径（纯 BM25 / 纯向量 / 并集）。同一个指标在不同口径下差异很大，口径不同不能直接比。

## 缺向量模型时

`cases.json` 里的召回基线需要语义检索模型（见 [`models/README.md`](../../models/README.md)）。
缺模型时 `tests/test_memory_eval.py` 的 6 条召回用例会**显式 skip**（不是失败）。
