"""只读取小地图黄点，为平台/绳索自动采集轨迹。"""

import time

from PyQt6.QtCore import QThread, pyqtSignal

from detection.minimap_monitor import MinimapMonitor


class MapTraceWorker(QThread):
    sample_ready = pyqtSignal(tuple)
    status_update = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, hwnd, window_selector=None, parent=None):
        super().__init__(parent)
        self.hwnd = hwnd
        self.window_selector = window_selector
        self.monitor = MinimapMonitor()
        self.monitor.set_window_handle(hwnd)
        self._running = True

    def stop(self):
        self._running = False
        self.requestInterruption()

    def run(self):
        try:
            if self.window_selector and not self.window_selector.is_window_valid(self.hwnd):
                raise RuntimeError("游戏窗口已失效")
            if self.monitor.auto_detect_dark_region() is None:
                raise RuntimeError("无法识别小地图")
            missing = 0
            while self._running and not self.isInterruptionRequested():
                image = self.monitor.capture_minimap()
                if image is None:
                    missing += 1
                else:
                    point, _ = MinimapMonitor.find_player_position_in_image(image)
                    if point is None:
                        missing += 1
                    else:
                        missing = 0
                        self.sample_ready.emit((float(point[0]), float(point[1])))
                if missing == 15:
                    self.status_update.emit("暂未识别到玩家黄点")
                time.sleep(1 / 30)
        except Exception as error:
            self.error_signal.emit(str(error))
