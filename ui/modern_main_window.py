"""Mac-like compact Windows UI for YzY - Auto Buff."""

import ctypes
import os
import sys
from typing import List, Optional

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QIcon, QIntValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_BUFF_SLOT_COUNT,
    MAX_BUFF_SLOT_COUNT,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    WINDOW_X,
    WINDOW_Y,
)
from models.buff_config import BuffConfig
from models.skill_config import SkillConfig
from ui.main_window import MainWindow as LegacyMainWindow
from ui.virtual_keyboard import VirtualKeyboardDialog
from utils.screen_utils import get_screen_resolution


def resource_path(relative_path: str) -> str:
    """Resolve resources in source and PyInstaller builds."""
    base_path = getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    return os.path.join(base_path, relative_path)


class MainWindow(LegacyMainWindow):
    """Modern compact shell while retaining the proven Windows workflows."""

    def init_ui(self):
        self._loading_settings = True
        self.buffs = [BuffConfig() for _ in range(DEFAULT_BUFF_SLOT_COUNT)]
        self.mode = "dead"
        self.pre_skill_move_mode = "right_only"
        self.follow_heal_key = ""
        self.follow_heal_anchor_pos = None
        self.follow_heal_minimap_region = None
        self.follow_heal_adjust_hold_ms = (200, 300)
        self.buff_rows = []
        self.buff_remove_btns = []
        self.chair_checkboxes = []
        self.chair_key_btns = []

        self.setWindowTitle(APP_NAME)
        self.setGeometry(WINDOW_X, WINDOW_Y, WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._apply_light_theme()

        central = QWidget()
        central.setObjectName("appRoot")
        central.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setObjectName("mainScroll")
        body = QWidget()
        body.setObjectName("scrollBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 12, 18, 6)
        body_layout.setSpacing(9)

        self._create_header(body_layout)
        self._create_status_bar(body_layout)
        self._create_mode_tabs(body_layout)
        self.create_settings_section(body_layout)
        self.create_log_section(body_layout)
        self._create_debug_section(body_layout)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.create_control_section(root)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._persist_settings)

        self.speed_threshold_input = QLineEdit()
        self.speed_threshold_input.setVisible(False)
        self.return_to_market_checkbox = QCheckBox()
        self.return_to_market_checkbox.setVisible(False)

        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)
        QTimer.singleShot(0, self._dismiss_input_focus)

    def _apply_light_theme(self):
        self.setStyleSheet(
            """
            QMainWindow, #appRoot, #scrollBody, #mainScroll {
                background: #F4F7FC;
            }
            QWidget {
                color: #171E30;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                font-size: 11px;
            }
            QFrame#card {
                background: white;
                border: 1px solid #E3E8F2;
                border-radius: 14px;
            }
            QFrame#buffRows {
                background: #F8FAFD;
                border: none;
                border-radius: 10px;
            }
            QFrame#buffRow {
                background: transparent;
                border: none;
                border-bottom: 1px solid #EBEFF6;
            }
            QPushButton {
                background: #FFFFFF;
                color: #171E30;
                border: 1px solid #DDE3EE;
                border-radius: 8px;
                padding: 5px 10px;
                min-height: 20px;
            }
            QPushButton:hover {
                background: #F2F7FF;
                border-color: #7FB1FF;
            }
            QPushButton:pressed {
                background: #E6F0FF;
            }
            QPushButton:disabled {
                color: #A9B0BD;
                background: #F4F6F9;
                border-color: #EBEEF3;
            }
            QPushButton#linkButton {
                border: none;
                color: #1370F7;
                background: transparent;
                font-weight: 600;
                padding: 3px 5px;
            }
            QPushButton#modeCard {
                text-align: left;
                padding: 10px 13px;
                border-radius: 12px;
                min-height: 42px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#primaryAction {
                background: #1370F7;
                color: white;
                border: none;
                border-radius: 10px;
                min-height: 36px;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#primaryAction:hover { background: #0C63E8; }
            QPushButton#primaryAction[running="true"] {
                background: #E9404A;
            }
            QLineEdit, QComboBox {
                background: white;
                color: #171E30;
                border: 1px solid #D9E0EB;
                border-radius: 6px;
                padding: 4px 7px;
                min-height: 20px;
                selection-background-color: #1370F7;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #1370F7;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QCheckBox { spacing: 6px; color: #5F6878; }
            QCheckBox::indicator {
                width: 28px;
                height: 16px;
                border-radius: 8px;
                background: #D6DBE4;
                border: none;
            }
            QCheckBox::indicator:checked {
                background: #2B7BF4;
            }
            QTextEdit {
                background: #F8FAFD;
                color: #4D5668;
                border: 1px solid #E5EAF2;
                border-radius: 8px;
                padding: 7px;
                font-family: "Consolas", "Microsoft YaHei UI";
                font-size: 10px;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 7px;
            }
            QScrollBar::handle:vertical {
                background: #CDD4E0;
                border-radius: 3px;
                min-height: 24px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )

    def _create_header(self, parent_layout):
        header = QHBoxLayout()
        header.setSpacing(11)

        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(40, 40)
        app_icon = QIcon(resource_path(os.path.join("resources", "app_icon.ico")))
        icon.setPixmap(
            app_icon.pixmap(
                40,
                40,
                QIcon.Mode.Normal,
                QIcon.State.Off,
            )
        )
        icon.setScaledContents(True)
        header.addWidget(icon)

        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size:20px;font-weight:700;color:#171E30;")
        subtitle = QLabel("Power by 小新")
        subtitle.setStyleSheet("font-size:10px;color:#747D8D;")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch(1)

        version = QLabel(f"v{APP_VERSION}")
        version.setStyleSheet(
            "color:#747D8D;background:white;border:1px solid #E3E8F2;"
            "border-radius:10px;padding:4px 8px;font-size:10px;"
        )
        header.addWidget(version)
        parent_layout.addLayout(header)

    def _create_status_bar(self, parent_layout):
        row = QHBoxLayout()
        row.setSpacing(6)

        self.admin_status = QLabel()
        self._refresh_admin_status()
        row.addWidget(self.admin_status)

        self.identify_btn = QPushButton("● 游戏窗口")
        self.identify_btn.setObjectName("statusChip")
        self.identify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.identify_btn.clicked.connect(self.on_identify_window)
        self.identify_btn.setEnabled(self.window_selector is not None)
        self._set_game_status_chip(False)
        row.addWidget(self.identify_btn)

        self.window_status_label = QLabel("未识别")
        self.window_status_label.setStyleSheet("color:#747D8D;font-size:10px;")
        self.window_status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        row.addWidget(self.window_status_label, 1)

        self.portal_marker_btn = QPushButton("⌖")
        self.portal_marker_btn.setFixedSize(28, 26)
        self.portal_marker_btn.setToolTip("标记传送门")
        self.portal_marker_btn.clicked.connect(self.on_mark_portal)
        row.addWidget(self.portal_marker_btn)
        parent_layout.addLayout(row)

    def _refresh_admin_status(self):
        is_admin = False
        if sys.platform == "win32":
            try:
                is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                is_admin = False
        color = "#19A866" if is_admin else "#E78A15"
        text = "管理员" if is_admin else "非管理员"
        self.admin_status.setText(f"● {text}")
        self.admin_status.setStyleSheet(
            f"color:{color};background:white;border:1px solid #E3E8F2;"
            "border-radius:10px;padding:4px 8px;font-size:10px;"
        )

    def _set_game_status_chip(self, ready: bool):
        color = "#19A866" if ready else "#E78A15"
        self.identify_btn.setStyleSheet(
            f"QPushButton{{color:{color};background:white;"
            "border:1px solid #E3E8F2;border-radius:10px;"
            "padding:3px 8px;font-size:10px;min-height:18px;}"
            "QPushButton:hover{background:#F2F7FF;border-color:#9FC4FF;}"
        )

    def _create_mode_tabs(self, parent_layout):
        row = QHBoxLayout()
        row.setSpacing(9)
        self.dead_flower_tab = QPushButton(
            "↩  死花模式\n    释放后进入自由市场"
        )
        self.live_flower_tab = QPushButton(
            "↻  活花模式\n    在当前地图循环释放"
        )
        self.follow_heal_tab = QPushButton(
            "♥  跟补模式\n    自动补血并回位"
        )
        for button in (self.dead_flower_tab, self.live_flower_tab, self.follow_heal_tab):
            button.setObjectName("modeCard")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(button, 1)
        self.dead_flower_tab.clicked.connect(
            lambda: self._switch_mode_tab("dead")
        )
        self.live_flower_tab.clicked.connect(
            lambda: self._switch_mode_tab("live")
        )
        self.follow_heal_tab.clicked.connect(
            lambda: self._switch_mode_tab("follow_heal")
        )
        parent_layout.addLayout(row)
        self._update_mode_tab_style()

    def _switch_mode_tab(self, mode):
        if self.is_worker_running:
            return
        if isinstance(mode, bool):
            mode = "dead" if mode else "live"
        self.mode = mode
        self.return_to_market = self.mode == "dead"
        self._update_mode_tab_style()
        self._update_movement_mode_visibility()
        self.logger.log(f"切换到: {self._mode_title(self.mode)}")
        self.update_log_display()
        self._schedule_save()

    def _mode_title(self, mode: str) -> str:
        return {
            "dead": "死花模式",
            "live": "活花模式",
            "follow_heal": "跟补模式",
        }.get(mode, "活花模式")

    def _update_mode_tab_style(self):
        selected = (
            "QPushButton{background:#ECF4FF;color:#171E30;"
            "border:1px solid #68A7FF;border-radius:12px;"
            "padding:10px 13px;text-align:left;min-height:42px;"
            "font-size:12px;font-weight:600;}"
        )
        normal = (
            "QPushButton{background:white;color:#5F6878;"
            "border:1px solid #E3E8F2;border-radius:12px;"
            "padding:10px 13px;text-align:left;min-height:42px;"
            "font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#F8FAFD;border-color:#AFCFFF;}"
        )
        self.dead_flower_tab.setStyleSheet(selected if self.mode == "dead" else normal)
        self.live_flower_tab.setStyleSheet(selected if self.mode == "live" else normal)
        self.follow_heal_tab.setStyleSheet(
            selected if self.mode == "follow_heal" else normal
        )

    def create_settings_section(self, parent_layout):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("BUFF 配置")
        title.setStyleSheet("font-size:14px;font-weight:700;")
        subtitle = QLabel("按键完成后立即开始独立倒计时")
        subtitle.setStyleSheet("color:#747D8D;font-size:9px;")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.add_buff_btn = QPushButton("＋ 添加")
        self.add_buff_btn.setObjectName("linkButton")
        self.add_buff_btn.clicked.connect(self.add_buff)
        header.addWidget(self.add_buff_btn)
        layout.addLayout(header)

        self.buff_rows_container = QFrame()
        self.buff_rows_container.setObjectName("buffRows")
        self.buff_rows_layout = QVBoxLayout(self.buff_rows_container)
        self.buff_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.buff_rows_layout.setSpacing(0)
        layout.addWidget(self.buff_rows_container)
        self._rebuild_buff_rows()

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color:#E7EBF2;")
        layout.addWidget(divider)

        self.movement_stack = QStackedWidget()
        self.movement_stack.addWidget(self._create_live_options())
        self.movement_stack.addWidget(self._create_dead_options())
        self.movement_stack.addWidget(self._create_follow_heal_options())
        layout.addWidget(self.movement_stack)
        parent_layout.addWidget(card)

    def _create_live_options(self):
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.movement_combo = QComboBox()
        for text, value in (
            ("原地不动", "none"),
            ("右走（回左）", "right"),
            ("左走（回右）", "left"),
        ):
            self.movement_combo.addItem(text, value)
        self.movement_combo.currentIndexChanged.connect(
            self._on_movement_combo_changed
        )
        row.addWidget(self._option_column("移动方式", self.movement_combo), 1)

        random_row = QWidget()
        random_layout = QHBoxLayout(random_row)
        random_layout.setContentsMargins(0, 0, 0, 0)
        random_layout.setSpacing(5)
        self.random_behavior_checkbox = QCheckBox()
        self.random_behavior_checkbox.toggled.connect(self._schedule_save)
        self.random_behavior_input = QLineEdit("20")
        self.random_behavior_input.setValidator(QIntValidator(1, 60, self))
        self.random_behavior_input.setFixedWidth(44)
        self.random_behavior_input.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.random_behavior_input.textChanged.connect(self._schedule_save)
        random_layout.addWidget(self.random_behavior_checkbox)
        random_layout.addWidget(self.random_behavior_input)
        random_layout.addWidget(QLabel("秒"))
        random_layout.addStretch(1)
        row.addWidget(self._option_column("提前释放", random_row), 1)

        chair_row = self._create_chair_controls()
        row.addWidget(self._option_column("空闲时坐椅子", chair_row), 1)
        return panel

    def _create_dead_options(self):
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.pre_skill_combo = QComboBox()
        for text, value in (
            ("先右再左", "right_left"),
            ("只向左（鱼窝）", "left_only"),
            ("只向右（骨龙）", "right_only"),
        ):
            self.pre_skill_combo.addItem(text, value)
        self.pre_skill_combo.currentIndexChanged.connect(
            self._on_pre_skill_combo_changed
        )
        row.addWidget(
            self._option_column("出市场后移动方式", self.pre_skill_combo), 2
        )

        self.selected_jump_key = "Alt"
        self.jump_key_btn = QPushButton("Alt")
        self.jump_key_btn.setFixedWidth(54)
        self.jump_key_btn.clicked.connect(self.on_select_jump_key)
        row.addWidget(self._option_column("跳跃键", self.jump_key_btn), 1)

        chair_row = self._create_chair_controls()
        row.addWidget(self._option_column("空闲时坐椅子", chair_row), 1)
        return panel

    def _create_follow_heal_options(self):
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.heal_key_btn = QPushButton("选键")
        self.heal_key_btn.setFixedWidth(54)
        self.heal_key_btn.clicked.connect(self.on_select_heal_key)
        row.addWidget(self._option_column("加血技能键", self.heal_key_btn), 1)

        anchor_row = QWidget()
        anchor_layout = QHBoxLayout(anchor_row)
        anchor_layout.setContentsMargins(0, 0, 0, 0)
        anchor_layout.setSpacing(6)
        self.follow_anchor_btn = QPushButton("⌖ 标记")
        self.follow_anchor_btn.clicked.connect(self.on_mark_follow_anchor)
        self.follow_anchor_label = QLabel("未标记")
        self.follow_anchor_label.setStyleSheet("color:#747D8D;font-size:9px;")
        anchor_layout.addWidget(self.follow_anchor_btn)
        anchor_layout.addWidget(self.follow_anchor_label, 1)
        row.addWidget(self._option_column("跟补基准点", anchor_row), 2)

        adjust_row = QWidget()
        adjust_layout = QHBoxLayout(adjust_row)
        adjust_layout.setContentsMargins(0, 0, 0, 0)
        adjust_layout.setSpacing(4)
        self.follow_adjust_min_input = QLineEdit("200")
        self.follow_adjust_min_input.setValidator(QIntValidator(50, 1000, self))
        self.follow_adjust_min_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.follow_adjust_min_input.setFixedWidth(42)
        self.follow_adjust_min_input.textChanged.connect(self._schedule_save)
        self.follow_adjust_max_input = QLineEdit("300")
        self.follow_adjust_max_input.setValidator(QIntValidator(50, 1000, self))
        self.follow_adjust_max_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.follow_adjust_max_input.setFixedWidth(42)
        self.follow_adjust_max_input.textChanged.connect(self._schedule_save)
        adjust_layout.addWidget(self.follow_adjust_min_input)
        adjust_layout.addWidget(QLabel("-"))
        adjust_layout.addWidget(self.follow_adjust_max_input)
        adjust_layout.addWidget(QLabel("ms"))
        row.addWidget(self._option_column("修正按住", adjust_row), 1)

        return panel

    def _option_column(self, title: str, control: QWidget):
        column = QFrame()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(title)
        label.setStyleSheet("color:#747D8D;font-size:9px;")
        label.setWordWrap(False)
        layout.addWidget(label)
        layout.addWidget(control)
        return column

    def _create_chair_controls(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        checkbox = QCheckBox()
        checkbox.toggled.connect(self.on_sit_chair_toggled)
        button = QPushButton("=")
        button.setFixedWidth(38)
        button.clicked.connect(self.on_select_chair_key)
        self.chair_checkboxes.append(checkbox)
        self.chair_key_btns.append(button)
        if not hasattr(self, "sit_chair_checkbox"):
            self.sit_chair_checkbox = checkbox
            self.chair_key_btn = button
        layout.addWidget(checkbox)
        layout.addWidget(button)
        layout.addStretch(1)
        return widget

    def _rebuild_buff_rows(self):
        while self.buff_rows_layout.count():
            item = self.buff_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.buff_rows = []
        self.buff_checkboxes = []
        self.buff_key_btns = []
        self.buff_duration_inputs = []
        self.buff_countdown_labels = []
        self.buff_remove_btns = []

        for index, buff in enumerate(self.buffs):
            row = QFrame()
            row.setObjectName("buffRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(9, 6, 9, 6)
            row_layout.setSpacing(7)

            checkbox = QCheckBox()
            checkbox.setChecked(buff.enabled)
            row_layout.addWidget(checkbox)

            name = QLabel(f"BUFF {index + 1}")
            name.setFixedWidth(48)
            name.setStyleSheet("font-weight:600;font-size:10px;")
            row_layout.addWidget(name)

            key_button = QPushButton(buff.key or "选键")
            key_button.setFixedWidth(52)
            key_button.clicked.connect(
                lambda _=False, idx=index: self.on_buff_key_btn_clicked(idx)
            )
            row_layout.addWidget(key_button)

            duration = QLineEdit(
                str(int(buff.duration)) if buff.duration > 0 else ""
            )
            duration.setPlaceholderText("时长")
            duration.setValidator(QIntValidator(0, 3600, self))
            duration.setAlignment(Qt.AlignmentFlag.AlignRight)
            duration.setFixedWidth(58)
            row_layout.addWidget(duration)
            seconds = QLabel("秒")
            seconds.setStyleSheet("color:#747D8D;font-size:9px;")
            row_layout.addWidget(seconds)
            row_layout.addStretch(1)

            countdown = QLabel("--")
            countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
            countdown.setFixedWidth(54)
            countdown.setStyleSheet(
                "color:#747D8D;background:white;border-radius:10px;"
                "padding:4px;font-family:Consolas;font-weight:600;"
            )
            row_layout.addWidget(countdown)

            remove = QPushButton("×")
            remove.setFixedSize(24, 24)
            remove.setToolTip("删除此 BUFF")
            remove.setVisible(len(self.buffs) > DEFAULT_BUFF_SLOT_COUNT)
            remove.clicked.connect(
                lambda _=False, idx=index: self.remove_buff(idx)
            )
            row_layout.addWidget(remove)

            checkbox.toggled.connect(
                lambda checked, idx=index: self.on_buff_toggled(idx, checked)
            )
            duration.textChanged.connect(
                lambda text, idx=index: self.on_buff_duration_changed(idx, text)
            )

            self.buff_rows_layout.addWidget(row)
            self.buff_rows.append(row)
            self.buff_checkboxes.append(checkbox)
            self.buff_key_btns.append(key_button)
            self.buff_duration_inputs.append(duration)
            self.buff_countdown_labels.append(countdown)
            self.buff_remove_btns.append(remove)
            row.installEventFilter(self)

        self.add_buff_btn.setVisible(len(self.buffs) < MAX_BUFF_SLOT_COUNT)

    def add_buff(self):
        if self.is_worker_running or len(self.buffs) >= MAX_BUFF_SLOT_COUNT:
            return
        self._sync_buff_values_from_inputs()
        self.buffs.append(BuffConfig())
        self._rebuild_buff_rows()
        self._schedule_save()

    def remove_buff(self, index: int):
        if (
            self.is_worker_running
            or len(self.buffs) <= DEFAULT_BUFF_SLOT_COUNT
            or not 0 <= index < len(self.buffs)
        ):
            return
        self._sync_buff_values_from_inputs()
        self.buffs.pop(index)
        self._rebuild_buff_rows()
        self._schedule_save()

    def _sync_buff_values_from_inputs(self):
        for index, buff in enumerate(self.buffs):
            if index >= len(self.buff_checkboxes):
                break
            buff.enabled = self.buff_checkboxes[index].isChecked()
            buff.key = (
                buff.key
                if self.buff_key_btns[index].text() == "选键"
                else self.buff_key_btns[index].text()
            )
            text = self.buff_duration_inputs[index].text().strip()
            buff.duration = float(text) if text else 0.0

    def _read_follow_adjust_hold_ms(self):
        try:
            min_ms = int(self.follow_adjust_min_input.text() or "200")
        except ValueError:
            min_ms = 200
        try:
            max_ms = int(self.follow_adjust_max_input.text() or "300")
        except ValueError:
            max_ms = 300
        min_ms = max(50, min(1000, min_ms))
        max_ms = max(50, min(1000, max_ms))
        return (min_ms, max_ms)

    def _update_follow_adjust_inputs(self):
        min_ms, max_ms = self.follow_heal_adjust_hold_ms
        self.follow_adjust_min_input.setText(str(min_ms))
        self.follow_adjust_max_input.setText(str(max_ms))

    def create_log_section(self, parent_layout):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(5)

        header = QHBoxLayout()
        self.log_toggle_btn = QPushButton("›  运行日志")
        self.log_toggle_btn.setObjectName("linkButton")
        self.log_toggle_btn.setStyleSheet(
            "QPushButton{border:none;background:transparent;color:#171E30;"
            "font-weight:700;text-align:left;padding:2px;}"
        )
        self.log_toggle_btn.clicked.connect(self._toggle_log_section)
        header.addWidget(self.log_toggle_btn)
        header.addStretch(1)
        clear_button = QPushButton("清空")
        clear_button.setObjectName("linkButton")
        clear_button.clicked.connect(self.clear_logs)
        header.addWidget(clear_button)
        layout.addLayout(header)

        self.log_preview = QLabel("暂无运行记录")
        self.log_preview.setStyleSheet("color:#747D8D;font-size:9px;")
        self.log_preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.log_preview)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMinimumHeight(96)
        self.log_display.setVisible(False)
        layout.addWidget(self.log_display)
        parent_layout.addWidget(card)

    def _toggle_log_section(self):
        expanded = not self.log_display.isVisible()
        self.log_display.setVisible(expanded)
        self.log_preview.setVisible(not expanded)
        self.log_toggle_btn.setText(
            "⌄  运行日志" if expanded else "›  运行日志"
        )
        self.adjustSize()

    def _create_debug_section(self, parent_layout):
        self.debug_toggle_btn = QPushButton("›  调试工具")
        self.debug_toggle_btn.setObjectName("linkButton")
        self.debug_toggle_btn.setStyleSheet(
            "QPushButton{border:none;background:transparent;color:#747D8D;"
            "text-align:left;padding:2px;font-size:9px;}"
        )
        self.debug_toggle_btn.clicked.connect(self._toggle_debug_section)
        parent_layout.addWidget(self.debug_toggle_btn)

        self.debug_widget = QWidget()
        self.debug_widget.setVisible(False)
        row = QHBoxLayout(self.debug_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self.test_market_btn = QPushButton("测试离开市场")
        self.test_return_market_btn = QPushButton("测试回到市场")
        self.test_dialog_btn = QPushButton("测试关闭弹窗")
        self.test_market_btn.clicked.connect(self.start_test_market_nav)
        self.test_return_market_btn.clicked.connect(
            self.start_test_return_to_market
        )
        self.test_dialog_btn.clicked.connect(self.start_test_dismiss_dialog)
        row.addWidget(self.test_market_btn)
        row.addWidget(self.test_return_market_btn)
        row.addWidget(self.test_dialog_btn)
        parent_layout.addWidget(self.debug_widget)

    def _toggle_debug_section(self):
        visible = not self.debug_widget.isVisible()
        self.debug_widget.setVisible(visible)
        self.debug_toggle_btn.setText(
            "⌄  调试工具" if visible else "›  调试工具"
        )

    def create_control_section(self, parent_layout):
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setStyleSheet(
            "QFrame#footer{background:rgba(255,255,255,245);"
            "border-top:1px solid #E3E8F2;}"
        )
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(18, 9, 18, 10)
        self.is_worker_running = False
        self.toggle_btn = QPushButton("▶  开始运行")
        self.toggle_btn.setObjectName("primaryAction")
        self.toggle_btn.setProperty("running", False)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.on_toggle_worker)
        layout.addWidget(self.toggle_btn)
        parent_layout.addWidget(footer)

    def load_default_config(self):
        saved = self.settings_manager.load_settings()
        if saved:
            self._apply_saved_settings(saved)
            self.logger.log("已加载保存的设置")
        else:
            self._apply_default_settings()
            self.logger.log("使用默认设置")

        width, height = get_screen_resolution()
        if width > 0 and height > 0:
            self.game_config.set_resolution(width, height)
        self._loading_settings = False
        self.update_window_status_display()
        self.update_log_display()
        self._update_movement_mode_visibility()
        QTimer.singleShot(0, self._dismiss_input_focus)

    def _apply_saved_settings(self, settings: dict):
        self.mode = settings.get(
            "mode",
            "dead" if settings.get("return_to_market", True) else "live",
        )
        self.return_to_market = self.mode == "dead"
        self.selected_jump_key = settings.get("jump_key", "Alt")
        self.follow_heal_key = settings.get("heal_skill_key", "")
        self.follow_heal_anchor_pos = settings.get("follow_heal_anchor_pos")
        self.follow_heal_minimap_region = settings.get("follow_heal_minimap_region")
        self.follow_heal_adjust_hold_ms = settings.get(
            "follow_heal_adjust_hold_ms",
            (200, 300),
        )
        self.sit_chair_enabled = settings.get("sit_chair_enabled", False)
        self.selected_chair_key = settings.get("chair_key", "=")
        self.movement_mode = settings.get("movement_mode", "none")
        self.pre_skill_move_mode = settings.get(
            "pre_skill_move_mode", "right_only"
        )
        self.manual_portal_pos = settings.get("manual_portal_pos")
        self.game_config.random_behavior_enabled = settings.get(
            "random_behavior_enabled", True
        )
        self.game_config.random_behavior_value = settings.get(
            "random_behavior_value", 20
        )

        configs = settings.get("buffs", [])
        self.buffs = [
            BuffConfig.from_dict(item)
            for item in configs[:MAX_BUFF_SLOT_COUNT]
        ]
        while len(self.buffs) < DEFAULT_BUFF_SLOT_COUNT:
            self.buffs.append(BuffConfig())
        self._rebuild_buff_rows()

        self.jump_key_btn.setText(self.selected_jump_key)
        self.heal_key_btn.setText(self.follow_heal_key or "选键")
        self._update_follow_heal_anchor_label()
        self._update_follow_adjust_inputs()
        self._sync_chair_controls()
        self.random_behavior_checkbox.setChecked(
            self.game_config.random_behavior_enabled
        )
        self.random_behavior_input.setText(
            str(self.game_config.random_behavior_value)
        )
        self._set_movement_mode_radio(self.movement_mode)
        self._set_pre_skill_move_mode_radio(self.pre_skill_move_mode)
        self._update_mode_tab_style()

    def _apply_default_settings(self):
        self.mode = "dead"
        self.return_to_market = True
        self.movement_mode = "none"
        self.pre_skill_move_mode = "right_only"
        self.selected_jump_key = "Alt"
        self.follow_heal_key = ""
        self.follow_heal_anchor_pos = None
        self.follow_heal_minimap_region = None
        self.follow_heal_adjust_hold_ms = (200, 300)
        self.sit_chair_enabled = False
        self.selected_chair_key = "="
        self.manual_portal_pos = None
        self.game_config.random_behavior_enabled = True
        self.game_config.random_behavior_value = 20
        self.buffs = [
            BuffConfig(True, "1", 200),
            BuffConfig(True, "2", 200),
            BuffConfig(),
        ]
        self._rebuild_buff_rows()
        self.jump_key_btn.setText("Alt")
        self.heal_key_btn.setText("选键")
        self._update_follow_heal_anchor_label()
        self._update_follow_adjust_inputs()
        self._sync_chair_controls()
        self.random_behavior_checkbox.setChecked(True)
        self.random_behavior_input.setText("20")
        self._set_movement_mode_radio("none")
        self._set_pre_skill_move_mode_radio("right_only")
        self._update_mode_tab_style()

    def _persist_settings(self):
        if self._loading_settings:
            return
        self._sync_buff_values_from_inputs()
        try:
            random_value = int(self.random_behavior_input.text() or "20")
        except ValueError:
            random_value = 20
        self.follow_heal_adjust_hold_ms = self._read_follow_adjust_hold_ms()
        self.settings_manager.save_settings(
            buffs=self.buffs,
            mode=self.mode,
            return_to_market=self.return_to_market,
            jump_key=self.selected_jump_key,
            heal_skill_key=self.follow_heal_key,
            follow_heal_anchor_pos=self.follow_heal_anchor_pos,
            follow_heal_minimap_region=self.follow_heal_minimap_region,
            follow_heal_adjust_hold_ms=self.follow_heal_adjust_hold_ms,
            sit_chair_enabled=self.sit_chair_enabled,
            chair_key=self.selected_chair_key,
            random_behavior_enabled=self.random_behavior_checkbox.isChecked(),
            random_behavior_value=random_value,
            movement_mode=self.movement_mode,
            pre_skill_move_mode=self.pre_skill_move_mode,
            manual_portal_pos=self.manual_portal_pos,
        )

    def save_settings(self):
        self._persist_settings()
        self.logger.log("设置已保存")
        self.update_log_display()

    def _schedule_save(self, *_):
        if not self._loading_settings and hasattr(self, "_save_timer"):
            self._save_timer.start(250)

    def on_buff_toggled(self, index: int, checked: bool):
        if 0 <= index < len(self.buffs):
            self.buffs[index].enabled = checked
        self._schedule_save()

    def on_buff_key_btn_clicked(self, index: int):
        if not 0 <= index < len(self.buffs):
            return
        dialog = VirtualKeyboardDialog(self, self.buffs[index].key or "Ctrl")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            key = dialog.get_selected_key()
            self.buffs[index].key = key
            self.buff_key_btns[index].setText(key)
            self.logger.log(f"BUFF {index + 1} 按键设置为: {key}")
            self.update_log_display()
            self._schedule_save()

    def on_buff_duration_changed(self, index: int, text: str):
        if 0 <= index < len(self.buffs):
            try:
                self.buffs[index].duration = float(text) if text else 0
            except ValueError:
                return
        self._schedule_save()

    def _set_movement_mode_radio(self, mode: str):
        index = self.movement_combo.findData(mode)
        self.movement_combo.setCurrentIndex(index if index >= 0 else 0)

    def _set_pre_skill_move_mode_radio(self, mode: str):
        index = self.pre_skill_combo.findData(mode)
        if index < 0:
            index = self.pre_skill_combo.findData("right_only")
        self.pre_skill_combo.setCurrentIndex(index)

    def _on_movement_combo_changed(self):
        self.movement_mode = self.movement_combo.currentData() or "none"
        self._schedule_save()

    def _on_pre_skill_combo_changed(self):
        self.pre_skill_move_mode = (
            self.pre_skill_combo.currentData() or "right_only"
        )
        self._schedule_save()

    def on_sit_chair_toggled(self, checked: bool):
        self.sit_chair_enabled = checked
        for checkbox in self.chair_checkboxes:
            if checkbox.isChecked() != checked:
                checkbox.blockSignals(True)
                checkbox.setChecked(checked)
                checkbox.blockSignals(False)
        for button in self.chair_key_btns:
            button.setVisible(checked)
        self._schedule_save()

    def _sync_chair_controls(self):
        for checkbox in self.chair_checkboxes:
            checkbox.blockSignals(True)
            checkbox.setChecked(self.sit_chair_enabled)
            checkbox.blockSignals(False)
        for button in self.chair_key_btns:
            button.setText(self.selected_chair_key)
            button.setVisible(self.sit_chair_enabled)

    def on_select_chair_key(self):
        dialog = VirtualKeyboardDialog(self, self.selected_chair_key)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_chair_key = dialog.get_selected_key()
            self._sync_chair_controls()
            self._schedule_save()

    def on_select_jump_key(self):
        dialog = VirtualKeyboardDialog(self, self.selected_jump_key)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_jump_key = dialog.get_selected_key()
            self.jump_key_btn.setText(self.selected_jump_key)
            self._schedule_save()

    def on_select_heal_key(self):
        previous = self.follow_heal_key
        super().on_select_heal_key()
        if self.follow_heal_key != previous:
            self.heal_key_btn.setText(self.follow_heal_key or "选键")
            self._schedule_save()

    def on_mark_follow_anchor(self):
        previous_anchor = self.follow_heal_anchor_pos
        previous_region = self.follow_heal_minimap_region
        super().on_mark_follow_anchor()
        if (
            self.follow_heal_anchor_pos != previous_anchor
            or self.follow_heal_minimap_region != previous_region
        ):
            self._update_follow_heal_anchor_label()
            self._schedule_save()

    def _update_follow_heal_anchor_label(self):
        if not hasattr(self, "follow_anchor_label"):
            return
        if self.follow_heal_anchor_pos:
            x, _ = self.follow_heal_anchor_pos
            self.follow_anchor_label.setText(f"X={x} · ±7")
        else:
            self.follow_anchor_label.setText("未标记")

    def _update_movement_mode_visibility(self):
        if self.mode == "dead":
            self.movement_stack.setCurrentIndex(1)
        elif self.mode == "follow_heal":
            self.movement_stack.setCurrentIndex(2)
        else:
            self.movement_stack.setCurrentIndex(0)
        self.portal_marker_btn.setVisible(self.mode == "dead")

    def update_window_status_display(
        self, status_text: Optional[str] = None, success: bool = False
    ):
        if self.is_window_identified and self.game_window_hwnd:
            info = (
                self.window_selector.get_window_info(self.game_window_hwnd)
                if self.window_selector
                else None
            )
            if info:
                self.window_status_label.setText(
                    f"{info['title']} · {info['size'][0]}×{info['size'][1]}"
                )
                success = True
            else:
                self.window_status_label.setText("游戏窗口已失效")
                success = False
        else:
            self.window_status_label.setText("未识别")
            success = False
        self._set_game_status_chip(success)

    def update_log_display(self):
        text = self.logger.get_logs_text()
        self.log_display.setPlainText(text)
        last = self.logger.get_last_log() or "暂无运行记录"
        self.log_preview.setText(last)
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_logs(self):
        self.logger.clear()
        self.update_log_display()

    def start_worker(self):
        self._sync_buff_values_from_inputs()
        self.follow_heal_adjust_hold_ms = self._read_follow_adjust_hold_ms()
        errors = []
        enabled = [buff for buff in self.buffs if buff.enabled]
        if not enabled:
            errors.append("请至少启用一个 BUFF")
        for index, buff in enumerate(self.buffs):
            if not buff.enabled:
                continue
            if not buff.key:
                errors.append(f"BUFF {index + 1} 尚未选择按键")
            if buff.duration <= 0:
                errors.append(f"BUFF {index + 1} 的持续时间必须大于 0")
        keys = [buff.key.lower() for buff in enabled if buff.key]
        if len(keys) != len(set(keys)):
            errors.append("启用的 BUFF 按键不能重复")
        if self.mode == "follow_heal":
            if not self.follow_heal_key:
                errors.append("请设置加血技能键")
            elif self.follow_heal_key.lower() in keys:
                errors.append("加血技能键不能和 BUFF 按键重复")
            if not self.follow_heal_anchor_pos:
                errors.append("请先标记跟补基准点")
        if errors:
            QMessageBox.warning(self, "配置有误", "\n".join(errors))
            return
        self._persist_settings()
        super().start_worker()
        self._refresh_primary_action()

    def stop_worker(self):
        super().stop_worker()
        self._refresh_primary_action()

    def _refresh_primary_action(self):
        self.toggle_btn.setStyleSheet("")
        self.toggle_btn.setProperty("running", self.is_worker_running)
        self.toggle_btn.setText(
            "■  停止运行" if self.is_worker_running else "▶  开始运行"
        )
        self.toggle_btn.style().unpolish(self.toggle_btn)
        self.toggle_btn.style().polish(self.toggle_btn)

    def _show_buff_countdown(self, show: bool):
        if not show:
            return
        for label in self.buff_countdown_labels:
            label.setText("--")

    def on_countdown_update(self, countdown_info: dict):
        for index, buff in enumerate(self.buffs):
            if index >= len(self.buff_countdown_labels):
                break
            label = self.buff_countdown_labels[index]
            if buff.enabled and buff.key in countdown_info:
                remaining = countdown_info[buff.key]
                label.setText(f"{remaining}s")
                if remaining <= 5:
                    color, background = "#E9404A", "#FDECEE"
                elif remaining <= 30:
                    color, background = "#E78A15", "#FFF4E4"
                else:
                    color, background = "#19A866", "#EAF8F1"
                label.setStyleSheet(
                    f"color:{color};background:{background};"
                    "border-radius:10px;padding:4px;"
                    "font-family:Consolas;font-weight:600;"
                )
            else:
                label.setText("--")

    def _set_buff_settings_enabled(self, enabled: bool):
        for widget in (
            self.buff_checkboxes
            + self.buff_key_btns
            + self.buff_duration_inputs
            + self.buff_remove_btns
            + self.chair_checkboxes
            + self.chair_key_btns
        ):
            widget.setEnabled(enabled)
        self.add_buff_btn.setEnabled(enabled)
        self.random_behavior_checkbox.setEnabled(enabled)
        self.random_behavior_input.setEnabled(enabled)
        self.movement_combo.setEnabled(enabled)
        self.pre_skill_combo.setEnabled(enabled)
        self.jump_key_btn.setEnabled(enabled)
        self.heal_key_btn.setEnabled(enabled)
        self.follow_anchor_btn.setEnabled(enabled)

    def on_mark_portal(self):
        previous = self.manual_portal_pos
        super().on_mark_portal()
        if self.manual_portal_pos != previous:
            self._schedule_save()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and not isinstance(
            obj, QLineEdit
        ):
            self._dismiss_input_focus()
        return super().eventFilter(obj, event)

    def _dismiss_input_focus(self):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            focused.clearFocus()
        if self.centralWidget():
            self.centralWidget().setFocus()

    def closeEvent(self, event):
        self._persist_settings()
        super().closeEvent(event)
