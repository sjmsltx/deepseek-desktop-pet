# -*- coding: utf-8 -*-
"""pet_anim.py — 状态机与动画（低耦合段）

2026-09-13 桌宠收尾批 4（任务 C1 低耦合段）从 desktop_pet.PetWidget 拆出。

搬迁范围（只碰状态/立绘字典/睡眠标志，**不碰窗口几何与扒边坐标**）：
- 受控状态写入口 set_state + 白名单 SET_STATE_KEYS
- 状态/场景立绘显示、显示态恢复
- 眨眼与过渡收尾、场景动作播放与结束、情绪/惊吓收尾
- 睡眠切换、随机问候
- 系统空闲秒数（纯函数）

**不属本模块**（留着与窗口几何/定时器驱动强耦合，属批 8）：
- 贴边与弹出：_edge_dock_check / _enter_dock / _exit_dock_to_free / _popup_from_dock / toggle_edge_mode
- 主循环与渲染：animate / _render_frame / _render_idle_offset / _show_idle（依赖窗口尺寸与 peek 图）
- 定时器编排：_start_idle_system / _check_idle_state

调用约定：函数首参 w 为宿主（PetWidget）视图对象，读取/写入其状态与控件。
"""
import ctypes
import random

from PySide6.QtCore import QTimer

# 受控写入口白名单（原 PetWidget._SET_STATE_KEYS）
SET_STATE_KEYS = {
    'char': 'current', 'language': 'language', 'max_tokens': 'max_tokens',
    'temperature': 'temperature', 'theme': 'theme', 'ai_enabled': 'ai_enabled',
    'ai_key': 'ai_key', 'cfg': '_cfg', 'chat_msgs': 'chat_history_msgs',
    'memory_summaries': 'memory_summaries', 'api_stats': 'api_stats',
    'edge_mode': '_edge_mode', 'display_mode': 'display_mode',
    'choices_requested': '_choices_requested',
}

# 场景动作表（原 desktop_pet.SCENE_ACTIONS）
SCENE_ACTIONS = {
    'lying': ('🛏️ 趴地板', '慵懒趴地翘脚'),
    'eating': ('🍜 吃面', '抱碗吃面'),
    'phone': ('📱 玩手机', '低头刷手机'),
    'hug_whale': ('🐋 抱玩偶', '抱着鲸鱼玩偶蹭蹭'),
    'typing': ('💻 打字', '认真码字工作'),
    'reading': ('📖 看书', '沉浸阅读'),
    'coffee': ('☕ 喝咖啡', '优雅小酌咖啡'),
    'music': ('🎧 听歌', '戴耳机陶醉'),
    'exercise': ('💪 健身', '举哑铃锻炼'),
    'flower': ('🌸 捧花', '害羞捧花'),
    'gift': ('🎁 礼物', '开心捧礼物'),
    'umbrella': ('🌂 撑伞', '雨中撑伞漫步'),
}


def idle_seconds():
    """系统空闲秒数（GetLastInputInfo，零依赖）"""
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
    except Exception:
        pass
    return 0


def set_state(w, **kw):
    """受控写入口：只接受白名单键（写错立刻报错，不静默写坏状态）"""
    for k, v in kw.items():
        attr = SET_STATE_KEYS.get(k)
        if attr is None:
            raise KeyError('set_state 不支持的键：%s（可用：%s）'
                           % (k, '、'.join(sorted(SET_STATE_KEYS))))
        setattr(w, attr, v)
    return w


def show_state_image(w, st):
    """显示状态立绘（sleep/happy/thinking/scared/...；Live2D 模式由模型代替）"""
    if getattr(w, 'display_mode', 'static') == 'live2d':
        return
    img = w._get_state_img(st)
    if img is None:
        w._show_idle()
        return
    w._render_frame(img)


def restore_display_state(w):
    """恢复显示状态：睡眠→睡眠立绘，否则→待机（贴边拖出/弹出后用）"""
    if w.sleeping:
        w._show_state_image('sleep')
    else:
        w._show_idle()


def play_scene(w, key):
    """播放场景动作立绘（6 秒后恢复待机）"""
    if w.sleeping:
        return
    img = w._get_scene_img(key)
    if img is None or img.isNull():
        w.say_plain('这个动作还没准备好~')
        return
    w.state = 'scene'  # 关键：锁定状态，防止 blink/光标跟随在播放期间切回待机
    w.phase = 0
    w._render_frame(img)
    desc = SCENE_ACTIONS[key][1]
    w.say_plain(desc[:10])
    QTimer.singleShot(6000, w._end_scene)


def end_scene(w):
    """场景动作结束：恢复待机"""
    if not w.sleeping:
        w.state = 'idle'
        w._show_idle()


def blink_tick(w):
    """眨眼定时器回调（睡眠/拖拽/非待机/贴边时不眨眼）"""
    if (w.sleeping or w.dragging or w._blinking or w.state != 'idle'
            or w._edge_side is not None):
        w.blink_timer.start(random.randint(8000, 15000))
        return
    if w.blink_aligned is None:
        w.blink_timer.start(random.randint(8000, 15000))
        return
    w._blinking = True
    # 缩放渲染（blink 是 2048 原图，必须缩放到 pet_label 尺寸，否则只显示左上角局部）
    w._render_frame(w.blink_aligned)
    QTimer.singleShot(1500, w._blend_end)
    w.blink_timer.start(random.randint(8000, 15000))


def blend_end(w):
    """眨眼结束：按当前所处状态回到 peek / 待机"""
    w._blinking = False
    if w._edge_side is not None and not w._edge_popped:
        w._show_peek()
    elif not w.sleeping and w.state == 'idle':
        w._show_idle()


def end_state(w, st):
    """情绪/惊吓等临时状态收尾（仅当仍处于该状态时回待机）"""
    if not w.sleeping and w.state == st:
        w.state = 'idle'
        w._show_idle()


def restore_after_emotion(w):
    """情绪立绘结束后恢复待机"""
    if not w.sleeping:
        w.state = 'idle'
        w._show_idle()


def toggle_sleep(w):
    """睡眠切换：睡觉时停打字并藏气泡，醒来恢复待机"""
    w.sleeping = not w.sleeping
    if w.sleeping:
        w.type_timer.stop()
        w.bubble.hide()
        w._show_state_image('sleep')
        w.say_plain('我先睡一会儿，有事叫我…')
    else:
        w._render_frame()
        w.say_plain('醒啦！')


def say_random(w):
    """随机说一句问候（气泡 + 聊天记录）"""
    if w.sleeping:
        return
    lines = w._char_lines('greetings')
    text = random.choice(lines) if lines else 'Hello!'
    w.say_plain(text)
    w._append_chat('桌宠', text)
