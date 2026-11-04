# -*- coding: utf-8 -*-
"""embedding 评估：量出「词面边」的真实缺口（2026-11-04）

## 两个实验，都是客观测量，不靠我主观挑例子

### 实验一：同义改写召回（量「漏连」）
取 N 条真实记忆，让模型**保留含义但换用词**改写一遍。
改写前后语义相同 ⇒ 任何"关系"算法都该把它们连起来。
然后看词面 jaccard 是否达到 STRONG_EDGE_JACCARD(0.045)。

  · 若大量改写对达不到阈值 ⇒ 词面边抓不住语义关系（这是 embedding 的收益空间）

### 实验二：现有强边精度（量「误连」）
从真实强边里抽 M 条，让模型判断两段记忆是否真的相关。
  · 得到词面边的 precision ⇒ 决定"加 embedding"是为了补漏还是为了去噪

## 口径

- 用产品同一个 API（deepseek-flash），严格复刻 run_experiment.py 的调用形状
- 写结果到 results/embedding-eval.json
- key 只从 config.json 读，**不打印、不落盘**
"""
import io
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
DATA = os.path.join(EXP, 'data')
RESULTS = os.path.join(EXP, 'results')
REPO = os.path.dirname(os.path.dirname(os.path.dirname(EXP)))
sys.path.insert(0, REPO)

MODEL = 'deepseek-flash'
ENDPOINT = 'https://api.deepseek.com/chat/completions'
N_PARA = 40
N_EDGE = 80

PARA_PROMPT = """把下面这句话改写成**意思完全相同**的说法。

硬要求：
1. 换用同义词、换语序、换表达方式，**尽量不复用原句的词语**
2. 不许增加原文没有的信息，不许删掉关键信息
3. 保持原来的具体名词（人名/专有名词/数字）可以保留，其余尽量换掉
4. 只输出改写后的一句话，不要任何解释

原句：%s"""

#: 变体 A：允许保留专有名词（= 同一件事被自然复述时的真实情形）
PARA_PROMPT_EASY = PARA_PROMPT

#: 变体 B：**连专有名词也换成描述**（纯语义改写，词面几乎不重叠）
PARA_PROMPT_HARD = """把下面这句话改写成**意思完全相同**的说法。

硬要求：
1. 把所有具体名词也换成**描述性说法**。例：「合川桃片」→「那种薄薄的甜味切片」；
   「战争雷霆」→「那款坦克对战游戏」；「Python」→「那门编程语言」
2. 换用同义词、换语序，**不要复用原句的任何实词**
3. 不许增加原文没有的信息，不许删掉关键信息
4. 只输出改写后的一句话，不要任何解释

原句：%s"""

JUDGE_PROMPT = """下面两段文字都来自同一个人（用户）的记忆记录。
请判断它们**是否真的有关联**（指同一件事、同一个人、同一偏好、同一话题或因果相关）。

判定从宽：只要主题相近、能看出是同一个人生活里的相关片段，就算「相关」。
只有主题完全无关（例如一个是吃饭、一个是写代码）才算「不相关」。

严格按 JSON 输出：{"related": true/false, "reason": "20字以内"}"""


def _read_key():
    """从仓库 config.json 读 key。不打印。"""
    for name in ('config.json', 'config_backup_20261007.json'):
        p = os.path.join(REPO, name)
        if not os.path.exists(p):
            continue
        try:
            with io.open(p, encoding='utf-8') as f:
                cfg = json.loads(f.read())
        except Exception:
            continue
        k = (cfg.get('deepseek_api_key') or '').strip()
        if k:
            return k
    return ''


