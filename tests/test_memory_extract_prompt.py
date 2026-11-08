# -*- coding: utf-8 -*-
"""抽取提示词的规则锁（2026-11-08）

为什么锁提示词：记忆抽取的偏斜（把「我们正在做的事」记成用户属性）只在提示词里治，
而提示词是长字符串、改别的规则时很容易顺手删掉某一条，且删了不会有任何报错。
这里只锁「哪几条规则必须在」，不锁措辞 —— 措辞可以改，规则不能丢。
"""
import io
import os

import memory_engine as me


def _prompt():
    return me.EXTRACT_PROMPT


# ---------- 规则锁：每条都用「必须出现的关键词」+「必须消失的旧措辞」 ----------

def test_rule_forbids_recording_work_material_as_user_possession():
    """必须禁止把「正在处理的数据/文件/代码」记成用户持有。

    2026-11-08 实测依据：6 段真实对话，旧提示词下 3/3 遍都抽出
    「用户手里有一份重庆区县矢量数据」——那是我们当轮一起在分析的那份文件，
    用户从没说过他「持有」它。改成点名列举后，3/3 遍都没再出现。
    """
    t = _prompt()
    assert '我们这段对话里正在处理的数据、文件、代码、项目' in t
    assert '不是用户「持有/拥有」的东西' in t
    # 旧措辞只针对「项目/代码」，盖不住「数据」，必须已被替换
    assert '我们正在讨论的项目/代码本身' not in t


def test_rule_forbids_recording_assistant_speculation_as_user_attribute():
    """必须禁止把助手自己的推测记成用户属性。

    2026-11-08 实测依据：段1 里助手说「从我们刚才的对话里，我能猜到你大概是
    和重庆有关联」——**用户从未说过**。旧提示词下每条出现该段的抽取都写成了
    「用户与重庆有关联，可能是重庆人」。加这条规则后 3/3 遍都没再出现。
    """
    t = _prompt()
    assert '我自己（助手）的推测' in t
    assert '那是我在猜，不是用户说的' in t


def test_rule_still_keeps_greeting_and_task_rules():
    """原有的两类规则不许在改提示词时被顺手删掉。"""
    t = _prompt()
    assert '一句寒暄或客套' in t, '寒暄规则丢了'
    assert '正在进行的具体任务' in t, '进行中任务规则丢了'


def test_prompt_is_not_blank_and_keeps_json_contract():
    """提示词不许被清空，且必须仍要求 JSON 输出（下游按 JSON 解析）。"""
    t = _prompt()
    assert len(t) > 500, '提示词短得不像话：%d 字' % len(t)
    assert 'JSON' in t
