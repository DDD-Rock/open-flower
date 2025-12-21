"""
配置模块
包含应用配置和常量定义
"""

# 应用配置
APP_NAME = "苗圃助手"
APP_VERSION = "1.0.0"

# UI配置
WINDOW_WIDTH = 280  # 窗口宽度（瘦长布局）
WINDOW_HEIGHT = 700  # 窗口高度（瘦长布局）
WINDOW_X = 100
WINDOW_Y = 100

# 技能释放配置
DEFAULT_INTERVAL = 5.0  # 默认释放间隔（秒）
DEFAULT_RANDOM_DELAY = 2.0  # 默认随机延迟（秒）
MIN_INTERVAL = 0.1  # 最小释放间隔（秒）
MAX_INTERVAL = 3600.0  # 最大释放间隔（秒）

# 线程配置
THREAD_SLEEP_INTERVAL = 0.1  # 线程检查间隔（秒）
CYCLE_PAUSE_TIME = 0.5  # 每轮循环之间的暂停时间（秒）
INITIAL_WAIT_TIME = 0  # 开始前初始等待时间（秒）

__all__ = [
    'APP_NAME',
    'APP_VERSION',
    'WINDOW_WIDTH',
    'WINDOW_HEIGHT',
    'WINDOW_X',
    'WINDOW_Y',
    'DEFAULT_INTERVAL',
    'DEFAULT_RANDOM_DELAY',
    'MIN_INTERVAL',
    'MAX_INTERVAL',
    'THREAD_SLEEP_INTERVAL',
    'CYCLE_PAUSE_TIME',
    'INITIAL_WAIT_TIME',
]

