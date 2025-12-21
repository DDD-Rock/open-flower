"""
窗体选择模块
支持自动识别游戏窗体
"""

try:
    import win32gui
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    win32gui = None
    win32con = None

from typing import List, Dict, Optional, Tuple


class WindowSelector:
    """窗体选择器类"""
    
    def __init__(self):
        """初始化窗体选择器"""
        if not WIN32_AVAILABLE:
            raise ImportError("需要安装pywin32库: pip install pywin32")
    
    def get_all_windows(self) -> List[Dict]:
        """
        获取所有可见窗体
        
        Returns:
            窗体信息列表，每个元素包含 {'hwnd', 'title', 'rect', 'class_name', 'size'}
        """
        windows = []
        
        def enum_windows_callback(hwnd, windows_list):
            # 只获取可见的窗体
            if win32gui.IsWindowVisible(hwnd):
                # 获取窗体标题
                title = win32gui.GetWindowText(hwnd)
                # 过滤掉空标题和系统窗体
                if title and len(title.strip()) > 0:
                    # 获取窗体位置和大小
                    rect = win32gui.GetWindowRect(hwnd)
                    # 获取窗体类名
                    class_name = win32gui.GetClassName(hwnd)
                    
                    # 过滤掉太小的窗体（可能是工具栏等）
                    width = rect[2] - rect[0]
                    height = rect[3] - rect[1]
                    if width > 100 and height > 100:
                        windows_list.append({
                            'hwnd': hwnd,
                            'title': title,
                            'rect': rect,
                            'class_name': class_name,
                            'size': (width, height)
                        })
            return True
        
        win32gui.EnumWindows(enum_windows_callback, windows)
        
        # 按窗体大小排序，大窗体在前
        windows.sort(key=lambda x: x['size'][0] * x['size'][1], reverse=True)
        
        return windows
    
    def find_windows_by_title(self, title_pattern: str) -> List[Dict]:
        """
        根据标题模式查找窗体
        
        Args:
            title_pattern: 标题模式（支持部分匹配）
            
        Returns:
            匹配的窗体列表
        """
        all_windows = self.get_all_windows()
        matched_windows = []
        
        title_pattern_lower = title_pattern.lower()
        
        for window in all_windows:
            if title_pattern_lower in window['title'].lower():
                matched_windows.append(window)
        
        return matched_windows
    
    def auto_detect_game_window(self, keywords: List[str] = None) -> Optional[Dict]:
        """
        自动检测游戏窗口
        
        Args:
            keywords: 关键词列表，用于匹配游戏窗口标题
                     如果为None，默认检测以 "MapleStory Worlds-Artale" 开头的窗口
            
        Returns:
            找到的游戏窗口信息，或None
        """
        all_windows = self.get_all_windows()
        
        # 默认行为：查找以 "MapleStory Worlds-Artale" 开头的窗口
        if keywords is None:
            target_prefix = "MapleStory Worlds-Artale"
            for window in all_windows:
                if window['title'].startswith(target_prefix):
                    return window
            return None
        
        # 如果提供了自定义关键词，使用关键词匹配
        for keyword in keywords:
            for window in all_windows:
                if keyword.lower() in window['title'].lower():
                    # 返回第一个匹配的窗口
                    return window
        
        return None
    
    def get_window_screenshot_region(self, hwnd: int) -> Tuple[int, int, int, int]:
        """
        获取窗体的截图区域（去除边框）
        
        Args:
            hwnd: 窗体句柄
            
        Returns:
            (x, y, width, height) 截图区域
        """
        # 获取窗体矩形
        rect = win32gui.GetWindowRect(hwnd)
        
        # 获取客户区矩形（去除标题栏和边框）
        try:
            client_rect = win32gui.GetClientRect(hwnd)
            # 将客户区坐标转换为屏幕坐标
            client_point = win32gui.ClientToScreen(hwnd, (0, 0))
            
            x = client_point[0]
            y = client_point[1]
            width = client_rect[2]
            height = client_rect[3]
            
        except Exception:
            # 如果获取客户区失败，使用整个窗体区域
            x, y = rect[0], rect[1]
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
        
        return (x, y, width, height)
    
    def bring_window_to_front(self, hwnd: int) -> bool:
        """
        将窗体置于前台并设置焦点
        
        Args:
            hwnd: 窗体句柄
            
        Returns:
            是否成功
        """
        try:
            # 如果窗体被最小化，先还原
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            
            # 先显示窗口（确保窗口可见）
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            
            # 将窗体置于前台
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
            
            # 再次尝试设置前台（有时需要多次调用）
            win32gui.SetForegroundWindow(hwnd)
            
            return True
            
        except Exception:
            return False
    
    def is_window_valid(self, hwnd: int) -> bool:
        """
        检查窗体是否仍然有效
        
        Args:
            hwnd: 窗体句柄
            
        Returns:
            窗体是否有效
        """
        try:
            return win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
        except:
            return False
    
    def get_window_info(self, hwnd: int) -> Optional[Dict]:
        """
        获取指定窗体的详细信息
        
        Args:
            hwnd: 窗体句柄
            
        Returns:
            窗体信息字典或None
        """
        if not self.is_window_valid(hwnd):
            return None
            
        try:
            title = win32gui.GetWindowText(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            
            return {
                'hwnd': hwnd,
                'title': title,
                'rect': rect,
                'class_name': class_name,
                'size': (rect[2] - rect[0], rect[3] - rect[1])
            }
        except Exception:
            return None

