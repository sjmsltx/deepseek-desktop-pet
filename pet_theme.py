# -*- coding: utf-8 -*-
"""pet_theme.py — 主题颜色 token 唯一源（v6.57 / A1）

为什么要有这个文件
------------------
主题 token 原先**内联在 desktop_pet.py**（DEFAULT_THEME 17 项），而 settings_ui.py 又另
写了一套配色（`#14161f` / `rgba(255,255,255,0.05)` 等 11 处字面量）——"主题源不唯一"，
导致 AI 与用户想改外观时不知道改哪里：该走主题的地方可能没有 token，去改源码又定位不准。

本文件是**唯一**的颜色 token 源：
  · 主程序、设置窗口，以及后续接入主题的小游戏/关系面板/卡片等，一律从这里取值；
  · theme 插件（plugin.json 的 `theme` 字段）用**同名键**即可覆盖任意 token
    （见 plugin_manager.theme_vars → host.theme.update(...)）；
  · 新增外观需求：**先在这里加 token**，再去对应 UI 引用；禁止在各模块里写死颜色字面量。

TOKEN_GROUPS 只是分类索引（便于人和 AI 快速定位"某组件用哪些 token"），不参与渲染。

约定：token 值就用 Qt 能直接吃的字符串（`#RRGGBB` / `rgba(r,g,b,a)`）。
"""

