# -*- coding: utf-8 -*-
"""术语一致性护栏（C2③ 防山机制③）—— 把"三层用名"与"两步走"钉成可机械核对的断言。

背景（2026-10-03）：
  · 同一个 L 字串曾管三件事（视图层 / 存储层 / 架构层）→ 已解撞 ✓
  · 字段 interrupt_timeout_ms 已更名 interrupt_notice_ms ✓（旧名只留兼容别名与留痕 ✓）
  · M2 契约里 data-layer="L1|L2|L3" 已冻结 → 属**第②步**，本批**不许偷跑** ✗
"""
import io
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT = r"E:\Git\cmd\git.exe"


def _read(rel):
    """读仓库内文件（⭐ 用 with 关句柄 ✓ 不留 ResourceWarning ✗）"""
    with io.open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


# ── 1. 三层术语表存在且三套用名都在（按用途命名 ✓） ───────────────────
def test_terminology_table_declares_three_namespaces():
    doc = _read('docs/3.0-总方案-20260921.md')
    assert '术语澄清' in doc, '必须有术语澄清块 ✓'
    for token in ('V1/V2/V3', 'L0/L1/L2', '桌宠', '协作台', 'DSH'):
        assert token in doc, '术语表缺 %s' % token
    # 视图层三个视图用 V 前缀 ✓
    for name in ('V1 群聊流', 'V2 投递轨道', 'V3 后台总线'):
        assert name in doc, '视图层应使用 %s ✓' % name


# ── 2. 旧写法不许复活（视图层不再连写 Lx + 中文名；架构层不再挂 L 编号）──
def test_old_layer_writing_is_gone():
    doc = _read('docs/3.0-总方案-20260921.md')
    for bad in ('L1 群聊流', 'L2 投递轨道', 'L3 后台总线'):
        assert bad not in doc, '视图层旧写法复活 ✗：%s' % bad
    for bad in ('桌宠（L1）', '协作台（L2', 'DSH（L3）'):
        assert bad not in doc, '架构层不应再挂 L 编号 ✗：%s' % bad


# ── 3. 字段更名：旧名只允许留在 relay_log.py 的兼容别名与契约留痕处 ────
def test_legacy_field_name_only_in_alias_and_contract():
    # relay_log.py 里必须有兼容别名（否则旧配置会被静默忽略 ✗）
    rl = _read('relay_log.py')
    assert '_LEGACY_LIMIT_KEYS' in rl and 'interrupt_timeout_ms' in rl
    assert "'interrupt_notice_ms': 60_000," in rl, '默认值应用新名 ✓'
    # 其它 .py 一律不许再出现旧名 ✗（测试与产品代码都算 ✓）
    out = subprocess.run([GIT, "-c", "core.quotepath=false", "ls-files", "*.py"],
                         cwd=ROOT, capture_output=True)
    offenders = []
    # ⭐ 白名单：relay_log.py（兼容别名所在 ✓）＋ 本护栏文件自身（断言里必须写旧名字符串 ✓ 属自指 ✗不违规范）
    ALLOW = ('relay_log.py', 'tests/test_term_consistency.py')
    for f in out.stdout.decode("utf-8", "replace").splitlines():
        f = f.strip()
        if not f or f.endswith(ALLOW):
            continue
        p = os.path.join(ROOT, f)
        if os.path.isfile(p):
            with io.open(p, encoding='utf-8', errors='ignore') as fh:
                if 'interrupt_timeout_ms' in fh.read():
                    offenders.append(f)
    assert offenders == [], '旧字段名不应再出现在这些文件 ✗：%s' % offenders
    # 契约件保留"原名 -> 现名"留痕 ✓（防后人误读成超时自动恢复）
    m1 = _read('docs/3.0-M1-API契约-冻结v1.md')
    assert 'interrupt_notice_ms' in m1 and '原名' in m1


