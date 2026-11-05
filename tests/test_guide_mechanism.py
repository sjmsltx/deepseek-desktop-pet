# -*- coding: utf-8 -*-
"""「运行中追加消息」= AutoClaw 的「引导」机制测试（2026-11-01）

Owner 需求：
    「在你任务进行过程当中我还能够直接插话进来相当于说是指导你的方向，
      但是原来的那个任务还没停止」

口径来源：AutoClaw 实测（评审-309），不是我的推测：
    · 两档 queue / guide，**默认 queue**
    · guide = 立即并入当前任务，**不中断正在进行的模型请求**
    · 只有存在 running 的 run 才允许引导
    · Ctrl+Enter 临时改用另一种

本文件锁住这些行为，特别是「假引导」（说了但没注入）这类最容易骗过自己的问题。
"""
import json
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

import desktop_pet as dp  # noqa: E402
import affection_engine as ae  # noqa: E402


def _pet(tmp_path, **attrs):
    p = dp.PetWidget()
    p._save_cfg_value = lambda *a, **k: True
    p.affection = ae.AffectionEngine(str(tmp_path / 'aff.json'))
    # 气泡/通知/聊天记录全部打桩：这些不是本文件要测的东西，
    # 真跑会引入时序与 Qt 控件副作用（上一轮 flaky 就是这么来的）
    p._bubbles = []
    p._notices = []
    p._chats = []
    p.say_plain = lambda t, *a, **k: p._bubbles.append(t)
    p._notify = lambda t, *a, **k: p._notices.append(t)
    p._append_chat = lambda who, t: p._chats.append((who, t))
    for k, v in attrs.items():
        setattr(p, k, v)
    return p


# ---------- A. 档位与默认值 ----------
def test_modes_and_default():
    assert dp.PetWidget.FOLLOW_UP_MODES == ('queue', 'guide')
    assert dp.PetWidget.FOLLOW_UP_DEFAULT == 'queue', '默认必须是排队（与 AutoClaw 一致）'


@pytest.mark.parametrize('raw,want', [
    ('guide', 'guide'), ('GUIDE', 'guide'), (' queue ', 'queue'),
    ('乱写', 'queue'), ('', 'queue'), (None, 'queue'), ('steer', 'queue'),
])
def test_normalize(raw, want):
    assert dp.PetWidget._normalize_follow_up_mode(raw) == want


def test_default_is_structural_not_only_in_cfg_branch(tmp_path):
    """没有 config.json 时属性也必须存在且为 queue

    ⛔ 只在 cfg 分支里赋默认值 = 没配置文件就 AttributeError 或被 getattr
       兜底成别的档。这个坑 2026-10-31 踩过一次（random_action_when / drag_to_bin）。
    """
    p = _pet(tmp_path)
    assert hasattr(p, 'follow_up_mode'), 'follow_up_mode 必须是无条件初始化的'
    assert p.follow_up_mode == 'queue'


def test_not_in_config_whitelist():
    """模型不能自己改交互模式（同 affection_mode 的理由）"""
    wl = dp.PetWidget.CONFIG_WHITELIST
    wl = tuple(wl) if not isinstance(wl, str) else (wl,)
    assert 'follow_up_mode' not in wl, (
        'follow_up_mode 进了 CONFIG_WHITELIST —— 模型能自己决定要不要被打断')


# ---------- B. 提交引导 ----------
def test_guide_rejected_when_not_busy(tmp_path):
    """没有在跑的任务 → 不是引导，交给普通发送路径"""
    p = _pet(tmp_path, _ai_busy=False)
    assert p._submit_guide('改个方向') is False
    assert p._guide_inbox == []


def test_guide_accepted_when_busy(tmp_path):
    p = _pet(tmp_path, _ai_busy=True)
    assert p._submit_guide('先别改前端，把接口补上') is True
    assert len(p._guide_inbox) == 1
    assert p._guide_inbox[0]['text'] == '先别改前端，把接口补上'


