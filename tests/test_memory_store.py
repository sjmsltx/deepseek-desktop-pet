# -*- coding: utf-8 -*-
"""memory_store.remember_fact 的写入路径测试（2026-11-05 新建）

## 为什么建这个文件

`remember_fact` 是**三条实时写入路径的唯一入口**
（memorize 工具 / 自动抽取 / 记忆管理界面「添加」），
但在此之前**零测试覆盖** —— 所以它里面那段「超 50 条物理截断」活了很久没人发现。

WX-179 审出它把 2026-11-04 整批容量治理架空：
台账 / critical 保护 / 400 条上限，在真实路径上全部不生效。
另外 facts 侧 id 生成无撞号检查，存量已撞 3 组（6 条不同记忆共用 3 个 id）。

## 本文件锁什么

  · 容量判断只能有一个出口（`_enforce_memory_cap`），这里**不许**物理删
  · id 必须不撞号
  · 不再 `sort()` 打乱整库顺序（`_extract_worker` 靠 `[-10:]` 取上下文）
  · 既有的 add / update / delete 行为不因本次改动而变
"""
import sys

import pytest

sys.path.insert(0, __file__.rsplit('tests', 1)[0])

import memory_store as ms      # noqa: E402


def _f(fid, content='内容', imp=3, status='active', ts='2026-01-01T00:00:00'):
    return {'id': fid, 'content': content, 'importance': imp,
            'created_at': ts, 'updated_at': ts, 'status': status}


# ═══ 容量：只能有一个出口 ═══

def test_remember_fact_never_physically_drops():
    """★ 核心回归：这里物理删会让台账 / critical / FACTS_MAX 全部失效

    原代码（已删）：
        if len(facts) > 50:
            facts.sort(key=lambda x: (x.get('importance', 3), x.get('updated_at', '')))
            facts = facts[-50:]
    """
    facts = []
    for i in range(60):
        facts, _ = ms.remember_fact(facts, 'add', content='条目 %d 号唯一' % i, importance=3)
    assert len(facts) == 60, '被物理截断了：只剩 %d 条' % len(facts)


def test_no_cap_at_any_size():
    """加到 500 条也不能截断 —— 上限归 _enforce_memory_cap 管（FACTS_MAX=400）"""
    facts = []
    for i in range(500):
        facts, _ = ms.remember_fact(facts, 'add', content='#%d# 唯一标记' % i, importance=3)
    # ⚠ 必须是 == 不能是 >= 400（WX-180 ① 指出）：400 上限刚好能通过 >= 400，
    #   而本测试的名字和 docstring 都说「任何大小都不许有上限」。
    #   `>= 400` 区分不了「无上限」与「400 上限」⇒ 证明不了自己要证的事。
    assert len(facts) == 500, '这里不该有任何上限，实测只剩 %d 条' % len(facts)


def test_critical_entry_never_dropped_here():
    """过敏类条目不许在这条路径上消失（保护在 _enforce_memory_cap，这里不删）"""
    facts = [_f('n%d' % i, '普通 %d 唯一' % i, imp=2) for i in range(499)]
    facts.append(_f('ALLERGY', '对花生过敏，吃了会呼吸困难', imp=1, ts='2025-01-01T00:00:00'))
    out, _ = ms.remember_fact(facts, 'add', content='新条目 唯一内容', importance=3)
    assert 'ALLERGY' in [f['id'] for f in out], '过敏被物理删了'


def test_superseded_not_preferred_for_dropping():
    """作废条目不该因为是「已作废」就被优先清掉 —— 本层根本不做容量判断"""
    facts = [_f('SUP', '已作废', imp=5, status='superseded', ts='2020-01-01T00:00:00')]
    facts += [_f('n%d' % i, '普通 %d 唯一' % i, imp=2) for i in range(200)]
    out, _ = ms.remember_fact(facts, 'add', content='新条目 唯一内容', importance=3)
    assert 'SUP' in [f['id'] for f in out]
    assert len(out) == 202


def test_add_does_not_reorder_existing_facts():
    """不再 sort() 打乱顺序 —— _extract_worker 用 self.memory_facts[-10:] 取上下文"""
    facts = [_f('a%d' % i, '原始 %d 唯一' % i) for i in range(80)]
    before = [f['id'] for f in facts]
    out, _ = ms.remember_fact(facts, 'add', content='新来的 唯一内容', importance=3)
    after = [f['id'] for f in out if f['id'] in set(before)]
    assert after == before, '原有顺序被打乱了'


# ═══ id 撞号 ═══