# ── 4. 契约追加条款在位（写面/进程/额度/更名/术语 五条） ───────────────
def test_contract_appendix_clauses_in_place():
    m1 = _read('docs/3.0-M1-API契约-冻结v1.md')
    m2 = _read('docs/3.0-M2-UI导出契约-冻结v1.md')
    for doc in (m1, m2):
        assert '追加条款（2026-10-03' in doc, '契约件必须有追加条款小节 ✓'
        assert '只读投影' in doc and '不新增' in doc, 'C1 写面唯一通道条款缺 ✗'
        assert '互不启动' in doc, 'C2 进程关系条款缺 ✗'
    for tag in ('C1（写面唯一通道）', 'C2（进程关系）', 'C3（额度默认值来源）',
                'C4（字段更名留痕）', 'C5（术语三层解撞）'):
        assert tag in m1, 'M1 契约缺 %s' % tag


# ── 5. ⭐ 第②步不许偷跑：M2 已冻结的 data-layer 串必须原样保留 ─────────
def test_step_two_not_prematurely_applied():
    m2 = _read('docs/3.0-M2-UI导出契约-冻结v1.md')
    assert 'data-layer="L1|L2|L3"' in m2, \
        '⭐ 已冻结的 data-layer 不得在本批改名 ✗（须与下次契约版本同批 ✓）'
    idx = _read('collab/index.html') if os.path.isfile(os.path.join(ROOT, 'collab', 'index.html')) else ''
    if idx:
        assert 'data-layer' in idx, '协作台前端仍依赖 data-layer ✓（故不许半拉子改名 ✗）'
    # 追加条款里必须写明"不许半拉子"的处置
    assert '同批' in m2 and '半拉子' in m2


# ── 6. ⭐ 追加条款 II（采纳微信侧过目意见）在位 ──────────────────────────
def test_contract_appendix_ii_in_place():
    m1 = _read('docs/3.0-M1-API契约-冻结v1.md')
    m2 = _read('docs/3.0-M2-UI导出契约-冻结v1.md')
    for doc in (m1, m2):
        assert '追加条款 II' in doc, '追加条款 II 缺 ✗'
        assert '单一写者' in doc, '②-1 单一写者未钉住 ✗（最易堆山的一条）'
        assert '投影可以落后' in doc, '①-4 边界定义（不得反写）未钉住 ✗'
    # M1 专属：额度生效时机 ＋ 优先级预留 ＋ 成本真相唯一
    for token in ('启动时读一次', '项目级 > 全局 > 不限', '不自己算钱'):
        assert token in m1, 'M1 契约缺：%s ✗' % token
    # M2 专属：只读白名单预留 ＋ 能力不得含密钥
    assert '不得含密钥' in m2 and '/api/roles' in m2


# ── 6b. ⭐ 追加条款 III（Owner 2026-10-03 22:17 亲批）在位 ────────────
def test_contract_appendix_iii_in_place():
    m1 = _read('docs/3.0-M1-API契约-冻结v1.md')
    assert '追加条款 III' in m1, 'Owner 已亲批的条款 III 未落盘 ✗'
    # D1：额度改“双上限同时生效、先到者停”（min 语义 ✓）
    assert '三档同时生效、先到者停' in m1, 'D1 额度口径未写入 ✗'
    assert 'min' in m1 and '停 ＋ 出结论 ＋ @人类' in m1
    # D1 必须说明“实现零改动 / 只改文字”，避免后人以为要改代码 ✗
    assert '实现零改动' in m1 and '只改文字' in m1
    # D2：身份 = peer 白名单，零新增凭证，不得存密钥
    assert 'peer 白名单' in m1 and '零新增凭证' in m1
    assert 'identity' in m1
    # 效力递增声明在位 ✓
    assert 'III > II' in m1


