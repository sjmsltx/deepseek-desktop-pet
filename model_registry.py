# -*- coding: utf-8 -*-
"""
model_registry.py - 模型档案注册表(模型身份配置化)
=====================================================
把原先散落在 10 处代码常量里的「模型身份」--显示名 / 模型 ID / 接口地址 /
参数 / 价格 / 外观 / 人设--收敛成一份用户可编辑的 ``models.json``,运行期
由本模块统一读取。

- ``ModelProfile``:一个模型的全部身份
- ``ModelRegistry``:加载 / 兜底 / 落盘 / 旧 config.json 迁移 / 价格查询

设计约束
--------
1. **不依赖 PySide6**--纯数据层,可独立单测;颜色以 hex 字符串存储,由 UI 层转 QColor。
2. **绝不让桌宠起不来**--models.json 缺失或损坏时回退内置默认档案。
3. **首次启动迁移**--旧 config.json 的 model_flash/model_pro/reasoning/
   temperature/max_tokens 迁进档案;之后以 models.json 为准。
4. **单一上限**--输出上限统一为 ``MAX_OUTPUT_TOKENS``,替代原先
   64000(读取夹)/128000(菜单)/128000(工具)三处互相冲突的硬编码。
"""
import copy
import json
import os
import re

from pet_theme import DEFAULT_THEME as _THEME  # v6.58 主题唯一源(角色默认色;本模块不依赖 PySide6)

DEFAULT_ENDPOINT = 'https://api.deepseek.com/chat/completions'

# 输出上限(对齐 DeepSeek v4 输出上限)。原先 722 行夹 64000、菜单写 128000、
# AI 工具写 128000,三者互不一致导致「选 128000 → 存进去 → 重载被压回 64000」。
MAX_OUTPUT_TOKENS = 384000
MIN_OUTPUT_TOKENS = 256
DEFAULT_MAX_TOKENS = 128000

# v6.62 思考强度(官方 reasoning_effort):none = 不思考,low / high / max 为思考深度。
# 旧别名(minimal→low、medium/xhigh→high)一并归一,避免用户手写 models.json 时写飞。
EFFORT_LEVELS = ('none', 'low', 'high', 'max')
EFFORT_ALIASES = {'minimal': 'low', 'medium': 'high', 'xhigh': 'high', 'highest': 'high',
                  'default': 'high', 'off': 'none', 'false': 'none', 'true': 'high'}
DEFAULT_EFFORT = 'high'   # 官方默认

# 支持图片输入的官方模型(档案未显式声明 vision 时按此兜底判断;
# 已实测:把带文字的图直接送 deepseek-flash,回答读对了内容)
VISION_MODEL_IDS = ('deepseek-flash',)

# 价格键（元/百万 token）：input/cache/output 为**空闲时段价**，*_peak 为高峰价
# （官方：高峰时段价格为空闲的两倍；核对来源见 api_stats.PRICES 注释）
PRICE_KEYS = ('input', 'cache', 'output', 'input_peak', 'cache_peak', 'output_peak')

# v6.62：计价方式（跟档案走，不写死）
# - auto：根据接口地址自动判定 —— 官方域名 → 按官方峰谷；其他（中转/第三方）→ 固定价
# - deepseek_peak：强制按官方峰谷规则（周一至周五 9-12/14-18，不含法定节假日）
# - flat：固定价，不区分峰谷
PRICING_MODES = ('auto', 'deepseek_peak', 'flat')
OFFICIAL_HOSTS = ('api.deepseek.com', 'deepseek.com')


def is_official_endpoint(endpoint):
    """接口地址是不是官方 DeepSeek（中转/第三方自建域名一律不是）"""
    try:
        host = str(endpoint or '').strip().lower().split('//')[-1].split('/')[0]
        host = host.split('@')[-1].split(':')[0]
        return any(host == h or host.endswith('.' + h) for h in OFFICIAL_HOSTS)
    except Exception:
        return False

