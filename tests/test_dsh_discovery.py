# -*- coding: utf-8 -*-
"""DSH 位置发现 —— 三条护栏（2026-10-30）

修的三个 bug 全是同一个根：**模块级静态常量 DSH_ROOT 被当成「发现值」用**。
本机 DSH 恰好在默认位置 D:\\dsh，静态值和发现值相同，所以问题一直看不出来。

⛔ 所以每条用例都要**造一个装在别处的假 DSH**，否则等于没测。
"""
import ast
import io
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import dsh_adapter as ad  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_discovery(monkeypatch):
    """所有用例都不许摸真实环境。

    ⚠ 2026-10-30（WX-150 §4.1 指出）：本文件原先没有隔离 fixture，是环境依赖的根。
      当时 `installed()` 还有 fallback 扫进程，只要用户正用着 DSH，
      `test_installed_requires_real_marker_not_just_dir` 就会**假红**。
      现在 fallback 已去掉，但仍要把环境锁死 —— 否则测试结果取决于
      「跑测试时 DSH 有没有在运行」，那不是测试，是碰运气。

    锁三样：
      · `_running_dsh_processes` → 固定返回空（不扫真进程）
      · `_DISCOVERY_CACHE`       → 每次清空（不吃上一条用例的缓存）
      · `DSH_ROOT` 环境变量       → 清掉（本来也没设，防以后被外部污染）
    """
    monkeypatch.setattr(ad, '_running_dsh_processes', lambda timeout=15: [])
    monkeypatch.setattr(ad, '_DISCOVERY_CACHE', {'ts': 0.0, 'data': None})
    # ⚠ 2026-10-31：`installed()` 现在带 300 秒结果缓存 —— 不在这里换掉的话，
    #   上一条用例算出的 True/False 会被下一条用掉 ⇒ 结果取决于执行顺序。
    monkeypatch.setattr(ad, '_INSTALLED_CACHE', {'ts': 0.0, 'val': None})
    # ⚠ 2026-10-31：`installed()` 现在带 300 秒结果缓存 —— 不在这里换掉的话，
    #   上一条用例算出的 True/False 会被下一条用掉 ⇒ 结果取决于执行顺序。
    monkeypatch.setattr(ad, '_INSTALLED_CACHE', {'ts': 0.0, 'val': None})
    # ⚠ 2026-10-31：`installed()` 现在带 300 秒结果缓存 —— 不在这里换掉的话，
    #   上一条用例算出的 True/False 会被下一条用掉 ⇒ 结果取决于执行顺序。
    monkeypatch.setattr(ad, '_INSTALLED_CACHE', {'ts': 0.0, 'val': None})
    monkeypatch.delenv('DSH_ROOT', raising=False)
    monkeypatch.delenv('DSH_PORT', raising=False)


@pytest.fixture()
def fake_dsh(tmp_path, monkeypatch):
    """造一个「装在别处」的 DSH 目录，配置只写在 tmp 里。

    ⚠ 2026-11-02 改（本轮真踩到）：原来是把**产品目录下真的 `dsh_config.json`**
      改名成 `.bak-test`、用例结束再改回来。实测后果 ——
      测试进程被强杀（Ctrl+C / 超时 / OOM）时 `finally` 不执行 ⇒
      真配置里留下 `{"root": "...\\Temp\\chk_real_xxx"}` 这种指向桩目录的值，
      桌宠从此「✓ 已检测到 DSH」而入口打不开，**且不报警**（WX-166 §三 报的就是这个）。

      ⇒ 改成 `monkeypatch.setattr(ad, 'USER_CONFIG_PATH', <tmp>)`：测试连摸都摸不到真文件。
        `test_dsh_panel.py` 本来就是这么写的，**本文件是漏的**。

    ⚠ 同时把假安装造成**真安装的形状**（带 `lib/bin.js`）——
      判据 2026-11-02 已收紧，只有空 `@deepseek-ai/dsh` 目录的桩不再算已安装。
    """
    cfgp = tmp_path / 'dsh_config.json'
    monkeypatch.setattr(ad, 'USER_CONFIG_PATH', str(cfgp))

    root = tmp_path / 'my_dsh'
    pkg = root / 'node_modules' / '@deepseek-ai' / 'dsh' / 'lib'
    pkg.mkdir(parents=True)
    (pkg / 'bin.js').write_text('// fake entry\n', encoding='utf-8')
    (root / 'start-dsh.ps1').write_text('# fake\n', encoding='utf-8')
    yield str(root)
    ad.discover(force=True)


