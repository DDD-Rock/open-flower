"""
市场按钮检测模块

使用 OpenCV 进行图像模板匹配，在游戏窗口中查找按钮
需要提前截取"自由市场"按钮的截图保存为模板图片
"""

import os
import cv2
import numpy as np
import time
import win32gui
import mss
from typing import Optional, Tuple

import sys


def _get_base_dir():
    """获取项目根目录（兼容PyInstaller打包）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后
        return sys._MEIPASS
    else:
        # 源码运行
        return os.path.dirname(os.path.dirname(__file__))


class MarketButtonDetector:
    """市场按钮检测器（在游戏窗口中模板匹配）"""
    
    # 模板图片路径（兼容PyInstaller打包）
    TEMPLATE_DIR = os.path.join(_get_base_dir(), "templates", "market")
    MARKET_BTN_TEMPLATE = os.path.join(TEMPLATE_DIR, "market_btn.png")
    MARKET_LOGO_TEMPLATE = os.path.join(TEMPLATE_DIR, "market_logo.png")  # 市场Logo模板
    MARKET_MINIMAP_TEMPLATE = os.path.join(_get_base_dir(), "templates", "minimap", "market_minimap.png")
    
    def __init__(self, hwnd: int = None, confidence: float = 0.4):
        """
        初始化检测器
        
        Args:
            hwnd: 游戏窗口句柄
            confidence: 匹配置信度 (0.0-1.0)，越高越严格
        """
        self.hwnd = hwnd
        self.confidence = confidence
    
    def set_window_handle(self, hwnd: int):
        """设置游戏窗口句柄"""
        self.hwnd = hwnd
    
    def is_template_exists(self) -> bool:
        """检查模板图片是否存在"""
        return os.path.exists(self.MARKET_BTN_TEMPLATE)
    
    def capture_game_screen(self) -> Optional[np.ndarray]:
        """截取游戏窗口画面"""
        if not self.hwnd:
            print("❌ 未设置游戏窗口句柄")
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
                # 转换 BGRA -> BGR
                return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                
        except Exception as e:
            print(f"❌ 截取游戏画面失败: {e}")
            return None
    
    def find_market_button_in_game(self) -> Optional[Tuple[int, int]]:
        """
        在游戏画面中查找市场按钮（多尺度匹配，只搜索底部区域）
        
        Returns:
            (x, y) 按钮中心在游戏窗口内的坐标，或 None
        """
        if not self.is_template_exists():
            print(f"❌ 模板图片不存在: {self.MARKET_BTN_TEMPLATE}")
            return None
        
        # 截取游戏画面
        screen = self.capture_game_screen()
        if screen is None:
            return None
        
        # 加载模板
        template = cv2.imread(self.MARKET_BTN_TEMPLATE)
        if template is None:
            print(f"❌ 无法加载模板图片")
            return None
        
        # 只在底部 15% 区域搜索
        screen_height = screen.shape[0]
        bottom_region_start = int(screen_height * 0.85)
        bottom_region = screen[bottom_region_start:, :]
        
        # 多尺度匹配（应对窗口拉伸）
        scales = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]
        best_match = None
        best_val = 0
        best_scale = 1.0
        best_loc = None
        
        h_orig, w_orig = template.shape[:2]
        
        for scale in scales:
            # 缩放模板
            new_w = int(w_orig * scale)
            new_h = int(h_orig * scale)
            if new_w < 10 or new_h < 10:
                continue
            if new_w > bottom_region.shape[1] or new_h > bottom_region.shape[0]:
                continue
            
            scaled_template = cv2.resize(template, (new_w, new_h))
            
            # 模板匹配
            result = cv2.matchTemplate(bottom_region, scaled_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            if max_val > best_val:
                best_val = max_val
                best_scale = scale
                best_loc = max_loc
                best_match = (new_w, new_h)
        
        print(f"最佳匹配: scale={best_scale:.1f}, confidence={best_val:.3f}")
        
        if best_val >= self.confidence and best_match:
            w, h = best_match
            center_x = best_loc[0] + w // 2
            center_y = bottom_region_start + best_loc[1] + h // 2
            return (center_x, center_y)
        
        return None
    
    def find_market_button(self) -> Optional[Tuple[int, int]]:
        """
        查找市场按钮并返回屏幕绝对坐标
        
        Returns:
            (x, y) 屏幕绝对坐标，或 None
        """
        pos = self.find_market_button_in_game()
        if pos is None:
            return None
        
        # 转换为屏幕绝对坐标
        client_pos = win32gui.ClientToScreen(self.hwnd, (0, 0))
        screen_x = client_pos[0] + pos[0]
        screen_y = client_pos[1] + pos[1]
        
        return (screen_x, screen_y)
    
    def capture_minimap_region(self) -> Optional[np.ndarray]:
        """截取小地图区域（左上角 200x150）"""
        if not self.hwnd:
            return None
        
        try:
            client_pos = win32gui.ClientToScreen(self.hwnd, (0, 0))
            
            # 小地图在左上角，取前200x150范围
            monitor = {
                "top": client_pos[1],
                "left": client_pos[0],
                "width": 200,
                "height": 150
            }
            
            with mss.mss() as sct:
                screenshot = sct.grab(monitor)
                img = np.array(screenshot)
                return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                
        except Exception as e:
            print(f"❌ 截取小地图失败: {e}")
            return None
    
    def is_market_logo_visible(self, confidence: float = 0.5) -> bool:
        """
        检测小地图左上角是否有市场Logo
        
        活动期间屏幕顶部会出现滚动公告条，覆盖在画面之上，
        会挡住market_logo的上半部分，导致完整模板匹配失败。
        解决方案：先用完整模板匹配，失败后裁剪模板下半部分再尝试。
        
        Args:
            confidence: 匹配置信度阈值
            
        Returns:
            是否检测到市场Logo
        """
        # 检查模板是否存在
        if not os.path.exists(self.MARKET_LOGO_TEMPLATE):
            print(f"⚠️ 市场Logo模板不存在: {self.MARKET_LOGO_TEMPLATE}")
            return False
        
        # 截取小地图区域
        minimap = self.capture_minimap_region()
        if minimap is None:
            return False
        
        # 加载市场Logo模板
        template = cv2.imread(self.MARKET_LOGO_TEMPLATE)
        if template is None:
            print(f"❌ 无法加载市场Logo模板")
            return False
        
        # 第一次搜索：使用完整模板
        best_val = self._match_logo_multiscale(minimap, template)
        
        if best_val >= confidence:
            print(f"市场Logo匹配: confidence={best_val:.3f} (阈值={confidence})")
            return True
        
        # 第二次搜索：使用模板的下半部分（应对活动公告条遮挡Logo上半部分）
        h_orig = template.shape[0]
        crop_top = int(h_orig * 0.4)  # 裁掉上方40%，保留下方60%
        template_bottom = template[crop_top:, :]
        
        best_val_bottom = self._match_logo_multiscale(minimap, template_bottom)
        final_val = max(best_val, best_val_bottom)
        
        print(f"市场Logo匹配: confidence={final_val:.3f} (含局部匹配, 阈值={confidence})")
        return final_val >= confidence
    
    def _match_logo_multiscale(self, region: np.ndarray, template: np.ndarray) -> float:
        """
        多尺度模板匹配（提取公共逻辑）
        
        Args:
            region: 搜索区域图像
            template: 模板图片（完整或裁剪后的）
            
        Returns:
            最佳匹配置信度
        """
        scales = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        best_val = 0.0
        
        h_orig, w_orig = template.shape[:2]
        
        for scale in scales:
            new_w = int(w_orig * scale)
            new_h = int(h_orig * scale)
            
            if new_w < 10 or new_h < 10:
                continue
            if new_w > region.shape[1] or new_h > region.shape[0]:
                continue
            
            scaled_template = cv2.resize(template, (new_w, new_h))
            result = cv2.matchTemplate(region, scaled_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            
            if max_val > best_val:
                best_val = max_val
        
        return best_val
    
    def is_in_market_by_minimap(self, confidence: float = 0.5) -> bool:
        """
        通过小地图模板匹配判断是否在市场
        
        Args:
            confidence: 匹配置信度阈值
            
        Returns:
            是否在市场中
        """
        # 检查模板是否存在
        if not os.path.exists(self.MARKET_MINIMAP_TEMPLATE):
            print(f"⚠️ 市场小地图模板不存在: {self.MARKET_MINIMAP_TEMPLATE}")
            return False
        
        # 截取小地图区域
        minimap = self.capture_minimap_region()
        if minimap is None:
            return False
        
        # 加载市场小地图模板
        template = cv2.imread(self.MARKET_MINIMAP_TEMPLATE)
        if template is None:
            return False
        
        # 多尺度匹配（应对分辨率变化）
        scales = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        best_val = 0
        
        h_orig, w_orig = template.shape[:2]
        
        for scale in scales:
            new_w = int(w_orig * scale)
            new_h = int(h_orig * scale)
            
            if new_w < 10 or new_h < 10:
                continue
            if new_w > minimap.shape[1] or new_h > minimap.shape[0]:
                continue
            
            scaled_template = cv2.resize(template, (new_w, new_h))
            result = cv2.matchTemplate(minimap, scaled_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            
            if max_val > best_val:
                best_val = max_val
        
        print(f"小地图市场匹配: confidence={best_val:.3f} (阈值={confidence})")
        return best_val >= confidence

    def debug_find_market_button(self) -> Tuple[bool, str]:
        """
        调试方法：查找市场按钮并保存标记截图（多尺度匹配）
        
        Returns:
            (success, message)
        """
        if not self.is_template_exists():
            return False, f"模板图片不存在！请截取'自由市场'按钮保存到:\n{self.MARKET_BTN_TEMPLATE}"
        
        if not self.hwnd:
            return False, "未设置游戏窗口句柄"
        
        # 截取游戏画面
        screen = self.capture_game_screen()
        if screen is None:
            return False, "截取游戏画面失败"
        
        # 加载模板
        template = cv2.imread(self.MARKET_BTN_TEMPLATE)
        if template is None:
            return False, "无法加载模板图片"
        
        # 只在底部 15% 区域搜索
        screen_height = screen.shape[0]
        bottom_region_start = int(screen_height * 0.85)
        bottom_region = screen[bottom_region_start:, :]
        
        # 多尺度匹配
        scales = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]
        best_match = None
        best_val = 0
        best_scale = 1.0
        best_loc = None
        
        h_orig, w_orig = template.shape[:2]
        
        for scale in scales:
            new_w = int(w_orig * scale)
            new_h = int(h_orig * scale)
            if new_w < 10 or new_h < 10:
                continue
            if new_w > bottom_region.shape[1] or new_h > bottom_region.shape[0]:
                continue
            
            scaled_template = cv2.resize(template, (new_w, new_h))
            result = cv2.matchTemplate(bottom_region, scaled_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            if max_val > best_val:
                best_val = max_val
                best_scale = scale
                best_loc = max_loc
                best_match = (new_w, new_h)
        
        timestamp = int(time.time())
        
        # 在完整截图上画搜索区域边界
        cv2.line(screen, (0, bottom_region_start), (screen.shape[1], bottom_region_start), (255, 255, 0), 2)
        
        if best_val >= self.confidence and best_match:
            w, h = best_match
            top_left = (best_loc[0], bottom_region_start + best_loc[1])
            bottom_right = (top_left[0] + w, top_left[1] + h)
            
            # 画红色框
            cv2.rectangle(screen, top_left, bottom_right, (0, 0, 255), 3)
            
            # 添加信息
            text = f"Scale: {best_scale:.1f}x, Conf: {best_val:.3f}"
            cv2.putText(screen, text, (top_left[0], top_left[1] - 10), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            
            save_path = os.path.join(self.SCREENSHOTS_DIR, f"market_btn_found_{timestamp}.png")
            cv2.imwrite(save_path, screen)
            
            center_x = top_left[0] + w // 2
            center_y = top_left[1] + h // 2
            return True, f"找到市场按钮! 位置:({center_x},{center_y}) 缩放:{best_scale:.1f}x 置信度:{best_val:.3f}\n截图: {save_path}"
        else:
            text = f"Not found (best: scale={best_scale:.1f}x, conf={best_val:.3f})"
            cv2.putText(screen, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            
            save_path = os.path.join(self.SCREENSHOTS_DIR, f"market_btn_notfound_{timestamp}.png")
            cv2.imwrite(save_path, screen)
            
            return False, f"未找到市场按钮 (最佳: scale={best_scale:.1f}x, conf={best_val:.3f})\n截图: {save_path}"


# 兼容旧接口
def find_market_btn_center(hwnd: int, confidence: float = 0.4) -> Optional[Tuple[int, int]]:
    """查找市场按钮中心位置（屏幕绝对坐标）"""
    detector = MarketButtonDetector(hwnd=hwnd, confidence=confidence)
    return detector.find_market_button()
