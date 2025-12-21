"""
工具函数模块
包含各种工具函数和辅助类
"""

from .keyboard_utils import press_key
from .logger import Logger
from .screen_utils import get_screen_resolution, get_window_resolution

# 窗口选择器（需要pywin32，可能不可用）
try:
    from .window_selector import WindowSelector
    WINDOW_SELECTOR_AVAILABLE = True
except ImportError:
    WindowSelector = None
    WINDOW_SELECTOR_AVAILABLE = False

__all__ = ['press_key', 'Logger', 'get_screen_resolution', 'get_window_resolution', 'WindowSelector', 'WINDOW_SELECTOR_AVAILABLE']

