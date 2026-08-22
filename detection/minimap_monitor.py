
import cv2
import numpy as np
import mss
import os
import threading
import time
import win32gui
from typing import Optional, Tuple

from detection.minimap_region_detector import detect_minimap_content_region

class MinimapMonitor:
    """
    小地图监控与定位类（简化版）
    
    功能：
    1. 自动检测小地图深色区域边界
    2. 通过黄点颜色检测玩家位置
    
    注意：mss 不线程安全，高频调用时在所在线程显式开启复用会话。
    """
    
    def __init__(self):
        self.hwnd = 0
        self.last_player_detection_summary = "尚未执行玩家黄点检测"
        self.last_detection_summary = "尚未执行小地图检测"
        
        # 小地图区域配置（相对于游戏窗口客户区）
        # (x, y, width, height) - None 表示未配置
        self.minimap_region = None
        self._capture_local = threading.local()

    def start_capture(self):
        """在当前线程开启可复用的 MSS 截图会话。"""
        capture = getattr(self._capture_local, "capture", None)
        if capture is None:
            capture = mss.mss()
            self._capture_local.capture = capture
        return capture

    def _grab(self, region):
        """截取区域；显式开启会话时复用 MSS，否则保持原有的单次截图行为。"""
        capture = getattr(self._capture_local, "capture", None)
        if capture is not None:
            return np.array(capture.grab(region))
        with mss.mss() as one_shot_capture:
            return np.array(one_shot_capture.grab(region))

    def close_capture(self):
        """释放当前线程的截图资源。"""
        capture = getattr(self._capture_local, "capture", None)
        if capture is None:
            return
        try:
            capture.close()
        finally:
            self._capture_local.capture = None

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
            
            # 与 Mac 版本一致：优先识别左上角稳定的浅色外框，再裁掉地图
            # 名称区域和外框。地图本身可能很亮（例如自由市场），不能再把
            # “最大深色矩形”作为首选依据。
            full_screen = self.capture_game_screen()
            if full_screen is not None and search_region is None:
                frame_region = detect_minimap_content_region(full_screen)
                if frame_region is not None:
                    final_x, final_y, width, height = frame_region
                    self.set_minimap_region(final_x, final_y, width, height)
                    self.last_detection_summary = (
                        f"白框定位成功: x={final_x}, y={final_y}, "
                        f"w={width}, h={height}"
                    )
                    print(f"✅ {self.last_detection_summary}")
                    return frame_region

            # 白框识别失败时保留旧版深色区域后备。搜索范围增大到与 Mac
            # 版本相同的动态左上区域，避免高 DPI 或宽窗口截断小地图。
            if search_region is None:
                dynamic_search_size = min(640, max(480, client_width // 4))
                search_w = min(dynamic_search_size, client_width)
                search_h = min(max(420, dynamic_search_size), client_height)
                search_region = (0, 0, search_w, search_h)
            
            sx, sy, sw, sh = search_region
            
            # 白框检测与深色后备必须分析同一帧，否则 UI 动画期间可能前一帧
            # 判定失败、后一帧却裁到另一个状态的小地图。
            if full_screen is not None:
                screenshot = full_screen[sy : sy + sh, sx : sx + sw].copy()
            else:
                region = {
                    "top": client_y + sy,
                    "left": client_x + sx,
                    "width": sw,
                    "height": sh
                }
                screenshot = self._grab(region)
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
                self.last_detection_summary = "白框未匹配，深色后备未找到轮廓"
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
                
                if (
                    rectangularity > 0.55
                    and 0.5 < aspect_ratio < 4.0
                    and w >= 60
                    and h >= 40
                    and w <= 420
                    and h <= 320
                ):
                    # 同等面积时优先靠近游戏客户区左上角的候选，避免把
                    # 聊天框或其它大块暗色 UI 当成小地图。
                    score = area - (x + y) * 2
                    if score > best_area:
                        best_area = score
                        best_contour = contour
            
            if best_contour is None:
                self.last_detection_summary = "白框未匹配，深色后备无合格候选"
                print("⚠️ 未找到符合条件的深色区域")
                return None
            
            # 6. 获取最佳轮廓的外接矩形
            x, y, w, h = cv2.boundingRect(best_contour)
            
            # 坐标转换：从搜索区域坐标转为窗口坐标
            final_x = sx + x
            final_y = sy + y
            
            # 自动设置小地图区域
            self.set_minimap_region(final_x, final_y, w, h)
            self.last_detection_summary = (
                f"使用深色后备定位: x={final_x}, y={final_y}, w={w}, h={h}"
            )
            
            print(f"✅ 自动检测到小地图区域: ({final_x}, {final_y}, {w}, {h})")
            return (final_x, final_y, w, h)
            
        except Exception as e:
            self.last_detection_summary = f"小地图检测异常: {e}"
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
            screenshot = self._grab(monitor)
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
        # 玩家黄点会闪烁。若当前帧只有大量暗黄色地图装饰，短暂重采，
        # 等待纯黄色核心出现；正常首帧命中时不会增加延迟。
        for attempt in range(3):
            minimap = self.capture_minimap()
            if minimap is None:
                self.last_player_detection_summary = "截取小地图失败"
                return None

            position, summary = self.find_player_position_in_image(minimap)
            self.last_player_detection_summary = summary
            if position is not None:
                return position
            if attempt < 2:
                time.sleep(0.04)
        return None

    def find_player_position_once(self) -> Optional[Tuple[int, int]]:
        """只采集和分析一帧，供固定帧率的导航循环使用。"""
        minimap = self.capture_minimap()
        if minimap is None:
            self.last_player_detection_summary = "截取小地图失败"
            return None
        position, summary = self.find_player_position_in_image(minimap)
        self.last_player_detection_summary = summary
        return position

    @staticmethod
    def find_player_position_in_image(
        minimap: np.ndarray,
    ) -> Tuple[Optional[Tuple[int, int]], str]:
        """在已截取的小地图中查找黄点，便于离线测试和调节阈值。"""
        if minimap is None or minimap.ndim != 3 or minimap.size == 0:
            return None, "小地图图像无效"

        # 不再只接受接近 (0, 255, 255) 的纯黄色。Windows 缩放、录屏色彩
        # 转换和黄点边缘抗锯齿都会明显降低 G/R，但色相和饱和度仍然稳定。
        strict_mask = cv2.inRange(
            minimap,
            np.array([0, 240, 240], dtype=np.uint8),
            np.array([30, 255, 255], dtype=np.uint8),
        )
        hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
        hsv_mask = cv2.inRange(
            hsv,
            np.array([18, 135, 165], dtype=np.uint8),
            np.array([38, 255, 255], dtype=np.uint8),
        )

        blue, green, red = cv2.split(minimap)
        channel_mask = (
            (red >= 170)
            & (green >= 165)
            & (blue <= 115)
            & ((red.astype(np.int16) - blue.astype(np.int16)) >= 75)
            & ((green.astype(np.int16) - blue.astype(np.int16)) >= 70)
            & (np.abs(red.astype(np.int16) - green.astype(np.int16)) <= 75)
        ).astype(np.uint8) * 255
        tolerant_mask = cv2.bitwise_or(hsv_mask, channel_mask)

        candidates = []
        count = 1
        centroids = None
        source = "宽容黄色"
        # 真实玩家标记包含纯黄色核心；自由市场建筑中却有大量暗黄色装饰。
        # 优先使用纯黄色核心，只有整帧不存在时才启用抗锯齿宽容范围。
        for source, mask in (
            ("纯黄色", strict_mask),
            ("宽容黄色", tolerant_mask),
        ):
            count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
            candidates = []
            for index in range(1, count):
                x, y, w, h, pixel_area = stats[index]
                # 2×2 的零散高光在自由市场小地图里很多，不是玩家标记。
                if pixel_area < 6 or pixel_area > 180:
                    continue
                if w < 2 or h < 2 or w > 18 or h > 18:
                    continue
                aspect = w / h
                fill_ratio = pixel_area / (w * h)
                minimum_fill = 0.30 if source == "纯黄色" else 0.35
                if not 0.5 <= aspect <= 2.0 or fill_ratio < minimum_fill:
                    continue

                square_penalty = abs(np.log(aspect))
                size_penalty = abs(pixel_area - 40) / 40
                score = (
                    fill_ratio * 8
                    + pixel_area / 20
                    - square_penalty * 3
                    - size_penalty
                )
                candidates.append((score, index, w, h, pixel_area))
            if candidates:
                break

        if not candidates or centroids is None:
            raw_count = max(0, count - 1)
            return None, f"未检测到玩家黄点，黄色连通域={raw_count}，有效候选=0"

        if source == "宽容黄色" and len(candidates) > 5:
            return (
                None,
                f"宽容黄色候选过多={len(candidates)}，等待玩家黄点亮起",
            )

        _, index, w, h, pixel_area = max(candidates, key=lambda item: item[0])
        cx, cy = centroids[index]
        summary = (
            f"玩家黄点 x={cx:.1f}, y={cy:.1f}，像素={pixel_area}，尺寸={w}×{h}，"
            f"候选数={len(candidates)}，来源={source}"
        )
        return (int(round(cx)), int(round(cy))), summary

    @staticmethod
    def _compact_marker_points(mask: np.ndarray) -> list:
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        points = []
        for index in range(1, count):
            _, _, width, height, area = stats[index]
            if not 2 <= area <= 120 or not 2 <= width <= 16 or not 2 <= height <= 16:
                continue
            aspect = width / height
            fill_ratio = area / (width * height)
            if not 0.5 <= aspect <= 2.0 or fill_ratio < 0.4:
                continue
            x, y = centroids[index]
            points.append((int(round(x)), int(round(y))))
        return sorted(points)

    @staticmethod
    def find_teammate_positions_in_image(minimap: np.ndarray) -> list:
        """识别一个或多个队友橙点，阈值与 macOS 监控模式保持一致。"""
        if minimap is None or minimap.ndim != 3 or minimap.size == 0:
            return []
        hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
        blue, green, red = [item.astype(np.int16) for item in cv2.split(minimap)]
        hue, saturation, value = cv2.split(hsv)
        mask = (
            (hue > 12)
            & (hue < 20)
            & (saturation >= 90)
            & (value >= 130)
            & (red >= 160)
            & (green >= 80)
            & (red >= green + 30)
            & (green >= blue + 30)
        ).astype(np.uint8) * 255
        return MinimapMonitor._compact_marker_points(mask)

    @staticmethod
    def count_player_marker_candidates_in_image(minimap: np.ndarray) -> int:
        """统计有效黄点候选，阈值与玩家定位保持一致。"""
        if minimap is None or minimap.ndim != 3 or minimap.size == 0:
            return 0
        strict_mask = cv2.inRange(
            minimap,
            np.array([0, 240, 240], dtype=np.uint8),
            np.array([30, 255, 255], dtype=np.uint8),
        )
        hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
        hsv_mask = cv2.inRange(
            hsv,
            np.array([18, 135, 165], dtype=np.uint8),
            np.array([38, 255, 255], dtype=np.uint8),
        )
        blue, green, red = cv2.split(minimap)
        channel_mask = (
            (red >= 170) & (green >= 165) & (blue <= 115)
            & ((red.astype(np.int16) - blue.astype(np.int16)) >= 75)
            & ((green.astype(np.int16) - blue.astype(np.int16)) >= 70)
            & (np.abs(red.astype(np.int16) - green.astype(np.int16)) <= 75)
        ).astype(np.uint8) * 255
        tolerant_mask = cv2.bitwise_or(hsv_mask, channel_mask)
        for source, mask in (("strict", strict_mask), ("tolerant", tolerant_mask)):
            count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
            candidates = 0
            for index in range(1, count):
                _, _, width, height, area = stats[index]
                if area < 6 or area > 180 or width < 2 or height < 2 or width > 18 or height > 18:
                    continue
                aspect = width / height
                fill = area / (width * height)
                if 0.5 <= aspect <= 2.0 and fill >= (0.30 if source == "strict" else 0.35):
                    candidates += 1
            if candidates:
                return 0 if source == "tolerant" and candidates > 5 else candidates
        return 0

    @staticmethod
    def find_other_player_positions_in_image(minimap: np.ndarray) -> list:
        """识别一个或多个其他玩家红点，过滤细线和大块红色 UI。"""
        if minimap is None or minimap.ndim != 3 or minimap.size == 0:
            return []
        hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
        blue, green, red = [item.astype(np.int16) for item in cv2.split(minimap)]
        hue, saturation, value = cv2.split(hsv)
        mask = (
            ((hue <= 12) | (hue >= 168))
            & (saturation >= 90)
            & (value >= 110)
            & (red >= 130)
            & (red >= green + 40)
            & (red >= blue + 40)
        ).astype(np.uint8) * 255
        return MinimapMonitor._compact_marker_points(mask)

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
            
            screenshot = self._grab(monitor)
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
