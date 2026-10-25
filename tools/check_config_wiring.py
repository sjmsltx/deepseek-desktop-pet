# -*- coding: utf-8 -*-
"""配置链路核对器（A 档止血的核心工具）

解决什么问题
------------
这一轮漏的 bug 全是「名字都对得上，就是没连上」：
  · asr_* 六个键 —— config 里有、程序里从没读（设置改了重启就丢）
  · voice_fallback —— 读了、也存了 self 属性，但**没传给 VoiceIO 构造**
    （而且两边名字还不一样：voice_fallback / fallback_voice）

现有的 `核接口.py` 只回答「这个名字存在吗」，查不出「线接没接」。
本工具专门查三段链路：

    ① config.json 的键   →  ② _load_ai_config 里的 self.属性   →  ③ 消费端（构造函数/方法参数）

检查项
------
  K1 配置文件里有的键，`_load_ai_config` 是否真的 `cfg.get('键')`
  K2 `_load_ai_config` 里设的 self.属性，是否在别处被真正用到（孤儿属性 = 可能漏接）
  K3 外部类构造参数（VoiceIO / AsrEngine 等），是否有对应的 self 属性传进去
     —— 名字允许不同（voice_fallback → fallback_voice），按「去掉 voice_/asr_ 前缀后比对」

用法
----
    python tools/check_config_wiring.py            # 人读的报告
    python tools/check_config_wiring.py --check    # 只退出码（0 通过 / 1 有缺口）

⚠ 边界（诚实标注）
  · 只做静态分析，不跑程序；动态生成的配置键查不到
  · K3 只核对**已知的几个外部类**（下面 WIRED_CLASSES），新增外部类要登记
  · 不做数据流追踪，只看「名字是否出现在构造调用里」，判据偏粗但能拦住这次的形态
"""
import ast
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 需要核对构造参数的外部类：(模块文件, 类名, 在 desktop_pet 里的实例属性名)
WIRED_CLASSES = [
    ('voice_io.py', 'VoiceIO', 'voice'),
    ('asr.py', 'AsrEngine', 'asr'),
]

#: 这些键允许只读不用（纯开关/外部模块自己读）
#: 确认过"本来就不该在 _load_ai_config 里加载"的键 —— 每条都要写原因，
#: 否则核对器会一直报，最后还是没人看。
ALLOW_UNUSED = {
    # config.example.json 模板里的说明性键，不是真配置
    '_note',
    # 圆桌协作的上限，值都是 0（功能未启用）；启用时要连带补读取代码
    'roundtable_max_cost_micro',
    'roundtable_max_tokens',
    # 历史遗留：2026-10-19 起「联网搜索」改用 DeepSeek 官方 Search API（复用 deepseek key），
    # 这个 Tavily 时代的 key 已无人读。配置键保留（删了会让老用户 config 少一项，无必要），
    # 属性也保留（_load_ai_config 仍赋值，属于无害残留）。
    'search_api_key',
}


def _read(p):
    # ⛔ 不要改成「一行式读取」的写法：产品代码规则禁止未关闭的 open
    #    （长驻进程里是真实资源泄漏，tests/test_product_open_hygiene.py 守着）。
    with io.open(p, encoding='utf-8-sig') as fh:
        return fh.read()


def load_config_keys():
    """配置里出现过的键（config.json 与 config.example.json 合并）"""
    keys = {}
    for name in ('config.json', 'config.example.json'):
        p = os.path.join(REPO, name)
        if not os.path.exists(p):
            continue
        try:
            d = json.loads(_read(p))
        except Exception:
            continue
        for k in d:
            keys.setdefault(k, []).append(name)
    return keys


def find_key_readers(key):
    """在整个仓库里找 `get('key')` / `['key']` 的读取点（跨模块）

    为什么范围要放到全仓库：配置键不一定在 _load_ai_config 里读。
    例如 side_panel_tabs 由 _read_side_cfg 读、api_prices 由计价模块读。
    只在 _load_ai_config 里找会把它们全报成"未读取"——假红一堆，报告就没人看了。
    """
    pats = ("get('%s'" % key, 'get("%s"' % key,
            "['%s']" % key, '["%s"]' % key)
    hits = []
    for root, dirs, files in os.walk(REPO):
        if any(x in root for x in ('.git', '__pycache__', 'release_build', '_archive')):
            continue
        for f in files:
            if not f.endswith('.py'):
                continue
            p = os.path.join(root, f)
            try:
                with io.open(p, encoding='utf-8-sig', errors='ignore') as fh:
                    txt = fh.read()
            except Exception:
                continue
            for i, l in enumerate(txt.splitlines(), 1):
                s = l.strip()
                if s.startswith('#'):
                    continue
                if any(pt in s for pt in pats):
                    hits.append('%s:%d' % (os.path.relpath(p, REPO), i))
    return hits


