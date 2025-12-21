"""
键盘操作工具函数
封装按键模拟相关的操作，便于未来扩展和替换实现
"""

import keyboard
import time
import random


# 按键按住时间范围（毫秒）
KEY_HOLD_MIN_MS = 50   # 最小按住时间
KEY_HOLD_MAX_MS = 150  # 最大按住时间


def press_key(key: str):
    """
    模拟人类按下并释放按键（按住随机毫秒数再松开）
    
    参数:
        key: 按键名称（如 '1', '2', 'F1', 'space' 等）
    
    异常:
        Exception: 当按键操作失败时抛出异常
    """
    try:
        # 按下键
        keyboard.press(key)
        
        # 随机按住时间（模拟人类操作）
        hold_time = random.randint(KEY_HOLD_MIN_MS, KEY_HOLD_MAX_MS) / 1000.0
        time.sleep(hold_time)
        
        # 松开键
        keyboard.release(key)
    except Exception as e:
        raise Exception(f"按键 '{key}' 操作失败: {str(e)}")


def is_key_pressed(key: str) -> bool:
    """
    检查按键是否被按下
    
    参数:
        key: 按键名称
    
    返回:
        bool: 如果按键被按下返回True，否则返回False
    """
    try:
        return keyboard.is_pressed(key)
    except Exception:
        return False