def test_guide_appears_as_own_chat_line(tmp_path):
    """引导在对话里独立显示，不混进用户气泡（AutoClaw 那边也是独立块）"""
    p = _pet(tmp_path, _ai_busy=True)
    p._submit_guide('换个思路')
    assert p._chats, '引导没有在对话里留痕'
    who, text = p._chats[-1]
    assert text.startswith('🧭 引导'), '引导行没有标记，和普通用户消息混在一起了'
    assert '换个思路' in text


def test_guide_with_images_degrades_to_queue(tmp_path):
    """带附件的引导注入不了图 ⇒ 诚实降级成排队，不假装已引导"""
    p = _pet(tmp_path, _ai_busy=True)
    ok = p._submit_guide('看这张图', images=['a.png'])
    assert ok is True
    assert p._guide_inbox == [], '带图时不该进引导收件箱（注入了模型也看不到图）'
    assert len(p._task_queue) == 1, '带图的引导必须转成排队，不能丢'
    assert any('改为排队' in n for n in p._notices)


def test_empty_guide_ignored(tmp_path):
    p = _pet(tmp_path, _ai_busy=True)
    assert p._submit_guide('   ') is False
    assert p._guide_inbox == []


# ---------- C. 取走 ----------
def test_drain_takes_all_and_clears(tmp_path):
    p = _pet(tmp_path, _ai_busy=True)
    p._submit_guide('第一条')
    p._submit_guide('第二条')
    got = p._drain_guides()
    assert got == ['第一条', '第二条']
    assert p._guide_inbox == []
    assert p._drain_guides() == []


def test_drain_is_thread_safe_on_repeat(tmp_path):
    """反复取不会重复交付（这是「引导被注入两次」的直接防线）"""
    p = _pet(tmp_path, _ai_busy=True)
    p._submit_guide('只应出现一次')
    assert p._drain_guides() == ['只应出现一次']
    assert p._drain_guides() == []
    assert p._drain_guides() == []


# ---------- D. 引导正文 ----------
def test_guide_message_tells_model_not_to_restart(tmp_path):
    p = _pet(tmp_path, _ai_busy=True)
    txt = p._guide_message_content('先修 A 再修 B')
    assert '先修 A 再修 B' in txt
    assert '不要' in txt and '重来' in txt, '没告诉模型「别把整个任务重来」'


def test_guide_message_english(tmp_path):
    p = _pet(tmp_path, _ai_busy=True, language='en')
    txt = p._guide_message_content('fix A first')
    assert 'fix A first' in txt
    assert 'do not restart' in txt.lower()


# ---------- E. ask_ai 的分流 ----------
def _pet_for_ask(tmp_path, **attrs):
    """ask_ai 专用：它第一行就是 _load_ai_config()，会按真实 config.json 覆盖
    档位、并可能因 ai_enabled 为假直接早退 —— 测试里必须先把这两点固定住，
    否则测的是「真实配置」而不是被测逻辑。"""
    p = _pet(tmp_path, **attrs)
    p._load_ai_config = lambda: None
    p.ai_enabled = True
    return p


def test_ask_ai_busy_queue_mode_queues(tmp_path):
    """回归：默认档位下，忙时发消息仍然进排队队列（老行为不能坏）"""
    p = _pet_for_ask(tmp_path, _ai_busy=True, follow_up_mode='queue')
    p.ask_ai('帮我看看这个')
    assert len(p._task_queue) == 1
    assert p._guide_inbox == []


def test_ask_ai_busy_guide_mode_guides(tmp_path):
    p = _pet_for_ask(tmp_path, _ai_busy=True, follow_up_mode='guide')
    p.ask_ai('走另一个方案')
    assert len(p._guide_inbox) == 1
    assert p._task_queue == [], '引导不该同时进排队'


