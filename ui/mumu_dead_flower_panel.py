"""Compact, per-stream dead-flower controls."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from config import DEFAULT_BUFF_SLOT_COUNT, MAX_BUFF_SLOT_COUNT
from ui.virtual_keyboard import VirtualKeyboardDialog


class MumuDeadFlowerPanel(QScrollArea):
    config_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.anchor = None
        self._countdowns = {}
        self._buff_identity = []
        self._restoring = False
        self.rows = []
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 6, 6, 3)
        layout.setSpacing(5)
        hint = QLabel("出市场 → 释放 BUFF → MENU 进入自由市场等待")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.anchor_label = QLabel("出口：自动识别最左蓝门，可点击小地图指定")
        self.anchor_label.setWordWrap(True)
        row.addWidget(self.anchor_label, 1)
        reset = QPushButton("自动识别")
        reset.clicked.connect(lambda: self.set_anchor(None))
        row.addWidget(reset)
        self.enabled = QPushButton("启动")
        self.enabled.setCheckable(True)
        self.enabled.toggled.connect(self._toggle)
        row.addWidget(self.enabled)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("出市场移动"))
        self.movement = QComboBox()
        for text, value in (("向左一小步", "left_only"), ("向右一小步", "right_only")):
            self.movement.addItem(text, value)
        self.movement.setCurrentIndex(self.movement.findData("right_only"))
        self.movement.currentIndexChanged.connect(self._emit)
        row.addWidget(self.movement)
        row.addWidget(QLabel("跳跃键"))
        self.jump = QPushButton("Alt")
        self.jump.clicked.connect(lambda: self._select_key(self.jump))
        row.addWidget(self.jump)
        row.addStretch(1)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.random_enabled = QCheckBox("提前释放")
        self.random_enabled.setChecked(True)
        self.random_enabled.toggled.connect(self._emit)
        row.addWidget(self.random_enabled)
        self.random_value = QSpinBox()
        self.random_value.setRange(1, 60)
        self.random_value.setValue(20)
        self.random_value.setSuffix(" 秒")
        self.random_value.valueChanged.connect(self._emit)
        row.addWidget(self.random_value)
        row.addStretch(1)
        layout.addLayout(row)
        self.status = QLabel("死花状态：未启动")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("BUFF 配置（启用、按键、持续时间、倒计时）"))
        self.buff_layout = QVBoxLayout()
        self.buff_layout.setSpacing(4)
        layout.addLayout(self.buff_layout)
        self.add = QPushButton("＋ 添加 BUFF")
        self.add.clicked.connect(lambda: self._add_row())
        layout.addWidget(self.add, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.setWidget(body)
        for _ in range(DEFAULT_BUFF_SLOT_COUNT):
            self._add_row(False)

    def _select_key(self, button):
        dialog = VirtualKeyboardDialog(self, button.text() if button.text() != "选键" else "Ctrl")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            button.setText(dialog.get_selected_key())
            self._emit()

    def _add_row(self, emit=True):
        if len(self.rows) >= MAX_BUFF_SLOT_COUNT:
            return
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(5)
        enabled = QCheckBox(f"BUFF {len(self.rows) + 1}")
        key = QPushButton("选键")
        key.setFixedWidth(68)
        key.clicked.connect(lambda: self._select_key(key))
        duration = QSpinBox()
        duration.setRange(1, 86400)
        duration.setValue(270)
        duration.setSuffix(" 秒")
        duration.setFixedWidth(88)
        countdown = QLabel("--")
        countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        countdown.setFixedWidth(56)
        countdown.setStyleSheet("color:#19A866;background:#EAF8F1;border-radius:8px;padding:3px;")
        remove = QPushButton("删除")
        remove.setFixedWidth(46)
        remove.clicked.connect(lambda: self._remove_row(widget))
        enabled.toggled.connect(self._emit)
        duration.valueChanged.connect(self._emit)
        for control in (enabled, key, duration, countdown, remove):
            row.addWidget(control)
        row.addStretch(1)
        self.buff_layout.addWidget(widget)
        self.rows.append((widget, enabled, key, duration, countdown, remove))
        self._refresh_rows()
        if emit:
            self._emit()

    def _refresh_rows(self):
        for index, (_, enabled, _, _, _, remove) in enumerate(self.rows):
            enabled.setText(f"BUFF {index + 1}")
            remove.setVisible(len(self.rows) > DEFAULT_BUFF_SLOT_COUNT)
        self.add.setVisible(len(self.rows) < MAX_BUFF_SLOT_COUNT)

    def _remove_row(self, widget):
        if len(self.rows) <= DEFAULT_BUFF_SLOT_COUNT:
            return
        index = next(i for i, row in enumerate(self.rows) if row[0] is widget)
        self.rows.pop(index)
        self._countdowns = {i if i < index else i - 1: v for i, v in self._countdowns.items() if i != index}
        self.buff_layout.removeWidget(widget)
        widget.deleteLater()
        self._refresh_rows()
        self._emit()

    def _toggle(self, checked):
        self.enabled.setText("停止" if checked else "启动")
        if not checked:
            self.status.setText("死花状态：未启动")
        self._emit()

    def _emit(self, *_):
        if not self._restoring:
            config = self.config()
            identity = [(buff["key"], buff["duration"]) for buff in config["buffs"]]
            retained = {i: value for i, value in self._countdowns.items()
                        if i < len(identity) and i < len(self._buff_identity)
                        and identity[i] == self._buff_identity[i]}
            self._buff_identity = identity
            self.update_countdown(retained if config["enabled"] else {})
            self.config_changed.emit(config)

    def set_anchor(self, anchor):
        self.anchor = tuple(anchor) if anchor else None
        self.anchor_label.setText(
            f"市场出口：X={anchor[0]} Y={anchor[1]}" if anchor else
            "出口：自动识别最左蓝门，可点击小地图指定"
        )
        self._emit()

    def config(self):
        return {
            "enabled": self.enabled.isChecked(),
            "portal_anchor": self.anchor,
            "pre_skill_move_mode": self.movement.currentData(),
            "jump_key": self.jump.text(),
            "random_behavior_enabled": self.random_enabled.isChecked(),
            "random_behavior_value": self.random_value.value(),
            "buffs": [{"enabled": on.isChecked(), "key": "" if key.text() == "选键" else key.text(),
                       "duration": duration.value()} for _, on, key, duration, _, _ in self.rows],
        }

    def set_config(self, config):
        self._restoring = True
        try:
            self.set_anchor(config.get("portal_anchor"))
            mode = config.get("pre_skill_move_mode")
            self.movement.setCurrentIndex(self.movement.findData("left_only" if mode == "left_only" else "right_only"))
            self.jump.setText(config.get("jump_key") or "Alt")
            self.random_enabled.setChecked(bool(config.get("random_behavior_enabled", True)))
            self.random_value.setValue(int(config.get("random_behavior_value", 20)))
            buffs = config.get("buffs") or []
            target_rows = max(DEFAULT_BUFF_SLOT_COUNT, min(MAX_BUFF_SLOT_COUNT, len(buffs)))
            while len(self.rows) > target_rows:
                self._remove_row(self.rows[-1][0])
            while len(self.rows) < min(MAX_BUFF_SLOT_COUNT, len(buffs)):
                self._add_row(False)
            for index, (_, on, key, duration, _, _) in enumerate(self.rows):
                buff = buffs[index] if index < len(buffs) else {}
                on.setChecked(bool(buff.get("enabled")))
                key.setText(buff.get("key") or "选键")
                duration.setValue(int(buff.get("duration", 270)))
            self.enabled.setChecked(bool(config.get("enabled")))
            self._buff_identity = [(buff["key"], buff["duration"]) for buff in self.config()["buffs"]]
            self.update_countdown({})
        finally:
            self._restoring = False

    def update_countdown(self, countdowns):
        self._countdowns = dict(countdowns or {})
        for index, (_, on, key, _, label, _) in enumerate(self.rows):
            value = self._countdowns.get(index)
            show = self.enabled.isChecked() and on.isChecked() and key.text() != "选键" and value is not None
            label.setText(f"{max(0, int(value))}s" if show else "--")
