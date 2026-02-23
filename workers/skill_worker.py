"""
技能释放工作线程
负责在后台线程中执行技能释放逻辑
"""

import time
import random
import threading
from typing import List

from PyQt6.QtCore import QObject, pyqtSignal

from models.skill_config import SkillConfig
from utils.keyboard_utils import press_key
from config import THREAD_SLEEP_INTERVAL, CYCLE_PAUSE_TIME, INITIAL_WAIT_TIME
from automation.human_input import HumanInput

# 尝试导入keyboard库
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

# 技能之间的间隔时间范围（毫秒），模拟人按完一个技能后等待再按下一个
SKILL_GAP_MIN_MS = 1000   # 最小间隔
SKILL_GAP_MAX_MS = 2000   # 最大间隔

# 攻击键松开后延迟释放技能的时间范围（毫秒）
ATTACK_KEY_RELEASE_DELAY_MIN_MS = 200
ATTACK_KEY_RELEASE_DELAY_MAX_MS = 500

# 释放技能前向右移动的时间范围（毫秒）- 防止掉落
PRE_SKILL_MOVE_RIGHT_MIN_MS = 500   # 最小0.5秒
PRE_SKILL_MOVE_RIGHT_MAX_MS = 1000  # 最大1秒

# 释放技能后向左移动回到最左边的时间（毫秒）- 向左不会掉落，所以可以稍长
POST_SKILL_MOVE_LEFT_MIN_MS = 2000  # 最小2秒
POST_SKILL_MOVE_LEFT_MAX_MS = 3000  # 最大3秒