def test_ask_ai_alt_flag_switches_once(tmp_path):
    """Ctrl+Enter：本次临时改用另一种，用完即清（不改设置）"""
    p = _pet_for_ask(tmp_path, _ai_busy=True, follow_up_mode='queue')
    p._followup_alt = True
    p.ask_ai('临时用引导')
    assert len(p._guide_inbox) == 1, 'Ctrl+Enter 没能临时切到引导'
    assert p._followup_alt is False, '临时标记用完必须清掉'
    # 下一次回到默认档位
    p.ask_ai('这次该排队了')
    assert len(p._task_queue) == 1


# ---------- F. 收尾不丢消息 ----------
def test_leftover_guides_become_queued_tasks(tmp_path):
    """本轮结束时没赶上注入的引导 → 转排队，并明确告知（不丢）"""
    p = _pet(tmp_path, _ai_busy=True)
    p._submit_guide('没赶上的一句话')
    n = p._settle_leftover_guides()
    assert n == 1
    assert p._guide_inbox == []
    assert len(p._task_queue) == 1
    assert p._task_queue[0]['text'] == '没赶上的一句话'
    assert any('转为排队' in x for x in p._notices)


def test_leftover_noop_when_empty(tmp_path):
    p = _pet(tmp_path)
    assert p._settle_leftover_guides() == 0
    assert p._task_queue == []


# ---------- G. 端到端：真的注入进下一轮请求 ----------
class _FakeStream:
    """假流式：第 1 轮返回一个工具调用，第 2 轮返回终稿

    用它替掉 `desktop_pet.stream_chat_completions`，就能在**不联网**的情况下
    走完 `_ai_worker` 的真实工具循环，并记录每一轮请求里的 messages。
    """

    def __init__(self, on_first_round=None):
        self.payloads = []
        self.round = 0
        self.on_first_round = on_first_round

    def __call__(self, api_key, data, **kw):
        payload = json.loads(data)
        self.payloads.append(payload)
        self.round += 1
        if self.round == 1:
            if self.on_first_round:
                # 模拟「任务正在跑的时候主人插话」
                self.on_first_round()
            yield ('content', '我先看看…')
            yield ('done', {'content': '我先看看…',
                            'tool_calls': [{'id': 'c1', 'type': 'function',
                                            'function': {'name': 'get_system_info',
                                                         'arguments': '{}'}}],
                            'reasoning_content': ''})
            return
        yield ('content', '好，按你说的方向做了')
        yield ('done', {'content': '好，按你说的方向做了', 'tool_calls': None,
                        'reasoning_content': ''})


def _wire_worker(p, fake):
    p._current_api_key = lambda: 'sk-test'
    p._request_endpoint = lambda: 'http://127.0.0.1:1/chat'
    p._execute_tool = lambda name, args: '工具结果'
    p._maybe_extract_memory = lambda: None
    p._speak_reply = lambda *a, **k: None
    p._record_api_usage = lambda *a, **k: None
    p._handle_affection = lambda *a, **k: None
    # ⛔ 不能给 Signal.emit 赋值（PySide6 里是 read-only，会 AttributeError）。
    #   改成断开所有槽：信号照发，但没人接 —— 既不起 UI，也不筛产品接口。
    for _sig in (p.ai_status_signal, p.reasoning_signal, p.stream_signal,
                 p.stream_done_signal, p.ai_reply_signal):
        try:
            _sig.disconnect()
        except Exception:
            pass
    return fake


