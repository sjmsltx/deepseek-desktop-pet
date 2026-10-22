# -*- coding: utf-8 -*-
"""模型能力表：统一读取入口 get_capability()

2026-10-19 引入（多 AI 接入准备）。
原则：capabilities 显式声明优先 → 旧字段兜底 → 默认值；
      老档案（没有 capabilities 块）不用改；不声明就按"不支持"处理。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_registry import CAPABILITY_DEFAULTS, ModelProfile  # noqa: E402


# ============ 显式声明优先 ============

def test_explicit_capabilities_override_legacy():
    """capabilities 说 false，就不该被顶层 vision:true 覆盖"""
    p = ModelProfile({'key': 'x', 'vision': True,
                      'capabilities': {'vision': False}})
    assert p.get_capability('vision') is False


def test_explicit_true_when_legacy_absent():
    p = ModelProfile({'key': 'x', 'capabilities': {'vision': True}})
    assert p.get_capability('vision') is True


# ============ 旧字段兜底（老档案不改也能用）============

def test_legacy_vision_field_falls_back():
    p = ModelProfile({'key': 'x', 'vision': True})
    assert p.get_capability('vision') is True


def test_legacy_vision_none_falls_back_to_model_table():
    """档案没声明 vision 时，交给 supports_vision 按官方能力表判断"""
    p = ModelProfile({'key': 'x', 'model_id': 'deepseek-flash'})
    assert p.get_capability('vision') == p.supports_vision


def test_reasoning_and_effort_follow_params():
    off = ModelProfile({'key': 'x', 'params': {'reasoning': False}})
    assert off.get_capability('reasoning') is False
    assert off.get_capability('effort') is False, '不开思考就没有强度可调'

    on = ModelProfile({'key': 'x', 'params': {'reasoning': True}})
    assert on.get_capability('reasoning') is True
    assert on.get_capability('effort') is True


# ============ 默认值 ============

def test_web_search_defaults_to_tool():
    """搜索是本地实现（走 DeepSeek 官方 Search API），与模型无关 ⇒ 默认可用"""
    p = ModelProfile({'key': 'x'})
    assert p.get_capability('web_search') == 'tool'
    assert CAPABILITY_DEFAULTS['web_search'] == 'tool'


def test_search_can_be_disabled_explicitly():
    p = ModelProfile({'key': 'x', 'capabilities': {'web_search': False}})
    assert p.get_capability('web_search') is False


def test_unknown_capability_returns_default():
    p = ModelProfile({'key': 'x'})
    assert p.get_capability('telepathy') is None
    assert p.get_capability('telepathy', 'fallback') == 'fallback'


def test_no_capabilities_block_is_safe():
    """完全没有 capabilities 的档案不能炸"""
    p = ModelProfile({'key': 'x', 'capabilities': None})
    assert p.capabilities == {}
    assert p.get_capability('vision') == p.supports_vision


# ============ 不污染真实配置 ============

def test_profile_construction_does_not_touch_disk():
    """ModelProfile(dict) 是纯内存构造，不该读写任何文件"""
    before = os.path.getmtime('models.json') if os.path.exists('models.json') else None
    ModelProfile({'key': 'tmp', 'capabilities': {'vision': True}})
    after = os.path.getmtime('models.json') if os.path.exists('models.json') else None
    assert before == after

# ============ 读写往返：能读也必须能存 ============

def test_capabilities_survive_to_dict_roundtrip():
    """to_dict() 必须带走 capabilities，否则 save() 之后就丢了"""
    p = ModelProfile({'key': 'x', 'capabilities': {'vision': False, 'web_search': False}})
    d = p.to_dict()
    assert 'capabilities' in d, 'to_dict 必须包含 capabilities'
    again = ModelProfile(d)
    assert again.get_capability('vision') is False
    assert again.get_capability('web_search') is False


def test_empty_capabilities_not_written():
    """老档案没有能力表时，保存后不该凭空多出一个空块"""
    p = ModelProfile({'key': 'x'})
    assert 'capabilities' not in p.to_dict()