def pet_source():
    return _read(os.path.join(REPO, 'desktop_pet.py'))


def analyze_load_config(src):
    """从 _load_ai_config 里抽出：读了哪些键 → 设了哪些 self 属性；以及构造了哪些外部类

    Returns:
        (key_to_attr, attr_to_key, ctor_calls)
        key_to_attr: {'voice_fallback': 'voice_fallback', ...}
        ctor_calls: {'voice': {'fallback_voice', ...}, ...}  构造时实传的关键字参数名
    """
    tree = ast.parse(src)
    fn = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == '_load_ai_config':
            fn = n
            break
    if fn is None:
        return {}, {}, {}

    key_to_attr, attr_to_key = {}, {}

    # 1) 找形如 self.X = ... cfg.get('K') ... 或 self.X = str(cfg.get('K', ...) or ...)
    for n in ast.walk(fn):
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if not (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                    and t.value.id == 'self'):
                continue
            attr = t.attr
            # 在该赋值表达式的整棵子树里找 cfg.get('KEY')
            for sub in ast.walk(n.value):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == 'get' and sub.args
                        and isinstance(sub.args[0], ast.Constant)
                        and isinstance(sub.args[0].value, str)):
                    k = sub.args[0].value
                    key_to_attr[k] = attr
                    attr_to_key[attr] = k

    # 2) 找构造调用 VoiceIO(...) / AsrEngine(...)，记下实传的关键字参数名
    #    ⛔ 范围必须是**整个 PetWidget 类**，不能只在这一个函数里找 ——
    #       构造实际发生在 __init__ 里（第一版就在这儿画窄了，报"找不到构造调用"）。
    ctor_calls = {}
    target_cls = {cls: attr for _m, cls, attr in WIRED_CLASSES}
    pet_cls = None
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == 'PetWidget':
            pet_cls = n
            break
    scope = pet_cls if pet_cls is not None else tree
    for n in ast.walk(scope):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in target_cls:
            attr = target_cls[n.func.id]
            ctor_calls[attr] = {kw.arg for kw in n.keywords if kw.arg}
    return key_to_attr, attr_to_key, ctor_calls


def ctor_params(module_file, cls):
    p = os.path.join(REPO, module_file)
    if not os.path.exists(p):
        return []
    tree = ast.parse(_read(p))
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == cls:
            for m in n.body:
                if isinstance(m, ast.FunctionDef) and m.name == '__init__':
                    return [a.arg for a in m.args.args if a.arg != 'self']
    return []


def attr_used_elsewhere(src, attr, skip_in_load=True):
    """self.ATTR 在 _load_ai_config **之外** 是否被读到（getattr 或 self.ATTR）"""
    tree = ast.parse(src)
    load_range = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == '_load_ai_config':
            load_range = (n.lineno, n.end_lineno)
            break
    used = []
    for n in ast.walk(tree):
        ln = getattr(n, 'lineno', 0)
        if skip_in_load and load_range and load_range[0] <= ln <= load_range[1]:
            continue
        # self.ATTR
        if (isinstance(n, ast.Attribute) and n.attr == attr
                and isinstance(n.value, ast.Name) and n.value.id == 'self'):
            used.append(ln)
        # getattr(self, 'ATTR', ...)
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == 'getattr' and len(n.args) >= 2
              and isinstance(n.args[1], ast.Constant) and n.args[1].value == attr):
            used.append(ln)
    return sorted(set(used))


def norm(name):
    """把 voice_fallback / fallback_voice 归一成可比较的形式"""
    for pre in ('voice_', 'asr_'):
        if name.startswith(pre):
            return name[len(pre):]
    return name