def test_guide_is_injected_into_next_round(tmp_path, monkeypatch):
    """核心：任务跑着的时候插话 → 下一轮请求里真的带上了这句话"""
    p = _pet(tmp_path, _ai_busy=True, follow_up_mode='guide')
    fake = _FakeStream(on_first_round=lambda: p._submit_guide('别改前端，先把接口补齐'))
    _wire_worker(p, fake)
    monkeypatch.setattr(dp, 'stream_chat_completions', fake)

    p._ai_worker('把项目整理一下')

    assert len(fake.payloads) >= 2, '没有走到第二轮，注入点没被触发'
    msgs_2 = fake.payloads[1]['messages']
    joined = json.dumps(msgs_2, ensure_ascii=False)
    assert '别改前端，先把接口补齐' in joined, (
        '第二轮请求里没有引导内容 —— 这就是「假引导」：用户以为说了，实际没生效')
    # 注入的那条要是 user 角色（模型侧才当指令读）
    assert any(m.get('role') == 'user' and '别改前端' in str(m.get('content'))
               for m in msgs_2)


def test_guide_sent_during_round_does_not_retroactively_change_it(tmp_path, monkeypatch):
    """本轮请求已发出后提交的引导，不能反过来改这一轮的请求体

    ⚠ 上一版这条测试的前提写反了：写的是「worker 启动前就有的引导也不许进第 1 轮」。
      那不是对错问题 —— 第 1 轮请求**还没发出去**，带上它是对的（甚至更好）。
      真正要防的是：**已经发出去的请求**被事后改 messages（那叫假注入）。
    """
    p = _pet(tmp_path, _ai_busy=True, follow_up_mode='guide')
    fake = _FakeStream(on_first_round=lambda: p._submit_guide('第 1 轮进行中插的话'))
    _wire_worker(p, fake)
    monkeypatch.setattr(dp, 'stream_chat_completions', fake)
    p._ai_worker('开始干活')

    first = json.dumps(fake.payloads[0]['messages'], ensure_ascii=False)
    assert '第 1 轮进行中插的话' not in first, (
        '第 1 轮的请求体里出现了「第 1 轮进行中」才提交的话 —— '
        '请求已经发出去又被改，这是假注入')
    second = json.dumps(fake.payloads[1]['messages'], ensure_ascii=False)
    assert '第 1 轮进行中插的话' in second, '本轮插的话没有进下一轮'


def test_guide_present_before_run_goes_into_first_round(tmp_path, monkeypatch):
    """对照：跑之前就在的引导，进第 1 轮是正确行为（请求还没发）"""
    p = _pet(tmp_path, _ai_busy=True, follow_up_mode='guide')
    fake = _FakeStream()
    _wire_worker(p, fake)
    monkeypatch.setattr(dp, 'stream_chat_completions', fake)
    p._submit_guide('开跑之前就在的话')
    p._ai_worker('开始干活')
    first = json.dumps(fake.payloads[0]['messages'], ensure_ascii=False)
    assert '开跑之前就在的话' in first


def test_drain_after_injection_leaves_inbox_empty(tmp_path, monkeypatch):
    p = _pet(tmp_path, _ai_busy=True, follow_up_mode='guide')
    fake = _FakeStream(on_first_round=lambda: p._submit_guide('注入一次就够'))
    _wire_worker(p, fake)
    monkeypatch.setattr(dp, 'stream_chat_completions', fake)
    p._ai_worker('干活')
    assert p._guide_inbox == [], '引导取走后收件箱必须清空（否则会重复注入）'