# ---------------------------------------------------------------------------
# 唯一 token 表（theme 插件同名键可覆盖）
# ---------------------------------------------------------------------------
DEFAULT_THEME = {
    # ---- 聊天气泡 ----
    'user_bubble': 'rgba(30,88,70,0.80)',
    'ai_bubble': 'rgba(46,54,76,0.80)',
    'name_user': '#6fe3a1',
    'name_ai': '#7fb2ff',
    'bubble_text': '#eee',  # v6.44 气泡内文字颜色（白底气泡需配深色文字）
    # ---- 顶部说话气泡（say_plain）----
    'say_bg': 'rgba(255,255,255,0.92)',
    'say_text': '#333',
    'say_border': '#ccc',
    # ---- 聊天面板 ----
    'panel_bg': 'rgba(20,20,30,0.85)',
    'text': '#eee',
    'input_bg': 'rgba(255,255,255,0.12)',
    'input_focus': 'rgba(255,255,255,0.18)',
    'input_text': '#fff',  # v6.52 输入框文字色（原先写死在 _panel_qss 里，浅色主题下会看不见）
    'accent': '#7fb2ff',
    'scroll_bg': 'rgba(255,255,255,0.08)',
    'scroll_handle': '#ffffff',
    'scroll_handle_hover': 'rgba(255,255,255,0.65)',
    # ---- 设置窗口（v6.57 从 settings_ui.py 的字面量提升而来，取值与原样一致）----
    'dialog_bg': '#14161f',
    'list_bg': 'rgba(255,255,255,0.05)',
    'list_border': 'rgba(255,255,255,0.10)',
    'list_sel_bg': 'rgba(127,178,255,0.20)',
    'list_sel_text': '#ffffff',
    'item_bg': 'rgba(255,255,255,0.08)',
    'item_border': 'rgba(255,255,255,0.14)',
    'item_hover_bg': 'rgba(255,255,255,0.15)',
    'popup_bg': '#1b1e2a',
    'popup_sel_bg': 'rgba(127,178,255,0.25)',
    'hint_text': '#7c8486',
    # ---- 小游戏（v6.58 A2-1：从 pet_minigames.py 的字面量提升，取值与原样逐项一致）----
    'ui_bg': '#1e2430',            # 游戏窗口底
    'ui_input_bg': '#141b2c',      # 输入框 / 棋盘底
    'ui_board_bg': '#182136',      # 井字棋 / 打地鼠 棋盘、卡片底
    'ui_board_deep': '#0d1320',    # 俄罗斯方块底
    'ui_stone_dark': '#111111',    # 五子棋黑子
    'ui_flash': '#ffffff',         # 西蒙记忆点亮闪烁
    'ui_text': '#dce3f0',          # 正文
    'ui_text_strong': '#fff',      # 2048 高位数方块上的文字
    'ui_text_soft': '#9ec',        # 保存按钮文字
    'ui_text_dim': '#8aa',         # 次要文字
    'ui_text_muted': '#667',       # 禁用态文字
    'ui_text_faint': '#445',       # 更淡的禁用文字
    'ui_btn_bg': '#2a3a55',
    'ui_btn_hover': '#35507a',
    'ui_btn_alt': '#24314a',       # 井字棋 / 打地鼠 悬停
    'ui_btn_disabled': '#1c2740',
    'ui_border': '#3a4a66',
    'ui_border_soft': '#2c3a52',
    'ui_accent': '#7fb2ff',        # 数独给定数字
    'ui_accent_soft': '#9fd0ff',   # 桌宠表情文字 / 扫雷数字 1
    'ui_gold': '#ffd700',
    'ui_red': '#e0527a',
    'ui_green': '#6ecb7a',
    'ui_green_dark': '#3f8f5f',
    'ui_blue': '#4a8ac2',
    'ui_blue_deep': '#3f6ca8',
    'ui_blue_light': '#5aa7d6',
    'ui_cyan': '#00e5ff',
    'ui_purple': '#c9a0ff',
    'ui_orange': '#ffa040',
    'ui_orange_deep': '#ff8c00',
    'ui_pink_soft': '#e8739a',
    'ui_pink_light': '#f09ab5',
    'ui_pink_lighter': '#f5b8cc',
    'ui_red_soft': '#ff8a8a',
    'ui_red_bright': '#ff5555',
    # ---- 主程序 UI（v6.58 A2-2：从 desktop_pet.py 字面量提升，取值与原样一致）----
    'ui_popup_bg': 'rgba(18,26,44,.5)',        # 任务侧栏底
    'ui_popup_list_bg': 'rgba(12,18,32,.6)',   # 侧栏列表底
    'ui_popup_btn_bg': 'rgba(18,26,44,.4)',    # 侧栏把手底
    'ui_popup_btn_hover': 'rgba(40,60,90,.7)',
    'ui_status_text': '#7a8aa0',               # 思考 / 流式辅助文字
    'ui_warn': '#e8c76a',                      # 代码告警
    'ui_card_bg': '#2b3245',                   # 附件卡片底
    'ui_card_border': '#3a4158',
    'ui_card_text': '#cfd6e6',
    'ui_card_text_dim': '#7a8299',
    'ui_card_btn': '#9aa2b8',
    'ui_card_btn_hover': '#ff6b6b',
    'ui_stats_bg': 'rgba(15,20,32,0.92)',      # API 监控悬浮窗
    'ui_stats_track': 'rgba(255,255,255,0.08)',
    'ui_hint_dark': '#4d5456',                  # 模型管理窗深色提示文字
    'ui_code_btn': '#2a3142',                  # 代码/表格卡片按钮
    'ui_code_btn_hover': '#3a4152',
    'ui_code_bg': '#161b26',                   # 卡片内代码区底
    'ui_code_text': '#d8e0f0',
    'ui_code_sel': '#2a4a6b',                  # 卡片内选中色
    'ui_bubble_bg': 'rgba(20,27,44,0.75)',      # 角色头顶气泡底（affection_ui.CostBubble）
    'char_default_color': '#B0C4DE',           # 角色立绘默认色（模型档案未指定时）
}

