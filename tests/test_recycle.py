# -*- coding: utf-8 -*-
"""真送回收站（Owner 需求第 3 条）

需求原件：待办-喂食扩展与记忆星图-需求记录-20261031.md
Owner 原话：「还可以再优化一下，给他单独再加一个可选项就是链接回收站站，
             选择之后把文件拖给他他会真的把它转送到回收站里面去。」

## 破坏性功能的纪律（写进代码，不只写在文档里）
1. **默认关**
2. 每次执行前**二次确认**，且确认框里列出**完整路径与文件大小**
3. 只走**回收站**，绝不直接删（不用 os.remove / shutil.rmtree）
4. 每次执行**写审计**（governance.log_event），可追溯
5. 只对**文件**生效，不对文件夹（Owner 原话是「文件」；保守解释）
6. 拒绝系统目录 / 程序目录 / 桌宠自身目录

## 回收站 API 的实测依据（2026-11-01，本轮用临时文件验过）
    SHFileOperationW + FOF_ALLOWUNDO  → rc=0，文件消失，回收站条目 +1，
                                        且能在 $Recycle.Bin 里找到原内容 ✓
    同一个 API 但**不加** ALLOWUNDO   → rc=0，文件被**永久删除**，回收站不增 ✗
    ⇒ 这条对照证明「进回收站」确实是 ALLOWUNDO 带来的，不是我的测量方法看不出差别
    不存在的路径 → rc=2（有错误码，不是静默成功）
    send2trash 未安装 ⇒ 不采用（桌宠是打包分发，不能让用户装依赖）

本文件锁八件事：
A. 默认关；开关能写配置
B. 关着的时候拖文件 → 假装吃，**文件不动**
C. 开着的时候拖文件 → 真的进回收站（用临时文件验）
D. 确认框：拒绝就不动文件；同意才动
E. 文件夹拒收（即使开关开着）
F. 受保护目录拒收
G. 每次执行写审计
H. 实现里不许出现 os.remove / shutil.rmtree / unlink
"""
import hashlib
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp  # noqa: E402
import recycle_box as rb  # noqa: E402


def _pet(tmp_path):
    import affection_engine as ae
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p._append_chat = lambda *a, **k: None
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    p._bubbles = []
    p._show_pet_bubble = lambda t, *a, **k: p._bubbles.append(t)
    p._scenes = []
    p.play_scene = lambda k: p._scenes.append(k)
    p._kisses = []
    p._show_state_image = lambda st: p._kisses.append(st)
    p._audits = []

    def _fake_audit(ok, err):
        for _pth, _m in ok:
            p._audits.append(('recycle', 'ui.feed', '送回收站', str(_pth), True))
        for _pth, _why in err:
            p._audits.append(('recycle', 'ui.feed', '送回收站', str(_pth), False))
    p._audit_recycle = _fake_audit
    return p


def _fp(path):
    st = os.stat(path)
    with open(path, 'rb') as f:
        return (st.st_size, st.st_mtime_ns, hashlib.sha256(f.read()).hexdigest()[:16])


# ---------- A. 默认关 ----------
def test_drag_to_bin_defaults_off(tmp_path):
    p = _pet(tmp_path)
    assert p.drag_to_bin is False, '真送回收站必须默认关'


def test_drag_to_bin_readable_from_config():
    src = open(os.path.join(BASE, 'desktop_pet.py'), encoding='utf-8').read()
    assert "cfg.get('drag_to_bin'" in src, '配置读取里没有 drag_to_bin'


def test_set_drag_to_bin_saves(tmp_path):
    p = _pet(tmp_path)
    saved = {}
    p._save_cfg_value = lambda k, v: saved.setdefault(k, v)
    p._set_drag_to_bin(True)
    assert p.drag_to_bin is True
    assert saved.get('drag_to_bin') is True, '没落盘：%r' % saved


