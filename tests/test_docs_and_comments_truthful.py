# -*- coding: utf-8 -*-
"""A 组的回归锁（2026-11-14）

⚠ 2026-11-14 晚更新：rerank 两条锁已随实测结论改写（原文见文件内说明）。
  锁钉的应该是当前事实，不是我当时下的结论。

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


def test_rerank_docstring_records_the_real_root_cause():
    """docstring 必须写清「根因是没关思考」，不许把 60 当现状。

    ⚠ 本条 2026-11-14 改写过一次。上一版钉的是「60 是启用前置条件」，
    那个定性被实测推翻：真因是请求没关思考，推理 token 与正文共享
    max_tokens，60 被推理一个人吃光（实测 27/29 截断）。
    锁跟着事实走，不跟着我的旧结论走。
    """
    src = _read('desktop_pet.py')
    i = src.find('def _rerank_memories')
    assert i > 0
    doc = src[i:i + 4000].split('"""')[1]
    assert '关思考' in doc, 'docstring 没写真正的根因（关思考）'
    assert 'RERANK_THINKING_FIELDS' in doc, 'docstring 没指向实际生效的常量'
    assert '未修' not in doc, 'docstring 还写着「未修」（已修）'
    assert '属另一件事' not in doc, 'docstring 退回了「属另一件事」的旧判断'


def test_rerank_tooltip_says_abstain_is_normal():
    """tooltip 必须说清「空 = 模型主动弃权，属正常」，不许再拿 60/49% 吓人。"""
    src = _read('settings_ui.py')
    i = src.find('ck_rerank.setToolTip')
    assert i > 0
    tip = src[i:i + 700]
    assert '弃权' in tip, 'tooltip 没说清「空」是弃权'
    assert '60 token' not in tip, 'tooltip 还把 60 token 当现状'
    assert '49%' not in tip, 'tooltip 还把 49% 当现状'


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