def call(key, prompt, max_tokens=300, temperature=0.8, as_json=True):
    """调 chat/completions。

    ⚠ response_format=json_object 要求**提示词里出现 json 字样**，否则 DeepSeek 返回
      400。第一版我给「改写」也加了 json_object 而提示词里没有 json
      ⇒ 40/40 全失败（这是我调用写错，不是模型问题）。
    """
    payload = {
        'model': MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': temperature,
        'max_tokens': max_tokens,
        # ⚠ 关掉思考模式。deepseek-flash 是推理模型，reasoning_tokens **计入**
        #   max_tokens：实测 2000 预算下 reasoning 就吃掉 2000、content 为空
        #   （finish_reason=length）。改写/判定这类任务不需要推理，直接关掉最省。
        'thinking': {'type': 'disabled'},
    }
    if as_json:
        payload['response_format'] = {'type': 'json_object'}
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + key,
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode('utf-8'))
        ch = d['choices'][0]
        txt = (ch['message'].get('content') or '').strip()
        if not txt:
            # ⚠ deepseek-flash 是推理模型：reasoning_tokens 计入 max_tokens。
            #   预算不够时 finish_reason=length 且 content 为空（本项目踩过多次）。
            print('      [空内容] finish=%s usage=%s'
                  % (ch.get('finish_reason'), d.get('usage', {}).get('completion_tokens_details')))
        return txt
    except urllib.error.HTTPError as e:
        print('      [HTTP %d] %s' % (e.code, e.read().decode('utf-8', 'replace')[:160]))
        return ''
    except Exception as e:
        print('      [%s] %s' % (type(e).__name__, str(e)[:120]))
        return ''


def load_facts(n):
    """真实库 21 条 + 实验数据补足 —— 用实验数据是为了有足够样本"""
    real = [f for f in json.loads(io.open(os.path.join(REPO, 'memory.json'),
                                         encoding='utf-8').read())['facts']
            if f.get('status') == 'active']
    exp = json.loads(io.open(os.path.join(DATA, 'memories-1411.json'),
                             encoding='utf-8').read())['facts']
    out = [(f.get('content') or '').strip() for f in real]
    out += [(f.get('content') or '').strip() for f in exp]
    out = [x for x in out if len(x) >= 12]
    seen, uniq = set(), []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq[:n]