# ── 6c. ⭐ 追加条款 IV（Owner 2026-10-03 23:01 已批：写回协议 ＋ C1 补条）────
def test_contract_appendix_iv_in_place():
    m1 = _read('docs/3.0-M1-API契约-冻结v1.md')
    assert '追加条款 IV' in m1, 'Owner 已批的条款 IV 未落盘 ✗'
    # E1：C1 补条 —— 唯一窄写端点，七条约束必须在位
    assert 'POST /api/pending' in m1
    for n in range(1, 8):
        assert ('%d. ⭐' % n) in m1, 'E1 第 %d 条约束未写明 ✗' % n
    assert '类型枚举' in m1 and 'collab/pending/' in m1 and '不执行' in m1
    assert '单写者' in m1 and '失败必落结果' in m1 and '人触发' in m1
    # E2：文件格式（待办 ＋ 结果）＋ 幂等键
    assert 'YYYYMMDD-HHMMSS' in m1 and 'results.jsonl' in m1 and 'op_id' in m1
    assert '只追加' in m1
    # E3：只读端点取最严形态（三个 bool、无路径）
    assert '/api/assets' in m1 and 'white' in m1 and 'chroma' in m1 and 'alpha' in m1
    assert '不含任何路径' in m1
    # 效力递增
    assert 'IV > III' in m1


# ── 6d. ⭐ 追加条款 E4（E1③ 例外：`root` 唯一允许绝对路径 ✓ Owner 23:04 已批）──
def test_contract_appendix_e4_root_exception_in_place():
    m1 = _read('docs/3.0-M1-API契约-冻结v1.md')
    assert 'E4' in m1 and 'E1③ 例外' in m1, 'E1③ 例外条款未落盘 ✗'
    assert '`root`' in m1
    # 四条限缩逐条在位 ✓
    assert '只此一项' in m1 and '已存在目录' in m1
    assert '512' in m1 and 'UNC' in m1
    # 原则未被削弱 ✓
    assert '仍只允许相对路径' in m1
    # ⭐ 代码侧必须与条款一致（双向钉 ✓）：例外函数＋护栏都在 ✓
    code = io.open(os.path.join(ROOT, 'collab', 'pending_ops.py'), encoding='utf-8').read()
    assert '_root_problem' in code, '条款写了例外，代码却没实现 ✗'
    assert 'isdir' in code, '⭐ 例外必须校验「已存在目录」✗'


# ── 7. ⭐ ③-2 非法值必须“可见”（设置页回显，不只收进变量） ────────────
def test_invalid_config_visible_in_settings():
    with io.open(os.path.join(ROOT, 'settings_ui.py'), encoding='utf-8') as fh:
        src = fh.read()
    assert '配置有误' in src, '设置页必须回显“配置有误，已按不限运行” ✗'
    assert 'lb_rt_note.setText' in src
    # 并确认回显确由 load_limits 的 problems 驱动（不是写死的文字）
    seg = src[src.index('_probs = []'):]
    assert '_probs' in seg and 'load_limits(warn=_probs.append)' in src


# ── 6e. ⭐ 追加条款 E5（只读 GET /api/pending ✓ 界面侧提请 ✓ 电脑侧采纳）──
def test_contract_appendix_e5_pending_readonly_in_place():
    m1 = _read('docs/3.0-M1-API契约-冻结v1.md')
    assert 'E5' in m1 and 'GET /api/pending' in m1, 'E5（只读面扩充）未落盘 ✗'
    assert 'pending' in m1 and 'results' in m1
    # ⭐ 必须写明"只读、不新增写能力、不含路径/凭证" ✓
    assert '只读' in m1 and '不含绝对路径' in m1 and '不含凭证' in m1
    # ⭐ 代码侧双向钉：路由存在 ✓ 且是 do_GET 里的 handler ✓
    srv = io.open(os.path.join(ROOT, 'collab', 'relay_server.py'), encoding='utf-8').read()
    assert 'def pending_view' in srv and "'/api/pending'" in srv
    get_seg = srv[srv.index('def do_GET'):]
    assert "'/api/pending'" in get_seg, '⭐ 必须在 do_GET 里（只读面）✗ 不得放进 do_POST（除窄写外）✗'
    assert 'pending_view()' in get_seg