def test_leftover_after_run_is_queued(tmp_path, monkeypatch):
    """跑完才发现还有没注入的引导 → 转排队，不丢"""
    p = _pet(tmp_path, _ai_busy=True, follow_up_mode='guide')

    class OneShot:
        def __init__(self):
            self.n = 0

        def __call__(self, api_key, data, **kw):
            self.n += 1
            if self.n == 1:
                yield ('content', '直接答完，不调工具')
                yield ('done', {'content': '直接答完，不调工具', 'tool_calls': None,
                                'reasoning_content': ''})
                return
            yield ('content', '续')
            yield ('done', {'content': '续', 'tool_calls': None, 'reasoning_content': ''})

    p = _pet(tmp_path, _ai_busy=True, follow_up_mode='guide')
    holder = {}

    class OneShot:
        """只在收到请求时（= 本轮已发出、且是最后一轮）提交一条引导

        这样引导落在「最后一次回合边界之后」⇒ 循环不会再取它
        ⇒ 正好构造出「剩余引导」这个场景。
        """
        def __init__(self):
            self.n = 0

        def __call__(self, api_key, data, **kw):
            self.n += 1
            if self.n == 1:
                holder['p']._submit_guide('这轮赶不上了')
                yield ('content', '直接答完，不调工具')
                yield ('done', {'content': '直接答完，不调工具', 'tool_calls': None,
                                'reasoning_content': ''})
                return
            yield ('content', '续')
            yield ('done', {'content': '续', 'tool_calls': None, 'reasoning_content': ''})

    fake = OneShot()
    holder['p'] = p
    _wire_worker(p, fake)
    monkeypatch.setattr(dp, 'stream_chat_completions', fake)
    # worker 的 finally 会 _next_task() 把转来的排队任务**立刻接走执行**
    # ⇒ 跑完之后它不在队列里是正常的。把 _run_task 拦住并记录，
    #   才能区分「没丢、被接走执行了」和「真丢了」。
    ran = []
    p._run_task = lambda text, images=None: ran.append(text)
    p._ai_worker('一问一答')
    assert p._guide_inbox == [], '剩余引导没有被结算'
    survived = ('这轮赶不上了' in ran) or any(
        t.get('text') == '这轮赶不上了' for t in p._task_queue)
    assert survived, (
        '剩余引导既没注入、也没转排队、更没被接走 —— 消息丢了。'
        'ran=%r queue=%r' % (ran, [t.get('text') for t in p._task_queue]))


# ---------- H. 侧栏显示 ----------
def test_sidebar_shows_guides_separately(tmp_path):
    p = _pet(tmp_path, _ai_busy=True)
    p._submit_guide('侧栏要能看到')
    items = [p.side_panel._tasks_list.item(i).text()
             for i in range(p.side_panel._tasks_list.count())]
    assert any(x.startswith('🧭 引导') for x in items), (
        '侧栏没有单列引导 —— 用户看不出「我插的那句话进去了没」：%r' % items)


def test_sidebar_guide_row_not_draggable(tmp_path):
    """已提交的引导不可拖（拖了也没意义，还可能被当成排队项再执行一次）"""
    from PySide6.QtCore import Qt
    p = _pet(tmp_path, _ai_busy=True)
    p._submit_guide('不可拖')
    for i in range(p.side_panel._tasks_list.count()):
        it = p.side_panel._tasks_list.item(i)
        if it.text().startswith('🧭'):
            assert it.flags() == Qt.NoItemFlags
            return
    pytest.fail('侧栏里找不到引导行')


# ---------- I. 设置界面 ----------
def test_settings_has_followup_combo(tmp_path):
    import settings_ui
    dlg = settings_ui.SettingsDialog.__new__(settings_ui.SettingsDialog)
    # 只验证控件名与取值映射存在（不实例化整个对话框：它要宿主 + 一堆依赖）
    src = open(os.path.join(BASE, 'settings_ui.py'), encoding='utf-8').read()
    assert 'cb_followup' in src, '设置界面没有「运行中追加消息」控件'
    assert '_set_follow_up_mode' in src, '设置界面没有接到 _set_follow_up_mode'
    assert "'queue'" in src and "'guide'" in src
    del dlg


def test_set_follow_up_mode_persists(tmp_path):
    p = _pet(tmp_path)
    saved = {}
    p._save_cfg_value = lambda k, v: saved.__setitem__(k, v) or True
    p._set_follow_up_mode('guide')
    assert p.follow_up_mode == 'guide'
    assert saved.get('follow_up_mode') == 'guide'
    # 非法值回落默认
    p._set_follow_up_mode('胡说')
    assert p.follow_up_mode == 'queue'