def test_installed_uses_discovered_root_not_static(fake_dsh):
    """DSH 装在别处并配好后，installed() 必须为真

    ⛔ bug① 的复现点：原判据是 os.path.exists(DSH_ROOT)（静态默认值），
      装在别处时返回假 ⇒ 菜单误报「未检测到 DSH」。
    """
    assert ad.save_user_config(root=fake_dsh) is True
    assert ad.resolve_root() == fake_dsh, '发现链没跟上配置'
    assert ad.installed() is True, 'bug①：装在别处被误判为未安装'


def test_installed_requires_real_marker_not_just_dir(tmp_path, monkeypatch):
    """只判目录存在不够 —— 空壳目录不许算「已安装」

    ⚠ 显式把「运行中进程」锁成空：这条测的是**判据本身**，不是环境。
      （旧实现有 fallback 扫进程时，用户正用着 DSH 就会把空目录救活 ⇒ 假红）
    """
    monkeypatch.setattr(ad, '_running_dsh_processes', lambda timeout=15: [])
    # 配置路径也锁到 tmp —— 绝不动产品目录下真的 dsh_config.json（2026-11-02）
    monkeypatch.setattr(ad, 'USER_CONFIG_PATH', str(tmp_path / 'dsh_config.json'))
    empty = tmp_path / 'empty_dsh'
    empty.mkdir()
    assert ad.save_user_config(root=str(empty)) is True
    assert ad.installed() is False, '空目录被当成已安装'
    ad.discover(force=True)


def test_installed_false_when_config_points_to_bad_path_even_if_dsh_running(
        tmp_path, monkeypatch):
    """⭐ S1 反例：配置指向坏路径、而 DSH 正在默认目录跑着 ⇒ 必须 False

    来自 WX-150 §2.1 的实测反例（我复现过）：
      旧实现 `installed()` 有「候选不合格就扫进程兜底」的 fallback ⇒
        resolve_root()  = F:/typo/dsh（坏路径，面板会用它找启动器）
        installed()     = True（fallback 扫到 D:/dsh 有标志）
      ⇒ 菜单说「已检测到」，点面板拿坏路径拉不起来
      ⇒ 正是本文件要防的 bug① 换了个形态又出现

    判据能证伪：把 `installed()` 改回带 fallback 的版本，这条立刻红。
    """
    # 造一个真实存在的 DSH（用 tmp_path，带标志文件）
    real = tmp_path / 'real_dsh'
    pkg = real / 'node_modules' / '@deepseek-ai' / 'dsh' / 'lib'
    pkg.mkdir(parents=True)
    (pkg / 'bin.js').write_text('// fake entry\n', encoding='utf-8')
    (real / 'start-dsh.ps1').write_text('# fake\n', encoding='utf-8')
    # 进程在跑，且进程报的 root 是那个真实目录
    monkeypatch.setattr(ad, '_running_dsh_processes',
                        lambda timeout=15: [{'pid': 1, 'cmdline': 'node bin.js web',
                                             'root': str(real), 'port': 3080}])
    # 配置路径锁到 tmp（2026-11-02：原来会改名真配置，强杀即污染）
    monkeypatch.setattr(ad, 'USER_CONFIG_PATH', str(tmp_path / 'dsh_config.json'))
    # 配置指向一个不存在的路径（用户手滑写错）
    bad = str(tmp_path / 'typo' / 'dsh')
    assert ad.save_user_config(root=bad) is True
    ad.discover(force=True)
    assert ad.resolve_root() == bad, '前提不成立：resolve_root 没拿到配置值'
    assert ad.installed() is False, (
        'installed() 说已检测到，但 resolve_root() 指向不存在的路径 —— '
        '菜单会骗人（面板拿这个路径找不到启动器）')
    ad.discover(force=True)


def test_launcher_follows_discovered_root(fake_dsh):
    """bug② 的复现点：启动器路径必须跟着发现值走

    原来是模块级常量 LAUNCHER = os.path.join(ad.DSH_ROOT, ...)，import 那刻定死。
    """
    import dsh_panel
    assert ad.save_user_config(root=fake_dsh) is True
    lp = dsh_panel._launcher()
    assert lp.startswith(fake_dsh), '启动器仍指向静态默认目录：%r' % lp
    assert lp.endswith('start-dsh.ps1')
    assert os.path.exists(lp), '启动器路径指向的文件不存在'