# ---------------------------------------------------------------------------
# 分类索引（供人/AI 定位；不参与渲染）
# ---------------------------------------------------------------------------
TOKEN_GROUPS = {
    'panel': ['panel_bg', 'text', 'input_bg', 'input_focus', 'input_text', 'accent',
              'scroll_bg', 'scroll_handle', 'scroll_handle_hover'],
    'bubble': ['user_bubble', 'ai_bubble', 'name_user', 'name_ai', 'bubble_text',
               'say_bg', 'say_text', 'say_border'],
    'dialog': ['dialog_bg', 'list_bg', 'list_border', 'list_sel_bg', 'list_sel_text',
               'item_bg', 'item_border', 'item_hover_bg', 'popup_bg', 'popup_sel_bg',
               'hint_text'],
    # v6.58 A2-1：小游戏（pet_minigames.py 已接入；取值与原写死配色一致）
    'minigame': ['ui_bg', 'ui_input_bg', 'ui_board_bg', 'ui_board_deep', 'ui_stone_dark', 'ui_flash', 'ui_text', 'ui_text_strong', 'ui_text_soft',
                 'ui_text_dim', 'ui_text_muted', 'ui_text_faint', 'ui_btn_bg', 'ui_btn_hover',
                 'ui_btn_alt', 'ui_btn_disabled', 'ui_border', 'ui_border_soft', 'ui_accent',
                 'ui_accent_soft', 'ui_gold', 'ui_red', 'ui_green', 'ui_green_dark', 'ui_blue',
                 'ui_blue_deep', 'ui_blue_light', 'ui_cyan', 'ui_purple', 'ui_orange',
                 'ui_orange_deep', 'ui_pink_soft', 'ui_pink_light', 'ui_pink_lighter',
                 'ui_red_soft', 'ui_red_bright'],
    # v6.58 A2-2：主程序 UI（侧栏 / 监控窗 / 附件卡片 / 选项按钮 / 代码卡片 …）
    'host': ['ui_popup_bg', 'ui_popup_list_bg', 'ui_popup_btn_bg', 'ui_popup_btn_hover',
             'ui_status_text', 'ui_warn', 'ui_card_bg', 'ui_card_border', 'ui_card_text',
             'ui_card_text_dim', 'ui_card_btn', 'ui_card_btn_hover', 'ui_stats_bg',
             'ui_stats_track', 'ui_hint_dark', 'ui_code_btn', 'ui_code_btn_hover', 'ui_code_bg', 'ui_code_text',
             'ui_code_sel', 'ui_bubble_bg', 'char_default_color'],
}


_ACTIVE_THEME = dict(DEFAULT_THEME)   # 当前生效主题（默认值 + 插件覆盖）
_WATCHERS = []


def active():
    """当前生效的主题字典（默认值 + 插件覆盖）。"""
    return _ACTIVE_THEME


def color(key, fallback='#ff00ff'):  # theme-exempt（缺键兜底色，故意写死）
    """取当前生效颜色。缺键回退默认值；再缺返回 fallback（洋红=显而易见的漏配提示）。"""
    return _ACTIVE_THEME.get(key) or DEFAULT_THEME.get(key) or fallback


def set_active(theme):
    """更新当前生效主题，并通知所有订阅者重刷。宿主在应用/切换主题时调用。"""
    global _ACTIVE_THEME
    t = dict(DEFAULT_THEME)
    if theme:
        t.update({k: v for k, v in theme.items() if v})
    _ACTIVE_THEME = t
    for fn in list(_WATCHERS):
        try:
            fn()
        except Exception:
            pass          # 单个订阅者失败不影响其它模块
    return _ACTIVE_THEME


def subscribe(fn):
    """登记"主题变化时重刷"回调，返回取消函数。"""
    _WATCHERS.append(fn)

    def _unsubscribe():
        try:
            _WATCHERS.remove(fn)
        except ValueError:
            pass
    return _unsubscribe


def merged(overrides=None):
    """返回"默认 token + 插件覆盖"的合并副本（唯一源 + 插件覆盖的标准取用方式）。"""
    t = dict(DEFAULT_THEME)
    if overrides:
        t.update({k: v for k, v in overrides.items() if isinstance(v, str) and v})
    return t