class SkillWorker(QObject):
    """技能释放工作线程类"""
    
    # 移动模式常量
    MOVEMENT_NONE = "none"      # 原地不动
    MOVEMENT_RIGHT = "right"    # 向右走开buff，然后向左回
    MOVEMENT_LEFT = "left"      # 向左走开buff，然后向右回
    
    # 定义信号，用于更新UI状态
    status_update = pyqtSignal(str)
    skill_pressed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    countdown_update = pyqtSignal(dict)  # 发送倒计时信息 {skill_key: remaining_seconds}
    
    def __init__(self, skills: List[SkillConfig], window_selector=None, game_window_hwnd=None, 
                 attack_key: str = "ctrl", movement_mode: str = "none"):
        """
        初始化工作线程
        
        参数:
            skills: 技能配置列表
            window_selector: 窗口选择器实例
            game_window_hwnd: 游戏窗口句柄
            attack_key: 攻击键，用于检测玩家是否正在攻击
            movement_mode: 移动模式 - "none"(原地不动), "right"(向右走开buff), "left"(向左走开buff)
        """
        super().__init__()
        self.skills = skills
        self.window_selector = window_selector
        self.game_window_hwnd = game_window_hwnd
        self.attack_key = attack_key.lower() if attack_key else "ctrl"
        self.movement_mode = movement_mode  # 移动模式
        self.is_running = False
        self.thread = None
        # 初始化拟人化输入控制器（用于移动）
        self.human_input = HumanInput()

    
    def start(self):
        """启动技能释放线程"""
        if self.is_running:
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.status_update.emit("运行中...")
    
    def stop(self):
        """停止技能释放线程"""
        self.is_running = False
        # 释放所有按键，确保不会卡住方向键
        if self.human_input:
            self.human_input.release_all()
        self.status_update.emit("已停止")
    
    def _run_loop(self):
        """技能释放循环（在后台线程中运行）"""
        try:
            # 第一次循环前等待初始时间
            if INITIAL_WAIT_TIME > 0:
                self.status_update.emit(f"等待 {INITIAL_WAIT_TIME} 秒后开始...")
                elapsed = 0
                while elapsed < INITIAL_WAIT_TIME and self.is_running:
                    time.sleep(THREAD_SLEEP_INTERVAL)
                    elapsed += THREAD_SLEEP_INTERVAL
            
            if not self.is_running:
                return
            
            self.status_update.emit("开始释放技能...")
            
            # 记录每个技能的下次释放时间
            current_time = time.time()
            next_release_times = {}
            
            # 初始化：立即批量释放所有技能（只移动一次）
            self._release_skills_batch(self.skills, next_release_times)
            
            # 主循环：检查每个技能是否到了释放时间
            last_log_time = time.time()
            
            while self.is_running:
                current_time = time.time()
                
                # 收集所有需要释放的技能
                skills_to_release = []
                for skill in self.skills:
                    if current_time >= next_release_times.get(skill.key, 0):
                        skills_to_release.append(skill)
                
                # 批量释放需要释放的技能（只移动一次）
                if skills_to_release:
                    self._release_skills_batch(skills_to_release, next_release_times)
                
                # 每秒发送一次倒计时更新（通过UI显示）
                countdown_info = {}
                for skill in self.skills:
                    remaining = max(0, int(next_release_times.get(skill.key, 0) - current_time))
                    countdown_info[skill.key] = remaining
                self.countdown_update.emit(countdown_info)
                
                # 短暂休眠，避免CPU占用过高
                time.sleep(THREAD_SLEEP_INTERVAL)
                    
        except Exception as e:
            error_msg = f"运行错误: {str(e)}"
            self.error_occurred.emit(error_msg)
            self.status_update.emit(error_msg)
        finally:
            self.is_running = False
            self.status_update.emit("已停止")
    
    def _release_skills_batch(self, skills_to_release: List[SkillConfig], next_release_times: dict):
        """
        批量释放技能（根据移动模式决定是否移动）
        流程：
        - none模式：直接释放所有技能，不移动
        - right模式：向右移动 → 释放所有技能 → 向左移动回去
        - left模式：向左移动 → 释放所有技能 → 向右移动回去
        """
        if not skills_to_release or not self.is_running:
            return
        
        try:
            # 检测攻击键是否被按住，如果是则等待松开后再释放
            self._wait_for_attack_key_release()
            
            # 确保游戏窗口获得焦点
            self._ensure_game_window_focus()
            
            # === 1. 释放技能前移动（根据模式） ===
            self._move_before_skill()
            
            # === 2. 停止移动后再释放技能，避免按键冲突 ===
            if self.movement_mode != self.MOVEMENT_NONE:
                self.human_input.stop_move()
                time.sleep(0.1)  # 等待移动完全停止
            
            # === 3. 批量释放所有技能（技能之间有间隔，但不移动） ===
            for i, skill in enumerate(skills_to_release):
                if not self.is_running:
                    break
                
                # 释放单个技能（只按键，不移动）
                self._release_single_skill_only(skill)
                
                # 计算下次释放时间（随机提前释放）
                random_delay = random.uniform(0, skill.random_delay)
                wait_time = skill.interval - random_delay
                next_release_times[skill.key] = time.time() + wait_time
                
                self.status_update.emit(f"技能 {skill.key} 将在 {int(wait_time)} 秒后再次释放")
                
                # 只有当还有下一个技能要释放时，才需要间隔
                if i < len(skills_to_release) - 1:
                    gap_time = random.randint(SKILL_GAP_MIN_MS, SKILL_GAP_MAX_MS) / 1000.0
                    time.sleep(gap_time)
            
            # === 4. 所有技能释放完毕后移动回去（根据模式） ===
            self._move_after_skill()
            
        except Exception as e:
            error_msg = f"批量释放技能错误: {str(e)}"
            self.error_occurred.emit(error_msg)
            self.status_update.emit(error_msg)
        finally:
            # 确保移动停止
            self.human_input.stop_move()
    
    def _release_single_skill_only(self, skill: SkillConfig):
        """
        仅释放单个技能（只按键，不包含移动逻辑）
        用于批量释放时，在多个技能之间调用
        """
        try:
            self.status_update.emit(f"准备释放技能: {skill.key}")
            press_key(skill.key)
            self.skill_pressed.emit(skill.key)
        except Exception as e:
            error_msg = f"按键错误: {str(e)}"
            self.error_occurred.emit(error_msg)
            self.status_update.emit(error_msg)
    
    def _release_skill(self, skill: SkillConfig):
        """
        释放单个技能（包含前后移动逻辑）
        用于单独释放一个技能时（非批量场景）
        """
        # 使用批量方法处理，传入单个技能的列表
        dummy_next_times = {}
        self._release_skills_batch([skill], dummy_next_times)
    
    def _move_before_skill(self):
        """释放技能前移动（根据movement_mode决定方向）"""
        if not self.is_running:
            return
        
        if self.movement_mode == self.MOVEMENT_NONE:
            # 原地不动，不移动
            return
        elif self.movement_mode == self.MOVEMENT_RIGHT:
            # 向右走开buff
            self._move_direction("right", PRE_SKILL_MOVE_RIGHT_MIN_MS, PRE_SKILL_MOVE_RIGHT_MAX_MS)
        elif self.movement_mode == self.MOVEMENT_LEFT:
            # 向左走开buff
            self._move_direction("left", PRE_SKILL_MOVE_RIGHT_MIN_MS, PRE_SKILL_MOVE_RIGHT_MAX_MS)
    
    def _move_after_skill(self):
        """释放技能后移动回去（根据movement_mode决定方向）"""
        if not self.is_running:
            return
        
        if self.movement_mode == self.MOVEMENT_NONE:
            # 原地不动，不移动
            return
        elif self.movement_mode == self.MOVEMENT_RIGHT:
            # 向右走开buff后，向左回去
            self._move_direction("left", POST_SKILL_MOVE_LEFT_MIN_MS, POST_SKILL_MOVE_LEFT_MAX_MS)
        elif self.movement_mode == self.MOVEMENT_LEFT:
            # 向左走开buff后，向右回去
            self._move_direction("right", POST_SKILL_MOVE_LEFT_MIN_MS, POST_SKILL_MOVE_LEFT_MAX_MS)
    
    def _move_direction(self, direction: str, min_ms: int, max_ms: int):
        """
        向指定方向移动一段时间
        
        Args:
            direction: 移动方向 "left" 或 "right"
            min_ms: 最小移动时间（毫秒）
            max_ms: 最大移动时间（毫秒）
        """
        if not self.is_running:
            return
        
        move_duration = random.randint(min_ms, max_ms) / 1000.0
        direction_cn = "向左" if direction == "left" else "向右"
        self.status_update.emit(f"{direction_cn}移动 {int(move_duration * 1000)}ms...")
        
        if direction == "left":
            self.human_input.move_left()
        else:
            self.human_input.move_right()
        
        time.sleep(move_duration)
        self.human_input.stop_move()
    
    def _wait_for_attack_key_release(self):
        """等待攻击键松开后再继续"""
        if not KEYBOARD_AVAILABLE:
            return
        
        try:
            # 检查攻击键是否被按住
            attack_key = self.attack_key
            
            # 检测是否按住攻击键
            def is_attack_key_pressed():
                if attack_key == "ctrl":
                    return keyboard.is_pressed("ctrl") or keyboard.is_pressed("left ctrl") or keyboard.is_pressed("right ctrl")
                else:
                    return keyboard.is_pressed(attack_key)
            
            # 如果攻击键被按住，等待它被松开
            if is_attack_key_pressed():
                self.status_update.emit(f"检测到攻击键({attack_key})被按住，等待松开...")
                
                # 循环等待：松开后延迟，如果延迟期间又按下则重新等待
                while self.is_running:
                    # 等待攻击键松开
                    while is_attack_key_pressed() and self.is_running:
                        time.sleep(0.05)  # 50ms检测一次
                    
                    if not self.is_running:
                        return
                    
                    # 攻击键松开后，随机延迟200-500ms再释放技能
                    delay_ms = random.randint(ATTACK_KEY_RELEASE_DELAY_MIN_MS, ATTACK_KEY_RELEASE_DELAY_MAX_MS)
                    delay_seconds = delay_ms / 1000.0
                    self.status_update.emit(f"攻击键已松开，延迟 {delay_ms}ms 后释放技能")
                    
                    # 分段等待，每10ms检测一次攻击键是否又被按下
                    elapsed = 0
                    check_interval = 0.01  # 10ms
                    while elapsed < delay_seconds and self.is_running:
                        time.sleep(check_interval)
                        elapsed += check_interval
                        
                        # 如果在延迟期间攻击键又被按下，重新等待
                        if is_attack_key_pressed():
                            self.status_update.emit(f"延迟期间检测到攻击键再次按下，重新等待...")
                            break
                    
                    # 如果延迟期间没有按下攻击键，则完成等待
                    if elapsed >= delay_seconds:
                        break
                
        except Exception as e:
            # 如果检测失败，不影响技能释放
            pass
    
    def _ensure_game_window_focus(self):
        """确保游戏窗口获得焦点"""
        if self.window_selector and self.game_window_hwnd:
            try:
                self.window_selector.bring_window_to_front(self.game_window_hwnd)
            except Exception:
                pass  # 静默处理错误，不影响技能释放
    

