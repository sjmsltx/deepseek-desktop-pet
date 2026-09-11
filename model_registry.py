# -*- coding: utf-8 -*-
"""
model_registry.py — 模型档案注册表（模型身份配置化）
=====================================================
把原先散落在 10 处代码常量里的「模型身份」——显示名 / 模型 ID / 接口地址 /
参数 / 价格 / 外观 / 人设——收敛成一份用户可编辑的 ``models.json``，运行期
由本模块统一读取。

- ``ModelProfile``：一个模型的全部身份
- ``ModelRegistry``：加载 / 兜底 / 落盘 / 旧 config.json 迁移 / 价格查询

设计约束
--------
1. **不依赖 PySide6**——纯数据层，可独立单测；颜色以 hex 字符串存储，由 UI 层转 QColor。
2. **绝不让桌宠起不来**——models.json 缺失或损坏时回退内置默认档案。
3. **首次启动迁移**——旧 config.json 的 model_flash/model_pro/reasoning/
   temperature/max_tokens 迁进档案；之后以 models.json 为准。
4. **单一上限**——输出上限统一为 ``MAX_OUTPUT_TOKENS``，替代原先
   64000（读取夹）/128000（菜单）/128000（工具）三处互相冲突的硬编码。
"""
import copy
import json
import os

DEFAULT_ENDPOINT = 'https://api.deepseek.com/chat/completions'

# 输出上限（对齐 DeepSeek v4 输出上限）。原先 722 行夹 64000、菜单写 128000、
# AI 工具写 128000，三者互不一致导致「选 128000 → 存进去 → 重载被压回 64000」。
MAX_OUTPUT_TOKENS = 384000
MIN_OUTPUT_TOKENS = 256
DEFAULT_MAX_TOKENS = 128000

# 官方已重命名的旧 ID → 当前规范 ID。迁移时自动升级，避免沿用过时别名。
# （实测：deepseek-v4-flash 请求仍通，但响应 model 归一化为 deepseek-flash）
RENAMED_MODEL_IDS = {
    'deepseek-v4-flash': 'deepseek-flash',
}

