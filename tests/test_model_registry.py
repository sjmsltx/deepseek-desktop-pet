# -*- coding: utf-8 -*-
"""
test_model_registry.py — 模型档案注册表单测
============================================
覆盖：首次生成 / 旧配置迁移 / 重命名升级 / 上限夹取 / 损坏回退 /
      价格查询 / 兼容层 characters() / 增删档案 / 落盘往返。

直接运行：python tests/test_model_registry.py
也可被 pytest 收集。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_registry import (  # noqa: E402
    BUILTIN_PROFILES, MAX_OUTPUT_TOKENS, MIN_OUTPUT_TOKENS, ModelRegistry, clamp_tokens,
)


def _write_cfg(d, **kw):
    p = os.path.join(d, 'config.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(kw, f, ensure_ascii=False)
    return p


def _fresh(cfg=None):
    """建一个临时目录并返回 (registry, models_path, dir)"""
    d = tempfile.mkdtemp(prefix='petreg_')
    cfg_path = _write_cfg(d, **cfg) if cfg else None
    mp = os.path.join(d, 'models.json')
    return ModelRegistry(mp, cfg_path), mp, d


# ---------- 1. 首次生成 ----------
def test_first_run_generates_file():
    reg, mp, _ = _fresh()
    assert os.path.exists(mp), 'models.json 应被自动生成'
    assert len(reg) == 2
    assert set(reg.keys()) == {'flash', 'pro'}
    assert reg.loaded_from == 'builtin'


def test_builtin_model_ids_are_current():
    """出厂档案必须用官方当前规范 ID，不能再用被重命名的旧 ID"""
    reg, _, _ = _fresh()
    assert reg.get('flash').model_id == 'deepseek-flash'
    assert reg.get('pro').model_id == 'deepseek-v4-pro'
    assert 'deepseek-v4-flash' in reg.get('flash').aliases


# ---------- 2. 旧配置迁移 ----------
def test_migrate_upgrades_renamed_id():
    """config 里是被重命名的旧 ID → 迁移时升级为规范 ID"""
    reg, _, _ = _fresh({'model_flash': 'deepseek-v4-flash', 'model_pro': 'deepseek-v4-pro'})
    assert reg.get('flash').model_id == 'deepseek-flash', '旧 ID 应被升级'
    assert reg.get('pro').model_id == 'deepseek-v4-pro'


def test_migrate_keeps_custom_id():
    """config 里是自定义 ID → 原样保留，不擅自改写"""
    reg, _, _ = _fresh({'model_flash': 'my-own-model-2026', 'model_pro': 'another-one'})
    assert reg.get('flash').model_id == 'my-own-model-2026'
    assert reg.get('pro').model_id == 'another-one'


def test_migrate_params():
    reg, _, _ = _fresh({'reasoning': False, 'temperature': 0.3, 'max_tokens': 4096})
    p = reg.get('flash')
    assert p.reasoning is False
    assert abs(p.temperature - 0.3) < 1e-9
    assert p.max_tokens == 4096


# ---------- 3. 上限夹取 ----------
def test_clamp_tokens():
    assert clamp_tokens(999999) == MAX_OUTPUT_TOKENS
    assert clamp_tokens(10) == MIN_OUTPUT_TOKENS
    assert clamp_tokens(128000) == 128000, '128000 必须原样保留（原先被夹到 64000 就是 bug）'
    assert clamp_tokens('abc') == clamp_tokens(None) == 128000, '非法值应回落到默认'


def test_clamp_reaches_profile():
    reg, _, _ = _fresh({'max_tokens': 999999})
    assert reg.get('flash').max_tokens == MAX_OUTPUT_TOKENS


# ---------- 4. 已有文件优先 ----------
def test_existing_file_wins_over_config():
    reg, mp, _ = _fresh({'model_flash': 'deepseek-v4-flash'})
    reg.set_field('flash', 'display_name', '小蓝')
    reg.set_field('flash', 'model_id', 'hand-edited-id')
    assert reg.save()
    reg2 = ModelRegistry(mp, os.path.join(os.path.dirname(mp), 'config.json'))
    assert reg2.loaded_from == 'file'
    assert reg2.get('flash').display_name == '小蓝', '文件里的改动不能被 config 覆盖'
    assert reg2.get('flash').model_id == 'hand-edited-id'


# ---------- 5. 损坏回退 ----------
def test_corrupt_file_recovers():
    reg, mp, _ = _fresh()
    with open(mp, 'w', encoding='utf-8') as f:
        f.write('{ this is not json')
    reg2 = ModelRegistry(mp)
    assert reg2.loaded_from == 'recovered'
    assert len(reg2) == 2, '损坏时应回退出厂默认而不是崩'
    # 应已被重写为合法 JSON
    with open(mp, encoding='utf-8') as f:
        json.load(f)


def test_empty_profiles_recovers():
    reg, mp, _ = _fresh()
    with open(mp, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'profiles': []}, f)
    reg2 = ModelRegistry(mp)
    assert len(reg2) == 2


# ---------- 6. 价格查询 ----------
def test_price_lookup():
    reg, _, _ = _fresh()
    assert reg.price_for('deepseek-flash')['output'] == 4.5
    assert reg.price_for('deepseek-v4-flash')['output'] == 4.5, '别名应命中'
    assert reg.price_for('flash')['output'] == 4.5, '档案键应命中'
    assert reg.price_for('deepseek-v4-pro')['output'] == 13.5
    assert reg.price_for('totally-unknown') is None, '未知模型必须返回 None，不静默兜底'
    assert reg.price_for('') is None


def test_canonical_model_id():
    reg, _, _ = _fresh()
    assert reg.canonical_model_id('deepseek-v4-flash') == 'deepseek-flash'
    assert reg.canonical_model_id('flash') == 'deepseek-flash'
    assert reg.canonical_model_id('deepseek-v4-pro') == 'deepseek-v4-pro'
    assert reg.canonical_model_id('unknown-x') == 'unknown-x'


# ---------- 7. 兼容层 ----------
def test_characters_shape_matches_old():
    """characters() 必须能顶替原 CHARACTERS（老代码到处在用）"""
    reg, _, _ = _fresh()
    ch = reg.characters()
    assert set(ch.keys()) == {'flash', 'pro'}
    for k, required in (('flash', ('name', 'sub', 'color', 'greetings', 'happy_lines',
                                   'think_lines', 'greetings_en', 'happy_lines_en', 'think_lines_en')),
                        ('pro', ('name', 'sub', 'color', 'greetings', 'scared_lines', 'scared_lines_en'))):
        for field in required:
            assert field in ch[k], f'{k} 缺字段 {field}'
        assert isinstance(ch[k]['greetings'], list) and ch[k]['greetings']
        assert ch[k]['color'].startswith('#'), '颜色应为 hex 字符串（由 UI 层转 QColor）'
    assert ch['flash']['name'] == 'V4 Flash'
    assert ch['pro']['name'] == 'V4 Pro'


def test_display_name_is_editable():
    """改显示名 → 兼容层跟着变（这就是本改造的核心目的）"""
    reg, _, _ = _fresh()
    reg.set_field('flash', 'display_name', '小蓝')
    assert reg.characters()['flash']['name'] == '小蓝'


# ---------- 8. 增删档案 ----------
def test_add_and_remove_profile():
    reg, _, _ = _fresh()
    assert reg.add_profile('turbo', display_name='V4 Turbo', model_id='deepseek-turbo')
    assert len(reg) == 3
    assert reg.characters()['turbo']['name'] == 'V4 Turbo'
    assert reg.get('turbo').model_id == 'deepseek-turbo'
    assert not reg.add_profile('flash'), '重复键应被拒'
    assert reg.remove_profile('turbo')
    assert len(reg) == 2
    assert reg.remove_profile('flash')
    assert not reg.remove_profile('pro'), '不能删到一份不剩'


# ---------- 9. 落盘往返 ----------
def test_roundtrip_and_no_secrets():
    reg, mp, _ = _fresh()
    reg.set_field('pro', 'display_name', '深思鲸')
    reg.set_param('pro', 'temperature', 0.7)
    reg.set_price('pro', {'input': 5.0, 'cache': 0.2, 'output': 15.0})
    assert reg.save()
    reg2 = ModelRegistry(mp)
    p = reg2.get('pro')
    assert p.display_name == '深思鲸' and abs(p.temperature - 0.7) < 1e-9
    assert p.price['output'] == 15.0
    raw = open(mp, encoding='utf-8').read()
    assert 'sk-' not in raw, 'models.json 绝不能出现 API Key'
    assert 'deepseek_api_key' in raw, '只应存 key 的引用字段名'


def test_price_unknown_flag():
    reg, _, _ = _fresh()
    assert reg.set_price('flash', {}) is False
    assert reg.get('flash').price_known is False
    assert reg.price_for('deepseek-flash') is None


# ---------- 10. 出厂档案自检 ----------
def test_builtin_profiles_sane():
    for p in BUILTIN_PROFILES:
        assert p['key'] and p['display_name'] and p['model_id']
        assert p['endpoint'].startswith('https://')
        assert 0 <= p['params']['temperature'] <= 2
        assert p['price']['input'] > 0 and p['price']['output'] > 0


if __name__ == '__main__':
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith('test_') and callable(f)]
    ok = fail = 0
    for name, fn in fns:
        try:
            fn()
            print(f'  \u2705 {name}')
            ok += 1
        except Exception as e:
            print(f'  \u274c {name}: {e}')
            fail += 1
    print(f'\n模型档案注册表单测：PASS {ok} / FAIL {fail} / 共 {ok + fail}')
    sys.exit(1 if fail else 0)
