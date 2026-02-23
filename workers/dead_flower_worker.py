"""
死花模式 Worker

功能：
1. 检测当前位置（市场/刷怪地图）
2. 在市场等待，CD到了出去放技能
3. 放完技能回到市场

使用模板匹配查找"自由市场"按钮
"""

import time
import random
import win32gui
from typing import List, Dict, Optional
from PyQt6.QtCore import QThread, pyqtSignal
from detection.minimap_monitor import MinimapMonitor
from detection.market_button import MarketButtonDetector
from automation.human_input import HumanInput
from models.buff_config import BuffConfig
from workers.skill_worker import (
    PRE_SKILL_MOVE_RIGHT_MIN_MS, PRE_SKILL_MOVE_RIGHT_MAX_MS,
    POST_SKILL_MOVE_LEFT_MIN_MS, POST_SKILL_MOVE_LEFT_MAX_MS
)


class DeadFlowerWorker(QThread):
    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    countdown_update = pyqtSignal(dict)  # buff倒计时更新

    def __init__(self, hwnd: int, buffs: List[BuffConfig]):
        super().__init__()
        self.hwnd = hwnd
        self.buffs = [b for b in buffs if b.enabled and b.key]  # 只保留启用的buff
        self.is_running = True
        self.monitor = MinimapMonitor()
        self.monitor.set_window_handle(hwnd)
        self.market_detector = MarketButtonDetector(hwnd=hwnd, confidence=0.3)
        self.human = HumanInput()
        
        # Buff倒计时跟踪 {key: 下次释放时间戳}
        self.buff_next_cast: Dict[str, float] = {}
        
        # 窗口大小与位置缓存
        self._cached_window_size: Optional[tuple] = None           # (width, height)
        self._cached_market_btn_pos: Optional[tuple] = None        # 屏幕绝对坐标
        self._cached_market_btn_game_pos: Optional[tuple] = None   # 游戏窗口内坐标
        self._cached_portal_pos: Optional[tuple] = None            # 小地图内坐标
        
        # 导航参数
        self.TOLERANCE = 3
        self.DETECT_INTERVAL = (50, 100)
        
        # 时间参数
        self.BATCH_CAST_WINDOW = 10.0  # 10秒内的buff一起放
        self.BLACK_SCREEN_WAIT = 2.5   # 传送黑屏等待时间
        self.SCENE_CHECK_INTERVAL = 3.0  # 场景检测间隔

    def _bring_window_to_front(self) -> bool:
        """将游戏窗口设置为前台"""
        try:
            if win32gui.IsIconic(self.hwnd):
                win32gui.ShowWindow(self.hwnd, 9)
            win32gui.ShowWindow(self.hwnd, 5)
            win32gui.SetForegroundWindow(self.hwnd)
            win32gui.BringWindowToTop(self.hwnd)
            return True
        except Exception as e:
            self.log_update.emit(f"设置窗口焦点失败: {e}")
            return False

    def _interruptible_sleep(self, seconds: float):
        """
        可中断的睡眠 - 每100ms检查一次is_running标志
        这样stop()调用后最多100ms内就能响应
        """
        if seconds <= 0:
            return
        
        interval = 0.1  # 100ms检查间隔
        elapsed = 0.0
        
        while elapsed < seconds and self.is_running:
            sleep_time = min(interval, seconds - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time

    def _random_sleep(self, min_sec: float, max_sec: float):
        """拟人化随机延迟（可中断）"""
        delay = random.uniform(min_sec, max_sec)
        self._interruptible_sleep(delay)

    def _is_market_logo_visible(self) -> bool:
        """检测小地图左上角是否有市场Logo"""
        try:
            result = self.market_detector.is_market_logo_visible()
            return result
        except Exception as e:
            self.log_update.emit(f"市场Logo检测异常: {e}")
            return False

    def _is_in_market(self) -> bool:
        """
        判断是否在市场中
        规则：小地图有市场Logo + 能看到自由市场按钮
        """
        has_logo = self._is_market_logo_visible()
        has_btn = self._is_market_btn_visible()
        is_in = has_logo and has_btn
        self.log_update.emit(f"市场检测: Logo={has_logo}, 按钮={has_btn}, 在市场={is_in}")
        return is_in

    def _is_market_btn_visible(self) -> bool:
        """判断自由市场按钮是否可见（使用缓存或模板匹配）"""
        try:
            pos = self._get_market_button_in_game_pos()
            return pos is not None
        except Exception as e:
            self.log_update.emit(f"检测异常: {e}")
            return False
    
    def _is_in_monster_map(self) -> bool:
        """
        判断是否在怪物地图
        规则：没有市场Logo + 能看到自由市场按钮
        """
        has_logo = self._is_market_logo_visible()
        has_btn = self._is_market_btn_visible()
        is_monster = (not has_logo) and has_btn
        self.log_update.emit(f"怪物地图检测: Logo={has_logo}, 按钮={has_btn}, 怪物地图={is_monster}")
        return is_monster

    def _get_window_size(self) -> Optional[tuple]:
        """获取当前游戏窗口客户区大小"""
        try:
            rect = win32gui.GetClientRect(self.hwnd)
            return (rect[2], rect[3])  # (width, height)
        except Exception as e:
            self.log_update.emit(f"获取窗口大小失败: {e}")
            return None

    def _check_window_size_changed(self) -> bool:
        """
        检查窗口大小是否改变，如果改变则清空所有缓存坐标
        
        Returns:
            True 表示窗口大小已改变且缓存已清空
        """
        current_size = self._get_window_size()
        if current_size is None:
            return False
        
        if self._cached_window_size and current_size != self._cached_window_size:
            self.log_update.emit(
                f"窗口大小已改变: {self._cached_window_size} -> {current_size}，重新检测位置..."
            )
            self._cached_window_size = current_size
            self._cached_market_btn_pos = None
            self._cached_market_btn_game_pos = None
            self._cached_portal_pos = None
            return True
        
        return False

    def _get_market_button_pos(self) -> Optional[tuple]:
        """
        获取自由市场按钮的屏幕绝对坐标（带缓存）
        
        首次调用或窗口大小改变后执行检测，后续直接返回缓存值
        """
        self._check_window_size_changed()
        
        if self._cached_market_btn_pos:
            self.log_update.emit(f"使用缓存的市场按钮位置: {self._cached_market_btn_pos}")
            return self._cached_market_btn_pos
        
        try:
            self.log_update.emit("首次检测自由市场按钮位置...")
            pos = self.market_detector.find_market_button()
            if pos:
                self._cached_market_btn_pos = pos
                self.log_update.emit(f"已缓存市场按钮位置: {pos}")
            return pos
        except Exception as e:
            self.log_update.emit(f"检测市场按钮异常: {e}")
            return None

    def _get_market_button_in_game_pos(self) -> Optional[tuple]:
        """
        获取自由市场按钮在游戏窗口内的坐标（带缓存）
        
        用于状态判断（按钮是否可见）
        """
        self._check_window_size_changed()
        
        if self._cached_market_btn_game_pos:
            return self._cached_market_btn_game_pos
        
        try:
            pos = self.market_detector.find_market_button_in_game()
            if pos:
                self._cached_market_btn_game_pos = pos
                self.log_update.emit(f"已缓存市场按钮游戏窗口坐标: {pos}")
            return pos
        except Exception as e:
            self.log_update.emit(f"检测市场按钮异常: {e}")
            return None

    def _get_portal_pos(self) -> Optional[tuple]:
        """
        获取传送门在小地图中的坐标（带缓存）
        
        首次使用时检测并缓存，后续直接返回
        窗口大小改变时缓存会被清空
        """
        self._check_window_size_changed()
        
        if self._cached_portal_pos:
            self.log_update.emit(f"使用缓存的传送门位置: {self._cached_portal_pos}")
            return self._cached_portal_pos
        
        try:
            self.log_update.emit("首次检测传送门位置...")
            pos = self.monitor.find_blue_portal(find_leftmost=True)
            if pos:
                self._cached_portal_pos = pos
                self.log_update.emit(f"已缓存传送门位置: {pos}")
            return pos
        except Exception as e:
            self.log_update.emit(f"检测传送门异常: {e}")
            return None

    def _get_buffs_to_cast(self, include_upcoming: bool = True) -> List[BuffConfig]:
        """
        获取当前需要释放的buff列表
        
        Args:
            include_upcoming: 是否包含10秒内即将需要释放的buff
        """
        now = time.time()
        to_cast = []
        
        for buff in self.buffs:
            next_cast = self.buff_next_cast.get(buff.key, 0)
            time_until_cast = next_cast - now
            
            # 已经过期 或 10秒内即将过期
            if time_until_cast <= 0 or (include_upcoming and time_until_cast <= self.BATCH_CAST_WINDOW):
                to_cast.append(buff)
        
        return to_cast

    def _cast_buff(self, buff: BuffConfig):
        """释放单个buff"""
        self.log_update.emit(f"释放技能: {buff.key}")
        
        # 拟人化按键
        duration = random.uniform(0.05, 0.15)
        self.human.keyboard.press(buff.key)
        time.sleep(duration)
        self.human.keyboard.release(buff.key)
        
        # 更新下次释放时间
        self.buff_next_cast[buff.key] = time.time() + buff.duration

    def _cast_all_ready_buffs(self):
        """释放所有准备好的buff（包括10秒内即将到期的）"""
        to_cast = self._get_buffs_to_cast(include_upcoming=True)
        
        if not to_cast:
            return
        
        self.log_update.emit(f"准备释放 {len(to_cast)} 个技能")
        
        for i, buff in enumerate(to_cast):
            if not self.is_running:
                break
            self._cast_buff(buff)
            
            # 技能之间的间隔（拟人化，与活花模式一致：1-2秒）
            if i < len(to_cast) - 1:
                self._random_sleep(1.0, 2.0)
    
    def _move_right_before_skill(self):
        """释放技能前向右移动一段距离（拟人化微调）"""
        if not self.is_running:
            return
        
        # 拟人化短按 (100-300ms)
        move_duration = random.uniform(0.1, 0.3)
        self.log_update.emit(f"向右微调 {int(move_duration * 1000)}ms...")
        
        self.human.move_right()
        self._interruptible_sleep(move_duration)
        self.human.stop_move()
    
    def _move_left_wiggle(self):
        """释放技能前向左移动一小段距离（拟人化晃动）"""
        if not self.is_running:
            return
        
        # 拟人化短按 (100-300ms)
        move_duration = random.uniform(0.1, 0.3)
        self.log_update.emit(f"向左微调 {int(move_duration * 1000)}ms...")
        
        self.human.move_left()
        self._interruptible_sleep(move_duration)
        self.human.stop_move()

    def _return_to_market(self) -> bool:
        """
        回到市场（使用缓存或模板匹配查找并点击"自由市场"按钮）
        
        Returns:
            是否成功回到市场
        """
        self.log_update.emit("正在回到市场...")
        
        # 1. 获取自由市场按钮位置（带缓存）
        btn_pos = self._get_market_button_pos()
        if not btn_pos:
            self.log_update.emit("❌ 未找到自由市场按钮")
            return False
        
        self.log_update.emit(f"按钮位置: {btn_pos}")
        
        # 2. 拟人化多次点击按钮（2-3次短按，防止一次没按好）
        click_count = random.randint(2, 3)
        for i in range(click_count):
            if not self.is_running:
                break
            # 每次点击添加小偏移，模拟真人不精确点击
            self.human.click_at(btn_pos[0], btn_pos[1], offset_range=8)
            
            # 点击之间随机间隔 (150-400ms)
            if i < click_count - 1:
                self._random_sleep(0.15, 0.40)
        
        # 3. 等待黑屏（按钮会消失）
        self.log_update.emit("等待传送...")
        self._interruptible_sleep(self.BLACK_SCREEN_WAIT)
        
        # 4. 循环检测：市场Logo + 按钮可见 = 回到市场
        max_wait = 15  # 最多等待15秒
        start_time = time.time()
        
        while self.is_running and (time.time() - start_time) < max_wait:
            if self._is_in_market():
                self.log_update.emit("✅ 已回到市场")
                return True
            
            self._interruptible_sleep(self.SCENE_CHECK_INTERVAL)
        
        self.log_update.emit("⚠️ 回到市场超时")
        return False

    def _leave_market(self) -> bool:
        """
        离开市场（走到传送门并进入）
        
        Returns:
            是否成功离开市场
        """
        self.log_update.emit("正在离开市场...")
        
        # 1. 获取传送门位置（带缓存，首次使用时检测）
        portal_pos = self._get_portal_pos()
        if not portal_pos:
            self.log_update.emit("❌ 未找到传送门")
            return False
        
        portal_x, portal_y = portal_pos
        self.log_update.emit(f"传送门位置: ({portal_x}, {portal_y})")
        
        # 2. 导航到传送门
        retry_count = 0
        max_retries = 100
        
        while self.is_running and retry_count < max_retries:
            player_pos = self.monitor.find_player_position()
            
            if not player_pos:
                retry_count += 1
                self._random_sleep(0.1, 0.2)
                continue
            
            player_x, player_y = player_pos
            dx = portal_x - player_x
            
            if abs(dx) <= self.TOLERANCE:
                self.log_update.emit("到达传送门，准备进入...")
                self.human.stop_move()
                self._random_sleep(0.1, 0.2)
                self.human.use_portal()
                break
            
            if dx > self.TOLERANCE:
                self.human.move_right()
            elif dx < -self.TOLERANCE:
                self.human.move_left()
            
            self._random_sleep(*[x/1000 for x in self.DETECT_INTERVAL])
            retry_count += 1
        
        self.human.stop_move()
        
        # 3. 等待黑屏
        self.log_update.emit("等待传送...")
        self._interruptible_sleep(self.BLACK_SCREEN_WAIT)
        
        # 4. 循环检测：无市场Logo + 按钮可见 = 离开市场
        max_wait = 15
        start_time = time.time()
        
        while self.is_running and (time.time() - start_time) < max_wait:
            if self._is_in_monster_map():
                self.log_update.emit("✅ 已离开市场")
                return True
            
            self._interruptible_sleep(self.SCENE_CHECK_INTERVAL)
        
        self.log_update.emit("⚠️ 离开市场超时")
        return False

    def _update_countdown_display(self):
        """更新UI倒计时显示"""
        now = time.time()
        countdown_info = {}
        
        for buff in self.buffs:
            next_cast = self.buff_next_cast.get(buff.key, 0)
            remaining = max(0, int(next_cast - now))
            countdown_info[buff.key] = remaining
        
        self.countdown_update.emit(countdown_info)

    def _get_time_until_next_cast(self) -> float:
        """获取距离下次需要释放技能的时间（秒）"""
        now = time.time()
        min_wait = float('inf')
        
        for buff in self.buffs:
            next_cast = self.buff_next_cast.get(buff.key, 0)
            wait_time = next_cast - now
            if wait_time < min_wait:
                min_wait = wait_time
        
        return max(0, min_wait)

    def run(self):
        try:
            self.log_update.emit("死花模式启动...")
            
            # 初始化
            self._bring_window_to_front()
            self._interruptible_sleep(0.5)
            
            self.monitor.set_window_handle(self.hwnd)
            
            # 记录初始窗口大小
            self._cached_window_size = self._get_window_size()
            self.log_update.emit(f"记录窗口大小: {self._cached_window_size}")
            
            # 初始化小地图检测
            success, _, _ = self.monitor.debug_save_minimap()
            if not success:
                self.log_update.emit("❌ 小地图检测失败")
                self.error_signal.emit("小地图检测失败")
                return
            
            # 初始化所有buff为立即释放
            now = time.time()
            for buff in self.buffs:
                self.buff_next_cast[buff.key] = now
            
            # 主循环
            while self.is_running:
                # 更新倒计时显示
                self._update_countdown_display()
                
                # 检查是否有buff需要释放
                buffs_to_cast = self._get_buffs_to_cast(include_upcoming=False)
                
                if buffs_to_cast:
                    # 需要出去放技能
                    self.log_update.emit(f"有 {len(buffs_to_cast)} 个技能需要释放")
                    
                    # 判断当前位置
                    in_market = self._is_in_market()
                    in_monster_map = self._is_in_monster_map()
                    
                    self.log_update.emit(f"状态检测: 市场={in_market}, 怪物地图={in_monster_map}")
                    
                    if in_monster_map:
                        # 已经在怪物地图，直接释放技能
                        self.log_update.emit("已在怪物地图，直接释放技能...")
                        self._cast_all_ready_buffs()
                        self._update_countdown_display()  # 释放后立即刷新倒计时
                    elif in_market:
                        # 在市场，需要先出去
                        if not self._leave_market():
                            self.log_update.emit("离开市场失败，等待重试...")
                            self._interruptible_sleep(5)
                            continue
                        
                        # 1. 释放技能前：先向右微调
                        self._move_right_before_skill()
                        
                        # 停止移动并拟人化等待
                        self.human.stop_move()
                        self._random_sleep(0.3, 0.8)
                        
                        # 2. 向左微调
                        self._move_left_wiggle()
                        
                        self.human.stop_move()
                        self._random_sleep(0.3, 0.8)
                        
                        # 3. 释放所有需要的技能
                        self._cast_all_ready_buffs()
                        self._update_countdown_display()  # 释放后立即刷新倒计时
                        
                        # 4. 释放完毕后直接准备回市场 (不需要再移动)
                    else:
                        # 未知状态（可能在加载中）
                        self.log_update.emit("位置状态未知，等待...")
                        self._interruptible_sleep(2)
                        continue
                    
                    # 拟人化：释放完技能后随机等待1-2秒再回市场
                    self.log_update.emit("等待后返回市场...")
                    self._random_sleep(1.0, 2.0)
                    
                    # 回到市场（循环重试直到成功）
                    return_retry_count = 0
                    max_return_retries = 10  # 最多重试10次
                    
                    while self.is_running and return_retry_count < max_return_retries:
                        if self._return_to_market():
                            self.log_update.emit("技能释放完成，回到市场等待...")
                            break
                        else:
                            return_retry_count += 1
                            self.log_update.emit(f"回到市场失败，第 {return_retry_count}/{max_return_retries} 次重试...")
                            # 拟人化随机间隔 (2-4秒)
                            self._random_sleep(2.0, 4.0)
                    
                    if return_retry_count >= max_return_retries:
                        self.log_update.emit("⚠️ 回到市场多次失败，继续主循环...")
                else:
                    # 没有buff需要释放，更新显示并等待
                    wait_time = self._get_time_until_next_cast()
                    
                    if wait_time > 1:
                        # 每秒更新一次倒计时
                        self._interruptible_sleep(1)
                    else:
                        # 快到时间了，频繁检查
                        self._interruptible_sleep(0.5)
            
            self.log_update.emit("死花模式已停止")
            self.finished_signal.emit()

        except Exception as e:
            self.log_update.emit(f"发生错误: {str(e)}")
            import traceback
            self.log_update.emit(traceback.format_exc())
            self.error_signal.emit(str(e))
        finally:
            self.human.release_all()

    def stop(self):
        """停止Worker（非阻塞）"""
        self.is_running = False
        self.human.release_all()
        # 注意：不调用 wait()，让线程自然退出
        # 由于使用了 _interruptible_sleep()，线程会在100ms内响应停止
