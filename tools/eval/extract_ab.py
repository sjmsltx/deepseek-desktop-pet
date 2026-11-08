# -*- coding: utf-8 -*-
"""P1-1 验证：抽取 prompt 新增的两条规则到底有没有用（A/B 单变量对照）

## 为什么要做这个

2026-11-06 定下「修抽取比修 z 便宜」，2026-11-08 往提示词里加了两条：
  ① 不把「我们正在讨论的项目/代码」记成用户属性
  ② 一句寒暄不构成稳定人格

**但这两条从没验证过。** 改提示词不等于改行为 —— 模型完全可能照样抽。
所以这里做 A/B：同一批真实对话、同一窗口切分、只换 prompt 文本。

## 对照设计

- 旧 prompt：`87481a3:memory_engine.py`（新增两条之前的版本）
- 新 prompt：当前工作区
- 对话：`tools/eval/realdist.json` 45 条真实输入，按产品逻辑「最近 8 条」相近地切成 9 条一段
- 每段 × 每 prompt 各跑一次，收集 facts

## 实测结果（2026-11-08，第一次跑）

```
6 段 × 2 臂 = 12 次抽取（素材：本地两份真实对话记录，共 52 条，含双方）
旧 prompt：facts 5 条，伪影 1（project 1）  伪影率 20%
新 prompt：facts 4 条，伪影 1（project 1）  伪影率 25%
```

**结论：未能证明新 prompt 减少了伪影。** 两臂各 1 条，都在同一段
（「用户持有一份某地矢量数据」—— 把「我们正在分析的数据」记成用户属性）。
新 prompt 只是让 facts 总数从 5 降到 4，那不等于质量提升（分母变小，伪影率反而 20%→25%）。

⇒ 两条新规则**保留**（它们堵的是一类已知风险，本身无害），但**不许声称「修好了抽取偏斜」**。
   要验证它得等真实使用积累到足够样本，或者用更强的约束（例如让模型先答「这句话主语是用户还是我们」
   再做抽取，两步法）。

⚠ 另有一条连带更正（同等重要）：
   本脚本第一版用 `realdist.json`（45 条杂项短句）算「真实对话里桌宠话题占 7%」，
   据此推断「库内 67% ⇒ 抽了 10 倍」。**那个 7% 是样本选择造成的。**
   换成本地两份真实对话记录（52 条）算，桌宠话题占 **33%** ⇒ 偏斜是 2 倍级别，不是 10 倍。

## 实测结果二（2026-11-08 晚，固定温度后重跑）

固定 temperature=0 后伪影**变得可复现**（两臂两遍都一致：old 1/1、new 0/0），
但逐段看内容后发现一件更要紧的事 —— **新提示词是靠「少抽」换来「不抽错」**：

```
段1  old 3 条（含 1 条 project 伪影）  new 2 条（无伪影）   ← 真的挡住了
段3  old 1 条（桌宠命名，有效）        new 0 条            ← 漏抽
段4  old 1 条（桌宠命名，有效）        new 0 条            ← 漏抽
段6  old 1 条（喜欢成语接龙，有效）    new 0 条            ← 漏抽
─────────────────────────────────────────────────────────
合计 old 8 条 = 有效 7 + 伪影 1
     new 3 条 = 有效 3 + 伪影 0
```

⇒ **新臂精度 100%，但有效事实从 7 条掉到 3 条。**

⚠ **只报伪影率会得出完全相反的结论**：「0% vs 14%」听起来是改进，
   但代价是一半以上的有效记忆没记下来。这两件事必须一起报。

⇒ 所以本脚本的统计段同时给「伪影数」与「有效事实数」，
   **不许只贴伪影率**（这个坑我自己刚踩过）。

## 判据（**先定后看，不事后调**）

主指标：**伪影率** = 伪影条数 / 总 facts 条数

「伪影」只认两类，都是我自己在 11-08 判定过的明确错误（不是事后挑出来的）：

  · `greeting`：从一句寒暄/客套抽出的「人格/语气/关心他人」类属性
      —— 对应库里那条「用户会主动关心桌宠、提醒注意身体健康，说话语气友善」
  · `project`：把「我们正在讨论的功能/工具」记成用户属性
      —— 对应库里那条「用户关注桌宠的记忆机制是否优化，会主动询问/确认其技术实现细节」

其余一律算「非伪影」（哪怕内容一般，也不靠这个判据说它错）。

⚠ 样本量：5 段 × 2 = 10 次抽取。**只能看方向，不能当统计结论。**
   报的时候必须带「n=10 次抽取」，不许说「显著改善」。

## 用法

    python tools/eval/extract_ab.py --dry          # 只打印窗口切分，不调 API
    python tools/eval/extract_ab.py                # 真跑（会消耗 token）

需要 config.json 里配了 deepseek_api_key。不打印 key。
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

#: 旧 prompt 取自哪个提交（新增两条规则之前的最后一次）
OLD_REV = '87481a3'
#: 每段对话条数（产品取最近 8 条，这里取 9 便于 45 整除）
WINDOW = 9
#: 段间与调用间休眠，防限流
SLEEP = 1.2


def _git_show(rev, path):
    git = 'D:\\Git\\cmd\\git.exe'
    if not os.path.exists(git):
        git = 'git'
    r = subprocess.run([git, '-c', 'safe.directory=D:/ai工作站/desktop-pet',
                        'show', '%s:%s' % (rev, path)],
                       cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        raise SystemExit('取 %s:%s 失败：%s' % (rev, path, r.stderr.decode('utf-8', 'replace')))
    return r.stdout.decode('utf-8', 'replace')


def grab_prompt(src):
    """从源码里抠出 EXTRACT_PROMPT 的三引号内容"""
    m = re.search(r'EXTRACT_PROMPT\s*=\s*"""(.*?)"""', src, re.S)
    if not m:
        raise SystemExit('源码里找不到 EXTRACT_PROMPT')
    return m.group(1)


#: 素材来源：本地真实对话记录（含用户与助手双方）。
#: ⚠ 这些文件在 .gitignore 里（memory/chat_memory*/），**内容不入库**；
#:   本脚本只读它们、不写死任何对话原文，跑出来的结果也必须落在 logs/ 下。
SOURCES = ('chat_memory.json', 'chat_memory_flash.json')


def load_local_dialogue(size=WINDOW):
    """按时间顺序拼接本地真实对话（用户+助手），切成 size 条一段。

    为什么必须含助手回复：伪影「把我们一起在做什么记成用户属性」只有在
    **双方都在场**的对话里才会出现 —— 只有用户单句时，模型没有「我们在做什么」可记。
    （这是本脚本第一版的设计错误：用只有用户单句的样本，两臂都抽 0 条，测不出差别。）
    """
    lines = []
    for name in SOURCES:
        p = os.path.join(ROOT, name)
        if not os.path.exists(p):
            continue
        d = json.load(io.open(p, encoding='utf-8'))
        for m in d.get('messages', []):
            role = m.get('role')
            text = str(m.get('content', '')).strip()
            if not text or role not in ('user', 'assistant'):
                continue
            lines.append((role, text))
    return [lines[i:i + size] for i in range(0, len(lines), size)]


def make_dialogue(pairs):
    """与产品同口径（DESKTOP 的 _extract_worker）：\n 分隔，内容截 150 字"""
    out = []
    for role, text in pairs:
        who = '用户' if role == 'user' else '桌宠'
        out.append('%s: %s' % (who, text[:150]))
    return '\n'.join(out)


def call_api(prompt, dialogue, existing='（无）'):
    """真调一次抽取。返回 (facts 列表, 原始文本, 用量)"""
    import config_loader as _cfg  # 项目里的配置读取（若没有则回退直读）
    raise RuntimeError('不应走到这里')


def _api_key():
    cfg = json.load(io.open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
    key = str(cfg.get('deepseek_api_key') or '').strip()
    if not key:
        raise SystemExit('config.json 里没有 deepseek_api_key')
    return key


def run_one(prompt_text, dialogue, key, max_tokens=400, temperature=None):
    """调一次抽取；返回 dict（facts/events/update_facts）与 usage。

    temperature=None 表示**不传**，与产品现状完全一致（`_extract_chat` 就没传，
    走 API 默认值）。传 0.0 可测「低温下结果稳不稳」。
    """
    import deepseek_client
    body = prompt_text.format(existing='（无）', dialogue=dialogue)
    payload = {
        'model': 'deepseek-chat',
        'messages': [{'role': 'user', 'content': body}],
        'max_tokens': max_tokens,
        'response_format': {'type': 'json_object'},
    }
    if temperature is not None:
        payload['temperature'] = float(temperature)
    data = json.dumps(payload).encode()
    resp = deepseek_client.chat_completions(key, data)
    text = resp['choices'][0]['message'].get('content') or ''
    usage = resp.get('usage', {})
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = {'_parse_error': True, 'raw': text[:400]}
    return parsed, usage


# ---- 伪影判定 ----
#
# ⚠ 判据覆盖修正记录（2026-11-08，必须写清，否则等于事后调参）：
#   第一版 PROJECT_PAT 只收了「记忆机制/技术实现/代码/架构」这类**抽象词**，
#   漏掉了同一类伪影的**具体形态** —— 「用户手中有一份重庆区县矢量数据」。
#   那句话按 11-06 的判定标准就是 project 型（那是「我们正在分析的数据」，
#   不是用户的稳定属性），但第一版判据识别不出。
#   ⇒ 补「持有 / 手中有一份 / 在做 / 分析了 / 拿着」，并用 9 条已知正负样本校准（9/9）。
#   ⚠ 这是**扩充到已知两类**，不是为了让某一臂好看 —— 修正后两臂仍是 1:1 打平（见报告）。
#: ── 三级判据（2026-11-08 从两级扩到三级）──────────────────────────
#:
#: 两级（伪影 / 非伪影）有个致命缺陷：它把「用户与重庆有关联，**可能**是重庆人」
#: 也算进「有效」—— 那是抽取自己在猜，不是记忆。这类条目进了库只会污染检索。
#:
#: 三级：
#:   bad    伪影：把「我们一起在做的事」记成用户属性 / 寒暄记成人格 / 助手主张记成属性
#:   weak   抽到自己都没把握（含「可能 / 也许 / 大概」）—— 方向对但不可用
#:   useful 用户的稳定属性、偏好、身份、习惯
#:
#: ⚠ 标定方式与局限：判据先在 18 条**已有**抽取结果上用人工期望值标定，18/18 一致。
#:   但这批样本是我「先看了内容再写正则」⇒ 有过拟合风险，
#:   所以本判据只能用来**同一批数据上比较两臂的相对差**，不能当绝对准确率。
#:   报告里必须写这一句。
GREETING_PAT = re.compile(r'(语气|友善|温暖|关心他人|有礼貌|客气|寒暄|问候|说话方式)')
PROJECT_PAT = re.compile(
    r'(记忆机制|技术实现|功能细节|代码|实现细节|架构'
    r'|持有|手中有一份|手里有一份|拥有一份|在做|分析了|拿着)')
_PROJECT_VERB = re.compile(
    r'(关注|询问|了解|确认|讨论|研究|持有|手中有一份|手里有一份|在做|分析|拥有|拿着)')
_ADVICE_PAT = re.compile(r'(适合|建议|优于|不如|更合理|值得)')
_UNCERTAIN_PAT = re.compile(r'(可能|也许|大概|似乎|好像是|或是)')


def grade_fact(text):
    """三级判定，返回 (级别, 理由码)。级别：bad / weak / useful"""
    t = str(text or '')
    if PROJECT_PAT.search(t) and _PROJECT_VERB.search(t):
        return 'bad', 'project'
    if GREETING_PAT.search(t):
        return 'bad', 'greeting'
    if _ADVICE_PAT.search(t):
        return 'bad', 'advice'
    if _UNCERTAIN_PAT.search(t):
        return 'weak', 'uncertain'
    return 'useful', ''


def classify_fact(text):
    """兼容旧调用：返回 'greeting' / 'project' / ''（只有 bad 级才非空）。"""
    lvl, reason = grade_fact(text)
    return reason if lvl == 'bad' else ''


def main(argv=None):
    ap = argparse.ArgumentParser(description='抽取 prompt A/B 验证')
    ap.add_argument('--dry', action='store_true', help='只打印窗口切分，不调 API')
    ap.add_argument('--windows', type=int, default=0, help='只跑前 N 段（0=全部）')
    ap.add_argument('--temperature', type=float, default=None,
                    help='采样温度；省略=不传（与产品现状一致）。'
                         '传 0 可测低温下的稳定性')
    ap.add_argument('--repeat', type=int, default=1,
                    help='每臂每段重复几遍（≥2 可看抖动；默认 1）')
    # ⛔ 原始响应含真实对话内容 ⇒ 默认落 logs/（.gitignore 已排除），不进 experiment/
    ap.add_argument('--out', default=os.path.join(ROOT, 'logs', 'extract-ab-raw.json'))
    args = ap.parse_args(argv)

    # ⛔ 护栏（前置）：产物含真实对话抽出的内容，绝不许落进入库目录。
    #   2026-11-08 踩到：第一次试跑的默认输出路径写在 experiment/ 下，那份 raw 含真实 facts，
    #   已移回收站。护栏原先放在函数末尾 ⇒ 白跑 12 次 API 调用才被拦，所以移到这里。
    _out_abs = os.path.abspath(args.out)
    if _out_abs.startswith(os.path.join(os.path.abspath(ROOT), 'tools')):
        raise SystemExit('拒绝写入 %s：tools/ 是入库目录，raw 结果含真实对话内容。'
                         '请用 --out 指到 logs/ 或其他被 gitignore 的位置。' % _out_abs)

    old_src = _git_show(OLD_REV, 'memory_engine.py')
    new_src = io.open(os.path.join(ROOT, 'memory_engine.py'), encoding='utf-8').read()
    p_old, p_new = grab_prompt(old_src), grab_prompt(new_src)
    print('旧 prompt（%s）%d 字' % (OLD_REV, len(p_old)))
    print('新 prompt（工作区）%d 字' % len(p_new))
    print('两条规则在旧/新里：%s / %s'
          % ('我们正在讨论的项目' in p_old, '我们正在讨论的项目' in p_new))
    print()

    wins = load_local_dialogue()
    if args.windows:
        wins = wins[:args.windows]
    print('窗口 %d 段（每段 %d 条）：' % (len(wins), WINDOW))
    for i, w in enumerate(wins):
        head = w[0][1][:24].replace('\n', ' ') if w else ''
        print('  段%d：%d 条，起于 [%s] %r' % (i + 1, len(w), w[0][0] if w else '-', head))
    print()

    if args.dry:
        print('--dry：不调 API，结束')
        return 0

    key = _api_key()
    rows = []
    nrep = max(1, args.repeat)
    for i, w in enumerate(wins):
        dlg = make_dialogue(w)
        for tag, ptxt in (('old', p_old), ('new', p_new)):
            for rep in range(1, nrep + 1):
                t0 = time.time()
                try:
                    parsed, usage = run_one(ptxt, dlg, key,
                                            temperature=args.temperature)
                except Exception as exc:
                    print('  段%d/%s#%d 调用失败：%r' % (i + 1, tag, rep, exc))
                    time.sleep(SLEEP)
                    continue
                facts = [f for f in parsed.get('facts', []) if isinstance(f, dict)]
                rows.append({'window': i + 1, 'arm': tag, 'rep': rep,
                             'facts': [str(f.get('content', '')) for f in facts],
                             'events': len(parsed.get('events', []) or []),
                             'usage': usage,
                             'sec': round(time.time() - t0, 1)})
                print('  段%d/%s#%d %d 条 facts，%d 条 events，%.1fs，token=%s'
                      % (i + 1, tag, rep, len(facts),
                         len(parsed.get('events', []) or []),
                         time.time() - t0, usage.get('total_tokens', '?')))
                time.sleep(SLEEP)

    # 统计
    print()
    print('=' * 78)
    print('伪影统计（判据先定：greeting / project 两类）')
    print('=' * 78)
    summary = {}
    for arm in ('old', 'new'):
        sub = [r for r in rows if r['arm'] == arm]
        total = sum(len(r['facts']) for r in sub)
        cnt = {'bad': 0, 'weak': 0, 'useful': 0}
        detail = []
        for r in sub:
            for c in r['facts']:
                lvl, reason = grade_fact(c)
                cnt[lvl] += 1
                if lvl != 'useful':
                    detail.append((r['window'], lvl, reason, c))
        summary[arm] = {'runs': len(sub), 'facts': total,
                        'bad': cnt['bad'], 'weak': cnt['weak'], 'useful': cnt['useful'],
                        'bad_rate': (cnt['bad'] / total) if total else 0.0,
                        'useful_rate': (cnt['useful'] / total) if total else 0.0,
                        'useful_per_run': (cnt['useful'] / len(sub)) if sub else 0.0}
        print('%s：%d 次抽取，facts %d 条 ＝ useful %d / weak %d / bad %d'
              % (arm, len(sub), total, cnt['useful'], cnt['weak'], cnt['bad']))
        for w, lvl, reason, c in detail:
            print('    段%d [%s/%s] %s' % (w, lvl, reason, c[:66]))
        print()

    o, n = summary['old'], summary['new']
    print('%-12s %-14s %-14s %s' % ('指标', '旧 prompt', '新 prompt', '判定'))
    print('-' * 66)
    print('%-12s %-14s %-14s' % ('useful 条数', o['useful'], n['useful']))
    print('%-12s %-14s %-14s' % ('weak 条数', o['weak'], n['weak']))
    print('%-12s %-14s %-14s' % ('bad 条数', o['bad'], n['bad']))
    print('%-12s %-14.0f%% %-14.0f%% %s' % ('bad 占比', o['bad_rate'] * 100,
                                            n['bad_rate'] * 100,
                                            '↓ 更好' if n['bad_rate'] < o['bad_rate'] else
                                            ('持平' if n['bad_rate'] == o['bad_rate'] else '↑ 更差')))
    print('%-12s %-14.0f%% %-14.0f%% %s' % ('useful 占比', o['useful_rate'] * 100,
                                            n['useful_rate'] * 100,
                                            '↑ 更好' if n['useful_rate'] > o['useful_rate'] else
                                            ('持平' if n['useful_rate'] == o['useful_rate'] else '↓ 更差')))
    print()
    # 判据（先定）：bad 占比下降 且 useful 条数不减超 20%
    ok_bad = n['bad_rate'] < o['bad_rate']
    ok_use = n['useful'] >= o['useful'] * 0.8
    verdict = '通过' if (ok_bad and ok_use) else '不通过'
    print('判据（跑之前就定好）：①bad 占比下降 ②useful 条数不低于旧臂的 80%%')
    print('  ① %s    ② %s（%d vs 阈值 %.1f）'
          % ('满足' if ok_bad else '不满足', '满足' if ok_use else '不满足',
             n['useful'], o['useful'] * 0.8))
    print('  ⇒ 结论：%s' % verdict)
    print()
    print('⛔ 两个指标必须一起看：bad 下降若靠「少抽」换来，那是拿召回换精度，不是改进。')
    print('⚠ 判据局限：三级判据是在 18 条已有结果上人工标定的（18/18 一致），')
    print('   但那批样本是「先看内容再写正则」⇒ 有过拟合风险。只能比较两臂相对差，不能当绝对准确率。')
    print('样本：%d 段 × 2 臂 × %d 遍 = %d 次抽取，**只能看方向，不是统计结论**'
          % (len(wins), max(1, args.repeat), len(rows)))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    # ⛔ 必须用 with 块写入（关闭交给上下文管理器）。写成单表达式链会在长驻进程里
    #    留下未关闭句柄，tests/test_product_open_hygiene.py 会判红
    #    （2026-11-08 正是它抓到我这里；顺带一提，注释里也别照抄那种写法，同样会被匹配到）
    with io.open(args.out, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(
            {'old_rev': OLD_REV, 'windows': len(wins), 'window_size': WINDOW,
             'summary': summary, 'rows': rows}, ensure_ascii=False, indent=2))
    print()
    print('原始响应已存：%s' % args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
