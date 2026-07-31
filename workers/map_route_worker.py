"""按实时黄点重新定位、规划并执行地图路径。"""

from __future__ import annotations

import random
import time

from PyQt6.QtCore import QThread, pyqtSignal
from pynput.keyboard import Key

from automation.human_input import HumanInput
from detection.minimap_monitor import MinimapMonitor
from models.map_navigation import MapNavigationGraphBuilder, MapPathPlanner
from models.map_topology import MinimapVisualMatcher, NormalizedMapPoint


class MapRouteWorker(QThread):
    log_update = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    route_finished = pyqtSignal(bool)

    MAX_ACTIONS = 30

    def __init__(
        self,
        hwnd,
        topology,
        target_reference_id,
        target_map_name=None,
        maps=None,
        jump_key="Alt",
        window_selector=None,
        parent=None,
    ):
        super().__init__(parent)
        self.hwnd = hwnd
        self.topology = topology
        self.maps = list(maps or [topology])
        self.current_topology = topology
        self.target_reference_id = target_reference_id
        self.target_map_name = target_map_name or topology.map_name
        self.jump_key = jump_key
        self.window_selector = window_selector
        self.human = HumanInput()
        self.monitor = MinimapMonitor()
        self.monitor.set_window_handle(hwnd)
        self._running = True

    def stop(self):
        self._running = False
        self.requestInterruption()
        self.human.release_all()

    def run(self):
        succeeded = False
        try:
            if self.window_selector and not self.window_selector.ensure_window_focus(self.hwnd):
                raise RuntimeError("无法激活游戏窗口")
            if self.monitor.auto_detect_dark_region() is None:
                raise RuntimeError("无法识别小地图")
            graph = MapNavigationGraphBuilder.build(self.maps)
            if not any(
                node.reference_id == self.target_reference_id
                and node.map_name == self.target_map_name
                for node in graph.nodes
            ):
                raise RuntimeError("目标节点不存在")

            consecutive_failures = 0
            for action_index in range(self.MAX_ACTIONS):
                if not self._running:
                    break
                point, topology = self._current_location()
                if point is None:
                    raise RuntimeError("连续未识别到玩家黄点")
                source = MapPathPlanner.locate_current_node(point, topology, graph)
                if source is None:
                    raise RuntimeError("玩家位置无法定位到路径图")
                if (
                    source.reference_id == self.target_reference_id
                    and source.map_name == self.target_map_name
                ):
                    succeeded = True
                    self.log_update.emit("已到达目标")
                    break
                path = MapPathPlanner.shortest_path_to_target(
                    graph,
                    source.id,
                    self.target_reference_id,
                    self.target_map_name,
                )
                if not path:
                    raise RuntimeError("当前位置到目标没有可执行路径")
                edge = path[0]
                destination = graph.node(edge.destination_id)
                self.log_update.emit(
                    f"执行 {edge.kind}（{action_index + 1}/{self.MAX_ACTIONS}）"
                )
                if not self._execute_edge(edge, source, destination):
                    consecutive_failures += 1
                    self.log_update.emit(
                        f"动作 {edge.kind} 未确认到达，重新定位"
                        f"（{consecutive_failures}/3）"
                    )
                    if consecutive_failures >= 3:
                        raise RuntimeError(
                            f"动作 {edge.kind} 连续失败，已安全停止"
                        )
                    continue
                consecutive_failures = 0
            else:
                raise RuntimeError("路径执行超过最大动作次数，已安全停止")
        except Exception as error:
            self.error_signal.emit(str(error))
        finally:
            self.human.release_all()
            self.route_finished.emit(succeeded)

    def _execute_edge(self, edge, source, destination):
        if edge.kind in {"walk", "approach"}:
            return self._walk_to(destination.point)
        if edge.kind == "climb":
            return self._climb_to(destination.point)
        if edge.kind == "drop":
            if edge.direction in {"left", "right"}:
                self._walk_off(
                    edge.direction,
                    edge.key_hold_milliseconds / 1000,
                )
            else:
                self._drop()
            return self._wait_near(
                destination.point,
                4.0,
                edge.landing_tolerance,
                destination.map_name,
            )
        if edge.kind == "jump":
            self._jump_rope(edge.direction)
            return self._wait_near(
                destination.point,
                4.0,
                edge.landing_tolerance,
                destination.map_name,
            )
        if edge.kind == "approach_rope":
            if source.kind == "platform" and destination.kind == "rope":
                direction = "right" if destination.point.x >= source.point.x else "left"
                self._jump_rope(direction)
            else:
                direction = "right" if destination.point.x >= source.point.x else "left"
                self._dismount(direction)
            return self._wait_near(
                destination.point,
                3.0,
                0.15,
                destination.map_name,
            )
        if edge.kind == "portal":
            self.human.use_portal()
            return self._wait_near(
                destination.point,
                4.0,
                0.18,
                destination.map_name,
            )
        return False

    def _walk_to(self, target):
        deadline = time.monotonic() + 5
        missing = 0
        while self._running and time.monotonic() < deadline:
            current = self._player_point()
            if current is None:
                missing += 1
                if missing >= 8:
                    break
                self._sleep(0.08)
                continue
            missing = 0
            delta = target.x - current.x
            if abs(delta) <= 0.025:
                self.human.stop_move()
                self._sleep(random.uniform(0.08, 0.16))
                return True
            self.human._change_direction("right" if delta > 0 else "left")
            self._sleep(random.uniform(0.06, 0.11))
        self.human.stop_move()
        return False

    def _climb_to(self, target):
        deadline = time.monotonic() + 6
        while self._running and time.monotonic() < deadline:
            current = self._player_point()
            if current is None:
                self._sleep(0.08)
                continue
            delta = target.y - current.y
            if abs(delta) <= 0.035:
                self.human.stop_move()
                return True
            self.human._change_direction("down" if delta > 0 else "up")
            self._sleep(random.uniform(0.07, 0.12))
        self.human.stop_move()
        return False

    def _wait_near(self, target, timeout, tolerance, map_name=None):
        deadline = time.monotonic() + timeout
        while self._running and time.monotonic() < deadline:
            current, topology = self._current_location()
            if current is not None and (
                map_name is None or topology.map_name == map_name
            ):
                distance = ((current.x - target.x) ** 2 + (current.y - target.y) ** 2) ** 0.5
                if distance <= tolerance:
                    return True
            self._sleep(0.1)
        return False

    def _current_location(self):
        image = self.monitor.capture_minimap()
        if image is None:
            return None, self.current_topology
        point, _ = MinimapMonitor.find_player_position_in_image(image)
        if point is None:
            return None, self.current_topology
        signature = MinimapVisualMatcher.signature(image)
        matches = []
        for topology in self.maps:
            if topology.visual_signature:
                comparison = MinimapVisualMatcher.comparison(
                    signature,
                    topology.visual_signature,
                )
                if comparison["isMatch"]:
                    matches.append((comparison["similarityPercentage"], topology))
        if matches:
            self.current_topology = max(matches, key=lambda item: item[0])[1]
        return (
            NormalizedMapPoint.from_pixel(
                point,
                (image.shape[1], image.shape[0]),
            ),
            self.current_topology,
        )

    def _player_point(self):
        return self._current_location()[0]

    def _drop(self):
        jump = self._jump_key()
        self.human.keyboard.press(Key.down)
        self._sleep(random.uniform(0.08, 0.14))
        self.human.keyboard.press(jump)
        self._sleep(random.uniform(0.08, 0.13))
        self.human.keyboard.release(Key.down)
        self._sleep(random.uniform(0.03, 0.07))
        self.human.keyboard.release(jump)

    def _jump_rope(self, direction):
        jump = self._jump_key()
        direction_key = Key.right if direction == "right" else Key.left
        self.human.keyboard.press(direction_key)
        self._sleep(random.uniform(0.08, 0.13))
        self.human.keyboard.press(jump)
        self._sleep(random.uniform(0.10, 0.16))
        self.human.keyboard.press(Key.up)
        self._sleep(random.uniform(0.12, 0.20))
        self.human.keyboard.release(jump)
        self.human.keyboard.release(direction_key)
        self._sleep(random.uniform(0.06, 0.10))
        self.human.keyboard.release(Key.up)

    def _walk_off(self, direction, seconds=0.25):
        self.human._change_direction(direction)
        self._sleep(max(0.15, min(seconds, 1.2)))
        self.human.stop_move()

    def _dismount(self, direction):
        jump = self._jump_key()
        direction_key = Key.right if direction == "right" else Key.left
        self.human.keyboard.press(direction_key)
        self._sleep(random.uniform(0.045, 0.115))
        self.human.keyboard.press(jump)
        self._sleep(random.uniform(0.07, 0.14))
        self.human.keyboard.release(jump)
        self._sleep(random.uniform(0.025, 0.08))
        self.human.keyboard.release(direction_key)

    def _jump_key(self):
        normalized = str(self.jump_key).strip().lower()
        return {
            "alt": Key.alt,
            "ctrl": Key.ctrl,
            "shift": Key.shift,
            "space": Key.space,
        }.get(normalized, normalized[:1] or Key.alt)

    def _sleep(self, seconds):
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
