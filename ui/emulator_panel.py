"""UI for discovering, launching, and previewing MuMu instances."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QListView,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class EmulatorPanel(QFrame):
    refresh_requested = pyqtSignal()
    start_requested = pyqtSignal(str)
    settings_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._rows = {}
        self._running = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title = QLabel("MuMu 实例")
        title.setStyleSheet("font-size:14px;font-weight:700;")
        subtitle = QLabel("自动扫描本机实例，在线设备持续显示实时画面")
        subtitle.setStyleSheet("color:#747D8D;font-size:9px;")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch(1)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.summary_label = QLabel("正在扫描本机 MuMu 实例…")
        self.summary_label.setStyleSheet("color:#5F6878;")
        layout.addWidget(self.summary_label)

        self.device_list = QListWidget()
        self.device_list.setSpacing(6)
        self.device_list.setFrameShape(QFrame.Shape.NoFrame)
        self.device_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.device_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.device_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.device_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.device_list.setStyleSheet(
            "QListWidget{background:transparent;border:0;}"
            "QListWidget::item{border:0;padding:0;}"
            "QScrollBar:vertical{width:8px;background:transparent;}"
            "QScrollBar::handle:vertical{background:#CBD4E1;border-radius:4px;min-height:28px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )
        layout.addWidget(self.device_list, 1)

    def set_running(self, running: bool):
        self._running = running
        self.refresh_button.setEnabled(running)
        for _, row in self._rows.values():
            row.set_controls_enabled(running)

    def set_status(self, text: str):
        self.summary_label.setText(text)

    def update_devices(self, devices: list[dict]):
        current_ids = {
            device.get("id") or f"adb:{device.get('serial', '')}" for device in devices
        }
        for device_id in set(self._rows) - current_ids:
            item, _ = self._rows.pop(device_id)
            row_index = self.device_list.row(item)
            if row_index >= 0:
                self.device_list.takeItem(row_index)
        if not devices:
            self.summary_label.setText("未发现 MuMu 实例，请确认 MuMuPlayer 已安装")
            return
        online = sum(item.get("state") == "device" for item in devices)
        streaming = sum(bool(item.get("streaming")) for item in devices)
        self.summary_label.setText(
            f"共 {len(devices)} 个实例，在线 {online} 路，视频流 {streaming} 路"
        )
        for index, device in enumerate(devices, start=1):
            device_id = device.get("id") or f"adb:{device.get('serial', '')}"
            existing = self._rows.get(device_id)
            if existing is None:
                item = QListWidgetItem()
                row = EmulatorRow()
                row.start_requested.connect(self.start_requested.emit)
                row.settings_requested.connect(self.settings_requested.emit)
                item.setSizeHint(QSize(0, 94))
                self.device_list.addItem(item)
                self.device_list.setItemWidget(item, row)
                self._rows[device_id] = (item, row)
            else:
                item, row = existing
            row.update_metadata(index, device)
            row.set_controls_enabled(self._running)
            item.setSizeHint(QSize(0, 94))

    def update_frame(self, serial: str, frame, fps: float):
        for _, row in self._rows.values():
            if row.serial == serial:
                row.update_frame(frame, fps)
                break

    def update_analysis(self, serial: str, analysis):
        for _, row in self._rows.values():
            if row.serial == serial:
                row.update_analysis(analysis)
                break


class EmulatorRow(QFrame):
    start_requested = pyqtSignal(str)
    settings_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame_size = None
        self._vm_index = ""
        self._state = "unknown"
        self._analysis_state = "unknown"
        self._controls_enabled = False
        self._device = {}
        self.serial = ""
        self.setObjectName("emulatorRow")
        self.setFixedHeight(94)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "QFrame#emulatorRow{background:#F8FAFD;border:1px solid #E2E8F2;border-radius:9px;}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(9)

        self.preview = QLabel("正在连接视频流")
        self.preview.setFixedSize(124, 70)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:#151A24;border-radius:6px;color:#AAB2C0;")
        layout.addWidget(self.preview)

        info = QVBoxLayout()
        info.setSpacing(3)
        self.name_label = QLabel()
        self.name_label.setStyleSheet("font-size:12px;font-weight:700;color:#172033;")
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        info.addWidget(self.name_label)
        self.serial_label = QLabel()
        self.serial_label.setStyleSheet(
            "font-family:Consolas;color:#5F6878;font-size:9px;"
        )
        self.serial_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        info.addWidget(self.serial_label)
        self.status_label = QLabel()
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        info.addWidget(self.status_label)
        self.model_label = QLabel()
        self.model_label.setStyleSheet("color:#8791A3;font-size:9px;")
        self.model_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        info.addWidget(self.model_label)
        info.addStretch(1)
        layout.addLayout(info, 1)

        self.start_button = QPushButton("启动")
        self.start_button.setFixedSize(56, 30)
        self.start_button.setToolTip("启动这个 MuMu 实例")
        self.start_button.clicked.connect(self._emit_action_requested)
        layout.addWidget(self.start_button)

    def _emit_action_requested(self):
        if self._state == "device" and self._analysis_state == "in_game":
            self.settings_requested.emit(dict(self._device))
        elif self._vm_index:
            self.start_requested.emit(self._vm_index)

    def set_controls_enabled(self, enabled: bool):
        self._controls_enabled = enabled
        self._sync_action_button()

    def _sync_action_button(self):
        show_settings = (
            self._state == "device" and self._analysis_state == "in_game"
        )
        show_start = bool(self._vm_index) and self._state != "device"
        self.start_button.setVisible(show_settings or show_start)
        if show_settings:
            self.start_button.setText("设置")
            self.start_button.setToolTip("打开这个视频流的控制配置")
            self.start_button.setEnabled(self._controls_enabled)
            return
        if self._state == "booting":
            text = "启动中"
        elif self._state == "connecting":
            text = "连接中"
        else:
            text = "重试" if self._device.get("launch_error") else "启动"
        self.start_button.setText(text)
        self.start_button.setToolTip("启动这个 MuMu 实例")
        self.start_button.setEnabled(
            self._controls_enabled
            and self._state == "offline"
            and bool(self._vm_index)
        )

    def update_metadata(self, index: int, device: dict):
        previous_serial = self.serial
        self._device = dict(device)
        self._vm_index = str(device.get("vm_index") or "")
        self._state = device.get("state", "unknown")
        self.serial = device.get("serial") or ""
        if self.serial != previous_serial or self._state != "device":
            self._analysis_state = "unknown"
        name = device.get("name") or f"MuMu-{index}"
        if self._vm_index:
            display_name = f"{self._vm_index} · {name}"
            self.name_label.setText(display_name)
        else:
            display_name = name
            self.name_label.setText(display_name)
        self.name_label.setToolTip(display_name)
        self.serial_label.setText(self.serial or "ADB 尚未分配")
        self.model_label.setText(device.get("model") or "")
        state = self._state
        error = device.get("frame_error")
        launch_error = device.get("launch_error")
        if (
            state != "device" or self.serial != previous_serial
        ) and self._frame_size is not None:
            self._frame_size = None
            self.preview.clear()
        if self._frame_size is not None:
            width, height = self._frame_size
            text = f"视频流正常 · {width}×{height}"
            color = "#19A866"
        elif launch_error:
            text = f"启动失败 · {launch_error}"
            color = "#E9404A"
        elif error:
            text = f"连接失败 · {error}"
            color = "#E9404A"
        elif state == "device" and device.get("streaming"):
            text = "ADB 已连接 · 正在等待首帧"
            color = "#E78A15"
        elif state == "device":
            text = "ADB 已连接 · 正在启动视频流"
            color = "#E78A15"
        elif state == "booting":
            text = "MuMu 正在启动"
            color = "#E78A15"
        elif state == "connecting":
            text = "Android 已启动 · 正在连接 ADB"
            color = "#E78A15"
        elif state == "offline":
            text = "未启动"
            color = "#8791A3"
        else:
            text = f"ADB 状态：{state}"
            color = "#E9404A"
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};font-weight:600;")
        self._sync_action_button()
        if state == "offline":
            self.preview.setText("未启动")
        elif state == "booting":
            self.preview.setText("正在启动")
        elif state == "connecting":
            self.preview.setText("正在连接 ADB")
        elif state == "device" and self._frame_size is None:
            self.preview.setText("正在连接视频流")

    def update_frame(self, frame, fps: float):
        height, width, channels = frame.shape
        self._frame_size = (width, height)
        image = QImage(
            frame.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_BGR888,
        ).copy()
        self.preview.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        if self._analysis_state == "in_game":
            prefix = "游戏画面已识别"
        elif self._analysis_state == "loading":
            prefix = "过图中 / 状态未知"
        else:
            prefix = "视频流正常"
        self.status_label.setText(f"{prefix} · {width}×{height} · {fps:.1f} FPS")
        self.status_label.setStyleSheet("color:#19A866;font-weight:600;")

    def update_analysis(self, analysis):
        self._analysis_state = analysis.game_state
        self._sync_action_button()
