
import cv2
import numpy as np
import mss
import os
import time
import win32gui
from typing import Optional, Tuple

class MinimapMonitor:
    """
    小地图监控与定位类（简化版）
    
    功能：
    1. 自动检测小地图深色区域边界
    2. 通过黄点颜色检测玩家位置
    
    注意：mss 不线程安全，每次截图时创建新实例
    """
    
    def __init__(self):
        self.hwnd = 0
        
        # 小地图区域配置（相对于游戏窗口客户区）
        # (x, y, width, height) - None 表示未配置
        self.minimap_region = None

    def set_window_handle(self, hwnd: int):
        """设置游戏窗口句柄"""
        self.hwnd = hwnd
    
    def set_minimap_region(self, x: int, y: int, width: int, height: int):
        """
        手动设置小地图区域（相对于游戏窗口客户区）
        """
        self.minimap_region = (x, y, width, height)
        print(f"📍 小地图区域已设置: x={x}, y={y}, w={width}, h={height}")
    
    def get_minimap_size(self) -> Optional[Tuple[int, int]]:
        """获取当前小地图的宽高"""
        if self.minimap_region:
            return (self.minimap_region[2], self.minimap_region[3])
        return None
    
    def auto_detect_dark_region(self, search_region: Tuple[int, int, int, int] = None,
                                  dark_threshold: int = 100,
                                  min_area: int = 3000) -> Optional[Tuple[int, int, int, int]]:
        """
        通过连通域分析自动检测小地图的深色背景区域
        
        原理：小地图是深色背景，与周围UI形成明显对比
        通过二值化找到最大的深色连通区域
        
        Args:
            search_region: 搜索区域 (x, y, width, height)，默认为左上角 400x400
            dark_threshold: 深色阈值（低于此值视为深色），默认100
            min_area: 最小面积阈值，过滤小噪点
            
        Returns:
            (x, y, width, height) 或 None
        """
        if not self.hwnd:
            print("❌ 窗口句柄未设置")
            return None
            
        try:
            # 获取窗口客户区信息
            client_rect = win32gui.GetClientRect(self.hwnd)
            client_width = client_rect[2] - client_rect[0]
            client_height = client_rect[3] - client_rect[1]
            client_pos = win32gui.ClientToScreen(self.hwnd, (0, 0))
            client_x, client_y = client_pos
            
            # 默认搜索左上角 400x400 区域
            if search_region is None:
                search_w = min(400, client_width)
                search_h = min(400, client_height)
                search_region = (0, 0, search_w, search_h)
            
            sx, sy, sw, sh = search_region
            
            # 使用MSS截取搜索区域（每次创建新实例，线程安全）
            region = {
                "top": client_y + sy,
                "left": client_x + sx,
                "width": sw,
                "height": sh
            }
            
            with mss.mss() as sct:
                sct_img = sct.grab(region)
                screenshot = np.array(sct_img)
            screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
            
            # 1. 转为灰度图
            gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
            
            # 2. 二值化：深色区域变白，其他变黑
            _, binary = cv2.threshold(gray, dark_threshold, 255, cv2.THRESH_BINARY_INV)
            
            # 3. 形态学操作：去除噪点，填充小孔洞
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
            
            # 4. 查找轮廓
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                print("⚠️ 未找到任何轮廓")
                return None
            
            # 5. 筛选轮廓
            best_contour = None
            best_area = 0
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < min_area:
                    continue
                
                x, y, w, h = cv2.boundingRect(contour)
                rect_area = w * h
                rectangularity = area / rect_area if rect_area > 0 else 0
                aspect_ratio = w / h if h > 0 else 0
                
                if rectangularity > 0.6 and 0.5 < aspect_ratio < 3.0:
                    if area > best_area:
                        best_area = area
                        best_contour = contour
            
            if best_contour is None:
                print("⚠️ 未找到符合条件的深色区域")
                return None
            
            # 6. 获取最佳轮廓的外接矩形
            x, y, w, h = cv2.boundingRect(best_contour)
            
            # 坐标转换：从搜索区域坐标转为窗口坐标
            final_x = sx + x
            final_y = sy + y
            
            # 自动设置小地图区域
            self.set_minimap_region(final_x, final_y, w, h)
            
            print(f"✅ 自动检测到小地图区域: ({final_x}, {final_y}, {w}, {h})")
            return (final_x, final_y, w, h)
            
        except Exception as e:
            print(f"❌ 深色区域检测失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def capture_minimap(self) -> Optional[np.ndarray]:
        """
        截取当前游戏窗口的小地图区域
        
        如果已配置 minimap_region，使用精确区域截取
        否则使用默认的左上角 300x200 区域
        """
        if not self.hwnd:
            return None
        try:
            client_pos = win32gui.ClientToScreen(self.hwnd, (0, 0))
            client_x, client_y = client_pos
            
            if self.minimap_region:
                x, y, width, height = self.minimap_region
                monitor = {
                    "top": client_y + y,
                    "left": client_x + x,
                    "width": width,
                    "height": height
                }
            else:
                monitor = {
                    "top": client_y,
                    "left": client_x,
                    "width": 300,
                    "height": 200
                }
            # 使用MSS截取（每次创建新实例，线程安全）
            with mss.mss() as sct:
                screenshot = np.array(sct.grab(monitor))
            return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
        except Exception as e:
            print(f"截图失败: {e}")
            return None

    def find_player_position(self) -> Optional[Tuple[int, int]]:
        """
        在小地图上寻找玩家黄点位置
        
        Returns:
            (x, y) 玩家在小地图中的坐标，或 None
        """
        minimap = self.capture_minimap()
        if minimap is None:
            return None
        
        # 严格的 BGR 黄色范围
        lower_yellow = np.array([0, 240, 240])
        upper_yellow = np.array([30, 255, 255])
        mask = cv2.inRange(minimap, lower_yellow, upper_yellow)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
            
        max_contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(max_contour) < 5:
            return None
            
        M = cv2.moments(max_contour)
        if M["m00"] == 0:
            return None
            
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        return cx, cy

    def find_blue_portal(self, find_leftmost: bool = True) -> Optional[Tuple[int, int]]:
        """
        在小地图上寻找蓝色传送门位置（使用 HSV 色彩空间）
        
        Args:
            find_leftmost: True 返回最左侧的传送门，False 返回最大的传送门
        
        Returns:
            (x, y) 传送门中心坐标，或 None
        """
        minimap = self.capture_minimap()
        if minimap is None:
            return None
        
        # 转换到 HSV 色彩空间
        hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
        
        # 蓝色范围（HSV格式）- 更可靠的颜色检测
        lower_blue = np.array([90, 100, 100])   # H:90-130 是蓝色范围
        upper_blue = np.array([130, 255, 255])
        
        mask = cv2.inRange(hsv, lower_blue, upper_blue)
        
        # 形态学操作：连接相邻区域，填充小孔洞
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        
        # 过滤轮廓：面积 >= 10，且宽高比合理（传送门通常是竖长方形）
        valid_contours = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 10:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            # 宽高比过滤：允许 0.3 ~ 3.0 的范围
            if h > 0 and 0.3 < w / h < 3.0:
                valid_contours.append(cnt)
        
        if not valid_contours:
            return None
        
        if find_leftmost:
            # 找最左侧的传送门（X坐标最小）
            target_contour = min(valid_contours, key=lambda c: cv2.boundingRect(c)[0])
        else:
            # 找最大的传送门
            target_contour = max(valid_contours, key=cv2.contourArea)
        
        # 计算中心点
        M = cv2.moments(target_contour)
        if M["m00"] == 0:
            return None
            
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        return cx, cy


    def debug_save_minimap(self) -> Tuple[bool, str, str]:
        """
        初始化小地图检测（自动检测区域、查找传送门和玩家位置）
        
        Returns:
            (success, info_message, "")
        """
        # 如果没有配置小地图区域，先尝试自动检测
        if self.minimap_region is None:
            result = self.auto_detect_dark_region()
            if result is None:
                return False, "自动检测小地图区域失败", ""
        
        # 截取小地图验证
        minimap = self.capture_minimap()
        if minimap is None:
            return False, "截取小地图失败", ""
        
        # 查找蓝色传送门
        portal_pos = self.find_blue_portal(find_leftmost=True)
        if portal_pos:
            print(f"✅ 检测到传送门位置: {portal_pos}")
        
        # 查找玩家位置
        player_pos = self.find_player_position()
        if player_pos:
            print(f"✅ 检测到玩家位置: {player_pos}")
        
        return True, "小地图检测成功", ""

    def capture_game_screen(self) -> Optional[np.ndarray]:
        """
        截取整个游戏窗口画面
        
        Returns:
            游戏画面 BGR 图像，或 None
        """
        if not self.hwnd:
            return None
        try:
            # 获取窗口客户区
            client_rect = win32gui.GetClientRect(self.hwnd)
            client_width = client_rect[2] - client_rect[0]
            client_height = client_rect[3] - client_rect[1]
            client_pos = win32gui.ClientToScreen(self.hwnd, (0, 0))
            client_x, client_y = client_pos
            
            monitor = {
                "top": client_y,
                "left": client_x,
                "width": client_width,
                "height": client_height
            }
            
            with mss.mss() as sct:
                screenshot = np.array(sct.grab(monitor))
            return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
        except Exception as e:
            print(f"游戏画面截图失败: {e}")
            return None

    def find_template_on_screen(self, template_path: str, threshold: float = 0.8) -> Optional[Tuple[int, int, int, int]]:
        """
        在游戏画面中查找模板图片位置
        
        Args:
            template_path: 模板图片路径
            threshold: 匹配阈值 (0-1)，越高越严格
            
        Returns:
            (screen_x, screen_y, width, height) 模板在屏幕上的绝对坐标和尺寸，或 None
        """
        # 加载模板
        if not os.path.exists(template_path):
            print(f"❌ 模板图片不存在: {template_path}")
            return None
            
        template = cv2.imread(template_path)
        if template is None:
            print(f"❌ 无法加载模板图片: {template_path}")
            return None
        
        # 截取游戏画面
        screen = self.capture_game_screen()
        if screen is None:
            return None
        
        # 模板匹配
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        if max_val < threshold:
            return None
        
        # 计算屏幕绝对坐标
        client_pos = win32gui.ClientToScreen(self.hwnd, (0, 0))
        template_h, template_w = template.shape[:2]
        
        screen_x = client_pos[0] + max_loc[0]
        screen_y = client_pos[1] + max_loc[1]
        
        return (screen_x, screen_y, template_w, template_h)

    def find_template_center(self, template_path: str, threshold: float = 0.8) -> Optional[Tuple[int, int]]:
        """
        在游戏画面中查找模板图片的中心位置（用于点击）
        
        Returns:
            (center_x, center_y) 模板中心在屏幕上的绝对坐标，或 None
        """
        result = self.find_template_on_screen(template_path, threshold)
        if result is None:
            return None
        
        x, y, w, h = result
        center_x = x + w // 2
        center_y = y + h // 2
        return (center_x, center_y)

    def find_template_multiscale(self, template_path: str, threshold: float = 0.7, 
                                  scales: list = None) -> Optional[Tuple[int, int, int, int, float, float]]:
        """
        多尺度模板匹配（容忍不同分辨率和非等比例拉伸）
        
        Args:
            template_path: 模板图片路径
            threshold: 匹配阈值
            scales: 尝试的缩放比例列表，宽高独立组合
            
        Returns:
            (screen_x, screen_y, width, height, scale_x, scale_y) 或 None
        """
        if scales is None:
            scales = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]
        
        # 加载模板
        if not os.path.exists(template_path):
            print(f"❌ 模板图片不存在: {template_path}")
            return None
            
        template_orig = cv2.imread(template_path)
        if template_orig is None:
            print(f"❌ 无法加载模板图片: {template_path}")
            return None
        
        # 截取游戏画面
        screen = self.capture_game_screen()
        if screen is None:
            return None
        
        best_val = 0
        best_scale_x = 1.0
        best_scale_y = 1.0
        best_loc = None
        best_template = None
        
        orig_h, orig_w = template_orig.shape[:2]
        
        # 尝试不同的宽高缩放比例组合（非等比例）
        for scale_x in scales:
            for scale_y in scales:
                # 缩放模板
                new_w = int(orig_w * scale_x)
                new_h = int(orig_h * scale_y)
                
                # 确保尺寸有效
                if new_w < 10 or new_h < 10:
                    continue
                if new_w > screen.shape[1] or new_h > screen.shape[0]:
                    continue
                
                template = cv2.resize(template_orig, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                
                # 模板匹配
                result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                
                if max_val > best_val:
                    best_val = max_val
                    best_scale_x = scale_x
                    best_scale_y = scale_y
                    best_loc = max_loc
                    best_template = template
        
        print(f"最佳匹配: 相似度={best_val:.3f}, 缩放X={best_scale_x:.2f}, 缩放Y={best_scale_y:.2f}")
        
        if best_val < threshold:
            print(f"未找到匹配（阈值={threshold}）")
            return None
        
        # 计算屏幕绝对坐标
        client_pos = win32gui.ClientToScreen(self.hwnd, (0, 0))
        template_h, template_w = best_template.shape[:2]
        
        screen_x = client_pos[0] + best_loc[0]
        screen_y = client_pos[1] + best_loc[1]
        return (screen_x, screen_y, template_w, template_h, best_scale_x, best_scale_y)