def test_stop_local_dsh_uses_discovered_root():
    """bug③ 的复现点：stop_local_dsh 不许再用静态 DSH_ROOT 拼命令行

    ⛔ 不真杀进程 —— 用 AST 查函数体：必须出现 resolve_root()，
      且不得出现 `% DSH_ROOT`（原来把静态值拼进 PowerShell 的写法）。
    """
    p = os.path.join(BASE, 'dsh_adapter.py')
    src = io.open(p, encoding='utf-8-sig').read()
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'stop_local_dsh':
            fn = node
            break
    assert fn is not None, '找不到 stop_local_dsh'
    seg = ast.get_source_segment(src, fn) or ''
    assert 'resolve_root()' in seg, '停服务没走发现值'
    assert '% DSH_ROOT' not in seg, '仍在用静态 DSH_ROOT 拼命令行'
    assert '拒绝执行' in seg, '缺少空 root 防误杀判断'


def test_save_user_config_clears_cache(fake_dsh):
    """写完配置必须清发现缓存，否则界面点了保存 30 秒内还显示旧状态"""
    ad.discover(force=True)
    ad.save_user_config(root=fake_dsh)
    # 不 force：若缓存没清，这里会读到旧值
    assert ad.resolve_root() == fake_dsh, '缓存未清，保存后不立刻生效'


def test_save_user_config_empty_means_auto(tmp_path, monkeypatch):
    """传空 = 删掉该项，回到自动发现（不是存一个空字符串）

    ⚠ 用 pytest 的 tmp_path 而不是 tempfile.mkdtemp —— 前者由 pytest 回收，
      后者会留垃圾目录（我第一次就漏了一个 cfgtest_* 在 TEMP 里）。
    ⚠ 配置路径同样锁到 tmp（2026-11-02），不许碰产品目录下的真文件。
    """
    cfg = str(tmp_path / 'dsh_config.json')
    monkeypatch.setattr(ad, 'USER_CONFIG_PATH', cfg)
    fake = str(tmp_path / 'my_dsh')
    os.makedirs(os.path.join(fake, 'node_modules', '@deepseek-ai', 'dsh', 'lib'))
    with open(os.path.join(fake, 'node_modules', '@deepseek-ai', 'dsh', 'lib',
                           'bin.js'), 'w', encoding='utf-8') as fh:
        fh.write('// fake entry\n')
    ad.save_user_config(root=fake)
    assert os.path.exists(cfg), '没写出配置文件'
    assert ad.resolve_root() == fake
    ad.save_user_config(root='')
    assert not os.path.exists(cfg), '清空后仍留着配置文件'
    assert ad.resolve_root() != fake
    ad.discover(force=True)


def test_stub_dir_is_not_goods(tmp_path, monkeypatch):
    """⭐ 2026-11-02 回归：桩目录不许算「已安装」（WX-166 §三 报出的真问题）

    实测原样（本机 TEMP 里真躺着一个）：

        node_modules/@deepseek-ai/dsh   1 字节空**文件**
        start-dsh.ps1                   5 字节

    旧判据 `os.path.exists(...)` 两样都命中 ⇒ `installed()` = True
    ⇒ 界面「✓ 已检测到 DSH」，点入口打不开，**一句报警都没有**。

    判据能证伪：把 `_has_marker` 改回「存在即算」，这条立刻红。
    """
    monkeypatch.setattr(ad, 'USER_CONFIG_PATH', str(tmp_path / 'dsh_config.json'))
    stub = tmp_path / 'stub_dsh'
    nm = stub / 'node_modules' / '@deepseek-ai'
    nm.mkdir(parents=True)
    (nm / 'dsh').write_bytes(b'\n')            # 空文件，不是目录
    (stub / 'start-dsh.ps1').write_text('#\n', encoding='utf-8')
    assert ad.save_user_config(root=str(stub)) is True
    ad.discover(force=True)
    assert ad.installed() is False, (
        '桩目录被判成已安装 —— 界面会显示「已检测到」而入口根本打不开')
    # 但「缺的是哪一样」要能说出来，不许和「压根没装」混成一句话
    det = ad.installed_detail()
    assert det['entry_missing'] is True, '缺入口这件事没被单独标出来'
    ad.discover(force=True)


