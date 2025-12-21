"""
屏幕工具模块
提供屏幕截图、分辨率检测等功能
"""

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


def get_screen_resolution() -> tuple:
    """
    获取屏幕分辨率
    
    返回:
        tuple: (width, height)
    """
    if PYAUTOGUI_AVAILABLE:
        try:
            width, height = pyautogui.size()
            return (width, height)
        except Exception:
            pass
    
    # 备用方法：使用Windows API
    try:
        import ctypes
        user32 = ctypes.windll.user32
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)
        return (width, height)
    except Exception:
        return (0, 0)


def get_window_resolution(window_title: str = None) -> tuple:
    """
    获取指定窗口的分辨率
    
    参数:
        window_title: 窗口标题（如果为None，返回当前活动窗口）
    
    返回:
        tuple: (width, height)
    """
    # 这里未来可以实现窗口检测功能
    # 目前先返回屏幕分辨率
    return get_screen_resolution()


def capture_screen(region: tuple = None) -> bytes:
    """
    截取屏幕
    
    参数:
        region: 截图区域 (x, y, width, height)，如果为None则截取全屏
    
    返回:
        bytes: 截图数据
    """
    if MSS_AVAILABLE:
        try:
            with mss.mss() as sct:
                if region:
                    monitor = {
                        "top": region[1],
                        "left": region[0],
                        "width": region[2],
                        "height": region[3]
                    }
                else:
                    monitor = sct.monitors[1]  # 主显示器
                
                screenshot = sct.grab(monitor)
                return screenshot
        except Exception as e:
            print(f"截图失败: {e}")
    
    return None

