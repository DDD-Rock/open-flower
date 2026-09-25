"""Per-stream configuration window for the experimental emulator mode."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import DEFAULT_BUFF_SLOT_COUNT, MAX_BUFF_SLOT_COUNT
from ui.virtual_keyboard import VirtualKeyboardDialog


class _ClickableMinimapLabel(QLabel):
    """Clickable label which reports coordinates in the unscaled map image."""

    clicked = pyqtSignal(int, int)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.pixmap() is not None:
            pixmap = self.pixmap()
            if not pixmap.isNull() and pixmap.width() and pixmap.height():
                x0 = (self.width() - pixmap.width()) / 2
                y0 = (self.height() - pixmap.height()) / 2
                x = (event.position().x() - x0) * self._source_width / pixmap.width()
                y = (event.position().y() - y0) * self._source_height / pixmap.height()
                if 0 <= x < self._source_width and 0 <= y < self._source_height:
                    self.clicked.emit(int(round(x)), int(round(y)))
        super().mousePressEvent(event)

    def set_source_size(self, width: int, height: int):
        self._source_width = max(1, int(width))
        self._source_height = max(1, int(height))


class EmulatorStreamDialog(QDialog):
    redetect_minimap_requested = pyqtSignal(str)
    smart_walk_anchor_selected = pyqtSignal(str, int, int)
    smart_walk_config_changed = pyqtSignal(str, object)
    active_mode_changed = pyqtSignal(str)

    def __init__(self, device: dict, parent=None):
        super().__init__(parent)
        self.serial = device.get("serial") or ""
        self.vm_index = str(device.get("vm_index") or "")
        self._minimap_image = None
        self._minimap_rect = None
        self.smart_walk_anchor = None
        self.smart_walk_half_width = 10
        self.smart_walk_min_minutes = 15
        self.smart_walk_max_minutes = 30
        self.smart_walk_jump_key = "Alt"
        self._active_mode = "live_flower"
        self._last_countdowns = {}
        name = device.get("name") or f"MuMu-{self.vm_index}"
        self.setWindowTitle(f"{name} · 视频流设置")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(820, 780)
        self.setMinimumSize(680, 460)
        self.setStyleSheet(
            "QDialog{background:#F4F7FB;color:#172033;}"
            "QLabel#sectionTitle{font-size:13px;font-weight:700;color:#172033;}"
            "QLabel#muted{color:#747D8D;}"
            "QFrame#previewSurface{background:#111722;border:1px solid #D8E0EC;border-radius:6px;}"
            "QFrame#statusPane{background:#FFFFFF;border-left:1px solid #DFE6F0;}"
            "QFrame#developmentPane{background:#FFFFFF;border-top:1px solid #DFE6F0;}"
            "QScrollArea#liveFlowerScroll{background:#FFFFFF;border:0;}"
            "QScrollArea#liveFlowerScroll > QWidget > QWidget{background:#FFFFFF;}"
            "QScrollBar:vertical{width:8px;background:transparent;margin:2px;}"
            "QScrollBar::handle:vertical{background:#CBD4E1;border-radius:4px;min-height:28px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        upper = QWidget()
        upper_layout = QHBoxLayout(upper)
        upper_layout.setContentsMargins(18, 18, 18, 16)
        upper_layout.setSpacing(0)

        preview_column = QWidget()
        preview_layout = QVBoxLayout(preview_column)
        preview_layout.setContentsMargins(0, 0, 18, 0)
        preview_layout.setSpacing(8)
        preview_title = QLabel("实时小地图")
        preview_title.setObjectName("sectionTitle")
        preview_layout.addWidget(preview_title)
        self.preview_surface = QFrame()
        self.preview_surface.setObjectName("previewSurface")
        self.preview_surface.setMinimumSize(360, 170)
        self.preview_surface.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        surface_layout = QVBoxLayout(self.preview_surface)
        surface_layout.setContentsMargins(10, 10, 10, 10)
        self.minimap_label = _ClickableMinimapLabel("等待小地图画面")
        self.minimap_label._source_width = 1
        self.minimap_label._source_height = 1
        self.minimap_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.minimap_label.setStyleSheet("color:#AAB2C0;")
        self.minimap_label.clicked.connect(self._on_minimap_clicked)
        surface_layout.addWidget(self.minimap_label)
        preview_layout.addWidget(self.preview_surface, 1)
        upper_layout.addWidget(preview_column, 2)

        status_pane = QFrame()
        status_pane.setObjectName("statusPane")
        status_pane.setMinimumWidth(230)
        status_layout = QVBoxLayout(status_pane)
        status_layout.setContentsMargins(22, 0, 4, 0)
        status_layout.setSpacing(8)
        status_title = QLabel("玩家位置")
        status_title.setObjectName("sectionTitle")
        status_layout.addWidget(status_title)
        self.redetect_button = QPushButton("再次识别小地图")
        self.redetect_button.setToolTip("重新查找当前视频流中的小地图范围")
        self.redetect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.redetect_button.clicked.connect(
            lambda: self.redetect_minimap_requested.emit(self.serial)
        )
        status_layout.addWidget(self.redetect_button)
        self.coordinate_label = QLabel("X: --\nY: --")
        self.coordinate_label.setStyleSheet(
            "font-family:Consolas;font-size:24px;font-weight:700;color:#172033;"
        )
        status_layout.addWidget(self.coordinate_label)
        self.map_size_label = QLabel("小地图尺寸：--")
        self.map_size_label.setObjectName("muted")
        status_layout.addWidget(self.map_size_label)
        self.detection_label = QLabel("等待识别")
        self.detection_label.setObjectName("muted")
        self.detection_label.setWordWrap(True)
        status_layout.addWidget(self.detection_label)
        self.latency_label = QLabel("视频帧龄：--\n坐标帧龄：--")
        self.latency_label.setObjectName("muted")
        self.latency_label.setWordWrap(True)
        status_layout.addWidget(self.latency_label)
        status_layout.addStretch(1)
        stream_label = QLabel(self.serial or "ADB 未连接")
        stream_label.setObjectName("muted")
        stream_label.setWordWrap(True)
        status_layout.addWidget(stream_label)
        upper_layout.addWidget(status_pane, 1)
        root.addWidget(upper, 2)

        development = QFrame()
        development.setObjectName("developmentPane")
        development_layout = QVBoxLayout(development)
        development_layout.setContentsMargins(18, 12, 18, 14)
        development_title = QLabel("控制配置")
        development_title.setObjectName("sectionTitle")
        development_layout.addWidget(development_title)
        self.mode_tabs = QTabWidget()
        self.mode_tabs.setDocumentMode(True)
        self.mode_tabs.addTab(self._create_live_flower_tab(), "活花模式")
        pending = QLabel("开发中")
        pending.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pending.setStyleSheet("color:#8791A3;font-size:15px;")
        self.mode_tabs.addTab(pending, "待定")
        self.mode_tabs.currentChanged.connect(self._on_mode_tab_changed)
        development_layout.addWidget(self.mode_tabs, 1)
        root.addWidget(development, 3)

    def _create_live_flower_tab(self):
        panel = QWidget()
        panel.setObjectName("liveFlowerPage")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(7)
        # Keep every row at its natural height. The default window is tall
        # enough to show this page; extra BUFF rows can still scroll.
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        hint = QLabel("移动方式：智能走（点击左上小地图选择中心点）")
        hint.setObjectName("muted")
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.smart_walk_anchor_label = QLabel("中心点：未选择")
        self.smart_walk_anchor_label.setObjectName("muted")
        row.addWidget(self.smart_walk_anchor_label, 1)
        row.addWidget(QLabel("左右范围"))
        self.smart_walk_width_input = QSpinBox()
        self.smart_walk_width_input.setRange(1, 2000)
        self.smart_walk_width_input.setValue(self.smart_walk_half_width)
        self.smart_walk_width_input.setSuffix(" px")
        self.smart_walk_width_input.valueChanged.connect(self._on_smart_walk_size_changed)
        row.addWidget(self.smart_walk_width_input)
        layout.addLayout(row)
        self.smart_walk_enabled = QPushButton("启动")
        self.smart_walk_enabled.setCheckable(True)
        self.smart_walk_enabled.setToolTip("启动或停止当前模拟器的活花模式")
        self.smart_walk_enabled.toggled.connect(self._on_smart_walk_enabled_changed)
        layout.addWidget(self.smart_walk_enabled, 0, Qt.AlignmentFlag.AlignLeft)
        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("触发间隔"))
        self.smart_walk_min_input = QSpinBox()
        self.smart_walk_min_input.setRange(1, 1440)
        self.smart_walk_min_input.setSuffix(" 分钟")
        self.smart_walk_min_input.setValue(self.smart_walk_min_minutes)
        self.smart_walk_min_input.valueChanged.connect(self._on_smart_walk_interval_changed)
        interval_row.addWidget(self.smart_walk_min_input)
        interval_row.addWidget(QLabel("至"))
        self.smart_walk_max_input = QSpinBox()
        self.smart_walk_max_input.setRange(1, 1440)
        self.smart_walk_max_input.setSuffix(" 分钟")
        self.smart_walk_max_input.setValue(self.smart_walk_max_minutes)
        self.smart_walk_max_input.valueChanged.connect(self._on_smart_walk_interval_changed)
        interval_row.addWidget(self.smart_walk_max_input)
        interval_row.addStretch(1)
        layout.addLayout(interval_row)
        jump_row = QHBoxLayout()
        jump_row.addWidget(QLabel("跳跃键"))
        self.smart_walk_jump_button = QPushButton(self.smart_walk_jump_key)
        self.smart_walk_jump_button.setFixedWidth(80)
        self.smart_walk_jump_button.clicked.connect(self._select_jump_key)
        jump_row.addWidget(self.smart_walk_jump_button)
        jump_row.addStretch(1)
        layout.addLayout(jump_row)
        random_row = QHBoxLayout()
        self.buff_random_checkbox = QCheckBox("提前释放")
        self.buff_random_checkbox.setChecked(True)
        self.buff_random_input = QSpinBox()
        self.buff_random_input.setRange(1, 60)
        self.buff_random_input.setValue(20)
        self.buff_random_input.setSuffix(" 秒")
        self.buff_random_checkbox.toggled.connect(self._emit_smart_walk_config)
        self.buff_random_input.valueChanged.connect(self._emit_smart_walk_config)
        random_row.addWidget(self.buff_random_checkbox)
        random_row.addWidget(self.buff_random_input)
        random_row.addStretch(1)
        layout.addLayout(random_row)
        buff_title = QLabel("BUFF 配置（启用、按键、持续时间）")
        buff_title.setObjectName("muted")
        layout.addWidget(buff_title)
        self.buff_status_label = QLabel("BUFF 状态：未启动")
        self.buff_status_label.setObjectName("muted")
        layout.addWidget(self.buff_status_label)
        self.buff_inputs = []
        self.buff_countdown_labels = []
        self.buff_row_widgets = []
        self.buff_remove_buttons = []
        self.buff_rows_container = QWidget()
        self.buff_rows_layout = QVBoxLayout(self.buff_rows_container)
        self.buff_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.buff_rows_layout.setSpacing(4)
        layout.addWidget(self.buff_rows_container)
        for _ in range(DEFAULT_BUFF_SLOT_COUNT):
            self._add_buff_row(emit_change=False)
        self.add_buff_button = QPushButton("＋ 添加 BUFF")
        self.add_buff_button.clicked.connect(self._add_buff_row)
        layout.addWidget(self.add_buff_button, 0, Qt.AlignmentFlag.AlignLeft)
        note = QLabel("区域和中心点均使用当前小地图像素坐标；切换到其他选项卡时标记会隐藏。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("liveFlowerScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(panel)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.live_flower_scroll = scroll
        return scroll

    def _add_buff_row(self, _checked=False, emit_change=True):
        if len(self.buff_inputs) >= MAX_BUFF_SLOT_COUNT:
            return
        row_widget = QWidget()
        row_widget.setMinimumHeight(34)
        buff_row = QHBoxLayout(row_widget)
        buff_row.setContentsMargins(0, 2, 0, 2)
        index = len(self.buff_inputs)
        enabled = QCheckBox(f"BUFF {index + 1}")
        key_input = QPushButton("选键")
        key_input.setFixedWidth(80)
        duration_input = QSpinBox()
        duration_input.setRange(1, 86400)
        duration_input.setValue(270)
        duration_input.setSuffix(" 秒")
        duration_input.setFixedWidth(100)
        countdown = QLabel("--")
        countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        countdown.setFixedWidth(64)
        countdown.setStyleSheet(
            "color:#747D8D;background:#EEF2F7;border-radius:9px;"
            "padding:3px;font-family:Consolas;font-weight:600;"
        )
        remove = QPushButton("删除")
        remove.setFixedWidth(54)
        enabled.toggled.connect(self._on_buff_enabled_changed)
        key_input.clicked.connect(
            lambda _=False, row=row_widget: self._select_buff_key(
                self.buff_row_widgets.index(row)
            )
        )
        duration_input.valueChanged.connect(self._emit_smart_walk_config)
        remove.clicked.connect(
            lambda _=False, row=row_widget: self._remove_buff_row(row)
        )
        buff_row.addWidget(enabled)
        buff_row.addWidget(key_input)
        buff_row.addWidget(duration_input)
        buff_row.addWidget(countdown)
        buff_row.addWidget(remove)
        buff_row.addStretch(1)
        self.buff_rows_layout.addWidget(row_widget)
        self.buff_inputs.append((enabled, key_input, duration_input))
        self.buff_countdown_labels.append(countdown)
        self.buff_row_widgets.append(row_widget)
        self.buff_remove_buttons.append(remove)
        self._refresh_buff_row_controls()
        if emit_change:
            self._emit_smart_walk_config()

    def _remove_buff_row(self, row_widget):
        if len(self.buff_inputs) <= DEFAULT_BUFF_SLOT_COUNT:
            return
        try:
            index = self.buff_row_widgets.index(row_widget)
        except ValueError:
            return
        self.buff_inputs.pop(index)
        self.buff_countdown_labels.pop(index)
        self.buff_row_widgets.pop(index)
        self.buff_remove_buttons.pop(index)
        self.buff_rows_layout.removeWidget(row_widget)
        row_widget.deleteLater()
        self._refresh_buff_row_controls()
        self._emit_smart_walk_config()

    def _refresh_buff_row_controls(self):
        can_remove = len(self.buff_inputs) > DEFAULT_BUFF_SLOT_COUNT
        for index, ((enabled, _key, _duration), remove) in enumerate(
            zip(self.buff_inputs, self.buff_remove_buttons)
        ):
            enabled.setText(f"BUFF {index + 1}")
            remove.setVisible(can_remove)
        if hasattr(self, "add_buff_button"):
            self.add_buff_button.setVisible(
                len(self.buff_inputs) < MAX_BUFF_SLOT_COUNT
            )

    def _select_jump_key(self):
        dialog = VirtualKeyboardDialog(self, self.smart_walk_jump_button.text() or "Alt")
        dialog.setWindowTitle("选择跳跃键")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.smart_walk_jump_button.setText(dialog.get_selected_key())
            self._emit_smart_walk_config()

    def _select_buff_key(self, index: int):
        if not 0 <= index < len(self.buff_inputs):
            return
        _, button, _ = self.buff_inputs[index]
        current = button.text() if button.text() != "选键" else "Ctrl"
        dialog = VirtualKeyboardDialog(self, current)
        dialog.setWindowTitle(f"选择 BUFF {index + 1} 按键")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            button.setText(dialog.get_selected_key())
            self._emit_smart_walk_config()

    def _on_minimap_clicked(self, x: int, y: int):
        if self._active_mode != "live_flower":
            return
        self.smart_walk_anchor = (int(x), int(y))
        self._update_smart_walk_label()
        self._render_minimap()
        self.smart_walk_anchor_selected.emit(self.serial, int(x), int(y))
        self._emit_smart_walk_config()

    def _on_smart_walk_size_changed(self):
        self.smart_walk_half_width = self.smart_walk_width_input.value()
        self._render_minimap()
        self._emit_smart_walk_config()

    def _on_buff_enabled_changed(self, _checked=False):
        """Show the stored remaining time again as soon as a BUFF is re-enabled."""
        self.update_buff_countdown(self._last_countdowns)
        self._emit_smart_walk_config()

    def _on_smart_walk_enabled_changed(self, enabled: bool):
        self.smart_walk_enabled.setText("停止" if enabled else "启动")
        if enabled:
            self.update_buff_countdown(self._last_countdowns)
        else:
            self.update_buff_countdown({})
            self.buff_status_label.setText("BUFF 状态：未启动")
        self._emit_smart_walk_config()

    def update_buff_countdown(self, countdowns: dict):
        """Display independent BUFF countdowns for this emulator stream."""
        normalized = {}
        for key, value in dict(countdowns or {}).items():
            try:
                normalized[int(key)] = int(value)
            except (TypeError, ValueError):
                continue
        if normalized:
            # A disabled skill is omitted from later updates. Keep its last
            # remaining time so turning that skill back on can show it at once.
            merged = dict(self._last_countdowns)
            merged.update(normalized)
            self._last_countdowns = merged
        # Hide the numbers while this emulator is stopped, but keep them in
        # memory. An empty update while running must not wipe the display.
        visible = (
            {}
            if not self.smart_walk_enabled.isChecked()
            else dict(self._last_countdowns)
        )
        for index, label in enumerate(self.buff_countdown_labels):
            enabled, key, _duration = self.buff_inputs[index]
            if enabled.isChecked() and key.text() != "选键" and index in visible:
                remaining = max(0, int(visible[index]))
                label.setText(f"{remaining}s")
                if remaining <= 5:
                    color, background = "#E9404A", "#FDECEE"
                elif remaining <= 30:
                    color, background = "#E78A15", "#FFF4E4"
                else:
                    color, background = "#19A866", "#EAF8F1"
                label.setStyleSheet(
                    f"color:{color};background:{background};"
                    "border-radius:9px;padding:3px;"
                    "font-family:Consolas;font-weight:600;"
                )
            else:
                label.setText("--")
                label.setStyleSheet(
                    "color:#747D8D;background:#EEF2F7;border-radius:9px;"
                    "padding:3px;font-family:Consolas;font-weight:600;"
                )

    def update_smart_walk_status(self, message: str):
        self.buff_status_label.setText(f"BUFF 状态：{message}")

    def _on_smart_walk_interval_changed(self):
        self.smart_walk_min_minutes = self.smart_walk_min_input.value()
        self.smart_walk_max_minutes = max(self.smart_walk_min_minutes, self.smart_walk_max_input.value())
        if self.smart_walk_max_input.value() < self.smart_walk_min_minutes:
            self.smart_walk_max_input.setValue(self.smart_walk_max_minutes)
        self._emit_smart_walk_config()

    def _emit_smart_walk_config(self):
        self.smart_walk_config_changed.emit(
            self.serial,
            {
                "enabled": bool(self.smart_walk_enabled.isChecked()),
                "anchor": self.smart_walk_anchor,
                "half_width": int(self.smart_walk_half_width),
                "min_minutes": int(self.smart_walk_min_minutes),
                "max_minutes": int(self.smart_walk_max_minutes),
                "jump_key": self.smart_walk_jump_button.text().strip() or "Alt",
                "random_behavior_enabled": bool(self.buff_random_checkbox.isChecked()),
                "random_behavior_value": int(self.buff_random_input.value()),
                "buffs": [
                    {
                        "enabled": enabled.isChecked(),
                        "key": "" if key.text() == "选键" else key.text().strip(),
                        "duration": duration.value(),
                    }
                    for enabled, key, duration in self.buff_inputs
                ],
            },
        )

    def _update_smart_walk_label(self):
        if self.smart_walk_anchor is None:
            self.smart_walk_anchor_label.setText("中心点：未选择")
        else:
            self.smart_walk_anchor_label.setText(
                f"中心点：X={self.smart_walk_anchor[0]}，Y={self.smart_walk_anchor[1]}"
            )

    def _on_mode_tab_changed(self, index: int):
        self._active_mode = "live_flower" if index == 0 else "pending"
        self.active_mode_changed.emit(self._active_mode)
        self._render_minimap()

    def smart_walk_config(self):
        return {
            "enabled": bool(self.smart_walk_enabled.isChecked()),
            "anchor": self.smart_walk_anchor,
            "half_width": int(self.smart_walk_half_width),
            "min_minutes": int(self.smart_walk_min_minutes),
            "max_minutes": int(self.smart_walk_max_minutes),
            "jump_key": self.smart_walk_jump_button.text().strip() or "Alt",
            "random_behavior_enabled": bool(self.buff_random_checkbox.isChecked()),
            "random_behavior_value": int(self.buff_random_input.value()),
            "buffs": [
                {
                    "enabled": enabled.isChecked(),
                    "key": "" if key.text() == "选键" else key.text().strip(),
                    "duration": duration.value(),
                }
                for enabled, key, duration in self.buff_inputs
            ],
        }

    def set_smart_walk_config(self, config: dict):
        """Restore this stream's independent configuration when reopened."""
        config = config or {}
        anchor = config.get("anchor")
        self.smart_walk_anchor = tuple(anchor) if anchor else None
        half_width = max(1, int(config.get("half_width", 10)))
        self.smart_walk_min_minutes = max(1, min(1440, int(config.get("min_minutes", 15))))
        self.smart_walk_max_minutes = max(self.smart_walk_min_minutes, min(1440, int(config.get("max_minutes", 30))))
        random_enabled = bool(config.get("random_behavior_enabled", True))
        random_value = max(1, min(60, int(config.get("random_behavior_value", 20))))
        self.smart_walk_jump_key = str(config.get("jump_key") or "Alt")
        self.smart_walk_width_input.blockSignals(True)
        self.smart_walk_min_input.blockSignals(True)
        self.smart_walk_max_input.blockSignals(True)
        self.smart_walk_enabled.blockSignals(True)
        self.smart_walk_jump_button.blockSignals(True)
        self.buff_random_checkbox.blockSignals(True)
        self.buff_random_input.blockSignals(True)
        self.smart_walk_width_input.setValue(half_width)
        self.smart_walk_min_input.setValue(self.smart_walk_min_minutes)
        self.smart_walk_max_input.setValue(self.smart_walk_max_minutes)
        self.smart_walk_enabled.setChecked(bool(config.get("enabled")))
        self.smart_walk_jump_button.setText(self.smart_walk_jump_key)
        self.buff_random_checkbox.setChecked(random_enabled)
        self.buff_random_input.setValue(random_value)
        self.smart_walk_width_input.blockSignals(False)
        self.smart_walk_min_input.blockSignals(False)
        self.smart_walk_max_input.blockSignals(False)
        self.smart_walk_enabled.blockSignals(False)
        self.smart_walk_jump_button.blockSignals(False)
        self.buff_random_checkbox.blockSignals(False)
        self.buff_random_input.blockSignals(False)
        self.smart_walk_half_width = half_width
        self.smart_walk_min_minutes = self.smart_walk_min_input.value()
        self.smart_walk_max_minutes = max(self.smart_walk_min_minutes, self.smart_walk_max_input.value())
        configured_buffs = [
            buff for buff in (config.get("buffs") or []) if isinstance(buff, dict)
        ][:MAX_BUFF_SLOT_COUNT]
        while len(self.buff_inputs) < max(DEFAULT_BUFF_SLOT_COUNT, len(configured_buffs)):
            self._add_buff_row(emit_change=False)
        while len(self.buff_inputs) > max(DEFAULT_BUFF_SLOT_COUNT, len(configured_buffs)):
            row = self.buff_row_widgets[-1]
            index = len(self.buff_inputs) - 1
            self.buff_inputs.pop(index)
            self.buff_countdown_labels.pop(index)
            self.buff_row_widgets.pop(index)
            self.buff_remove_buttons.pop(index)
            self.buff_rows_layout.removeWidget(row)
            row.deleteLater()
        self._refresh_buff_row_controls()
        for index, buff in enumerate(configured_buffs):
            if index >= len(self.buff_inputs) or not isinstance(buff, dict):
                continue
            enabled, key, duration = self.buff_inputs[index]
            enabled.blockSignals(True)
            key.blockSignals(True)
            duration.blockSignals(True)
            enabled.setChecked(bool(buff.get("enabled")))
            key.setText(str(buff.get("key") or "选键"))
            duration.setValue(max(1, int(float(buff.get("duration", 270) or 270))))
            enabled.blockSignals(False)
            key.blockSignals(False)
            duration.blockSignals(False)
        self._on_smart_walk_enabled_changed(bool(config.get("enabled")))
        self._update_smart_walk_label()
        self._render_minimap()

    def begin_minimap_redetection(self):
        self._minimap_rect = None
        self._minimap_image = None
        self.minimap_label.clear()
        self.minimap_label.setText("正在重新识别小地图")
        self.coordinate_label.setText("X: --\nY: --")
        self.map_size_label.setText("小地图尺寸：--")
        self.detection_label.setText("正在分析最新画面")

    def update_stream_metrics(
        self,
        fps: float,
        frame_age_ms,
        analysis_age_ms,
        analysis_processing_ms,
        dropped_analysis: int,
    ):
        frame_age = "--" if frame_age_ms is None else f"{frame_age_ms:.0f} ms"
        analysis_age = (
            "--" if analysis_age_ms is None else f"{analysis_age_ms:.0f} ms"
        )
        processing = (
            "--"
            if analysis_processing_ms is None
            else f"{analysis_processing_ms:.0f} ms"
        )
        dropped = f" · 丢弃 {dropped_analysis}" if dropped_analysis else ""
        self.latency_label.setText(
            f"视频：{fps:.1f} FPS · 帧龄 {frame_age}\n"
            f"坐标帧龄：{analysis_age} · 识别 {processing}{dropped}"
        )

    def update_analysis(self, analysis):
        if analysis.minimap_rect is not None:
            self._minimap_rect = analysis.minimap_rect
            if self._minimap_image is None:
                self.update_minimap_frame(
                    analysis.minimap_image, analysis.minimap_rect
                )
        elif analysis.title_rect is not None or analysis.game_state == "not_in_game":
            self._minimap_rect = None
            self.update_minimap_frame(None)
        if analysis.player_position is not None:
            x, y = analysis.player_position
            self.coordinate_label.setText(f"X: {x}\nY: {y}")
            self.detection_label.setText("已识别玩家黄点（相对小地图坐标）")
        else:
            self.coordinate_label.setText("X: --\nY: --")
            if analysis.game_state == "loading":
                self.detection_label.setText("过图中 / 状态未知")
            elif analysis.title_rect is not None:
                self.detection_label.setText("当前地图隐藏小地图画布")
            elif analysis.game_state == "in_game":
                self.detection_label.setText("已识别游戏画面，暂未找到玩家黄点")
            else:
                self.detection_label.setText("未识别到游戏画面")

    def update_minimap_frame(self, minimap, rect=None):
        if rect is not None:
            self._minimap_rect = rect
        if minimap is not None and minimap.size:
            self._minimap_image = minimap.copy()
            self._render_minimap()
            height, width = minimap.shape[:2]
            self.map_size_label.setText(f"小地图尺寸：{width} × {height}")
        else:
            self._minimap_image = None
            self.minimap_label.clear()
            self.minimap_label.setText("当前画面未检测到小地图")
            self.map_size_label.setText("小地图尺寸：--")

    def update_raw_frame(self, frame):
        """Refresh the displayed crop directly from each decoded video frame."""
        rect = self._minimap_rect
        if frame is None or rect is None:
            return
        x, y, width, height = rect
        frame_height, frame_width = frame.shape[:2]
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > frame_width
            or y + height > frame_height
        ):
            return
        self.update_minimap_frame(frame[y : y + height, x : x + width], rect)

    def _render_minimap(self):
        if self._minimap_image is None:
            return
        height, width, channels = self._minimap_image.shape
        image = QImage(
            self._minimap_image.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_BGR888,
        ).copy()
        if self.smart_walk_anchor is not None and self._active_mode == "live_flower":
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            x, y = self.smart_walk_anchor
            pen = QPen(Qt.GlobalColor.red, 1)
            painter.setPen(pen)
            painter.drawLine(x - 2, y, x + 2, y)
            painter.drawLine(x, y - 2, x, y + 2)
            painter.setPen(QPen(Qt.GlobalColor.green, max(1, round(width / 160))))
            left = max(0, x - self.smart_walk_half_width)
            right = min(width - 1, x + self.smart_walk_half_width)
            painter.drawRect(
                left,
                0,
                right - left,
                height - 1,
            )
            painter.end()
        self.minimap_label.set_source_size(width, height)
        target = self.minimap_label.size()
        self.minimap_label.setPixmap(
            QPixmap.fromImage(image).scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_minimap()
