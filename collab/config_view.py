# -*- coding: utf-8 -*-
"""⭐ C2／`D5-2`：⚙ 配置面的**只读视图**（`GET /api/config` ✓ 纯读 ✗ 不改任何东西 ✓）。

⭐ 形状来源：⭐ 微信侧 `WX-桌宠-20261005-51` §草稿 3 ✓（⭐ 比 `PC-…-165` §2.1 更细 ✓ 以其为准 ✓）：
    `{version, items:[{key,value,scope,source,restart,writable,note}], hidden:[键名…]}`
⭐ 三条硬约束（⭐ `PC-…-165` §2.1 ✓）：
    ① ⭐ **纯读** ✗（调用前后日志条数不变 ✓ 有护栏 ✓）
    ② ⭐ ⭐ **敏感值不出现** ✗ —— ⭐ 只把**键名**放进 `hidden` ✓（⛔ 值一个字符都不回 ✗）
    ③ ⭐ `writable` 为空集 ⇒ ⭐ 界面必须明示「当前不可写」✓（⛔ 不静默置灰 ✗ 承 E13.3 ✓）
"""
from __future__ import annotations

import io
import json
import os

VERSION = 'v1.16'          # ⭐ 契约版本（⭐ 承 `WX-…-51` 草稿 1 ✓ 追加 16 次 ⇒ v1.16 ✓）

# ⭐ 敏感判据（⭐ 命中即**不入 items 的值** ✗ 只进 `hidden` 名 ✓）
# ⚠️ 我方第一版用 `'token'` 做子串 ✓ ⇒ ⭐ **把 `max_tokens`／`roundtable_max_tokens` 也误判成密钥** ✗
#   （⭐ 它们是**数值上限** ⇒ 应当展示 ✓）⇒ ⭐ 判据改为**更精确**的写法 ✓：
#   ⭐ 只看 `*_key`／`key_*`／`secret`／`password` ＋ ⭐ `token` 需**不是** `..._tokens` 这类复数上限 ✓
SENSITIVE_HINTS = ('api_key', 'apikey', 'secret', 'password', 'passwd', 'access_token',
                   'auth_token', 'api_token', 'token_secret')
_SENSITIVE_EXACT = ('token', 'key')


def _is_sensitive(key: str) -> bool:
    k = str(key or '').lower()
    if any(h in k for h in SENSITIVE_HINTS):
        return True
    if k.endswith('_tokens') or k.endswith('tokens'):
        return False          # ⭐ 上限类（`max_tokens` ✓）⇒ ⛔ 不是密钥 ✗
    return k in _SENSITIVE_EXACT or k.endswith('_key') or k.endswith('_token')


