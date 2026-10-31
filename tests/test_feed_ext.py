# -*- coding: utf-8 -*-
"""喂食扩展（Owner 2026-10-31 需求，原件：待办-喂食扩展与记忆星图-需求记录-20261031.md）

Owner 原话：
    「就是那个不是有个喂食功能吗，这个东西可以优化一下，比如说可以选择一些更多样性的
      食物而不仅仅是单纯的一个显示喂食功能，或者说是可以与桌面的这些东西进行互动，
      比如说拖一个文件然后他假装把它吃掉了，但是不是真的给它吃掉。」

本批做前两条（第 3 条「真送回收站」有破坏性，单独一批，默认关 + 二次确认）：
    ① 食物多样化
    ② 拖文件给桌宠 → 假装吃掉（**绝不动真文件**）

## 一个必须先解决的冲突
主窗口已有 dropEvent → 把拖入路径**插进输入框**（既有行为，用于发消息）。
所以必须按区域区分：拖到**立绘区** = 喂；拖到聊天区 = 插路径（保持原样）。

## 食物表的一个设计取舍（写进代码注释）
素材里只有一张 `flash_eating.png`，没有不同食物的立绘 ⇒ 食物只能做
「emoji + 效果 + 台词」的差异，立绘统一用 eating。
好感增量统一走现有 `feed` 事件（EVENTS 表里 +2 且有冷却/每日上限）——
不按食物给不同好感，是为了不绕开 EVENTS 的防刷设计；改那套要动整个事件系统，
收益不成比例。

本文件锁八件事：
A. 食物表齐全、key 唯一、恢复量在合理区间
B. 喂不同食物真的给不同饱食度
C. 好感仍走 feed 事件（冷却/上限不受影响）
D. 拖文件：只演动作 + 说话，**文件一个字节都不动**（mtime/size/sha256 前后一致）
E. 拖文件夹/非文件：不喂、给提示、不动文件
F. 拖到立绘区才喂；主窗口原有的「插路径」行为不被破坏
G. 假装吃的时候提示语必须说明「文件没动」——不能让用户以为被吃了
H. 开关：可选「拖文件是不是真的送回收站」，**默认关**（本批只锁默认值）
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

    def _fake_show_state(st):
        p._kisses.append(st)
    p._show_state_image = _fake_show_state
    return p


def _fingerprint(path):
    st = os.stat(path)
    with open(path, 'rb') as f:
        return (st.st_size, st.st_mtime_ns, hashlib.sha256(f.read()).hexdigest()[:16])


# ---------- A. 食物表 ----------
def test_foods_table_exists_and_complete():
    foods = dp.PetWidget.FOODS
    assert isinstance(foods, dict) and len(foods) >= 4, \
        '食物表应有至少 4 种，实际 %d' % len(foods)
    for k, v in foods.items():
        for f in ('name', 'emoji', 'restore', 'line'):
            assert v.get(f), '食物 %s 缺字段 %s' % (k, f)
        assert 10 <= int(v['restore']) <= 100, \
            '食物 %s 的恢复量 %r 不合理（应在 10~100）' % (k, v['restore'])
        assert v['emoji'].strip(), '食物 %s 没有 emoji' % k


def test_food_keys_unique_and_stable():
    keys = list(dp.PetWidget.FOODS.keys())
    assert len(keys) == len(set(keys))
    assert dp.PetWidget.FOOD_DEFAULT in dp.PetWidget.FOODS, \
        '默认食物 %r 不在表里' % dp.PetWidget.FOOD_DEFAULT


# ---------- B/C. 喂不同食物 ----------
def test_different_food_gives_different_satiety(tmp_path):
    p = _pet(tmp_path)
    with p.affection._lock:
        st = p.affection._state(p.current)
        st['satiety'] = 20
        st['cooldowns'] = {}
        p.affection._save()
    p._feed_pet('cake')
    # ⚠ snapshot() 里**没有** satiety 字段（我第一版量错了）；
    #   饱食度要用 affection.satiety(role) 读
    s1 = p.affection.satiety(p.current)
    with p.affection._lock:
        st = p.affection._state(p.current)
        st['satiety'] = 20
        st['cooldowns'] = {}
        p.affection._save()
    p._feed_pet('noodle')
    s2 = p.affection.satiety(p.current)
    assert s1 != s2, '两种食物恢复量一样（%s vs %s），多样性没生效' % (s1, s2)


def test_feed_still_uses_feed_event(tmp_path):
    """好感必须仍走 feed 事件（冷却等防刷逻辑不能被绕过）"""
    p = _pet(tmp_path)
    with p.affection._lock:
        st = p.affection._state(p.current)
        st['affection'] = 100
        st['satiety'] = 20
        st['cooldowns'] = {}
        p.affection._save()
    p._feed_pet('cake')
    aff1 = p.affection.snapshot(p.current)['affection']
    p._feed_pet('cake')          # 立刻再喂：应被冷却拦住
    aff2 = p.affection.snapshot(p.current)['affection']
    assert aff1 == aff2, '连喂两次好感涨了两次 —— feed 的冷却被绕过了'
    assert any('刚喂过' in b for b in p._bubbles), '冷却期没提示'


def test_feed_unknown_food_falls_back(tmp_path):
    p = _pet(tmp_path)
    with p.affection._lock:
        st = p.affection._state(p.current)
        st['satiety'] = 20
        st['cooldowns'] = {}
        p.affection._save()
    p._feed_pet('不存在的食物')
    assert p._kisses or p._bubbles, '未知食物应当按默认食物喂，而不是什么都不做'


def test_feed_plays_eating_or_kiss(tmp_path):
    p = _pet(tmp_path)
    with p.affection._lock:
        st = p.affection._state(p.current)
        st['satiety'] = 20
        st['cooldowns'] = {}
        p.affection._save()
    p._feed_pet('cake')
    assert p._kisses, '喂食没有切换立绘'


# ---------- D/E. 拖文件 ----------
def test_drag_file_is_never_modified(tmp_path):
    """核心红线：假装吃，文件一个字节都不能动"""
    p = _pet(tmp_path)
    f = tmp_path / 'snack.txt'
    f.write_text('这是一份要被假装吃掉的文件', encoding='utf-8')
    before = _fingerprint(str(f))
    p._feed_by_drop([str(f)])
    after = _fingerprint(str(f))
    assert before == after, '文件被改动了！假装吃不该动真文件'


def test_drag_file_plays_eating_scene(tmp_path):
    p = _pet(tmp_path)
    f = tmp_path / 'a.txt'
    f.write_text('x', encoding='utf-8')
    p._feed_by_drop([str(f)])
    assert 'eating' in p._scenes, '拖文件应该演「吃」的动作，实际 %r' % p._scenes
    # ⚠ 端到端实测过：原先 eating 会被 _feed_pet 里的 kiss 顶掉（state 变 kiss）。
    #   Owner 要的是「假装把它吃掉了」⇒ 必须看到吃，不是亲。
    assert not p._kisses, \
        '拖文件后切成了亲亲（%r）—— 应该只演「吃」，不能被 kiss 顶掉' % (p._kisses,)


def test_right_click_feed_still_kisses(tmp_path):
    """右键喂食仍保持原行为（撒娇亲亲）—— 别把老体验改掉"""
    p = _pet(tmp_path)
    with p.affection._lock:
        st = p.affection._state(p.current)
        st['satiety'] = 20
        st['cooldowns'] = {}
        p.affection._save()
    p._feed_pet('cake')
    assert p._kisses, '右键喂食的亲亲反应被改掉了'


def test_drag_message_says_file_untouched(tmp_path):
    """提示语必须说明文件没动 —— 不能让用户以为真被吃了"""
    p = _pet(tmp_path)
    f = tmp_path / 'a.txt'
    f.write_text('x', encoding='utf-8')
    p._feed_by_drop([str(f)])
    joined = ' '.join(p._bubbles)
    assert ('没动' in joined) or ('原样' in joined) or ('还在' in joined), \
        '提示语没说明文件没动，容易被误解：%r' % (p._bubbles,)


def test_drag_folder_is_rejected(tmp_path):
    p = _pet(tmp_path)
    d = tmp_path / 'folder'
    d.mkdir()
    p._feed_by_drop([str(d)])
    assert not p._scenes, '文件夹不该被喂'
    assert any('文件夹' in b or '只吃文件' in b for b in p._bubbles), \
        '文件夹被喂时应有提示：%r' % (p._bubbles,)


def test_drag_missing_path_is_safe(tmp_path):
    p = _pet(tmp_path)
    p._feed_by_drop([str(tmp_path / '不存在.txt')])
    assert not p._scenes, '不存在的路径不该演动作'
    assert p._bubbles, '不存在的路径应有提示'


def test_drag_empty_list_is_noop(tmp_path):
    p = _pet(tmp_path)
    p._feed_by_drop([])
    assert not p._scenes and not p._bubbles


# ---------- F. 不破坏原「拖到聊天区插路径」 ----------
def test_original_drop_to_chat_still_inserts_path(tmp_path):
    """主窗口原有的 dropEvent（插路径到输入框）必须保持 ——
    我们只给立绘区加接受拖放，不改主窗口行为。
    """
    p = _pet(tmp_path)
    f = tmp_path / 'doc.txt'
    f.write_text('x', encoding='utf-8')
    p.chat_input.setPlainText('')
    p._insert_dropped_paths([f.as_uri()])
    txt = p.chat_input.toPlainText()
    assert str(f) in txt or 'doc.txt' in txt, '原「拖入插路径」行为被破坏了：%r' % txt


def test_pet_area_accepts_drops():
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    assert p.pet_label.acceptDrops(), '立绘区没开接受拖放'
    # QLabel 自己不处理 dropEvent，必须挂 eventFilter —— 顺带锁住这一点
    assert getattr(p, '_pet_area_drop_hooked', False) is True, \
        'pet_label 没有挂上 eventFilter，drop 事件到不了处理函数'


# ---------- G/H. 开关默认值 ----------
def test_bin_switch_defaults_off(tmp_path):
    """真送回收站：默认必须关（破坏性功能）"""
    p = _pet(tmp_path)
    assert getattr(p, 'drag_to_bin', False) is False, \
        '拖文件真送回收站的开关默认必须是关'


def test_bin_switch_read_only_with_ui_entry():
    """第 3 条已实现（2026-11-01）：配置读取 **必须** 同时有 UI 入口

    上一批这条断言是反的（当时故意不读，避免死配置）。
    现在实现了，判据变成：读了配置就必须有设置入口 ——
    否则又是死配置（test_config_dead_keys 会抓，但这里先说清楚意图）。
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dp_src = open(os.path.join(here, 'desktop_pet.py'), encoding='utf-8').read()
    su_src = open(os.path.join(here, 'settings_ui.py'), encoding='utf-8').read()
    assert "cfg.get('drag_to_bin'" in dp_src, '没读 drag_to_bin，第 3 条等于没接'
    assert 'drag_to_bin' in su_src, '读了配置却没有 UI 入口 ⇒ 死配置'