def test_tests_never_touch_real_product_config():
    """⭐ 结构钉：测试不许读写产品目录下真的 `dsh_config.json`

    ⚠ 2026-11-02 起因：本文件原来三处 `cfg = ad.USER_CONFIG_PATH` + 改名，
      强杀测试进程就污染真配置（10-31 11:20 真发生，指向 TEMP 桩目录）。
      正确写法只有一种：`monkeypatch.setattr(ad, 'USER_CONFIG_PATH', ...)`。

    判据（按 token 判，不按行文本判）：
      除 `monkeypatch.setattr(ad, 'USER_CONFIG_PATH', ...)` 之外，
      `USER_CONFIG_PATH` 不许以标识符形式出现在本文件里。

    ⚠ 必须按 token 判 —— 本函数自己的字符串、以及注释里的旧写法都会被文本匹配命中
      （这条坑本仓库早踩过：结构钉先剥注释/docstring 再匹配）。
      实测第一次就栽在自己的 `if 'USER_CONFIG_PATH' not in t:` 上：那是字符串，不是代码。
    """
    import tokenize
    p = os.path.join(BASE, 'tests', 'test_dsh_discovery.py')
    src = io.open(p, encoding='utf-8').read()
    lines = src.splitlines()
    bad = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        # 只认真标识符：字符串里的文字、注释都不会产生 NAME token
        if tok.type != tokenize.NAME or tok.string != 'USER_CONFIG_PATH':
            continue
        ln = tok.start[0]
        t = lines[ln - 1].strip() if ln <= len(lines) else ''
        if 'monkeypatch.setattr' in t:
            continue
        bad.append((ln, t[:80]))
    assert not bad, '测试直接摸了产品配置（会污染用户文件）：%r' % bad


def test_menu_predicate_uses_installed_not_static():
    """bug① 的结构钉：菜单判据必须是 installed()，不是 os.path.exists(DSH_ROOT)

    ⛔ 两个坑都在这条里踩过，都已避开：
      1. **不能 grep** —— 注释里提到旧写法不算违规（先剥注释/用 AST）
      2. **不能对每个节点调 get_source_segment** —— 它内部每次 splitlines()，
         1 万行源码 × 几千节点 = O(n²)，这条曾跑 76 秒。先做结构化判断，
         只在命中时才按行号取片段。
    """
    p = os.path.join(BASE, 'desktop_pet.py')
    src = io.open(p, encoding='utf-8').read()
    tree = ast.parse(src)

    # ⛔ 两个坑已避开（WX-150 §3.1 指出）：
    #   1. 原先只认 `ast.Attribute`（`_ad2.DSH_ROOT`），**同模块内的裸名 `DSH_ROOT`
    #      （`ast.Name`）完全抓不到**
    #   2. 原先只扫 desktop_pet.py，没扫 dsh_adapter.py（那里有裸名用法）
    #   现在两种形式都认、两个文件都扫。
    static_hits = []
    allowed = {
        # `DSH_ROOT = ...` 这个**定义**本身当然要允许
        ('dsh_adapter.py', 'definition'),
        # discover() 里「默认值兜底」是有意的
        ('dsh_adapter.py', 'default-fallback'),
        # LOG_CANDIDATES 的静态兜底候选（有注释说明，且 _candidate_logs 排在它前面）
        ('dsh_adapter.py', 'static-log-candidate'),
    }
    for fname in ('desktop_pet.py', 'dsh_adapter.py'):
        fp = os.path.join(BASE, fname)
        fsrc = io.open(fp, encoding='utf-8-sig').read()
        ftree = ast.parse(fsrc)
        for node in ast.walk(ftree):
            is_name = isinstance(node, ast.Name) and node.id == 'DSH_ROOT'
            is_attr = isinstance(node, ast.Attribute) and node.attr == 'DSH_ROOT'
            if not (is_name or is_attr):
                continue
            line = node.lineno
            ctx = fsrc.splitlines()[line - 1].strip() if line <= len(fsrc.splitlines()) else ''
            # 定义行
            if ctx.startswith('DSH_ROOT ='):
                continue
            # 「默认值」兜底与静态日志候选：已注释说明，判定豁免
            if '默认值' in ctx or 'dsh-web.log' in ctx or 'LOG_CANDIDATES' in ctx:
                continue
            static_hits.append((fname, line, ctx[:70]))

        assert not static_hits, '仍在用 os.path.exists(DSH_ROOT) 判安装，行号 %r' % static_hits

    installed_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == 'installed':
                installed_calls.append(node.lineno)
    assert installed_calls, '菜单里找不到 installed() 调用'


def test_settings_page_has_dsh_root_entry():
    """设置 → 系统 页要有 DSH 位置入口（控件 + 三个动作）"""
    p = os.path.join(BASE, 'settings_ui.py')
    src = io.open(p, encoding='utf-8-sig').read()
    for name in ('def _build_dsh_row', 'def _refresh_dsh_status',
                 'def _apply_dsh_root', 'def _pick_dsh_root'):
        assert name in src, '缺少 %s' % name
    assert 'self._build_dsh_row(f)' in src, '系统页没调用'
    assert 'self.ed_dsh_root' in src and 'self.lb_dsh' in src