def main():
    check_only = '--check' in sys.argv
    src = pet_source()
    cfg_keys = load_config_keys()
    key_to_attr, attr_to_key, ctor_calls = analyze_load_config(src)

    problems = []

    print('=' * 92)
    print('配置链路核对   仓库：%s' % REPO)
    print('=' * 92)
    print('  配置文件里的键 %d 个' % len(cfg_keys))
    print('  _load_ai_config 里读到并落到 self 属性的键 %d 个' % len(key_to_attr))
    print()

    # ---- K1：配置键有没有被加载 ----
    print('K1 配置键 → 是否被 _load_ai_config 读取')
    print('-' * 92)
    missing = []
    for k in sorted(cfg_keys):
        where = ','.join(cfg_keys[k])
        readers = find_key_readers(k)
        if k in key_to_attr:
            if k in ALLOW_UNUSED:
                print('  ⚠ %-28s 已加载但还留在 ALLOW_UNUSED —— 登记过期了，请删掉那条'
                      % k)
            print('  ✓ %-28s → self.%-22s  (读 %d 处)' % (k, key_to_attr[k], len(readers)))
        elif readers:
            # 别的模块/函数自己读，合理
            print('  · %-28s 由别处读  %s' % (k, readers[0]))
        elif k in ALLOW_UNUSED:
            print('  · %-28s 已登记：本就不该加载/未启用' % k)
        else:
            print('  ✗ %-28s **全仓库无人读取** (%s)' % (k, where))
            missing.append(k)
    if missing:
        print()
        print('  ⛔ 以下 %d 个键**全仓库没有任何代码读取**（改了不会生效）：' % len(missing))
        for k in missing:
            print('      %s' % k)
        print('    这正是 asr_* 那个 bug 的形态：config 里有、代码靠 getattr 兜默认值。')
        print('    处置：要么补读取代码，要么从配置里删掉；确认"故意留着的"才登记 ALLOW_UNUSED。')
        problems.append('K1: %d 个配置键全仓库无人读取' % len(missing))

    # ---- K2：设了的属性有没有人用 ----
    print()
    print('K2 self 属性 → 是否在 _load_ai_config 之外被使用')
    print('-' * 92)
    orphans = []
    for k, attr in sorted(key_to_attr.items(), key=lambda kv: kv[1]):
        if k in ALLOW_UNUSED or attr in ALLOW_UNUSED:
            print('  · %-40s 已登记：本就不该加载/已弃用' % ('self.' + attr))
            continue
        used = attr_used_elsewhere(src, attr)
        if used:
            print('  ✓ %-40s 用在 %s' % ('self.' + attr, used[:5]))
        else:
            print('  ? %-40s 只在 _load_ai_config 里赋值，别处没读到' % ('self.' + attr))
            orphans.append(attr)
    if orphans:
        print()
        print('  ⚠ %d 个属性设了但没人读（可能是漏接线，也可能只是暂时没用）：%r'
              % (len(orphans), orphans))
        problems.append('K2: %d 个属性设了没人读' % len(orphans))

    # ---- K3：外部类构造参数有没有接上 ----
    print()
    print('K3 外部类构造参数 → 是否真的传进去')
    print('-' * 92)
    for mod, cls, inst_attr in WIRED_CLASSES:
        params = ctor_params(mod, cls)
        actual = ctor_calls.get(inst_attr, set())
        print('  %s（self.%s）构造参数 %d 个，实传 %d 个' % (cls, inst_attr, len(params), len(actual)))
        if not actual:
            print('    ⛔ 没找到 self.%s = %s(...) 的构造调用（可能改了写法？）' % (inst_attr, cls))
            problems.append('K3: 找不到 %s 构造调用' % cls)
            continue
        skipped = []
        for p_ in params:
            if p_ in actual:
                continue
            # 名字不同但同义：voice_fallback ↔ fallback_voice
            if any(norm(p_) == norm(a) for a in actual):
                continue
            skipped.append(p_)
        # base_dir / runner 这类是本类自己给的，不算漏
        MUST = {'base_dir', 'runner', 'timeout', 'local_timeout', 'local_lang'}
        real_skipped = [p_ for p_ in skipped if p_ not in MUST]
        if real_skipped:
            print('    ⚠ 这些构造参数没传（用默认值）：')
            for p_ in real_skipped:
                print('        %s' % p_)
            problems.append('K3: %s 有 %d 个构造参数没传：%r' % (cls, len(real_skipped), real_skipped))
        else:
            print('    ✓ 该传的都传了')

    print()
    print('=' * 92)
    if problems:
        print('结论：发现 %d 类缺口' % len(problems))
        for p_ in problems:
            print('  · %s' % p_)
        print()
        print('  处置原则：真漏了的补代码；确认"本来就该这样"的登记到 ALLOW_UNUSED 并写原因。')
        print('  ⛔ 不许为了让核对通过就把检查删掉。')
    else:
        print('结论：✓ 三段链路完整')
    print('=' * 92)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
