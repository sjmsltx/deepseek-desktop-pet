# -*- coding: utf-8 -*-
"""pet_log.py — 统一日志（滚动文件，零依赖）
=============================================
背景（2026-09-12 审查）：项目里大量 `except Exception: pass` 让"记忆写不进去""统计
文件坏了"这类问题完全无声——用户只会觉得"它怎么不记得了"。本模块提供一个统一的
日志出口，把这类失败记到 logs/pet.log。

用法：
    from pet_log import get_logger
    _log = get_logger('memory_store')      # 名字会成为日志前缀
    _log.warning('读失败：%s', e)

开关：
- 默认只写文件（logs/pet.log，512 KB × 4 份滚动），不污染控制台；
- 设环境变量 PET_LOG_LEVEL=DEBUG/INFO 时同时打到控制台，便于开发排查。
"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'pet.log')
_LOGGER_NAME = 'pet'
_inited = False


def _init():
    global _inited
    if _inited:
        return
    _inited = True
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = RotatingFileHandler(LOG_FILE, maxBytes=512 * 1024, backupCount=3, encoding='utf-8')
        fh.setLevel(logging.INFO)      # 文件只记 INFO 及以上，避免刷爆
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass                            # 日志系统自己不能把主程序拖垮
    level = (os.environ.get('PET_LOG_LEVEL') or '').upper()
    if level:
        lv = getattr(logging, level, logging.INFO)
        sh = logging.StreamHandler()
        sh.setLevel(lv)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        logger.setLevel(lv)


def get_logger(name=''):
    """取一个带前缀的 logger（如 get_logger('memory_store')）"""
    _init()
    return logging.getLogger(_LOGGER_NAME + ('.' + name if name else ''))