# ---------- B. 关着 = 文件不动 ----------
def test_switch_off_never_touches_file(tmp_path):
    p = _pet(tmp_path)
    p.drag_to_bin = False
    f = tmp_path / 'a.txt'
    f.write_text('x', encoding='utf-8')
    before = _fp(str(f))
    p._feed_by_drop([str(f)])
    assert os.path.exists(str(f)), '开关关着，文件却不见了'
    assert _fp(str(f)) == before


# ---------- C/D. 开着 = 真进回收站（需要确认） ----------
def test_switch_on_recycles_after_confirm(tmp_path, monkeypatch):
    p = _pet(tmp_path)
    p.drag_to_bin = True
    asked = {}

    def _confirm(paths):
        asked['paths'] = list(paths)
        return True
    p._confirm_recycle = _confirm
    f = tmp_path / 'b.txt'
    f.write_text('要被回收的', encoding='utf-8')
    p._feed_by_drop([str(f)])
    assert 'paths' in asked, '没弹二次确认'
    assert str(f) in asked['paths'], '确认框里没列出这个文件：%r' % asked['paths']
    assert not os.path.exists(str(f)), '确认了却没进回收站'
    assert rb.recycle_available(), '回收站 API 不可用'


def test_confirm_declined_keeps_file(tmp_path):
    p = _pet(tmp_path)
    p.drag_to_bin = True
    p._confirm_recycle = lambda paths: False
    f = tmp_path / 'c.txt'
    f.write_text('不该被回收', encoding='utf-8')
    before = _fp(str(f))
    p._feed_by_drop([str(f)])
    assert os.path.exists(str(f)), '用户拒绝了，文件却没了'
    assert _fp(str(f)) == before


# ---------- E. 文件夹拒收 ----------
def test_folder_rejected_even_when_on(tmp_path):
    p = _pet(tmp_path)
    p.drag_to_bin = True
    p._confirm_recycle = lambda paths: True
    d = tmp_path / 'folder'
    d.mkdir()
    p._feed_by_drop([str(d)])
    assert os.path.exists(str(d)), '文件夹被回收了（应只处理文件）'


# ---------- F. 受保护目录 ----------
@pytest.mark.parametrize('bad', [
    r'C:\Windows\System32\drivers\etc\hosts',
    r'C:\Program Files\x\y.txt',
])
def test_protected_paths_refused(bad):
    ok, err = rb.recycle_paths([bad])
    assert not ok, '受保护路径不应被处理：%s' % bad
    assert err, '受保护路径应给拒绝原因'


def test_app_own_directory_refused(tmp_path):
    """桌宠自己的目录不能被回收（自毁）"""
    p = _pet(tmp_path)
    p.drag_to_bin = True
    p._confirm_recycle = lambda paths: True
    own = os.path.join(BASE, 'README.md')
    if not os.path.exists(own):
        pytest.skip('无 README.md')
    before = _fp(own)
    p._feed_by_drop([own])
    assert os.path.exists(own), '桌宠把自己的文件回收了'
    assert _fp(own) == before


# ---------- G. 审计 ----------
def test_recycle_writes_audit(tmp_path):
    p = _pet(tmp_path)
    p.drag_to_bin = True
    p._confirm_recycle = lambda paths: True
    f = tmp_path / 'e.txt'
    f.write_text('审计测试', encoding='utf-8')
    p._feed_by_drop([str(f)])
    assert p._audits, '回收没写审计'
    kinds = [a[0] for a in p._audits]
    assert 'recycle' in kinds or 'deny' in kinds, '审计 kind 不对：%r' % kinds


