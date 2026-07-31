"""地图移动动作的独立实机测试窗口。"""

from PyQt6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout

from workers.map_action_worker import MapActionWorker


class MapActionTestDialog(QDialog):
    ACTIONS = (
        ("向左步行", "walk_left"),
        ("向右步行", "walk_right"),
        ("按下进入绳索", "enter_rope"),
        ("向上爬绳", "climb_up"),
        ("向下爬绳", "climb_down"),
        ("原地下跳", "drop"),
        ("向左走出平台", "walk_off_left"),
        ("向右走出平台", "walk_off_right"),
        ("向左跳抓绳", "jump_rope_left"),
        ("向右跳抓绳", "jump_rope_right"),
        ("向左跳离绳索", "dismount_left"),
        ("向右跳离绳索", "dismount_right"),
        ("使用传送点", "portal"),
    )

    def __init__(
        self,
        jump_key="Alt",
        hwnd=None,
        window_selector=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("地图动作测试")
        self.jump_key = jump_key
        self.hwnd = hwnd
        self.window_selector = window_selector
        self.worker = None
        layout = QVBoxLayout(self)
        self.status = QLabel("每次只执行一个动作；关闭窗口会立即释放方向键。")
        layout.addWidget(self.status)
        grid = QGridLayout()
        for index, (title, action) in enumerate(self.ACTIONS):
            button = QPushButton(title)
            button.clicked.connect(lambda _checked=False, value=action: self._start(value))
            grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(grid)
        stop_button = QPushButton("紧急停止并释放按键")
        stop_button.clicked.connect(self._stop)
        layout.addWidget(stop_button)

    def _start(self, action):
        self._stop()
        worker = MapActionWorker(
            action,
            self.jump_key,
            self.hwnd,
            self.window_selector,
            self,
        )
        worker.log_update.connect(self.status.setText)
        worker.error_signal.connect(lambda message: self.status.setText(f"错误：{message}"))
        worker.finished.connect(lambda current=worker: self._finished(current))
        self.worker = worker
        worker.start()

    def _stop(self):
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.stop()
            worker.wait(1500)

    def _finished(self, worker):
        if self.worker is worker:
            self.worker = None

    def closeEvent(self, event):
        self._stop()
        super().closeEvent(event)
