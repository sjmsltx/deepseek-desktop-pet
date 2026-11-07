# models/ — 可选的本地模型

本目录存放**可选**的本地组件模型。缺了不影响主功能，相关能力会自动降级并在
状态里说明原因（不会静默失败）。

## bge-small-zh-v1.5（记忆语义检索）

| 文件 | 大小 | 说明 |
|---|---|---|
| `model.onnx` | ~22.9 MB | int8 量化版，CLS 池化，512 维 |
| `tokenizer.json` | ~0.42 MB | 与上面同一模型 |

放到这个位置即可被自动发现：

```
models/bge-small-zh-v1.5/model.onnx
models/bge-small-zh-v1.5/tokenizer.json
```

也可以不放在仓库里，改用自己的目录：

```powershell
$env:PET_EMBED_DIR = '<你的模型目录>'
```

### 为什么这两个文件不入库

二进制大件（23 MB）不适合进 Git。`.gitignore` 已排除
`models/**/*.onnx` 与 `models/**/tokenizer.json`，只保留本说明。

### 缺模型时测试会怎样（2026-11-08 补）

`tests/test_memory_eval.py` 里有 6 条用例依赖本模型：5 个召回指标基线
（`R@1` / `R@3` / `H_R@1` / `H_R@3` / `H_R@3_pure`）+ 一条开发集词汇空白用例。

缺模型时这 6 条**显式 skip 并写明原因**，不是失败 —— 让「环境缺件」和「代码回归」
在输出里长得不一样。其余指标（`FALSE` / `NOISE` / `EVID` / `SUPERSEDED`）不依赖模型，照常跑。

⇒ 干净克隆下应看到 `14 passed, 6 skipped`，**0 failed**。

### 模型与阈值的对应关系

阈值是在 **int8 版**上校准的。换成 fp32 版余弦整体会低约 0.02，同一处判定会掉出
阈值；组件加载时会按文件大小判断并在日志里给出警告（`calibration_warning`）。
换模型后请重新校准，不要沿用旧参数。