# ---------- H. 源码红线 ----------
def test_no_direct_delete_in_recycle_module():
    """回收站模块里不许**调用**直接删除原语

    ⛔ 用 ast 判实际调用，不 grep 文本 —— 我第一版 grep，结果被自己
       docstring 里「不采用 send2trash」这句话打成红。（同一个坑第三次踩了：
       check_channel_ledger 的 MUTATION 注释、test_no_log_pollution 的 reload 注释。）
    """
    import ast
    src = open(os.path.join(BASE, 'recycle_box.py'), encoding='utf-8').read()
    tree = ast.parse(src)

    def dotted(node):
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return '.'.join(reversed(parts))
        return ''

    banned = {'os.remove', 'os.unlink', 'os.rmdir', 'shutil.rmtree',
              'send2trash', 'send2trash.send2trash'}
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            if name in banned:
                hits.append('%s (L%d)' % (name, node.lineno))
    assert not hits, '出现直接删除原语调用：%r' % hits


def test_recycle_uses_allowundo():
    """必须用 FOF_ALLOWUNDO —— 实测证明不加它文件是被永久删除"""
    src = open(os.path.join(BASE, 'recycle_box.py'), encoding='utf-8').read()
    assert 'FOF_ALLOWUNDO' in src, '没有用 FOF_ALLOWUNDO，文件会被永久删除'


# ---------- 引擎层：回收站模块本身 ----------
def test_recycle_paths_on_real_temp_file(tmp_path):
    f = tmp_path / 'real.txt'
    f.write_text('真的进回收站', encoding='utf-8')
    ok, err = rb.recycle_paths([str(f)])
    assert ok and not err, '回收失败：%r' % (err,)
    assert not os.path.exists(str(f)), '文件还在'


def test_recycle_paths_reports_missing(tmp_path):
    ok, err = rb.recycle_paths([str(tmp_path / '不存在.txt')])
    assert not ok
    assert err


def test_recycle_paths_empty_list(tmp_path):
    ok, err = rb.recycle_paths([])
    assert ok == [] and err == [], '空列表应返回两个空列表'


def test_recycle_available():
    assert rb.recycle_available() is True, '本机回收站 API 不可用'


def test_describe_size_for_confirm():
    """确认框要能显示文件大小（让人知道要删多大）"""
    assert rb.human_size(0) == '0 B'
    assert 'KB' in rb.human_size(2048)
    assert 'MB' in rb.human_size(3 * 1024 * 1024)


# ---------- I. 真实确认框（这条能抓住「QMessageBox 没导入」）----------
def test_confirm_recycle_real_dialog_constructs(tmp_path, monkeypatch):
    """**真的**构造确认框，不替换整个函数

    为什么单列一条：上一版 18 条测试全绿，但 _confirm_recycle 里
    QMessageBox 根本没导入 —— 因为我没在测试里**替换整个函数**去测它。
    真实运行时它抛 NameError、被 except 吞掉、返回 False
    ⇒ 功能等于不存在，而测试全绿。（fail-safe 方向是对的：没删任何东西。）

    这里替换 QMessageBox.exec（只替换「等待用户点击」这一步），
    其余构造、文案、按钮、默认按钮全部走真实代码。
    """
    from PySide6.QtWidgets import QMessageBox
    p = _pet(tmp_path)
    seen = {}

    def fake_exec(self):
        seen['title'] = self.windowTitle()
        seen['text'] = self.text()
        seen['info'] = self.informativeText()
        seen['buttons'] = [b.text() for b in self.buttons()]
        seen['default'] = self.defaultButton().text() if self.defaultButton() else None
        return 0

    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    f = tmp_path / 'x.txt'
    f.write_text('x' * 2048, encoding='utf-8')
    got = p._confirm_recycle([str(f)])

    assert seen, '确认框根本没被构造（QMessageBox 未导入时就是这个症状）'
    assert got is False, '默认应返回 False（取消）'
    assert '送进回收站' in seen['title']
    assert '回收站' in seen['text']
    assert str(f) in seen['info'], '确认框没列出完整路径：%r' % seen['info']
    assert 'KB' in seen['info'], '没显示文件大小：%r' % seen['info']
    assert '还原' in seen['info'], '没说明可以从回收站恢复：%r' % seen['info']
    assert seen['default'] == '取消', '默认按钮必须是取消（手滑回车不该删东西）'