# 出厂默认档案：由原 desktop_pet.CHARACTERS 搬入，模型 ID 更新为官方当前规范 ID。
BUILTIN_PROFILES = [
    {
        'key': 'flash',
        'display_name': 'V4 Flash',
        'model_id': 'deepseek-flash',
        'aliases': ['deepseek-v4-flash'],
        'endpoint': DEFAULT_ENDPOINT,
        'api_key_field': 'deepseek_api_key',
        'params': {'temperature': 1.0, 'max_tokens': DEFAULT_MAX_TOKENS, 'reasoning': True},
        'price': {'input': 1.5, 'cache': 0.05, 'output': 4.5},
        'appearance': {'color': '#B0C4DE', 'portrait': '', 'sub': '浅蓝和服 · 快言快语'},
        'persona': {
            'greetings': [
                '我在呢！有什么要帮忙的？', 'Flash 模式，快问快答～', '今天也是效率满满的一天！',
                '要不要试试 V4 Pro 大哥？它想事情更细。', '别急，我打字很快的！',
                '你盯着我看好久了，我害羞了啦！', '今天天气不错，适合写代码！', '诶？你发现我在摸鱼了？',
            ],
            'happy_lines': ['耶！你戳我！(*≧▽≦)', '嘻嘻，痒痒的～', '今天心情超好！'],
            'think_lines': ['嗯…这个问题让我想想。', '正在高速运转中…', '我的小脑瓜快冒烟啦！'],
            'greetings_en': [
                'Here! Need any help?', 'Flash mode, quick Q&A～', 'Another productive day!',
                'Want to try V4 Pro? It thinks deeper.', 'No worries, I type fast!',
                'You have been staring at me… I am blushing!', 'Nice weather today, good for coding!',
            ],
            'happy_lines_en': ['Yay! You poked me! (*≧▽≦)', 'Hee hee, that tickles～', 'Feeling great today!'],
            'think_lines_en': ['Hmm… let me think about this.', 'Processing at full speed…',
                               'My little brain is smoking!'],
        },
    },
    {
        'key': 'pro',
        'display_name': 'V4 Pro',
        'model_id': 'deepseek-v4-pro',
        'aliases': [],
        'endpoint': DEFAULT_ENDPOINT,
        'api_key_field': 'deepseek_api_key',
        'params': {'temperature': 1.0, 'max_tokens': DEFAULT_MAX_TOKENS, 'reasoning': True},
        'price': {'input': 4.5, 'cache': 0.15, 'output': 13.5},
        'appearance': {'color': '#2E4A8E', 'portrait': '', 'sub': '深蓝女仆 · 深思熟虑'},
        'persona': {
            'greetings': [
                '我在。有什么需要仔细思考的吗？', '已经帮你推演了三套方案。', 'V4 Pro 模式，专注深度分析。',
                '别急，我把每一条都查证过再回答。', '这个需求需要拆解一下，我先列个提纲。',
                '嗯…这个问题值得深入想一想。', '数据都核对过了，可以放心用。', '要不要我帮你做个误差分析？',
            ],
            'happy_lines': ['能被你信任是我的荣幸。', '分析完成，一切尽在掌握。'],
            'think_lines': ['让我先梳理一下逻辑链。', '推演中…排除所有可能干扰项。', '这个问题有三层因果关系。'],
            'scared_lines': ['啊！别戳了别戳了！', '饶命！我这就认真思考！', '冷静！我先梳理一下逻辑！'],
            'greetings_en': [
                'I am here. Anything that needs deep thought?',
                'Already worked out three approaches for you.',
                'V4 Pro mode, focused deep analysis.',
                'No rush — I verify every detail before answering.',
                'This needs breaking down; let me outline it first.',
                'Hmm… this deserves deeper thought.',
                'All data cross-checked, safe to use.', 'Want me to run an error analysis?',
            ],
            'happy_lines_en': ['Being trusted by you is my honor.', 'Analysis complete, all under control.'],
            'think_lines_en': ['Let me sort out the logic chain first.',
                               'Reasoning… eliminating all possible interferences.',
                               'This problem has three layers of causality.'],
            'scared_lines_en': ['Ah! Stop poking me!', 'Mercy! I will think seriously!',
                                'Calm down! Let me sort out the logic first!'],
        },
    },
]

SCHEMA_VERSION = 1


def clamp_tokens(v, default=DEFAULT_MAX_TOKENS):
    """统一的输出上限夹取（全项目唯一一处）"""
    try:
        return max(MIN_OUTPUT_TOKENS, min(int(v), MAX_OUTPUT_TOKENS))
    except (TypeError, ValueError):
        return default


class ModelProfile:
    """一个模型的全部身份（对应 models.json 里的一条档案）"""

    def __init__(self, d):
        d = d or {}
        self.key = str(d.get('key') or 'model')
        self.display_name = str(d.get('display_name') or self.key)
        self.model_id = str(d.get('model_id') or '')
        self.aliases = [str(a) for a in (d.get('aliases') or []) if a]
        self.endpoint = str(d.get('endpoint') or DEFAULT_ENDPOINT)
        self.api_key_field = str(d.get('api_key_field') or 'deepseek_api_key')
        prm = d.get('params') or {}
        self.temperature = float(prm.get('temperature', 1.0))
        self.max_tokens = clamp_tokens(prm.get('max_tokens', DEFAULT_MAX_TOKENS))
        self.reasoning = bool(prm.get('reasoning', True))
        price = d.get('price') or {}
        self.price = ({k: float(v) for k, v in price.items() if k in ('input', 'cache', 'output')}
                      if isinstance(price, dict) else {})
        app = d.get('appearance') or {}
        self.color = str(app.get('color') or '#B0C4DE')
        self.portrait = str(app.get('portrait') or '')
        self.sub = str(app.get('sub') or '')
        self.persona = dict(d.get('persona') or {})

    @property
    def price_known(self):
        """价格是否明确（未知时不再静默套用兜底价）"""
        return 'input' in self.price and 'output' in self.price

    def to_dict(self):
        return {
            'key': self.key,
            'display_name': self.display_name,
            'model_id': self.model_id,
            'aliases': list(self.aliases),
            'endpoint': self.endpoint,
            'api_key_field': self.api_key_field,
            'params': {'temperature': self.temperature, 'max_tokens': self.max_tokens,
                       'reasoning': self.reasoning},
            'price': dict(self.price),
            'appearance': {'color': self.color, 'portrait': self.portrait, 'sub': self.sub},
            'persona': dict(self.persona),
        }

    def __repr__(self):
        return f'<ModelProfile {self.key} {self.model_id} "{self.display_name}">'