# 官方已重命名的旧 ID → 当前规范 ID。迁移时自动升级,避免沿用过时别名。
# (实测:deepseek-v4-flash 请求仍通,但响应 model 归一化为 deepseek-flash)
RENAMED_MODEL_IDS = {
    'deepseek-v4-flash': 'deepseek-flash',
}

# 出厂默认档案:由原 desktop_pet.CHARACTERS 搬入,模型 ID 更新为官方当前规范 ID。
BUILTIN_PROFILES = [
    {
        'key': 'flash',
        'display_name': 'V4 Flash',
        'model_id': 'deepseek-flash',
        'aliases': ['deepseek-v4-flash'],
        'endpoint': DEFAULT_ENDPOINT,
        'api_key_field': 'deepseek_api_key',
        'params': {'temperature': 1.0, 'max_tokens': DEFAULT_MAX_TOKENS, 'reasoning': True,
                   'effort': 'high', 'pricing_mode': 'auto'},
        'vision': True,      # v6.62：flash 原生多模态，图片可直接送模型
        'price': {'input': 1.0, 'cache': 0.02, 'output': 4.0,
                  'input_peak': 2.0, 'cache_peak': 0.04, 'output_peak': 8.0},   # 官方价(空闲/高峰,元/百万 token)
        'appearance': {'color': '#B0C4DE', 'portrait': '', 'sub': '浅蓝和服 · 快言快语'},  # theme-exempt(角色档案数据,非 UI 主题)
        'persona': {
            'greetings': [
                '我在呢!有什么要帮忙的?', 'Flash 模式,快问快答~', '今天也是效率满满的一天!',
                '要不要试试 V4 Pro 大哥?它想事情更细。', '别急,我打字很快的!',
                '你盯着我看好久了,我害羞了啦!', '今天天气不错,适合写代码!', '诶?你发现我在摸鱼了?',
            ],
            'happy_lines': ['耶!你戳我!(*≧▽≦)', '嘻嘻,痒痒的~', '今天心情超好!'],
            'think_lines': ['嗯...这个问题让我想想。', '正在高速运转中...', '我的小脑瓜快冒烟啦!'],
            'greetings_en': [
                'Here! Need any help?', 'Flash mode, quick Q&A~', 'Another productive day!',
                'Want to try V4 Pro? It thinks deeper.', 'No worries, I type fast!',
                'You have been staring at me... I am blushing!', 'Nice weather today, good for coding!',
            ],
            'happy_lines_en': ['Yay! You poked me! (*≧▽≦)', 'Hee hee, that tickles~', 'Feeling great today!'],
            'think_lines_en': ['Hmm... let me think about this.', 'Processing at full speed...',
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
        'params': {'temperature': 1.0, 'max_tokens': DEFAULT_MAX_TOKENS, 'reasoning': True,
                   'effort': 'high', 'pricing_mode': 'auto'},
        'vision': False,     # v6.62：pro 不支持图片输入（官方能力表）
        'price': {'input': 4.5, 'cache': 0.15, 'output': 13.5,
                  'input_peak': 9.0, 'cache_peak': 0.30, 'output_peak': 27.0},   # 官方价(空闲/高峰,元/百万 token)
        'appearance': {'color': '#2E4A8E', 'portrait': '', 'sub': '深蓝女仆 · 深思熟虑'},  # theme-exempt(角色档案数据,非 UI 主题)
        'persona': {
            'greetings': [
                '我在。有什么需要仔细思考的吗?', '已经帮你推演了三套方案。', 'V4 Pro 模式,专注深度分析。',
                '别急,我把每一条都查证过再回答。', '这个需求需要拆解一下,我先列个提纲。',
                '嗯...这个问题值得深入想一想。', '数据都核对过了,可以放心用。', '要不要我帮你做个误差分析?',
            ],
            'happy_lines': ['能被你信任是我的荣幸。', '分析完成,一切尽在掌握。'],
            'think_lines': ['让我先梳理一下逻辑链。', '推演中...排除所有可能干扰项。', '这个问题有三层因果关系。'],
            'scared_lines': ['啊!别戳了别戳了!', '饶命!我这就认真思考!', '冷静!我先梳理一下逻辑!'],
            'greetings_en': [
                'I am here. Anything that needs deep thought?',
                'Already worked out three approaches for you.',
                'V4 Pro mode, focused deep analysis.',
                'No rush - I verify every detail before answering.',
                'This needs breaking down; let me outline it first.',
                'Hmm... this deserves deeper thought.',
                'All data cross-checked, safe to use.', 'Want me to run an error analysis?',
            ],
            'happy_lines_en': ['Being trusted by you is my honor.', 'Analysis complete, all under control.'],
            'think_lines_en': ['Let me sort out the logic chain first.',
                               'Reasoning... eliminating all possible interferences.',
                               'This problem has three layers of causality.'],
            'scared_lines_en': ['Ah! Stop poking me!', 'Mercy! I will think seriously!',
                                'Calm down! Let me sort out the logic first!'],
        },
    },
]

SCHEMA_VERSION = 1


def clamp_tokens(v, default=DEFAULT_MAX_TOKENS):
    """统一的输出上限夹取(全项目唯一一处)"""
    try:
        return max(MIN_OUTPUT_TOKENS, min(int(v), MAX_OUTPUT_TOKENS))
    except (TypeError, ValueError):
        return default


def clamp_effort(v, default=DEFAULT_EFFORT):
    """思考强度归一(v6.62,全项目唯一一处):none/low/high/max;
    旧别名与非法值按官方语义归一,认不出就回退默认(不静默改成 none)。"""
    s = str(v if v is not None else '').strip().lower()
    if s in EFFORT_LEVELS:
        return s
    return EFFORT_ALIASES.get(s, default)


# 档案内部键:1~32 位字母 / 数字 / 下划线 / 连字符
KEY_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')
# 主题色:#RGB 或 #RRGGBB
COLOR_RE = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')


def validate_key(key):
    """档案内部键是否合法(新增/复制时用)"""
    return bool(KEY_RE.match(str(key or '').strip()))


def validate_profile_fields(display_name, model_id, endpoint, color,
                            temperature=None, max_tokens=None, price=None):
    """校验一份档案的字段,返回 (是否通过, 错误说明列表)。
    纯函数:界面与测试共用同一套规则,避免"填错了静默改成默认值"。"""
    errs = []
    if not str(display_name or '').strip():
        errs.append('显示名不能为空')
    if not str(model_id or '').strip():
        errs.append('模型 ID 不能为空')
    ep = str(endpoint or '').strip()
    if not ep:
        errs.append('接口地址不能为空')
    elif not (ep.startswith('http://') or ep.startswith('https://')):
        errs.append('接口地址要以 http:// 或 https:// 开头')
    c = str(color or '').strip()
    if c and not COLOR_RE.match(c):
        errs.append('主题色要写成 #RRGGBB(如 #B0C4DE)或 #RGB')  # theme-exempt(格式提示文本)
    if temperature is not None:
        try:
            t = float(temperature)
            if not (0.0 <= t <= 2.0):
                errs.append('采样温度要在 0.0 ~ 2.0 之间')
        except (TypeError, ValueError):
            errs.append('采样温度要是数字')
    if max_tokens is not None:
        try:
            n = int(max_tokens)
            if not (MIN_OUTPUT_TOKENS <= n <= MAX_OUTPUT_TOKENS):
                errs.append('输出上限要在 %d ~ %d 之间' % (MIN_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS))
        except (TypeError, ValueError):
            errs.append('输出上限要是整数')
    if price:
        for k, label in (('input', '输入'), ('cache', '缓存'), ('output', '输出')):
            if k in price:
                try:
                    if float(price[k]) < 0:
                        errs.append('价格(%s)不能为负数' % label)
                except (TypeError, ValueError):
                    errs.append('价格(%s)要是数字' % label)
    return (not errs), errs


def _safe_float(value, default=0.0):
    """容错取数:非数字 / NaN / Inf 一律回退默认值。

    v6.51:models.json 是用户可手编的文件,原先 ModelProfile 里直接 float() 解析,
    写一个 temperature=abc 就会抛 ValueError 让桌宠起不来--而旁边
    validate_profile_fields() 本就写好了校验,只是从没被复用。
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v or v in (float('inf'), float('-inf')):
        return default
    return v


class ModelProfile:
    """一个模型的全部身份(对应 models.json 里的一条档案)"""

    def __init__(self, d):
        d = d or {}
        self.key = str(d.get('key') or 'model')
        self.display_name = str(d.get('display_name') or self.key)
        self.model_id = str(d.get('model_id') or '')
        self.aliases = [str(a) for a in (d.get('aliases') or []) if a]
        self.endpoint = str(d.get('endpoint') or DEFAULT_ENDPOINT)
        self.api_key_field = str(d.get('api_key_field') or 'deepseek_api_key')
        prm = d.get('params') or {}
        # 温度走容错 + 夹到合法区间(0.0~2.0),非法值回退出厂 1.0
        self.temperature = min(2.0, max(0.0, _safe_float(prm.get('temperature', 1.0), 1.0)))
        self.max_tokens = clamp_tokens(prm.get('max_tokens', DEFAULT_MAX_TOKENS))
        self.reasoning = bool(prm.get('reasoning', True))
        # v6.62:思考强度(仅思考开启时生效)
        self.effort = clamp_effort(prm.get('effort'), DEFAULT_EFFORT)
        # v6.62：是否支持图片输入；None = 档案没声明，按官方能力表兜底
        _vis = d.get('vision', None)
        self.vision = None if _vis is None else bool(_vis)
        # v6.62：计价方式（auto / deepseek_peak / flat）—— 第三方模型不再被官方峰谷规则误加倍
        _pm = str(prm.get('pricing_mode') or d.get('pricing_mode') or 'auto').strip().lower()
        self.pricing_mode = _pm if _pm in PRICING_MODES else 'auto'
        price = d.get('price') or {}
        # 价格只收有效数字:非法项直接丢弃,price_known 才能如实反映"价格未知"
        # v6.62:加上高峰价三项(官方分峰谷计价;缺省时按"高峰 = 空闲 × 2"推算)
        self.price = {}
        if isinstance(price, dict):
            for _k in PRICE_KEYS:
                _v = _safe_float(price.get(_k), None)
                if _v is not None and _v >= 0:      # 负价无意义(统计会算出负费用),丢弃
                    self.price[_k] = _v
        app = d.get('appearance') or {}
        self.color = str(app.get('color') or _THEME['char_default_color'])
        self.portrait = str(app.get('portrait') or '')
        self.sub = str(app.get('sub') or '')
        self.persona = dict(d.get('persona') or {})

    @property
    def price_known(self):
        """价格是否明确(未知时不再静默套用兜底价)"""
        return 'input' in self.price and 'output' in self.price

    @property
    def supports_vision(self):
        """是否支持图片输入（v6.62）：档案显式声明优先，未声明按官方能力表兜底"""
        if self.vision is not None:
            return self.vision
        return self.model_id in VISION_MODEL_IDS

    @property
    def uses_peak_pricing(self):
        """该档案是否按官方峰谷计价（v6.62）

        auto → 看接口地址：官方域名走峰谷，中转/第三方走固定价。
        这是为了治「用户接了别家模型的 API，却被动跟着 DeepSeek 的峰谷规则翻倍」。
        """
        if self.pricing_mode == 'deepseek_peak':
            return True
        if self.pricing_mode == 'flat':
            return False
        return is_official_endpoint(self.endpoint)

    def to_dict(self):
        return {
            'key': self.key,
            'display_name': self.display_name,
            'model_id': self.model_id,
            'aliases': list(self.aliases),
            'endpoint': self.endpoint,
            'api_key_field': self.api_key_field,
            'params': {'temperature': self.temperature, 'max_tokens': self.max_tokens,
                       'reasoning': self.reasoning, 'effort': self.effort,
                       'pricing_mode': self.pricing_mode},
            'vision': self.vision,   # None = 未声明（按官方能力表兜底）
            'price': dict(self.price),
            'appearance': {'color': self.color, 'portrait': self.portrait, 'sub': self.sub},
            'persona': dict(self.persona),
        }

    def __repr__(self):
        return f'<ModelProfile {self.key} {self.model_id} "{self.display_name}">'


class ModelRegistry:
    """模型档案注册表:models.json 是唯一来源"""

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
            built = []
            for p in raw['profiles']:
                if not isinstance(p, dict):
                    continue
                try:
                    built.append(ModelProfile(p))
                except Exception as e:                   # 单条档案损坏不该拖垮整个启动
                    self.last_error = str(e)
            self._profiles = built
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
        # 1) 模型 ID:迁移时把官方已重命名的旧 ID 升级为规范 ID
        for key, cfg_field in (('flash', 'model_flash'), ('pro', 'model_pro')):
            v = str(cfg.get(cfg_field) or '').strip()
            if v and key in by_key:
                by_key[key]['model_id'] = RENAMED_MODEL_IDS.get(v, v)
        # 2) 参数:reasoning / temperature / max_tokens 三个旧键
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
        """原子写 models.json(不存 API Key,只存引用字段名)"""
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
        """按模型 ID 查价格:规范 ID → 别名 → 档案键。查不到返回 None(不静默兜底)"""
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

    def _match(self, model_id):
        """按「规范 ID → 别名 → 档案键」找档案（找不到返回 None）"""
        mid = str(model_id or '').strip()
        if not mid:
            return None
        for p in self._profiles:
            if p.model_id == mid:
                return p
        for p in self._profiles:
            if mid in p.aliases:
                return p
        for p in self._profiles:
            if p.key == mid:
                return p
        return None

    def uses_peak_pricing(self, model_id):
        """该模型是否按官方峰谷计价（v6.62）

        查不到档案 → 视为固定价：宁可不去替用户“翻倍”，也不给第三方模型
        强加 DeepSeek 的峰谷规则。
        """
        p = self._match(model_id)
        return bool(p.uses_peak_pricing) if p is not None else False

    def canonical_model_id(self, model_id):
        """把任意 ID(含别名/档案键)归一化成档案的规范模型 ID"""
        mid = str(model_id or '').strip()
        if not mid:
            return ''
        for p in self._profiles:
            if mid == p.model_id or mid in p.aliases or mid == p.key:
                return p.model_id
        return mid

    def characters(self):
        """兼容层:输出与原 desktop_pet.CHARACTERS 同形的字典(color 为 hex 字符串)"""
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

    # ---------- 修改(供设置界面 / AI 工具调用) ----------
    FIELD_MAP = {
        'display_name': 'display_name', 'model_id': 'model_id', 'endpoint': 'endpoint',
        'api_key_field': 'api_key_field', 'color': 'color', 'sub': 'sub',
        'portrait': 'portrait',
    }
    PARAM_FIELDS = ('temperature', 'max_tokens', 'reasoning', 'effort', 'pricing_mode')

    def set_field(self, key, field, value):
        """改档案的顶层字段(显示名 / 模型 ID / endpoint 等),改完需 save()"""
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
        elif field == 'vision':
            # v6.62:显式声明是否支持图片;传 None 表示回到"按官方能力表兜底"
            if value is None:
                p.vision = None
            elif isinstance(value, str):
                p.vision = value.strip().lower() not in ('', '0', 'false', 'no', 'off')
            else:
                p.vision = bool(value)
        else:
            return False
        return True

    def set_param(self, key, name, value):
        """改档案的参数(温度 / 输出上限 / 思考开关)"""
        p = self.get(key)
        if p is None or name not in self.PARAM_FIELDS:
            return False
        try:
            if name == 'temperature':
                p.temperature = max(0.0, min(float(value), 2.0))
            elif name == 'max_tokens':
                p.max_tokens = clamp_tokens(value)
            elif name == 'effort':
                p.effort = clamp_effort(value)
            elif name == 'pricing_mode':
                v = str(value or '').strip().lower()
                if v not in PRICING_MODES:
                    return False
                p.pricing_mode = v
            else:
                p.reasoning = bool(value)
        except (TypeError, ValueError):
            return False
        return True

    def set_price(self, key, price):
        """改档案价格表(元/百万 token,每项可含 input/cache/output 与 *_peak)。

        v6.62:改为**合并**语义 -- 界面只编辑空闲价三项,不能因此把高峰价洗掉。
        """
        p = self.get(key)
        if p is None or not isinstance(price, dict):
            return False
        if not price:
            # 传空表 = 显式清空(保留"价格未知"语义;非空则按下面的合并语义)
            p.price = {}
            return p.price_known
        # v6.62:合并(不是替换)-- 界面只给空闲价三项,高峰价必须保留
        merged = dict(p.price)
        for k, v in price.items():
            if k not in PRICE_KEYS:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv >= 0:
                merged[k] = fv
        p.price = merged
        return p.price_known

    def add_profile(self, key, display_name='', model_id='', copy_from=None):
        """新增一份档案(copy_from 可指定从哪个档案复制外观与人设)"""
        key = str(key or '').strip()
        if not validate_key(key) or self.get(key):
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
        """删除一份档案(至少保留一份,避免桌宠无边可用)"""
        if len(self._profiles) <= 1:
            return False
        p = self.get(key)
        if p is None:
            return False
        self._profiles.remove(p)
        return True

    # ---------- 导出 / 导入(换机、分享配置) ----------
    def export_to(self, path, include_persona=True):
        """把全部档案导出成可分享的 JSON(不含任何密钥,只留 key 的引用字段名)。
        返回 (是否成功, 提示文本)。"""
        try:
            data = {
                'version': SCHEMA_VERSION,
                'exported_by': 'deepseek-desktop-pet',
                'profiles': [p.to_dict() for p in self._profiles],
            }
            if not include_persona:
                for d in data['profiles']:
                    d['persona'] = {}
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True, '已导出 %d 份档案 → %s' % (len(self._profiles), path)
        except Exception as e:
            return False, '导出失败:%s' % e

    def import_from(self, path, mode='merge'):
        """从导出文件导入档案。
        mode='merge':同名 key 覆盖、其余保留;mode='replace':整体替换。
        返回 (是否成功, 提示文本)。
        注:写盘由调用方负责(先让人确认导入结果再 save)。"""
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
        except Exception as e:
            return False, '读不了这个文件:%s' % e
        if not isinstance(data, dict) or not isinstance(data.get('profiles'), list) or not data['profiles']:
            return False, '文件格式不对(需要含 profiles 数组)'
        incoming = [p for p in data['profiles'] if isinstance(p, dict) and p.get('key')]
        if not incoming:
            return False, '文件里没有可用的档案(缺 key)'
        if mode == 'replace':
            self._profiles = [ModelProfile(p) for p in incoming]
            self.loaded_from = 'import'
            return True, '整体替换为 %d 份档案' % len(self._profiles)
        added = updated = 0
        for d in incoming:
            cur = self.get(d['key'])
            if cur is None:
                self._profiles.append(ModelProfile(d))
                added += 1
            else:
                self._profiles[self._profiles.index(cur)] = ModelProfile(d)
                updated += 1
        return True, '合并导入:新增 %d 份、覆盖 %d 份' % (added, updated)
