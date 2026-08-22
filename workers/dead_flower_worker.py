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
from detection.dialog_detector import DialogDetector
from automation.human_input import HumanInput
from pynput.keyboard import Key
from models.buff_config import BuffConfig
from utils.key_names import normalize_key_name
from utils.window_selector import WindowSelector
from utils.countdown import (
    format_release_time,
    next_release_time,
    remaining_seconds,
)
from workers.skill_worker import (
    PRE_SKILL_MOVE_RIGHT_MIN_MS, PRE_SKILL_MOVE_RIGHT_MAX_MS,
    POST_SKILL_MOVE_LEFT_MIN_MS, POST_SKILL_MOVE_LEFT_MAX_MS
)


class DeadFlowerWorker(QThread):
    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    countdown_update = pyqtSignal(dict)  # buff倒计时更新

    NAVIGATION_TARGET_INTERVAL = 1.0 / 30.0
    PLAYER_MISSING_GRACE_SECONDS = 0.12
    PLAYER_MISSING_ABORT_SECONDS = 3.0
    PLAYER_RECOVERY_JUMP_INTERVAL = 0.45
    STUCK_TIMEOUT_SECONDS = 0.9
    FINE_ADJUST_DURATION_MS = (180, 280)
    PORTAL_TRANSITION_CHECK_ATTEMPTS = 3

    def __init__(
        self,
        hwnd: int,
        buffs: List[BuffConfig],
        jump_key: str = "alt",
        sit_chair_enabled: bool = False,
        chair_key: str = "=",
        pre_skill_move_mode: str = "right_only",
        manual_portal_pos: tuple = None,
        portal_width_threshold: float = 2.5,
    ):
        super().__init__()
        self.hwnd = hwnd
        self.buffs = [b for b in buffs if b.enabled and b.key]  # 只保留启用的buff
        self.is_running = True
        self.monitor = MinimapMonitor()
        self.monitor.set_window_handle(hwnd)
        self.market_detector = MarketButtonDetector(hwnd=hwnd, confidence=0.3)
        self.human = HumanInput()
        self.jump_key = self._resolve_key(jump_key)
        
        # 椅子配置
        self.sit_chair_enabled = sit_chair_enabled
        self.chair_key = self._resolve_key(chair_key)
        self.is_sitting = False
        
        # 出市场后移动模式
        self.pre_skill_move_mode = pre_skill_move_mode
        self.window_selector = WindowSelector()
        
        # 手动标记的传送门位置（优先于自动检测）
        self.manual_portal_pos = manual_portal_pos
        self.portal_width_threshold = self._clamp_portal_width_threshold(
            portal_width_threshold
        )
        
        # Buff倒计时跟踪 {key: 下次释放时间戳}
        self.buff_next_cast: Dict[str, float] = {}
        
        # 窗口大小与位置缓存
        self._cached_window_size: Optional[tuple] = None           # (width, height)
        self._cached_market_btn_pos: Optional[tuple] = None        # 屏幕绝对坐标
        self._cached_market_btn_game_pos: Optional[tuple] = None   # 游戏窗口内坐标
        self._cached_portal_pos: Optional[tuple] = None            # 小地图内坐标
        
        # 导航参数
        self.TOLERANCE = self.portal_width_threshold  # 到达传送门的容差(小地图像素)
        # 时间参数
        self.BATCH_CAST_WINDOW = 10.0  # 10秒内的buff一起放
        self.BLACK_SCREEN_WAIT = 2.5   # 传送黑屏等待时间
        self.SCENE_CHECK_INTERVAL = 3.0  # 场景检测间隔
        
        # 弹窗检测
        self.dialog_detector = DialogDetector(hwnd=hwnd, confidence=0.5)
        self._dialog_miss_count = 0        # 连续未检测到弹窗次数
        self._dialog_check_done = False    # 本轮回市场后是否已停止检测
        self._last_dialog_check = 0.0      # 上次检测时间戳

    @staticmethod
    def _clamp_portal_width_threshold(value: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 2.5
        return max(0.5, min(20.0, numeric))

    def _bring_window_to_front(self) -> bool:
        """将游戏窗口设置为前台"""
        if self.window_selector.ensure_window_focus(self.hwnd):
            return True
        self.log_update.emit("设置窗口焦点失败")
        return False

    def _ensure_game_focus(self, reason: str) -> bool:
        if self.window_selector.is_window_foreground(self.hwnd):
            return True
        if self.window_selector.ensure_window_focus(self.hwnd, attempts=12, delay=0.15):
            self.log_update.emit(f"✅ {reason}：游戏窗口焦点已恢复")
            return True
        foreground = win32gui.GetForegroundWindow()
        foreground_title = win32gui.GetWindowText(foreground) if foreground else "未知"
        self.log_update.emit(
            f"❌ {reason}：无法恢复游戏窗口焦点，当前前台窗口为 {foreground_title}"
        )
        return False

    def _interruptible_sleep(self, seconds: float):
        """
        可中断的睡眠 - 每100ms检查一次is_running标志
        同时每秒更新一次倒计时显示
        """
        if seconds <= 0:
            return
        
        interval = 0.1  # 100ms检查间隔
        elapsed = 0.0
        last_countdown_update = 0.0  # 上次更新倒计时的时间
        
        while elapsed < seconds and self.is_running:
            sleep_time = min(interval, seconds - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time
            
            # 每秒更新一次倒计时显示
            if elapsed - last_countdown_update >= 1.0:
                last_countdown_update = elapsed
                self._update_countdown_display()

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

    def _is_in_market(self, log_result: bool = True) -> bool:
        """
        判断是否在市场中
        规则：小地图有市场Logo + 能看到自由市场按钮
        """
        has_logo = self._is_market_logo_visible()
        has_btn = self._is_market_btn_visible()
        is_in = has_logo and has_btn
        if log_result:
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
    
    def _is_in_monster_map(self, log_result: bool = True) -> bool:
        """
        判断是否在怪物地图
        规则：没有市场Logo + 能看到自由市场按钮
        """
        has_logo = self._is_market_logo_visible()
        has_btn = self._is_market_btn_visible()
        is_monster = (not has_logo) and has_btn
        if log_result:
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
        
        优先使用手动标记的位置，其次试自动检测
        窗口大小改变时缓存会被清空
        """
        # 手动标记位置优先
        if self.manual_portal_pos:
            self.log_update.emit(f"使用手动标记的传送门位置: {self.manual_portal_pos}")
            return self.manual_portal_pos
        
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
    # 特殊键映射（pynput需要Key对象而不是字符串）
    SPECIAL_KEY_MAP = {
        'shift': Key.shift,
        'ctrl': Key.ctrl, 'control': Key.ctrl,
        'alt': Key.alt,
        'tab': Key.tab,
        'space': Key.space,
        'enter': Key.enter,
        'backspace': Key.backspace,
        'delete': Key.delete,
        'insert': Key.insert,
        'home': Key.home,
        'end': Key.end,
        'page_up': Key.page_up, 'pageup': Key.page_up,
        'page_down': Key.page_down, 'pagedown': Key.page_down,
        'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4,
        'f5': Key.f5, 'f6': Key.f6, 'f7': Key.f7, 'f8': Key.f8,
        'f9': Key.f9, 'f10': Key.f10, 'f11': Key.f11, 'f12': Key.f12,
    }

    def _resolve_key(self, key_str: str):
        """将按键字符串转换为pynput可识别的按键"""
        normalized_key = normalize_key_name(key_str)
        return self.SPECIAL_KEY_MAP.get(normalized_key.lower(), normalized_key)

    def _cast_buff(self, buff: BuffConfig):
        """释放单个buff"""
        self.log_update.emit(f"释放技能: {buff.key}")
        
        # 解析按键
        key = self._resolve_key(buff.key)
        
        # 与活花模式一致：连续短按两次，降低游戏偶发吞键概率。
        pressed_at = None
        for press_index in range(2):
            duration = random.uniform(0.05, 0.15)
            self.human.keyboard.press(key)
            pressed_at = time.time()
            time.sleep(duration)
            self.human.keyboard.release(key)
            if press_index == 0:
                time.sleep(random.uniform(0.1, 0.3))
        
        # 最后一次技能 key-down 后立即启动并发布该 Buff 的倒计时。
        release_at = next_release_time(
            pressed_at=pressed_at,
            interval=buff.duration,
        )
        self.buff_next_cast[buff.key] = release_at
        self._update_countdown_display(now=pressed_at)
        self.log_update.emit(
            f"技能 {buff.key} 倒计时 "
            f"{remaining_seconds(release_at, pressed_at)} 秒，"
            f"下次释放 {format_release_time(release_at)}"
        )

    def _cast_all_ready_buffs(self):
        """释放所有准备好的buff（包括10秒内即将到期的）"""
        to_cast = self._get_buffs_to_cast(include_upcoming=True)
        
        if not to_cast:
            return False
        
        self.log_update.emit(f"准备释放 {len(to_cast)} 个技能")
        if not self._ensure_game_focus("释放技能"):
            self.log_update.emit("❌ 释放技能前无法确认游戏窗口焦点")
            return False
        
        for i, buff in enumerate(to_cast):
            if not self.is_running:
                break
            self._cast_buff(buff)
            
            # 技能之间的间隔（拟人化，与活花模式一致：1-2秒）
            if i < len(to_cast) - 1:
                self._random_sleep(1.0, 2.0)
        return True
    
    def _move_right_before_skill(self):
        """释放技能前向右移动一段距离（拟人化微调）"""
        if not self.is_running:
            return
        
        # 拟人化短按 (100-300ms)
        move_duration = random.uniform(0.1, 0.3)
        self.log_update.emit(f"向右微调 {int(move_duration * 1000)}ms...")
        self._bring_window_to_front()
        
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
        self._bring_window_to_front()
        
        self.human.move_left()
        self._interruptible_sleep(move_duration)
        self.human.stop_move()
        self.is_sitting = False # 移动打断椅子
        
    def _sit_chair(self):
        """空闲时坐下"""
        if not self.sit_chair_enabled or self.is_sitting or not self.is_running:
            return
        
        self.log_update.emit(f"空闲时间过长，按下椅子键...")
        try:
            from automation.human_input import Key
            key_obj = self.chair_key
            if len(str(key_obj)) > 1 and hasattr(Key, str(key_obj)):
                key_obj = getattr(Key, str(key_obj))
            self.human.keyboard.press(key_obj)
            self._interruptible_sleep(random.uniform(0.05, 0.15))
            self.human.keyboard.release(key_obj)
            self.is_sitting = True
        except Exception as e:
            self.log_update.emit(f"坐椅子失败: {str(e)}")

    def _jump_before_move(self):
        """移动前短按跳跃键拟人化处理"""
        if not self.is_running:
            return
        # 拟人化短按跳跃键 (50-150ms)
        jump_duration = random.uniform(0.05, 0.15)
        self.log_update.emit(f"防卡死，短按跳跃键 {int(jump_duration * 1000)}ms...")
        self.human.keyboard.press(self.jump_key)
        self._interruptible_sleep(jump_duration)
        self.human.keyboard.release(self.jump_key)
        
        # 释放后与方向键的拟人化间隔 (100-300ms)
        wait_duration = random.uniform(0.1, 0.3)
        self._interruptible_sleep(wait_duration)

    def _find_player_position_during_jump(self) -> Optional[tuple]:
        """短按跳跃键，并在起跳期间重采一次玩家黄点。"""
        if not self.is_running:
            return None
        if not self._ensure_game_focus("跳跃定位"):
            return None

        jump_duration = random.uniform(0.08, 0.16)
        sample_delay = min(jump_duration, random.uniform(0.04, 0.08))
        self.human.keyboard.press(self.jump_key)
        try:
            self._interruptible_sleep(sample_delay)
            if not self.is_running:
                return None
            return self.monitor.find_player_position_once()
        finally:
            try:
                self.human.keyboard.release(self.jump_key)
            except Exception as e:
                self.log_update.emit(f"释放跳跃键失败: {e}")
            remaining = jump_duration - sample_delay
            if remaining > 0:
                self._interruptible_sleep(remaining)

    def _return_to_market(self) -> bool:
        """
        回到市场（使用缓存或模板匹配查找并点击"自由市场"按钮）
        
        Returns:
            是否成功回到市场
        """
        self.log_update.emit("正在回到市场...")
        self._bring_window_to_front()
        
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
        if not self._ensure_game_focus("离开市场"):
            return False
        
        # 确保小地图已初始化（在怪物地图启动时可能未成功，现在在市场内重试）
        if self.monitor.minimap_region is None:
            self.log_update.emit("小地图未初始化，正在重新检测...")
            success, _, _ = self.monitor.debug_save_minimap()
            if not success:
                self.log_update.emit("❌ 小地图检测失败，无法导航")
                return False
        
        # 1. 获取传送门位置（带缓存，首次使用时检测）
        portal_pos = self._get_portal_pos()
        if not portal_pos:
            self.log_update.emit("❌ 未找到传送门")
            return False
        
        portal_x, portal_y = portal_pos
        self.log_update.emit(f"传送门位置: ({portal_x}, {portal_y})")

        self._jump_before_move()
        self.log_update.emit("小地图导航已启用最高 30 FPS 识别")

        # 2. 导航到传送门
        navigation_started_at = time.monotonic()
        max_navigation_seconds = 30.0
        missing_since = None
        last_recovery_jump_at = 0.0
        last_missing_log_at = 0.0
        progress_anchor_x = None
        progress_anchor_at = None
        current_direction = None
        direct_approach_direction = None
        fine_adjusting = False
        entered_portal = False

        initial_player = None
        initial_deadline = time.monotonic() + 2.0
        while self.is_running and time.monotonic() < initial_deadline:
            if not self.is_running:
                return False
            frame_started = time.monotonic()
            initial_player = self.monitor.find_player_position_once()
            if initial_player:
                break
            self._sleep_navigation_frame(frame_started)
        if not initial_player:
            self.log_update.emit("导航前黄点被遮挡，尝试跳跃定位...")
            initial_player = self._find_player_position_during_jump()
            if initial_player:
                self.log_update.emit(f"跳跃时定位到玩家: X={initial_player[0]:.1f}")
        if not initial_player:
            self.log_update.emit(
                "❌ 导航前无法定位玩家黄点："
                f"{self.monitor.last_player_detection_summary}"
            )
            return False

        initial_dx = portal_x - initial_player[0]
        self.log_update.emit(
            f"导航坐标: 玩家X={initial_player[0]:.1f}，"
            f"传送门X={portal_x:.1f}，距离={initial_dx:.1f}"
        )
        if abs(initial_dx) <= self.TOLERANCE:
            entered_portal = self._try_enter_portal()
            if not entered_portal:
                fine_adjusting = True
        else:
            current_direction = "right" if initial_dx > 0 else "left"
            direct_approach_direction = current_direction
            if current_direction == "right":
                self.human.move_right()
            else:
                self.human.move_left()
        
        while (
            self.is_running
            and time.monotonic() - navigation_started_at < max_navigation_seconds
            and not entered_portal
        ):
            frame_started = time.monotonic()
            if not self.window_selector.is_window_foreground(self.hwnd):
                current_direction = None
                progress_anchor_x = None
                progress_anchor_at = None
                self.log_update.emit("⚠️ 检测到游戏窗口失去焦点，正在恢复")
                if not self._ensure_game_focus("导航恢复"):
                    break
                # 确保 key-up 发送给游戏窗口，再根据当前位置重新按方向键。
                self.human.release_all()

            recovered_by_jump = False
            player_pos = self.monitor.find_player_position_once()
            
            if not player_pos:
                now = time.monotonic()
                if missing_since is None:
                    missing_since = now
                missing_duration = now - missing_since

                if missing_duration < self.PLAYER_MISSING_GRACE_SECONDS:
                    self._sleep_navigation_frame(frame_started)
                    continue

                if current_direction is not None:
                    self.human.stop_move()
                    current_direction = None
                progress_anchor_x = None
                progress_anchor_at = None
                if now - last_missing_log_at >= 1.0:
                    self.log_update.emit(
                        f"⚠️ 玩家黄点持续丢失 {missing_duration:.1f}s，"
                        "已停止移动，尝试跳跃定位；"
                        f"{self.monitor.last_player_detection_summary}"
                    )
                    last_missing_log_at = now
                if now - last_recovery_jump_at >= self.PLAYER_RECOVERY_JUMP_INTERVAL:
                    player_pos = self._find_player_position_during_jump()
                    last_recovery_jump_at = time.monotonic()
                    recovered_by_jump = player_pos is not None
                if not player_pos:
                    if missing_duration >= self.PLAYER_MISSING_ABORT_SECONDS:
                        self.log_update.emit("❌ 连续无法定位玩家，终止本次导航")
                        break
                    self._sleep_navigation_frame(frame_started)
                    continue
            
            if missing_since is not None:
                prefix = "跳跃时重新定位玩家" if recovered_by_jump else "已重新定位玩家"
                self.log_update.emit(f"{prefix}: X={player_pos[0]:.1f}")
            missing_since = None
            player_x, _ = player_pos
            dx = portal_x - player_x

            # 按上键失败后已进入微调状态。即使当前 X 仍在容差内，
            # 也先朝传送门中心多走一步，避免只在原地重复按上。
            needed_direction = 'right' if dx > 0 else 'left'
            if fine_adjusting:
                if not self._ensure_game_focus("传送门微调"):
                    break
                self.log_update.emit(
                    f"向{'右' if needed_direction == 'right' else '左'}微调后尝试进入传送门"
                )
                self.human.tap_direction(
                    needed_direction,
                    self.FINE_ADJUST_DURATION_MS,
                )
                current_direction = None
                progress_anchor_x = None
                progress_anchor_at = None
                entered_portal = self._try_enter_portal()
                if entered_portal:
                    break
                continue

            if abs(dx) <= self.TOLERANCE:
                self.log_update.emit("到达传送门，准备进入...")
                self.human.stop_move()
                current_direction = None
                self._random_sleep(0.1, 0.3)
                entered_portal = self._try_enter_portal()
                if entered_portal:
                    break
                fine_adjusting = True
                continue

            if (
                direct_approach_direction is not None
                and needed_direction != direct_approach_direction
            ):
                if current_direction is not None:
                    self.human.stop_move()
                    current_direction = None
                fine_adjusting = True
                progress_anchor_x = None
                progress_anchor_at = None
                self.log_update.emit("已越过传送门，切换为长按微调并逐次试按上键")
                self._sleep_navigation_frame(frame_started)
                continue

            now = time.monotonic()
            if current_direction is not None:
                if progress_anchor_x is None:
                    progress_anchor_x = player_x
                    progress_anchor_at = now
                elif abs(player_x - progress_anchor_x) > 1:
                    progress_anchor_x = player_x
                    progress_anchor_at = now
                elif now - progress_anchor_at >= self.STUCK_TIMEOUT_SECONDS:
                    self.log_update.emit(
                        "检测到移动停滞（游戏焦点正常），重新按方向键："
                        f"{self.monitor.last_player_detection_summary}"
                    )
                    self.human.stop_move()
                    current_direction = None
                    progress_anchor_x = None
                    progress_anchor_at = None
                    self._random_sleep(0.1, 0.3)

            if current_direction != needed_direction:
                if not self._ensure_game_focus("方向移动"):
                    break
                if needed_direction == 'right':
                    self.human.move_right()
                else:
                    self.human.move_left()
                current_direction = needed_direction
                progress_anchor_x = player_x
                progress_anchor_at = time.monotonic()
            
            self._sleep_navigation_frame(frame_started)
        
        self.human.stop_move()
        if not entered_portal:
            self.log_update.emit("⚠️ 未能到达传送门")
            return False
        
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

    def _try_enter_portal(self) -> bool:
        """按上键后确认市场标志已连续消失，避免黑屏时继续微调。"""
        if not self._ensure_game_focus("进入传送门"):
            return False
        self.human.use_portal()

        consecutive_logo_misses = 0
        for _ in range(self.PORTAL_TRANSITION_CHECK_ATTEMPTS):
            if not self.is_running:
                return False
            if self._is_market_logo_visible():
                consecutive_logo_misses = 0
            else:
                consecutive_logo_misses += 1
                if consecutive_logo_misses >= 2:
                    self.log_update.emit("已触发传送，等待切换场景")
                    return True
            self._interruptible_sleep(0.08)
        return False

    def _sleep_navigation_frame(self, frame_started: float):
        """将导航采样限制在约 30 FPS，处理超时时不再额外等待。"""
        remaining = self.NAVIGATION_TARGET_INTERVAL - (
            time.monotonic() - frame_started
        )
        if remaining > 0:
            self._interruptible_sleep(remaining)


    def _update_countdown_display(self, now: float = None):
        """更新UI倒计时显示"""
        current_time = time.time() if now is None else now
        countdown_info = {}
        
        for buff in self.buffs:
            if buff.key not in self.buff_next_cast:
                continue
            countdown_info[buff.key] = remaining_seconds(
                self.buff_next_cast[buff.key],
                current_time,
            )
        
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
            self.monitor.start_capture()
            
            # 记录初始窗口大小
            self._cached_window_size = self._get_window_size()
            self.log_update.emit(f"记录窗口大小: {self._cached_window_size}")
            
            # 初始化小地图检测（非致命：在怪物地图上启动时可能没有小地图）
            success, _, _ = self.monitor.debug_save_minimap()
            if not success:
                self.log_update.emit("⚠️ 小地图检测未成功（可能不在市场），将在进入市场后重试")
            
            # 没有时间戳的 Buff 会被视为立即释放；在真正按下技能前
            # UI 保持 --:--，不会提前开始倒计时。
            self.buff_next_cast.clear()
            
            # 主循环
            while self.is_running:
                # 更新倒计时显示
                self._update_countdown_display()
                
                # 检查是否有buff需要释放
                buffs_to_cast = self._get_buffs_to_cast(include_upcoming=False)
                
                if buffs_to_cast:
                    # 需要出去放技能
                    self.log_update.emit(f"有 {len(buffs_to_cast)} 个技能需要释放")
                    
                    # 先将窗口置于前台，确保截图正确
                    self._bring_window_to_front()
                    self._interruptible_sleep(0.3)
                    
                    # 判断当前位置
                    in_market = self._is_in_market()
                    in_monster_map = self._is_in_monster_map()
                    
                    self.log_update.emit(f"状态检测: 市场={in_market}, 怪物地图={in_monster_map}")
                    
                    if in_monster_map:
                        # 已经在怪物地图，直接释放技能
                        self.log_update.emit("已在怪物地图，直接释放技能...")
                        if not self._cast_all_ready_buffs():
                            self.log_update.emit("释放技能未完成，等待后重试...")
                            self._interruptible_sleep(2)
                            continue
                        self._update_countdown_display()  # 释放后立即刷新倒计时
                    elif in_market:
                        # 在市场，需要先出去
                        if not self._leave_market():
                            self.log_update.emit("离开市场失败，等待重试...")
                            self._interruptible_sleep(5)
                            continue
                        
                        # 1. 释放技能前的移动
                        if self.pre_skill_move_mode == "left_only":
                            self._move_left_wiggle()
                        elif self.pre_skill_move_mode == "right_only":
                            self._move_right_before_skill()
                        else:
                            self._move_right_before_skill()
                            self.human.stop_move()
                            self._random_sleep(0.3, 0.8)
                            self._move_left_wiggle()
                        
                        self.human.stop_move()
                        self._random_sleep(0.5, 1.0)
                        
                        # 3. 释放所有需要的技能
                        if not self._cast_all_ready_buffs():
                            self.log_update.emit("释放技能未完成，等待后重试...")
                            self._interruptible_sleep(2)
                            continue
                        self._update_countdown_display()  # 释放后立即刷新倒计时
                        
                        # 4. 等待技能后摇结束，避免技能释放失败
                        self.log_update.emit("等待技能后摇结束...")
                        self._random_sleep(1.0, 1.5)
                        
                        # 5. 释放完毕后直接准备回市场 (不需要再移动)
                    else:
                        # 未知状态（可能在加载中）
                        self.log_update.emit("位置状态未知，等待...")
                        self._interruptible_sleep(2)
                        continue
                    
                    # 拟人化：释放完技能后随机等待1-2秒再回市场
                    self.log_update.emit("等待后返回市场...")
                    self._random_sleep(1.2, 1.8)
                    
                    # 回到市场（循环重试直到成功）
                    return_retry_count = 0
                    max_return_retries = 10  # 最多重试10次
                    
                    while self.is_running and return_retry_count < max_return_retries:
                        if self._return_to_market():
                            self.log_update.emit("技能释放完成，回到市场等待...")
                            # 重置弹窗检测状态（新一轮回市场）
                            self._dialog_miss_count = 0
                            self._dialog_check_done = False
                            self._last_dialog_check = 0.0
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
                    
                    # 在市场空闲时检测弹窗（每5秒一次，连续2次未检测到则停止）
                    if not self._dialog_check_done:
                        now = time.time()
                        if now - self._last_dialog_check >= 5.0:
                            self._last_dialog_check = now
                            pos = self.dialog_detector.find_confirm_button()
                            if pos:
                                self.log_update.emit("检测到弹窗，自动点击确定...")
                                self.human.click_at(pos[0], pos[1], offset_range=5)
                                self._dialog_miss_count = 0
                            else:
                                self._dialog_miss_count += 1
                                if self._dialog_miss_count >= 2:
                                    self._dialog_check_done = True
                                    self.log_update.emit("弹窗检测已停止（连续2次未检测到）")
                    
                    if wait_time > 5 and self._is_in_market(log_result=False) and self.sit_chair_enabled and not self.is_sitting:
                        # 只有真的在市场且时间够长且没坐下时才坐下
                        self._sit_chair()
                    
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
            self.monitor.close_capture()

    def stop(self):
        """停止Worker（非阻塞）"""
        self.is_running = False
        self.human.release_all()
        # 注意：不调用 wait()，让线程自然退出
        # 由于使用了 _interruptible_sleep()，线程会在100ms内响应停止
