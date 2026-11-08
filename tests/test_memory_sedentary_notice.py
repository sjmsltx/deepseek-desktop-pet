# -*- coding: utf-8 -*-
"""久坐提醒不得入事件库（2026-11-08 Owner 报障）

## 现象

星图里出现 11 条「提醒：😴 你已经连续坐 N 分钟了」，混在真回忆中间。
其中 11-06 19:26~19:38 是**一分钟一条**（51/55/56/57/59/60/61/62/63 分钟）。

## 根因

`say_care()` 把关心气泡文本写进 `memory_events.add()`，而 `add()` 的过滤
`is_recomputable_notice()` 只认「今天是X月X日」「当前设置了N条提醒」和金额播报。
久坐提醒不含 ¥、不匹配那两条 ⇒ 放行入库，还会被 `prompt_hint` 注入 system prompt。

## 同类问题第二次

`add()` 的 docstring 记着 2026-10-31 那次：「记得站起来活动一下」合并 32 次、weight 满格。
当时用 `origin='pet'` 解决的是「权重不涨」，**没解决「该不该入库」**。

## 这组锁的边界

只锁「久坐提醒必须被挡」和「真事件不许被误挡」。
**不锁「重复提醒」**：一分钟一条的机制我没有定论（单实例下 `_idle_warned` 逻辑不可能
一分钟一条，需要多实例或多重置点），登记为待查，不写成测试假装已知。
"""
import memory_events as mev


def test_sedentary_reminder_zh_is_blocked():
    """中文久坐提醒必须判为「可重算播报」——不入库、不注入 prompt。"""
    for n in (50, 51, 63, 111):
        title = '提醒：😴 你已经连续坐 %d 分钟了，起来活动一下、喝口水吧！' % n
        detail = '😴 你已经连续坐 %d 分钟了，起来活动一下、喝口水吧！' % n
        assert mev.is_recomputable_notice(title, detail), (
            '%d 分钟的久坐提醒没被挡住 —— 会进事件库、还会被注入 system prompt' % n)


def test_sedentary_reminder_en_is_blocked():
    """英文久坐提醒同样要挡（同一句话的英文分支，别只修中文）。"""
    title = '提醒：😴 You have been sitting for 51 minutes. Time to stretch!'
    assert mev.is_recomputable_notice(title, title), '英文久坐提醒没被挡住'


def test_sedentary_reminder_does_not_enter_store(tmp_path):
    """端到端：走产品入口 add()，久坐提醒必须返回 {} 且库里不新增。

    这是真正的行为锁 —— 上一条只测判定函数，判定对了但调用方没接也白搭。
    """
    st = mev.MemoryEvents(str(tmp_path / 'm.json'))
    before = len(st.all())
    for n in (50, 51, 52):
        got = st.add('flash', 'event',
                     '提醒：😴 你已经连续坐 %d 分钟了，起来活动一下、喝口水吧！' % n,
                     '😴 你已经连续坐 %d 分钟了' % n,
                     origin='pet')
        assert got == {}, '第 %d 分钟的久坐提醒入库了：%r' % (n, got)
    assert len(st.all()) == before, '库里条数变了：%d → %d' % (before, len(st.all()))


def test_real_reminder_is_not_swallowed():
    """带「提醒」二字的真事件不许被误挡。

    ⚠ 这是防「为了修 bug 把过滤写太宽」——比如直接匹配「提醒」两个字，
    就会把「提醒：明天记得交表」这类真回忆也吞掉。
    """
    for text in ('提醒：明天记得交表',
                 '提醒：妈妈说周五回家吃饭',
                 '用户连续坐了三年轮椅',          # 有「连续坐」但没有分钟数
                 '用户关注桌宠的记忆机制是否优化'):
        assert not mev.is_recomputable_notice(text, ''), (
            '真事件被误挡：%r —— 过滤写太宽了' % text)


def test_existing_auto_patterns_still_work():
    """既有的两类（日期 / 提醒条数）不许在加新规则时被弄坏。"""
    assert mev.is_recomputable_notice('今天是 10月31日 星期六', '')
    assert mev.is_recomputable_notice('当前设置了 0 条提醒', '')

def test_standup_template_is_blocked():
    """久坐关心的**另一种话术**也要挡：「主动关心：记得站起来活动一下」。

    为什么单列：这条没有分钟数，上一版只匹配「连续坐 N 分钟」时漏了它。
    库里确实留过一条（2026-10-30 10:56），清理时才看见。
    """
    for title, detail in (
            ('主动关心：记得站起来活动一下', '记得站起来活动一下'),
            ('记得站起来活动一下', ''),
            ('提醒：记得起身活动活动', ''),
    ):
        assert mev.is_recomputable_notice(title, detail), (
            '这句固定关心模板没被挡住：%r' % title)


def test_narration_about_standing_up_is_not_swallowed():
    """**叙述句**不许被吞 —— 「站起来活动」出现在真回忆里时是叙述，不是模板。

    ⚠ 这条是收窄判据的守门人：判据只能要求带「记得」这个祈使前缀。
    不能单用「起来活动」—— 它会命中「站**起来活动**」，把下面这类真事吞掉（实测过）。
    """
    for text in ('用户说他站起来活动了一下腰',
                 '用户站起来活动时把水杯碰倒了',
                 '用户今天起来活动了个够'):
        assert not mev.is_recomputable_notice(text, ''), (
            '叙述句被误当模板吞了：%r' % text)