class ModelRegistry:
    """模型档案注册表：models.json 是唯一来源"""

    def __init__(self, path, config_path=None):
        self.path = path
        self.config_path = config_path          # 旧配置迁移来源
        self._profiles = []
        self.loaded_from = 'builtin'            # builtin / file / recovered
        self.last_error = ''
        self.load()

    # ---------- 加载 / 兜底 ----------
    def load(self):
        raw = None
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8-sig') as f:
                    raw = json.load(f)
            except Exception as e:
                self.last_error = str(e)
                raw = None
        if not isinstance(raw, dict) or not isinstance(raw.get('profiles'), list) or not raw['profiles']:
            # 文件缺失 / 损坏 / 空档案 → 从旧 config 迁移或回退出厂默认
            self._profiles = [ModelProfile(p) for p in self._build_default()]
            self.loaded_from = 'builtin' if not os.path.exists(self.path) else 'recovered'
            self.save()
        else:
            self._profiles = [ModelProfile(p) for p in raw['profiles'] if isinstance(p, dict)]
            if not self._profiles:                       # 全是非法条目
                self._profiles = self._build_default()
                self.loaded_from = 'recovered'
                self.save()
            else:
                self.loaded_from = 'file'
        return self

    def _build_default(self):
        """出厂默认档案 + 旧 config.json 迁移覆盖"""
        profiles = copy.deepcopy(BUILTIN_PROFILES)
        cfg = self._read_config()
        if not isinstance(cfg, dict):
            return profiles
        by_key = {p['key']: p for p in profiles}
        # 1) 模型 ID：迁移时把官方已重命名的旧 ID 升级为规范 ID
        for key, cfg_field in (('flash', 'model_flash'), ('pro', 'model_pro')):
            v = str(cfg.get(cfg_field) or '').strip()
            if v and key in by_key:
                by_key[key]['model_id'] = RENAMED_MODEL_IDS.get(v, v)
        # 2) 参数：reasoning / temperature / max_tokens 三个旧键
        for p in profiles:
            if 'reasoning' in cfg:
                p['params']['reasoning'] = bool(cfg['reasoning'])
            if 'temperature' in cfg:
                try:
                    p['params']['temperature'] = float(cfg['temperature'])
                except (TypeError, ValueError):
                    pass
            if 'max_tokens' in cfg:
                p['params']['max_tokens'] = clamp_tokens(cfg['max_tokens'])
        return profiles

    def _read_config(self):
        try:
            if self.config_path and os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8-sig') as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    # ---------- 落盘 ----------
    def save(self):
        """原子写 models.json（不存 API Key，只存引用字段名）"""
        try:
            tmp = self.path + '.tmp'
            data = {'version': SCHEMA_VERSION,
                    'profiles': [p.to_dict() for p in self._profiles]}
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    # ---------- 查询 ----------
    def profiles(self):
        return list(self._profiles)

    def keys(self):
        return [p.key for p in self._profiles]

    def get(self, key):
        for p in self._profiles:
            if p.key == key:
                return p
        return None

    def first_key(self):
        return self._profiles[0].key if self._profiles else 'flash'

    def __len__(self):
        return len(self._profiles)

    def price_for(self, model_id):
        """按模型 ID 查价格：规范 ID → 别名 → 档案键。查不到返回 None（不静默兜底）"""
        mid = str(model_id or '').strip()
        if not mid:
            return None
        for p in self._profiles:
            if p.model_id == mid and p.price_known:
                return dict(p.price)
        for p in self._profiles:
            if mid in p.aliases and p.price_known:
                return dict(p.price)
        for p in self._profiles:
            if p.key == mid and p.price_known:
                return dict(p.price)
        return None

    def canonical_model_id(self, model_id):
        """把任意 ID（含别名/档案键）归一化成档案的规范模型 ID"""
        mid = str(model_id or '').strip()
        if not mid:
            return ''
        for p in self._profiles:
            if mid == p.model_id or mid in p.aliases or mid == p.key:
                return p.model_id
        return mid

    def characters(self):
        """兼容层：输出与原 desktop_pet.CHARACTERS 同形的字典（color 为 hex 字符串）"""
        out = {}
        for p in self._profiles:
            c = dict(p.persona)
            c['name'] = p.display_name
            c['sub'] = p.sub
            c['color'] = p.color
            if p.portrait:
                c['portrait'] = p.portrait
            out[p.key] = c
        return out

    # ---------- 修改（供设置界面 / AI 工具调用） ----------
    FIELD_MAP = {
        'display_name': 'display_name', 'model_id': 'model_id', 'endpoint': 'endpoint',
        'api_key_field': 'api_key_field', 'color': 'color', 'sub': 'sub',
        'portrait': 'portrait',
    }
    PARAM_FIELDS = ('temperature', 'max_tokens', 'reasoning')

    def set_field(self, key, field, value):
        """改档案的顶层字段（显示名 / 模型 ID / endpoint 等），改完需 save()"""
        p = self.get(key)
        if p is None:
            return False
        if field == 'color':
            p.color = str(value)
        elif field in self.FIELD_MAP:
            setattr(p, self.FIELD_MAP[field], str(value))
        elif field in self.PARAM_FIELDS:
            return self.set_param(key, field, value)
        elif field == 'aliases':
            p.aliases = [str(a) for a in (value or []) if a]
        else:
            return False
        return True

    def set_param(self, key, name, value):
        """改档案的参数（温度 / 输出上限 / 思考开关）"""
        p = self.get(key)
        if p is None or name not in self.PARAM_FIELDS:
            return False
        try:
            if name == 'temperature':
                p.temperature = max(0.0, min(float(value), 2.0))
            elif name == 'max_tokens':
                p.max_tokens = clamp_tokens(value)
            else:
                p.reasoning = bool(value)
        except (TypeError, ValueError):
            return False
        return True

    def set_price(self, key, price):
        """改档案价格表（{"input":x,"cache":y,"output":z}，每百万 token 单价）"""
        p = self.get(key)
        if p is None or not isinstance(price, dict):
            return False
        p.price = {k: float(v) for k, v in price.items() if k in ('input', 'cache', 'output')}
        return p.price_known

    def add_profile(self, key, display_name='', model_id='', copy_from=None):
        """新增一份档案（copy_from 可指定从哪个档案复制外观与人设）"""
        key = str(key or '').strip()
        if not key or self.get(key):
            return False
        base = self.get(copy_from) if copy_from else (self._profiles[0] if self._profiles else None)
        d = base.to_dict() if base else copy.deepcopy(BUILTIN_PROFILES[0])
        d['key'] = key
        d['display_name'] = display_name or key
        d['model_id'] = model_id or ''
        d['aliases'] = []
        self._profiles.append(ModelProfile(d))
        return True

    def remove_profile(self, key):
        """删除一份档案（至少保留一份，避免桌宠无边可用）"""
        if len(self._profiles) <= 1:
            return False
        p = self.get(key)
        if p is None:
            return False
        self._profiles.remove(p)
        return True