def test_ids_never_collide_on_rapid_add():
    """★ 核心回归：自动抽取一批多条同循环连写，同毫秒必然撞号（原实现）"""
    facts = []
    for i in range(300):
        facts, _ = ms.remember_fact(facts, 'add', content='#%d# 各不相同的标记内容' % i,
                                    importance=3)
    ids = [f['id'] for f in facts]
    assert len(ids) == len(set(ids)), '撞号 %d 组：%r' % (
        len(ids) - len(set(ids)), [(k, ids.count(k)) for k in set(ids) if ids.count(k) > 1][:3])


def test_next_fact_id_skips_used():
    """直接测 _next_fact_id：给定已占用的 id，必须返回没被占的"""
    used = [_f('f1000'), _f('f1000-1'), _f('f1000-2')]
    got = ms._next_fact_id(used)
    assert got not in {'f1000', 'f1000-1', 'f1000-2'}, '返回了已占用的 id：%s' % got


def test_next_fact_id_format():
    """保持原有 `f<毫秒>` 前缀，撞号才加 `-n` 后缀（不破坏既有数据形状）"""
    got = ms._next_fact_id([])
    assert got.startswith('f'), 'id 丢了 f 前缀：%s' % got
    assert got[1:].isdigit(), 'id 主体不是毫秒数字：%s' % got


def test_next_fact_id_handles_empty_and_junk():
    """空库 / 脏数据不许崩"""
    assert ms._next_fact_id([]).startswith('f')
    assert ms._next_fact_id([{'no_id': 1}, None, 'junk']).startswith('f')


# ═══ 既有行为回归（防我改坏）═══

def test_add_empty_content_rejected():
    facts, msg = ms.remember_fact([], 'add', content='   ')
    assert facts == []
    assert '为空' in msg


def test_add_merges_similar_content():
    """相似内容软覆盖（既有行为，不是我加的）"""
    facts = [_f('A', '用户喜欢喝冰美式咖啡')]
    out, msg = ms.remember_fact(facts, 'add', content='用户喜欢喝冰美式咖啡', importance=4)
    assert len(out) == 1, '相似内容应更新而非新增，实测 %d 条' % len(out)
    assert out[0]['importance'] == 4
    assert '已更新' in msg


def test_add_clamps_importance():
    for raw, want in ((0, 1), (9, 5), ('x', 3), (3, 3)):
        out, _ = ms.remember_fact([], 'add', content='内容唯一 %r' % (raw,), importance=raw)
        assert out[0]['importance'] == want, 'importance=%r 应夹到 %d，实得 %d' % (
            raw, want, out[0]['importance'])


def test_add_sets_active_and_role():
    out, _ = ms.remember_fact([], 'add', content='内容唯一 x', importance=3, role='flash')
    assert out[0]['status'] == 'active'
    assert out[0]['roles'] == 'flash'


def test_delete_marks_superseded():
    facts = [_f('D', '要忘掉的事')]
    out, msg = ms.remember_fact(facts, 'delete', fid='D')
    assert out[0]['status'] == 'superseded'
    assert '已遗忘' in msg


def test_delete_missing_returns_message():
    out, msg = ms.remember_fact([_f('D')], 'delete', fid='NOPE')
    assert out[0]['status'] == 'active'
    assert '未找到' in msg


def test_update_existing():
    facts = [_f('U', '旧内容', imp=2, status='superseded')]
    out, msg = ms.remember_fact(facts, 'update', fid='U', content='新内容', importance=5)
    assert out[0]['content'] == '新内容'
    assert out[0]['importance'] == 5
    assert out[0]['status'] == 'active', 'update 应把作废的救回 active'
    assert '已更新' in msg


def test_update_missing_returns_message():
    _, msg = ms.remember_fact([_f('U')], 'update', fid='NOPE', content='x')
    assert '未找到' in msg


def test_unknown_action_returns_message():
    facts = [_f('U')]
    out, msg = ms.remember_fact(facts, 'frobnicate')
    assert len(out) == 1
    assert '未知操作' in msg


def test_pure_function_does_not_mutate_input_list():
    """纯函数：返回新列表，不改调用方传入的 list 对象本身"""
    src = [_f('A'), _f('B')]
    original_len = len(src)
    ms.remember_fact(src, 'add', content='新内容 唯一', importance=3)
    assert len(src) == original_len, '入参 list 被就地追加了'


def test_evicted_entries_survive_here():
    """已淘汰（status=evicted）的条目也不许在本层被删 —— 淘汰归 _enforce_memory_cap"""
    facts = [_f('E%d' % i, '已淘汰 %d' % i, status='evicted') for i in range(60)]
    out, _ = ms.remember_fact(facts, 'add', content='新内容 唯一', importance=3)
    assert len([f for f in out if f.get('status') == 'evicted']) == 60
