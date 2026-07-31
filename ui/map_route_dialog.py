"""选择目标平台并执行实时重规划路径。"""

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from models.map_navigation import MapNavigationGraphBuilder, MapPathPlanner
from workers.map_route_worker import MapRouteWorker


class MapRouteDialog(QDialog):
    def __init__(
        self,
        hwnd,
        topology,
        maps=None,
        jump_key="Alt",
        window_selector=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"路径执行 · {topology.map_name}")
        self.hwnd = hwnd
        self.topology = topology
        self.maps = list(maps or [topology])
        self.jump_key = jump_key
        self.window_selector = window_selector
        self.worker = None

        layout = QVBoxLayout(self)
        graph = MapNavigationGraphBuilder.build(self.maps)
        disconnected = MapPathPlanner.disconnected_nodes(graph)
        layout.addWidget(
            QLabel(
                f"节点 {len(graph.nodes)} · 路径边 {len(graph.edges)}"
                f" · 未连通节点 {len(disconnected)}"
            )
        )
        row = QHBoxLayout()
        row.addWidget(QLabel("目标"))
        self.target = QComboBox()
        for item in self.maps:
            for index, platform in enumerate(item.platforms):
                self.target.addItem(
                    f"{item.map_name} · P{index + 1}",
                    (item.map_name, platform.id),
                )
            for index, portal in enumerate(item.portals):
                self.target.addItem(
                    f"{item.map_name} · T{index + 1}",
                    (item.map_name, portal.id),
                )
        row.addWidget(self.target)
        layout.addLayout(row)

        self.status = QLabel("执行过程中会按实时黄点在每一步后重新规划。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controls = QHBoxLayout()
        self.start_button = QPushButton("开始执行")
        self.stop_button = QPushButton("紧急停止")
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)

    def _start(self):
        if self.worker is not None or self.target.currentData() is None:
            return
        target_map_name, target_reference_id = self.target.currentData()
        worker = MapRouteWorker(
            hwnd=self.hwnd,
            topology=self.topology,
            target_reference_id=target_reference_id,
            target_map_name=target_map_name,
            maps=self.maps,
            jump_key=self.jump_key,
            window_selector=self.window_selector,
            parent=self,
        )
        worker.log_update.connect(self.status.setText)
        worker.error_signal.connect(lambda message: self.status.setText(f"错误：{message}"))
        worker.route_finished.connect(lambda succeeded: self.status.setText("路径执行完成" if succeeded else self.status.text()))
        worker.finished.connect(lambda current=worker: self._finished(current))
        self.worker = worker
        self.start_button.setEnabled(False)
        worker.start()

    def _stop(self):
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.stop()
            worker.wait(2000)
        self.start_button.setEnabled(True)

    def _finished(self, worker):
        if self.worker is worker:
            self.worker = None
        self.start_button.setEnabled(True)

    def closeEvent(self, event):
        self._stop()
        super().closeEvent(event)
