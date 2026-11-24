"""挑衅模式的地图、平台、跳跃及技能配置。"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ui.virtual_keyboard import VirtualKeyboardDialog
from utils.taunt_settings import (
    DEFAULT_TAUNT_HOLD_MS, DEFAULT_TAUNT_INTERVAL_MS, MAX_TAUNT_TIMING_MS,
    load_taunt_timing_ranges,
)
from workers.taunt_worker import TauntWorker


class TauntPanel(QWidget):
    changed = pyqtSignal()
    manage_maps_requested = pyqtSignal()

    def __init__(self, maps=None, parent=None):
        super().__init__(parent)
        self.maps = []
        self.jump_key = "Alt"
        self.skill_key = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("挑衅模式 · 平台往返跳走")
        title.setStyleSheet("font-size:14px;font-weight:700;")
        layout.addWidget(title)
        hint = QLabel("按所选平台横向范围往返，两端各内缩约 8% 后折返，忽略纵坐标。方向键持续按住，跳跃改为短按，每次起跳后再释放挑衅，折返时松键换向。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(QLabel("选择地图"))
        row.addStretch(1)
        manage = QPushButton("管理地图")
        manage.clicked.connect(self.manage_maps_requested)
        row.addWidget(manage)
        layout.addLayout(row)
        self.map_list = QListWidget()
        self.map_list.setFixedHeight(82)
        layout.addWidget(self.map_list)
        layout.addWidget(QLabel("选择平台（编号与地图标注一致）"))
        self.platform_list = QListWidget()
        self.platform_list.setFixedHeight(104)
        layout.addWidget(self.platform_list)
        row = QHBoxLayout()
        row.addWidget(QLabel("跳跃键"))
        self.jump_button = QPushButton(self.jump_key)
        self.jump_button.clicked.connect(self._select_jump_key)
        row.addWidget(self.jump_button)
        row.addWidget(QLabel("挑衅键"))
        self.skill_button = QPushButton("未设置")
        self.skill_button.clicked.connect(self._select_skill_key)
        row.addWidget(self.skill_button)
        self.clear_skill_button = QPushButton("清除")
        self.clear_skill_button.clicked.connect(self._clear_skill_key)
        row.addWidget(self.clear_skill_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.interval_min, self.interval_max = self._add_timing_range(
            layout, "动作组间隔", DEFAULT_TAUNT_INTERVAL_MS)
        self.hold_min, self.hold_max = self._add_timing_range(
            layout, "挑衅按住时长", DEFAULT_TAUNT_HOLD_MS)
        timing_hint = QLabel("每组跳后随机 70–150 毫秒按挑衅，再过 70–90 毫秒松跳；间隔从松开挑衅到下一次起跳计算。未设挑衅键时仅短跳。可在上方选配 BUFF，到期时松开方向、跳跃和挑衅键，原地放完 BUFF 后继续跳走和挑衅。静止 2 秒松键重试，失焦暂停，回到游戏后重新起跳。")
        timing_hint.setWordWrap(True)
        layout.addWidget(timing_hint)
        self.verification_checkbox = QCheckBox("测谎检测并喊话（默认关闭）")
        self.verification_checkbox.setToolTip(
            "检测鼠标跟随／寻找透明图形（包括开始前的暗色玩法说明框）、紫色符文诅咒横幅、蓝色输入答案面板三种提示。"
            "透明图形说明框在全画面按标题和说明文字特征定位，不固定屏幕位置；确认后提前喊话。"
            "支持缩放和关键短语容错，强匹配立即确认，较弱匹配连续两次再确认。"
            "全部使用图像特征识别，不启动 OCR。"
            "勾选即开启独立低频检测，无需启动挑衅；后台截图不依赖游戏焦点。"
            "一旦疑似就停止挑衅并松键，不会自动恢复；确认后按回车 → 随机 1–9 → 回车喊话两次，"
            "每条独立随机，两次间随机短暂停顿；同一提示不再重复喊话。"
            "确认需要喊话时立即激活游戏窗口，再发送；发送途中失焦会松键并重新激活，续发剩余步骤。"
            "未取得游戏焦点时不输入，保留通知重试；不发送其他通知。"
            "低配电脑可保持关闭，不进行额外截图和识别。")
        self.verification_checkbox.toggled.connect(lambda _: self.changed.emit())
        layout.addWidget(self.verification_checkbox)
        self.verification_status = QLabel("测谎检测：未开启")
        self.verification_status.setWordWrap(True)
        layout.addWidget(self.verification_status)
        self.status = QLabel("待机")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.map_list.currentRowChanged.connect(self._reload_platforms)
        self.platform_list.currentRowChanged.connect(lambda _: self.changed.emit())
        self.set_maps(maps or [])

    def _add_timing_range(self, layout, label, defaults):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        controls = []
        for index, value in enumerate(defaults):
            if index:
                row.addWidget(QLabel("至"))
            control = QSpinBox()
            control.setRange(1, MAX_TAUNT_TIMING_MS)
            control.setSuffix(" 毫秒")
            control.setValue(value)
            row.addWidget(control)
            controls.append(control)
        minimum, maximum = controls
        minimum.valueChanged.connect(lambda value: maximum.setValue(max(value, maximum.value())))
        maximum.valueChanged.connect(lambda value: minimum.setValue(min(value, minimum.value())))
        for control in controls:
            control.valueChanged.connect(lambda _: self.changed.emit())
        layout.addLayout(row)
        return minimum, maximum

    def selected_map(self):
        index = self.map_list.currentRow()
        return self.maps[index] if 0 <= index < len(self.maps) else None

    def selected_platform_id(self):
        item = self.platform_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else ""

    def settings(self):
        topology = self.selected_map()
        return {
            "taunt_map_name": topology.map_name if topology else "",
            "taunt_platform_id": self.selected_platform_id(),
            "taunt_jump_key": self.jump_key,
            "taunt_skill_key": self.skill_key,
            "taunt_interval_min_ms": self.interval_min.value(),
            "taunt_interval_max_ms": self.interval_max.value(),
            "taunt_hold_min_ms": self.hold_min.value(),
            "taunt_hold_max_ms": self.hold_max.value(),
            "taunt_verification_enabled": self.verification_checkbox.isChecked(),
        }

    def worker_options(self):
        return {
            "skill_key": self.skill_key,
            "interval_min_ms": self.interval_min.value(),
            "interval_max_ms": self.interval_max.value(),
            "hold_min_ms": self.hold_min.value(),
            "hold_max_ms": self.hold_max.value(),
        }

    def set_maps(self, maps, map_name=None, platform_id=None):
        old = self.settings()
        map_name = old["taunt_map_name"] if map_name is None else map_name
        platform_id = old["taunt_platform_id"] if platform_id is None else platform_id
        self.maps = list(maps)
        self.map_list.blockSignals(True)
        self.map_list.clear()
        for topology in self.maps:
            self.map_list.addItem(f"{topology.map_name} · {len(topology.platforms)} 个平台")
        index = next((i for i, item in enumerate(self.maps) if item.map_name == map_name), -1)
        if not map_name and self.maps:
            index = 0
        self.map_list.setCurrentRow(index)
        self.map_list.blockSignals(False)
        self._reload_platforms(platform_id=platform_id)

    def restore_settings(self, settings):
        self.verification_checkbox.blockSignals(True)
        self.verification_checkbox.setChecked(settings.get("taunt_verification_enabled", False))
        self.verification_checkbox.blockSignals(False)
        self.jump_key = settings.get("taunt_jump_key") or "Alt"
        self.jump_button.setText(self.jump_key)
        self.skill_key = settings.get("taunt_skill_key") or ""
        self.skill_button.setText(self.skill_key or "未设置")
        timing_ranges = load_taunt_timing_ranges(settings)
        for prefix, controls in (
            ("interval", (self.interval_min, self.interval_max)),
            ("hold", (self.hold_min, self.hold_max)),
        ):
            values = timing_ranges[prefix]
            for control in controls:
                control.blockSignals(True)
            for control, value in zip(controls, values):
                control.setValue(value)
                control.blockSignals(False)
        self.set_maps(self.maps, settings.get("taunt_map_name", ""),
                      settings.get("taunt_platform_id", ""))

    def _reload_platforms(self, _index=None, platform_id=""):
        self.platform_list.blockSignals(True)
        self.platform_list.clear()
        topology = self.selected_map()
        if topology:
            for index, platform in enumerate(topology.platforms):
                if len(platform.points) < 2:
                    continue
                xs = [point.x * topology.reference_width for point in platform.points]
                item = QListWidgetItem(f"P{index + 1} · 横坐标 {min(xs):.1f} – {max(xs):.1f}")
                item.setData(Qt.ItemDataRole.UserRole, platform.id)
                self.platform_list.addItem(item)
        selected = next((i for i in range(self.platform_list.count())
                         if self.platform_list.item(i).data(Qt.ItemDataRole.UserRole) == platform_id), -1)
        if not platform_id and self.platform_list.count():
            selected = 0
        self.platform_list.setCurrentRow(selected)
        self.platform_list.blockSignals(False)
        self.changed.emit()

    def _select_jump_key(self):
        dialog = VirtualKeyboardDialog(self, self.jump_key)
        dialog.setWindowTitle("设置挑衅模式跳跃键")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            value = dialog.get_selected_key()
            try:
                TauntWorker.resolve_jump_key(value)
                TauntWorker.resolve_skill_key(self.skill_key, value)
            except ValueError as error:
                self.status.setText(str(error))
                return
            self.jump_key = value
            self.jump_button.setText(value)
            self.changed.emit()

    def _select_skill_key(self):
        dialog = VirtualKeyboardDialog(self, self.skill_key)
        dialog.setWindowTitle("设置挑衅按键")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            value = dialog.get_selected_key()
            try:
                TauntWorker.resolve_skill_key(value, self.jump_key)
            except ValueError as error:
                self.status.setText(str(error))
                return
            self.skill_key = value
            self.skill_button.setText(value)
            self.changed.emit()

    def _clear_skill_key(self):
        self.skill_key = ""
        self.skill_button.setText("未设置")
        self.changed.emit()

    def set_running(self, running):
        self.map_list.setEnabled(not running)
        self.platform_list.setEnabled(not running)
        self.jump_button.setEnabled(not running)
        for control in (self.skill_button, self.clear_skill_button, self.interval_min,
                        self.interval_max, self.hold_min, self.hold_max):
            control.setEnabled(not running)
        self.status.setText("正在识别小地图…" if running else "待机")

    def update_position(self, x, direction):
        self.status.setText(f"黄点 X={x:.1f} · 向{'左' if direction == 'left' else '右'}行走并短按跳跃")
