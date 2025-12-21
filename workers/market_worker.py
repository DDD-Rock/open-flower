
"""
市场处理 Worker

功能：
1. 自动检测小地图区域
2. 识别蓝色传送门和玩家位置
3. 拟人化移动到传送门并进入
"""

import time
import random
import win32gui
from PyQt6.QtCore import QThread, pyqtSignal
from detection.minimap_monitor import MinimapMonitor
from automation.human_input import HumanInput
from utils.logger import Logger


class MarketWorker(QThread):
    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, hwnd):
        super().__init__()
        self.hwnd = hwnd
        self.is_running = True
        self.monitor = MinimapMonitor()
        self.human = HumanInput()
        self.logger = Logger()
        
        # 导航参数
        self.TOLERANCE = 3  # X坐标容差（像素），到达判定
        self.DETECT_INTERVAL = (50, 100)  # 检测间隔（ms），随机化

    def _bring_window_to_front(self) -> bool:
        """将游戏窗口设置为前台"""
        try:
            if win32gui.IsIconic(self.hwnd):
                win32gui.ShowWindow(self.hwnd, 9)  # SW_RESTORE
            win32gui.ShowWindow(self.hwnd, 5)  # SW_SHOW
            win32gui.SetForegroundWindow(self.hwnd)
            win32gui.BringWindowToTop(self.hwnd)
            return True
        except Exception as e:
            self.log_update.emit(f"设置窗口焦点失败: {e}")
            return False

    def run(self):
        try:
            self.log_update.emit("开始市场移动测试...")
            
            # 0. 将游戏窗口设置为前台焦点
            self.log_update.emit("设置游戏窗口为焦点...")
            self._bring_window_to_front()
            time.sleep(0.5)
            
            # 1. 初始化监控器（与测试小地图匹配完全相同的方式）
            self.monitor.set_window_handle(self.hwnd)
            
            # 2. 使用 debug_save_minimap 的方式来初始化（它会自动检测区域）
            self.log_update.emit("正在检测小地图区域（使用debug方法）...")
            success, minimap_path, marked_path = self.monitor.debug_save_minimap()
            
            if not success:
                self.log_update.emit(f"❌ 小地图检测失败: {minimap_path}")
                self.error_signal.emit(minimap_path)
                return
            
            size = self.monitor.get_minimap_size()
            self.log_update.emit(f"✅ 小地图区域: {size[0]}x{size[1]}" if size else "区域检测成功")
            
            # 3. 检测传送门位置
            portal_pos = self.monitor.find_blue_portal(find_leftmost=True)
            if not portal_pos:
                self.log_update.emit("❌ 未检测到蓝色传送门，停止")
                self.error_signal.emit("未检测到蓝色传送门")
                return
            
            portal_x, portal_y = portal_pos
            self.log_update.emit(f"🚪 传送门位置: ({portal_x}, {portal_y})")
            
            # 4. 导航循环 - 移动到传送门
            self.log_update.emit("开始导航到传送门...")
            
            retry_count = 0
            max_retries = 100
            
            while self.is_running and retry_count < max_retries:
                # 检测玩家位置
                player_pos = self.monitor.find_player_position()
                
                if not player_pos:
                    retry_count += 1
                    if retry_count % 10 == 0:
                        self.log_update.emit(f"未检测到玩家位置，重试 {retry_count}/{max_retries}")
                    self._random_sleep(100, 200)
                    continue
                
                player_x, player_y = player_pos
                dx = portal_x - player_x
                
                # 每10次打印一次状态
                if retry_count % 5 == 0:
                    self.log_update.emit(f"玩家: ({player_x}, {player_y}), 距离: {dx}px")
                
                # 判断是否到达目标
                if abs(dx) <= self.TOLERANCE:
                    self.log_update.emit("✅ 已到达传送门位置！")
                    
                    # 停止移动
                    self.human.stop_move()
                    self._random_sleep(100, 200)
                    
                    # 进入传送门
                    self.log_update.emit("正在进入传送门...")
                    self.human.use_portal()
                    
                    self.log_update.emit("✅ 传送完成！")
                    break
                
                # 根据方向移动
                if dx > self.TOLERANCE:
                    self.human.move_right()
                elif dx < -self.TOLERANCE:
                    self.human.move_left()
                
                # 拟人化检测间隔
                self._random_sleep(*self.DETECT_INTERVAL)
                retry_count += 1
            
            if retry_count >= max_retries:
                self.log_update.emit("⚠️ 达到最大尝试次数，停止导航")
            
            self.log_update.emit("市场移动测试完成")
            self.finished_signal.emit()

        except Exception as e:
            self.log_update.emit(f"发生错误: {str(e)}")
            import traceback
            self.log_update.emit(traceback.format_exc())
            self.error_signal.emit(str(e))
        finally:
            self.human.release_all()

    def _random_sleep(self, min_ms: int, max_ms: int):
        """拟人化随机延迟（毫秒）"""
        delay = random.uniform(min_ms, max_ms) / 1000.0
        time.sleep(delay)

    def stop(self):
        self.is_running = False
        self.human.release_all()
        self.wait()
