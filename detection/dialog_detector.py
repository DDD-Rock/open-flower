"""
游戏内对话框检测与关闭

功能：
检测游戏画面中是否出现 "確定" 按钮的对话框，
如果出现，自动点击确定按钮关闭对话框。

使用 OpenCV 模板匹配，复用 MarketButtonDetector 相同的模式。
"""

import os
import sys
import cv2
import numpy as np
import win32gui
import mss
from typing import Optional, Tuple


def _get_base_dir():
    """获取项目根目录（兼容PyInstaller打包）"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    else:
        return os.path.dirname(os.path.dirname(__file__))


class DialogDetector:
    """游戏内对话框检测器"""
    
    TEMPLATE_DIR = os.path.join(_get_base_dir(), "templates", "dialog")
    CONFIRM_BTN_TEMPLATE = os.path.join(TEMPLATE_DIR, "confirm_btn.png")
    
    def __init__(self, hwnd: int = None, confidence: float = 0.5):
        """
        Args:
            hwnd: 游戏窗口句柄
            confidence: 匹配置信度阈值 (0.0-1.0)
        """
        self.hwnd = hwnd
        self.confidence = confidence
    
    def set_window_handle(self, hwnd: int):
        self.hwnd = hwnd
    
    def capture_game_screen(self) -> Optional[np.ndarray]:
        """截取游戏窗口画面"""
        if not self.hwnd:
            return None
        try:
            rect = win32gui.GetClientRect(self.hwnd)
            client_pos = win32gui.ClientToScreen(self.hwnd, (0, 0))
            monitor = {
                "top": client_pos[1],
                "left": client_pos[0],
                "width": rect[2],
                "height": rect[3]
            }
            with mss.mss() as sct:
                screenshot = sct.grab(monitor)
                img = np.array(screenshot)
                return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        except Exception as e:
            print(f"截取游戏画面失败: {e}")
            return None
    
    def find_confirm_button(self) -> Optional[Tuple[int, int]]:
        """
        在游戏画面中查找 "確定" 按钮
        
        Returns:
            (screen_x, screen_y) 屏幕绝对坐标，或 None
        """
        if not os.path.exists(self.CONFIRM_BTN_TEMPLATE):
            print(f"❌ 确定按钮模板不存在: {self.CONFIRM_BTN_TEMPLATE}")
            return None
        
        screen = self.capture_game_screen()
        if screen is None:
            return None
        
        template = cv2.imread(self.CONFIRM_BTN_TEMPLATE)
        if template is None:
            print("❌ 无法加载确定按钮模板")
            return None
        
        # 在中间偏下区域搜索（对话框通常在画面中央）
        screen_height = screen.shape[0]
        search_start = int(screen_height * 0.3)
        search_region = screen[search_start:, :]
        
        # 多尺度匹配
        scales = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]
        best_val = 0
        best_scale = 1.0
        best_loc = None
        best_size = None
        
        h_orig, w_orig = template.shape[:2]
        
        for scale in scales:
            new_w = int(w_orig * scale)
            new_h = int(h_orig * scale)
            if new_w < 10 or new_h < 10:
                continue
            if new_w > search_region.shape[1] or new_h > search_region.shape[0]:
                continue
            
            scaled = cv2.resize(template, (new_w, new_h))
            result = cv2.matchTemplate(search_region, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            if max_val > best_val:
                best_val = max_val
                best_scale = scale
                best_loc = max_loc
                best_size = (new_w, new_h)
        
        print(f"确定按钮匹配: scale={best_scale:.1f}, confidence={best_val:.3f}")
        
        if best_val >= self.confidence and best_size:
            w, h = best_size
            # 在游戏窗口内的坐标
            game_x = best_loc[0] + w // 2
            game_y = search_start + best_loc[1] + h // 2
            
            # 转换为屏幕绝对坐标
            client_pos = win32gui.ClientToScreen(self.hwnd, (0, 0))
            screen_x = client_pos[0] + game_x
            screen_y = client_pos[1] + game_y
            
            return (screen_x, screen_y)
        
        return None
    
    def find_and_click_confirm(self, human_input) -> bool:
        """
        检测并点击確定按钮
        
        Args:
            human_input: HumanInput 实例用于拟人化点击
            
        Returns:
            是否找到并点击了按钮
        """
        pos = self.find_confirm_button()
        if pos:
            human_input.click_at(pos[0], pos[1], offset_range=5)
            return True
        return False