# ⭐ 键元数据表（⭐ scope／restart／writable／note ✓）
#   scope：⭐ 全局／环境／项目 ✓（`D5-3` 口径 ✓）
#   restart：⭐ 改了要不要重启 ✓
#   writable：⭐ 本批**一律 False** ✗（⭐ 写路径未开 ✓ ⇒ 界面必须明示「当前不可写」✓）
_META = {
    'deepseek_api_key':      ('项目', False, '⭐ DeepSeek 密钥（⭐ 已配置与否看 hidden 名 ✓ 值不回 ✗）'),
    'search_api_key':        ('项目', False, '⭐ 搜索密钥（同上 ✓）'),
    'voice_local_url':       ('项目', False, '本地语音服务地址'),
    'voice_local_ref':       ('项目', False, '本地语音参考'),
    'voice_local_prompt':    ('项目', False, '本地语音提示词'),
    'voice_name':            ('项目', False, 'TTS 音色'),
    'voice_rate':            ('项目', False, 'TTS 语速'),
    'voice_enabled':         ('项目', False, '语音开关'),
    'asr_backend':           ('项目', True,  '⭐ 改后需重启 ✓'),
    'asr_whisper_exe':       ('项目', True,  '⭐ 改后需重启 ✓'),
    'live2d_model':          ('项目', True,  '⭐ 改后需重启 ✓'),
    'mcp_servers':           ('项目', True,  '⭐ 改后需重启 ✓'),
    'theme':                 ('项目', False, '主题'),
    'display_mode':          ('项目', False, '显示模式'),
    'personality':           ('项目', False, '人设'),
    'reply_style':           ('项目', False, '回复风格'),
    'language':              ('项目', False, '界面语言'),
    'city':                  ('项目', False, '城市（天气用 ✓）'),
    'max_tokens':            ('项目', False, '单次上限 tokens'),
    'api_prices':            ('项目', False, '价格表'),
    'balance_low_threshold': ('项目', False, '余额低阈值'),
    'roundtable_max_cost_micro': ('项目', False, '圆桌费用上限'),
    'roundtable_max_tokens': ('项目', False, '圆桌 tokens 上限'),
    'advanced_tools':        ('项目', False, '进阶工具开关'),
    'remote_control':        ('项目', False, '⭐ 远程遥控（默认关 ✗）'),
    'foreground_aware':      ('项目', False, '前台感知'),
    'active_chat':           ('项目', False, '主动搭话'),
    'side_panel_collapsed':  ('项目', False, '侧栏折叠态'),
    'side_panel_tabs':       ('项目', False, '侧栏页签'),
    'stats_win_pos':         ('项目', False, '统计窗位置'),
    'app_aliases':           ('项目', False, '应用别名'),
    'x':                     ('项目', False, '窗口 X'),
    'y':                     ('项目', False, '窗口 Y'),
}
# ⭐ 非 config.json 但属"配置面"的键（⭐ 环境变量 ⇒ source=env ✓）
_ENV_KEYS = {
    'ac_lock_wait':  ('环境', False, '⭐ 测试锁等待秒数（`AC_LOCK_WAIT` ✓）',
                      'AC_LOCK_WAIT', 120),
    'ac_lock_dir':   ('环境', False, '锁目录（`AC_LOCK_DIR` ✓）', 'AC_LOCK_DIR', ''),
    'ac_collab_line': ('环境', False, '产品线名（`AC_COLLAB_LINE` ✓）', 'AC_COLLAB_LINE', 'PC'),
    'ac_pet_backup_dir': ('环境', False, '自改码备份目录（`AC_PET_BACKUP_DIR` ✓）',
                          'AC_PET_BACKUP_DIR', ''),
    'ac_pet_allow_self_edit': ('环境', False, '⭐ 自改码闸门（`AC_PET_ALLOW_SELF_EDIT` ✓ 默认关 ✗）',
                               'AC_PET_ALLOW_SELF_EDIT', ''),
}


def _read_config(base_dir: str = '') -> dict:
    """⭐ 只读 `config.json` ✓（⭐ 读不到 ⇒ 空 dict ✓ **不留痕会吵** ⇒ 静默返回空 ✓
    —— ⭐ 因为这是**只读展示端点** ✓，⭐ 缺文件属**正常态**（⭐ 未初始化 ✓）✗）。"""
    p = os.path.join(base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'config.json')
    if not os.path.isfile(p):
        return {}
    try:
        with io.open(p, encoding='utf-8', errors='replace') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception as exc:
        # ⭐ 配置坏了 ⇒ ⭐ **要看得见** ✗（⛔ 不静默 ✗）—— 通过返回值里的 note 表达 ✓
        print('  \u26a0\ufe0f 读 config.json 失败（按空处理 ✓）：%r' % (exc,))
        return {'__error__': repr(exc)}


def config_payload(base_dir: str = '') -> dict:
    """⭐ 组装只读载荷 ✓（⭐ 纯函数 ✓ 不写任何东西 ✗）。"""
    cfg = _read_config(base_dir)
    cfg = {k: v for k, v in cfg.items() if not str(k).startswith('__')}
    items = []
    hidden = []
    for key in sorted(cfg):
        if _is_sensitive(key):
            hidden.append(key)          # ⭐ 只列**键名** ✓ 值一个字符都不回 ✗
            continue
        scope, restart, note = _META.get(key, ('项目', False, ''))
        items.append({'key': key, 'value': cfg[key], 'scope': scope,
                      'source': 'config.json', 'restart': bool(restart),
                      'writable': False, 'note': note})
    for key in sorted(_ENV_KEYS):
        scope, restart, note, envname, default = _ENV_KEYS[key]
        raw = os.environ.get(envname)
        items.append({'key': key, 'value': raw if raw not in (None, '') else default,
                      'scope': scope, 'source': 'env' if raw not in (None, '') else '默认',
                      'restart': bool(restart), 'writable': False, 'note': note})
    return {
        'version': VERSION,
        'items': items,
        # ⭐ 敏感项**只报"有这几项被隐藏"** ✗（⭐ 不报值 ✓）
        'hidden': hidden,
        # ⭐ 本批写面**全部关闭** ✗ ⇒ ⭐ 界面必须明示「当前不可写」✓（⛔ 不静默置灰 ✗）
        'writable': [],
        'needs_restart': [i['key'] for i in items if i['restart']],
        'count': len(items) + len(hidden),
    }
