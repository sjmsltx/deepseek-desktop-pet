# -*- coding: utf-8 -*-
"""A 组的回归锁（2026-11-14）

光改一遍文字没用 —— 这些文字的特殊之处是「改错了不会报错，只会误导人」。
所以每条都加一个断言，把它们钉住。

钉四条：
1 rerank 的 docstring 必须写明「60 token 是启用前置条件」，且不许再出现「属另一件事」
2 rerank 开关的 tooltip 必须写明「约一半轮次不注入」
3 importorskip 的 reason 不许再写「尚未实现」（那两个模块早就存在了）
4 DSH 冷启动注释必须同时有两个测量点（19s / 34.8s），不许只有旧的
"""
import io
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return io.open(os.path.join(ROOT, rel), encoding='utf-8').read()


def test_rerank_docstring_states_the_coupling():
    """`max_tokens=60` 不是「另一件事」—— 它是启用 rerank 的前置条件。

    为什么钉它：弃权语义修好后，60 token 导致的 49% 空返回会从「硬塞三条」
    变成「一条不注入」。这句话如果退回旧表述，将来有人打开开关就会踩。
    """
    src = _read('desktop_pet.py')
    i = src.find('def _rerank_memories')
    assert i > 0
    doc = src[i:i + 3000]
    assert '前置条件' in doc, 'docstring 没写明 max_tokens 是启用前置条件'
    assert '49%' in doc, 'docstring 没写 49% 这个实测数'
    assert '改它要同时评估误注入，属另一件事' not in doc, (
        'docstring 退回了「属另一件事」的旧判断 —— 那个判断在弃权修好后已失效')


def test_rerank_tooltip_warns_about_half_silent():
    """设置界面的开关 tooltip 必须说清「约一半轮次不注入」。"""
    src = _read('settings_ui.py')
    i = src.find('ck_rerank.setToolTip')
    assert i > 0
    tip = src[i:i + 700]
    assert '49%' in tip, 'tooltip 没写 49%'
    assert '不注入' in tip, 'tooltip 没说清「不注入」这个后果'


def test_importorskip_reasons_are_not_stale():
    """不许再写「尚未实现」—— relay_log.py 与 collab/relay_server.py 早已存在。

    钉它是因为：这种文案不会让测试红，但会让「哪些没做」的审计直接跑偏
    （本轮盘点就差点被它带偏）。
    """
    bad = []
    for name in ('test_collab_server.py', 'test_relay_log_boundary.py',
                 'test_relay_log_replay_state.py', 'test_relay_log_reverse.py'):
        s = _read(os.path.join('tests', name))
        for i, line in enumerate(s.split('\n'), 1):
            if 'importorskip' in line and '尚未实现' in line:
                bad.append('%s:%d' % (name, i))
    assert not bad, '这些 importorskip 仍写着「尚未实现」：%r' % bad


def test_importorskip_targets_really_exist():
    """反过来：如果模块真不存在，那 importorskip 是合理的。

    这条防「把 reason 改对了、但模块后来被删了」这种反向漂移。
    """
    assert os.path.isfile(os.path.join(ROOT, 'relay_log.py')), 'relay_log.py 不见了'
    assert os.path.isfile(os.path.join(ROOT, 'collab', 'relay_server.py')), \
        'collab/relay_server.py 不见了'


def test_dsh_cold_start_has_two_data_points():
    """DSH 冷启动注释必须同时有 19s（10-04）与 34.8s（11-02 之后）两个数。

    钉它是因为：只写 19 秒会让人以为 40 秒预算还有 21 秒余量，实际只有 5 秒。
    """
    src = _read('desktop_pet.py')
    i = src.find('最多等 40 秒')
    assert i > 0
    seg = src[i:i + 900]
    assert '34.8' in seg, '冷启动注释没补 34.8 秒这个新测量点'
    assert '19 秒' in seg or '19s' in seg, '旧测量点被删了（两个都要留，才能看出涨了多少）'

    dsh = _read('dsh_panel.py')
    j = dsh.find('start_budget')
    assert j > 0
    seg2 = dsh[j:j + 500]
    assert '34.8' in seg2, 'dsh_panel 的 start_budget 说明没补 34.8s'


def test_good_first_issues_uses_real_dict_names():
    """`good-first-issues` 里的键名必须与代码一致（UI_ZH / UI_EN）。

    旧名 `_TEXT_ZH` / `_TEXT_EN` 在全仓 0 处，照原文找不到文件。
    ⚠ 允许在「更正说明」里提到旧名（那里本来就该说明旧名是什么），
       所以判据是：正文里提到字典时用的是 UI_ZH，且旧名只出现在更正段。
    """
    doc = _read(os.path.join('docs', 'good-first-issues.md'))
    assert 'UI_ZH' in doc and 'UI_EN' in doc, '文档里没有真实键名'
    # ⚠ 逐行判，不数总数 —— 数总数会被「更正说明里可以提旧名」这条放水
    #   （真锁第 1 轮就栽在这里：正文退回旧名后总数 2，仍 <= 阈值 2，假绿）
    offenders = []
    for i, line in enumerate(doc.split('\n'), 1):
        if '_TEXT_ZH' not in line and '_TEXT_EN' not in line:
            continue
        # 只允许在「更正/说明」引用里出现（以 > 开头的引用行）
        if line.lstrip().startswith('>'):
            continue
        offenders.append('L%d: %s' % (i, line.strip()[:60]))
    assert not offenders, (
        '正文里还在用不存在的旧键名（只允许在 > 开头的更正说明里提）：\n  '
        + '\n  '.join(offenders))

    src = _read('desktop_pet.py')
    assert 'UI_ZH = {' in src and 'UI_EN = {' in src, '代码里的字典名变了？'
