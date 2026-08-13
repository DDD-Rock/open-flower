"""神殿挂绳组队第一阶段：队长首次建队邀请，成员等待邀请。"""

from __future__ import annotations

import queue
import random
import time

from PyQt6.QtCore import QThread, pyqtSignal

from automation.human_input import HumanInput, input_transaction_lock
from detection.minimap_monitor import MinimapMonitor
from utils.countdown import remaining_seconds
from utils.keyboard_utils import press_key
from utils.window_selector import WindowSelector
from utils.rope_party import build_remove_member_command, build_rope_party_commands


class RopePartyWorker(QThread):
    log_update = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    team_disbanded = pyqtSignal()
    buff_due = pyqtSignal()
    boss_joined = pyqtSignal(int)
    boss_buffs_completed = pyqtSignal(int)
    party_commands_finished = pyqtSignal()
    party_rebuild_commands_finished = pyqtSignal(int)
    countdown_update = pyqtSignal(dict)

    def __init__(self, hwnd: int, is_leader: bool, first_creation: bool, invite_role_names: list[str], disband_only: bool = False, remove_role_name: str = "", buffs=None):
        super().__init__()
        self.hwnd = hwnd
        self.is_running = True
        self.disband_only = disband_only
        self.remove_role_name = remove_role_name.strip()
        self.invite_role_names = [name.strip() for name in invite_role_names if name.strip()]
        if self.remove_role_name:
            self.commands = [build_remove_member_command(self.remove_role_name)]
        else:
            self.commands = ["/退出隊伍"] if disband_only else build_rope_party_commands(is_leader, first_creation, invite_role_names)
        self.human = HumanInput()
        self.window_selector = WindowSelector()
        self.pending_commands = queue.Queue()
        self.buffs = [buff for buff in (buffs or []) if buff.enabled and buff.key]
        now = time.time()
        self.buff_deadlines = {buff.key: now + float(buff.duration) for buff in self.buffs}
        self.next_buff_due_report_at = 0.0
        self.monitor = MinimapMonitor()
        self.monitor.set_window_handle(hwnd)
        self.boss_cycle_id = 0
        self.boss_cycle_requested_id = 0
        self.boss_role_name = ""
        self.boss_orange_baseline = None
        self.boss_orange_candidate = None
        self.boss_orange_candidate_frames = 0
        self.boss_minimap_ready = False
        self.next_boss_invite_at = 0.0
        self.boss_join_detected_cycle_id = 0
        self.next_boss_joined_report_at = 0.0
        self.latest_boss_buff_cycle_id = 0
        self.latest_boss_disband_cycle_id = 0

    def enqueue_remove_member(self, role_name: str):
        role_name = role_name.strip()
        if role_name:
            self.pending_commands.put(build_remove_member_command(role_name))

    def start_boss_invite_cycle(self, cycle_id: int, role_name: str):
        if self.boss_cycle_id == int(cycle_id) or self.boss_cycle_requested_id == int(cycle_id):
            return
        self.boss_cycle_requested_id = int(cycle_id)
        self.pending_commands.put(("start_boss_invite", int(cycle_id), role_name.strip()))

    def cast_boss_buffs(self, cycle_id: int):
        self.pending_commands.put(("cast_boss_buffs", int(cycle_id)))

    def disband_boss_party(self, cycle_id: int):
        cycle_id = int(cycle_id)
        if cycle_id <= 0 or cycle_id <= self.latest_boss_disband_cycle_id:
            return
        self.latest_boss_disband_cycle_id = cycle_id
        self.pending_commands.put(("disband_boss_party", cycle_id))

    def run(self):
        try:
            self._update_countdown_display()
            last_countdown_update = time.time()
            if self.remove_role_name:
                self.log_update.emit(f"收到网页移除队伍成员指令：{self.remove_role_name}")
            else:
                self.log_update.emit("收到网页解散队伍指令" if self.disband_only else "神殿模式 · 挂绳组队启动")
            if self.commands:
                for index, command in enumerate(self.commands):
                    if not self.is_running or self.isInterruptionRequested():
                        return
                    if not self._send_chat_command(command):
                        return
                    self.log_update.emit(f"已发送队伍指令：{command}")
                    if index < len(self.commands) - 1:
                        self._sleep(random.uniform(0.55, 1.15))
                if self.remove_role_name:
                    self.log_update.emit(f"已发送移除成员指令：{self.commands[0]}")
                else:
                    self.log_update.emit("已发送解散队伍指令：/退出隊伍" if self.disband_only else "首次建队指令已发送完毕")
                if self.disband_only:
                    self.team_disbanded.emit()
                elif not self.remove_role_name:
                    self.party_commands_finished.emit()
            elif not self.remove_role_name:
                self.log_update.emit("等待并自动接受队伍邀请")
            if self.disband_only or self.remove_role_name:
                return
            while self.is_running and not self.isInterruptionRequested():
                now = time.time()
                if now - last_countdown_update >= 1.0:
                    last_countdown_update = now
                    self._update_countdown_display(now)
                if not self.window_selector.is_window_valid(self.hwnd):
                    self.error_signal.emit("游戏窗口已失效，挂绳组队已停止")
                    break
                try:
                    command = self.pending_commands.get_nowait()
                except queue.Empty:
                    command = None
                if command:
                    if isinstance(command, tuple):
                        if not self._handle_boss_action(command):
                            break
                    else:
                        if not self._send_chat_command(command):
                            break
                        self.log_update.emit(f"已发送移除成员指令：{command}")
                if not self._process_boss_invite_cycle():
                    break
                self._report_buff_due_if_needed()
                self._sleep(0.5)
        except Exception as exc:
            self.error_signal.emit(f"挂绳组队出错：{exc}")
        finally:
            self.is_running = False
            self.countdown_update.emit({})
            self.human.release_all()
            self.finished_signal.emit()

    def _send_chat_command(self, command: str):
        with input_transaction_lock:
            if not self._ensure_game_focus():
                self.error_signal.emit(f"发送指令前无法确认游戏窗口焦点：{command}")
                return False
            self._sleep(random.uniform(0.2, 0.45))
            if not self.is_running or self.isInterruptionRequested():
                return False

            # Once chat is opened, always finish the second Enter. A stop or
            # reconfigure request takes effect after this command completes.
            self.human.press_enter()
            self._sleep(random.uniform(0.18, 0.42))
            self.human.press_delete()
            self._sleep(random.uniform(0.08, 0.18))
            self.human.type_text(command)
            self._sleep(random.uniform(0.12, 0.32))
            self.human.press_enter()
            return True

    def _handle_boss_action(self, action) -> bool:
        kind = action[0]
        if kind == "start_boss_invite":
            _, cycle_id, role_name = action
            if cycle_id > 0 and role_name:
                self.boss_cycle_requested_id = 0
                self.boss_cycle_id = cycle_id
                self.boss_role_name = role_name
                self.boss_orange_baseline = None
                self.boss_orange_candidate = None
                self.boss_orange_candidate_frames = 0
                self.boss_minimap_ready = False
                self.next_boss_invite_at = 0.0
                self.boss_join_detected_cycle_id = 0
                self.next_boss_joined_report_at = 0.0
                self.log_update.emit(f"老板 Buff 周期 {cycle_id} 启动，等待小地图基线后邀请 {role_name}")
            return True
        if kind == "cast_boss_buffs":
            cycle_id = action[1]
            if cycle_id <= self.latest_boss_buff_cycle_id:
                return True
            self.latest_boss_buff_cycle_id = cycle_id
            self.boss_cycle_requested_id = 0
            self.boss_cycle_id = 0
            self.boss_join_detected_cycle_id = 0
            if self._cast_all_buffs():
                self.boss_buffs_completed.emit(cycle_id)
            return True
        if kind == "disband_boss_party":
            cycle_id = action[1]
            if not self._send_chat_command("/退出隊伍"):
                return False
            self.log_update.emit("老板 BUFF 周期完成，已发送解散队伍指令：/退出隊伍")
            self._sleep(random.uniform(0.8, 1.4))
            rebuild_commands = build_rope_party_commands(True, True, self.invite_role_names)[1:]
            for index, command in enumerate(rebuild_commands):
                if not self._send_chat_command(command):
                    return False
                self.log_update.emit(f"已发送重建队伍指令：{command}")
                if index < len(rebuild_commands) - 1:
                    self._sleep(random.uniform(0.55, 1.15))
            self.party_rebuild_commands_finished.emit(cycle_id)
            return True
        return True

    def _process_boss_invite_cycle(self) -> bool:
        if self.boss_cycle_id <= 0:
            return True
        if not self.boss_minimap_ready:
            if self.monitor.auto_detect_dark_region() is None:
                return True
            self.boss_minimap_ready = True
        frame = self.monitor.capture_minimap()
        if frame is None:
            return True
        orange_count = len(MinimapMonitor.find_teammate_positions_in_image(frame))
        if self.boss_orange_candidate == orange_count:
            self.boss_orange_candidate_frames += 1
        else:
            self.boss_orange_candidate = orange_count
            self.boss_orange_candidate_frames = 1
        if self.boss_orange_candidate_frames >= 2:
            if self.boss_orange_baseline is None:
                self.boss_orange_baseline = orange_count
                self.log_update.emit(f"老板邀请前橙点基线：{orange_count}")
            elif orange_count > self.boss_orange_baseline:
                cycle_id = self.boss_cycle_id
                self.log_update.emit(
                    f"橙点数量由 {self.boss_orange_baseline} 变为 {orange_count}，判定老板已进队"
                )
                self.boss_join_detected_cycle_id = cycle_id
                self.next_boss_joined_report_at = 0.0
        if self.boss_join_detected_cycle_id == self.boss_cycle_id:
            cycle_id = self.boss_cycle_id
            self.boss_joined.emit(cycle_id)
            self.log_update.emit(f"已上报老板进队，等待服务端下发放 BUFF：{cycle_id}")
            self.boss_cycle_id = 0
            return True
        if self.boss_orange_baseline is not None and time.time() >= self.next_boss_invite_at:
            command = f"/邀請組隊 {self.boss_role_name}"
            if not self._send_chat_command(command):
                self.next_boss_invite_at = time.time() + 8.0
                return True
            self.log_update.emit(f"已发送老板邀请：{command}")
            self.next_boss_invite_at = time.time() + 8.0
        return True

    def _report_buff_due_if_needed(self):
        if not self.buffs:
            return
        if self.boss_cycle_requested_id > 0 or self.boss_cycle_id > 0:
            return
        now = time.time()
        minimum_remaining = min(self.buff_deadlines.values(), default=now) - now
        if minimum_remaining <= 10 and now >= self.next_buff_due_report_at:
            self.buff_due.emit()
            self.next_buff_due_report_at = now + 8.0

    def _update_countdown_display(self, now=None):
        current_time = time.time() if now is None else now
        self.countdown_update.emit({
            buff.key: remaining_seconds(self.buff_deadlines[buff.key], current_time)
            for buff in self.buffs
            if buff.key in self.buff_deadlines
        })

    def _cast_all_buffs(self) -> bool:
        with input_transaction_lock:
            if not self.buffs:
                return True
            if not self._ensure_game_focus():
                self.error_signal.emit("强制释放老板 BUFF 前无法确认游戏窗口焦点")
                return False
            for index, buff in enumerate(self.buffs):
                if not self.is_running or self.isInterruptionRequested():
                    return False
                try:
                    press_key(buff.key)
                    self._sleep(random.uniform(0.1, 0.3))
                    press_key(buff.key)
                    self.log_update.emit(f"老板进队触发，已释放 BUFF：{buff.key}")
                except Exception as exc:
                    self.error_signal.emit(f"强制释放 BUFF {buff.key} 失败：{exc}")
                if index < len(self.buffs) - 1:
                    self._sleep(random.uniform(2.0, 3.0))
            now = time.time()
            self.buff_deadlines = {buff.key: now + float(buff.duration) for buff in self.buffs}
            self._update_countdown_display(now)
            self.next_buff_due_report_at = 0.0
            return True

    def _ensure_game_focus(self) -> bool:
        # Force the selected HWND to the foreground even when Windows reports it
        # as already active, then verify the exact handle after activation settles.
        self.window_selector.bring_window_to_front(self.hwnd)
        self._sleep(0.15)
        if not self.is_running or self.isInterruptionRequested():
            return False
        return self.window_selector.ensure_window_focus(
            self.hwnd,
            attempts=12,
            delay=0.15,
        )

    def _sleep(self, seconds: float):
        deadline = time.monotonic() + seconds
        while self.is_running and not self.isInterruptionRequested() and time.monotonic() < deadline:
            time.sleep(min(0.1, deadline - time.monotonic()))

    def stop(self):
        self.is_running = False
        self.requestInterruption()
        if self.isRunning():
            self.wait()
