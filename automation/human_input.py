
import time
import random
import threading
import ctypes
import sys
from typing import Tuple, Optional
from pynput.keyboard import Key, Controller as KeyboardController
from pynput.mouse import Button, Controller as MouseController

# A chat command is one indivisible input transaction: Enter, text, Enter.
# Workers share this lock so a replacement worker cannot type into an open
# chat box left by the worker that is finishing.
input_transaction_lock = threading.Lock()

class HumanInput:
    """
    模拟拟人化的键盘和鼠标输入
    所有操作都经过随机化处理，避免被检测为机器人
    """
    def __init__(self):
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        self.running = True
        self._lock = threading.RLock()  # 使用可重入锁，避免死锁
        
        # 当前按下的方向键
        self.current_direction = None  # 'left', 'right', 'up', 'down', None
        
        # 拟人化参数 (ms)
        self.direction_tap_duration = (40, 120)      # 轻点微调
        self.direction_change_delay = (50, 200)      # 换向延迟
        self.portal_press_duration = (200, 800)      # 传送门按住时长
        self.key_offset_range = (10, 80)             # 组合键偏移
        self.mouse_click_duration = (50, 150)        # 鼠标点击按住时长
        self.mouse_move_steps = (3, 8)               # 鼠标移动分步数

    def _random_duration(self, range_ms: Tuple[int, int]) -> float:
        """使用正态分布生成随机时长，大多数值接近中间"""
        min_ms, max_ms = range_ms
        mean = (min_ms + max_ms) / 2
        std = (max_ms - min_ms) / 4
        duration = random.gauss(mean, std)
        duration = max(min_ms, min(max_ms, duration))
        return duration / 1000.0  # 转为秒

    def _sleep(self, seconds: float):
        """可中断的睡眠"""
        if seconds <= 0:
            return
        time.sleep(seconds)

    def click_at(self, x: int, y: int, offset_range: int = 10):
        """
        拟人化点击指定屏幕坐标
        
        Args:
            x: 目标X坐标（中心点）
            y: 目标Y坐标（中心点）
            offset_range: 随机偏移范围（像素），避免精确点击中心
        """
        with self._lock:
            # 1. 添加随机偏移，避免精确点击中心
            offset_x = random.randint(-offset_range, offset_range)
            offset_y = random.randint(-offset_range, offset_range)
            target_x = x + offset_x
            target_y = y + offset_y
            
            # 2. 拟人化移动鼠标（分步移动）
            current_x, current_y = self.mouse.position
            steps = random.randint(*self.mouse_move_steps)
            
            for i in range(1, steps + 1):
                progress = i / steps
                # 使用 ease-out 曲线，开始快结束慢
                eased_progress = 1 - (1 - progress) ** 2
                
                new_x = int(current_x + (target_x - current_x) * eased_progress)
                new_y = int(current_y + (target_y - current_y) * eased_progress)
                
                # 添加微小抖动
                jitter_x = random.randint(-2, 2)
                jitter_y = random.randint(-2, 2)
                
                self.mouse.position = (new_x + jitter_x, new_y + jitter_y)
                self._sleep(random.uniform(0.01, 0.03))
            
            # 3. 最终位置（去除抖动）
            self.mouse.position = (target_x, target_y)
            self._sleep(random.uniform(0.05, 0.15))
            
            # 4. 点击（按住一段时间再松开）
            duration = self._random_duration(self.mouse_click_duration)
            self.mouse.press(Button.left)
            self._sleep(duration)
            self.mouse.release(Button.left)

    def move_left(self):
        """开始向左移动"""
        self._change_direction('left')

    def move_right(self):
        """开始向右移动"""
        self._change_direction('right')

    def stop_move(self):
        """停止移动"""
        self._change_direction(None)

    def _change_direction(self, new_direction: Optional[str]):
        """改变移动方向，包含拟人化延迟"""
        with self._lock:
            if self.current_direction == new_direction:
                return
            
            # 如果当前有方向键按下，先松开
            if self.current_direction:
                key = self._get_key_object(self.current_direction)
                self.keyboard.release(key)
                # 换向延迟
                delay = self._random_duration(self.direction_change_delay)
                self._sleep(delay)
            
            self.current_direction = new_direction
            
            # 如果新方向不为空，按下新键
            if new_direction:
                key = self._get_key_object(new_direction)
                self.keyboard.press(key)

    def use_portal(self):
        """使用传送门（按上键）"""
        # 确保先停止移动
        self.stop_move()
        self._sleep(0.1) # 等待稳定
        
        duration = self._random_duration(self.portal_press_duration)
        self.keyboard.press(Key.up)
        self._sleep(duration)
        self.keyboard.release(Key.up)

    def tap_direction(self, direction: str, duration_range: Optional[Tuple[int, int]] = None):
        """轻点方向键微调"""
        # 确保无其他方向键按下
        self.stop_move()
        self._sleep(0.05)
        
        duration = self._random_duration(duration_range or self.direction_tap_duration)
        key = self._get_key_object(direction)
        self.keyboard.press(key)
        self._sleep(duration)
        self.keyboard.release(key)

    def perform_directional_skill(
        self,
        direction: str,
        skill_key,
        direction_lead_range: Tuple[float, float] = (0.035, 0.075),
        skill_hold_range: Tuple[float, float] = (0.050, 0.110),
        direction_release_range: Tuple[float, float] = (0.025, 0.065),
    ):
        """按方向、点技能、松技能、松方向；不影响已按住的其它技能键。"""
        direction_key = self._get_key_object(direction)
        if direction_key is None:
            raise ValueError(f"不支持的方向: {direction}")
        skill_pressed = False
        with self._lock:
            self.keyboard.press(direction_key)
            self.current_direction = direction
            try:
                self._sleep(random.uniform(*direction_lead_range))
                self.keyboard.press(skill_key)
                skill_pressed = True
                self._sleep(random.uniform(*skill_hold_range))
                self.keyboard.release(skill_key)
                skill_pressed = False
                self._sleep(random.uniform(*direction_release_range))
            finally:
                if skill_pressed:
                    try:
                        self.keyboard.release(skill_key)
                    except Exception:
                        pass
                try:
                    self.keyboard.release(direction_key)
                finally:
                    if self.current_direction == direction:
                        self.current_direction = None

    def press_enter(self):
        """拟人化按下并释放回车。"""
        with self._lock:
            self.keyboard.press(Key.enter)
            self._sleep(random.uniform(0.05, 0.13))
            self.keyboard.release(Key.enter)

    def type_text(self, text: str, interval_range=(0.05, 0.12)):
        """逐字输入聊天文本；Windows 使用 Unicode SendInput 支持中文角色名。"""
        with self._lock:
            for character in text:
                if sys.platform == "win32":
                    self._send_unicode_character(character)
                else:
                    self.keyboard.type(character)
                self._sleep(random.uniform(*interval_range))

    @staticmethod
    def _send_unicode_character(character: str):
        ulong_ptr = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ulong_ptr),
            ]
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ulong_ptr),
            ]
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]
        class INPUTUNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]
        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", INPUTUNION)]
        encoded = character.encode("utf-16-le")
        units = [int.from_bytes(encoded[i:i + 2], "little")
                 for i in range(0, len(encoded), 2)]
        for unit in units:
            down = INPUT(1, INPUTUNION(ki=KEYBDINPUT(0, unit, 0x0004, 0, 0)))
            up = INPUT(1, INPUTUNION(ki=KEYBDINPUT(0, unit, 0x0004 | 0x0002, 0, 0)))
            ctypes.windll.user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
            ctypes.windll.user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))

    def _get_key_object(self, direction: str):
        mapping = {
            'left': Key.left,
            'right': Key.right,
            'up': Key.up,
            'down': Key.down
        }
        return mapping.get(direction)

    def release_all(self):
        """释放所有按键（用于异常退出）- 线程安全"""
        with self._lock:
            # 直接释放所有方向键，不调用其他方法避免死锁
            self.current_direction = None
            try:
                self.keyboard.release(Key.up)
            except:
                pass
            try:
                self.keyboard.release(Key.down)
            except:
                pass
            try:
                self.keyboard.release(Key.left)
            except:
                pass
            try:
                self.keyboard.release(Key.right)
            except:
                pass