def main():
    key = _read_key()
    if not key:
        print('✗ 找不到 API key（config.json 里没有 deepseek_api_key）')
        return 1
    print('key 已读到（长度 %d，不打印）' % len(key))
    import memory_starmap as sms
    thr = sms.STRONG_EDGE_JACCARD
    print('词面阈值 STRONG_EDGE_JACCARD = %.3f' % thr)
    print()

    rnd = random.Random(20261104)

    # ---------- 实验一：同义改写（两个变体） ----------
    src = load_facts(400)
    sample = rnd.sample(src, min(N_PARA, len(src)))
    para_out = {}
    for variant, prompt_tpl in (('A_允许保留专名', PARA_PROMPT_EASY),
                                ('B_连专名也换成描述', PARA_PROMPT_HARD)):
        print('=' * 76)
        print('实验一(%s)：同义改写召回 %d 条（%s）' % (variant, len(sample), MODEL))
        print('=' * 76)
        rows = []
        for i, text in enumerate(sample, 1):
            # 2000 而不是 260：推理 token 计入预算，260 时全被吃掉、content 为空
            out = call(key, prompt_tpl % text, max_tokens=400, temperature=0.9,
                       as_json=False)
            if not out:
                out = call(key, prompt_tpl % text, max_tokens=400, temperature=0.5,
                           as_json=False)
            para = out.strip().strip('"「」')
            if para and '\n' in para:
                para = max((x.strip() for x in para.splitlines()), key=len)
            if not para:
                continue
            j = sms.jaccard(text, para)
            ok = j >= thr
            rows.append({'src': text, 'para': para, 'jaccard': round(j, 4), 'pass': ok})
            if i <= 4:
                print('  --- 样例 %d ---' % i)
                print('    原: %s' % text[:68])
                print('    改: %s' % para[:68])
                print('    jaccard %.4f  %s' % (j, '✓ 过阈值' if ok else '✗ 不过阈值'))
        n = len(rows)
        npass = sum(1 for r in rows if r['pass'])
        js = sorted(r['jaccard'] for r in rows) if rows else [0]
        print()
        print('  有效 %d / %d' % (n, len(sample)))
        print('  ★ 词面判据认出「同义」：%d / %d = %.0f%% ⇒ 漏连 %.0f%%'
              % (npass, n, 100.0 * npass / max(n, 1), 100.0 * (1 - npass / max(n, 1))))
        print('  jaccard 中位 %.4f / 最大 %.4f' % (js[len(js) // 2], js[-1]))
        para_out[variant] = {
            'n': n, 'pass': npass,
            'recall_pct': round(100.0 * npass / max(n, 1), 1),
            'median_jaccard': round(js[len(js) // 2], 4),
            'max_jaccard': round(js[-1], 4),
            'rows': rows,
        }
        print()

    # ---------- 实验二：现有强边的精度 ----------
    print()
    print('=' * 76)
    print('实验二：现有词面强边的精度（抽 %d 条让模型判定）' % N_EDGE)
    print('=' * 76)
    big = [(f.get('content') or '') for f in json.loads(
        io.open(os.path.join(DATA, 'memories-1411.json'), encoding='utf-8').read())['facts']]
    big = [{'text': x, 'cat': 'like', 'imp': 3, 'age': 1.0, 'key': 'p%d' % i, 'kind': 'fact',
            'detail': '', 'time': ''} for i, x in enumerate(big) if len(x) >= 12]
    se, _we = sms.build_edges(big)
    print('  语料 %d 点 → 强边 %d 条，抽 %d 条判定' % (len(big), len(se), min(N_EDGE, len(se))))
    pick = rnd.sample(se, min(N_EDGE, len(se)))
    erows = []
    for i, (a, b, w) in enumerate(pick, 1):
        prompt = JUDGE_PROMPT + '\n\n甲：%s\n\n乙：%s' % (big[a]['text'][:200], big[b]['text'][:200])
        out = call(key, prompt, max_tokens=300, temperature=0.1)
        rel = None
        reason = ''
        if out:
            try:
                d = json.loads(out)
                rel = bool(d.get('related'))
                reason = str(d.get('reason') or '')[:24]
            except Exception:
                if 'true' in out.lower():
                    rel = True
                elif 'false' in out.lower():
                    rel = False
        if rel is None:
            continue
        erows.append({'w': round(w, 4), 'a': big[a]['text'][:90], 'b': big[b]['text'][:90],
                      'related': rel, 'reason': reason})
        if i <= 5:
            print('  %.3f %s  %s | %s' % (w, '相关' if rel else '★不相关',
                                          big[a]['text'][:34], big[b]['text'][:34]))
    m = len(erows)
    nrel = sum(1 for r in erows if r['related'])
    print()
    print('  有效判定 %d / %d' % (m, len(pick)))
    print('  ★ 词面强边 precision = %d / %d = %.0f%%' % (nrel, m, 100.0 * nrel / max(m, 1)))
    bad = [r for r in erows if not r['related']]
    if bad:
        print('  误连样例（前 5）：')
        for r in bad[:5]:
            print('    w=%.3f  %s' % (r['w'], r['reason']))
            print('       %s' % r['a'][:66])
            print('       %s' % r['b'][:66])

    # ---------- 落盘 ----------
    p = os.path.join(RESULTS, 'embedding-eval.json')
    os.makedirs(RESULTS, exist_ok=True)
    with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps({
            'generated': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
            'model': MODEL,
            'threshold': thr,
            'paraphrase': para_out,
            'edge_precision': {'n': m, 'related': nrel,
                               'precision_pct': round(100.0 * nrel / max(m, 1), 1),
                               'rows': erows},
        }, ensure_ascii=False, indent=1) + '\n')
    print()
    print('  已写 %s' % p)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
