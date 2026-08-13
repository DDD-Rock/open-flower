"""Mac-like compact Windows UI for YzY - Auto Buff."""

import ctypes
import os
import sys
import webbrowser
from typing import List, Optional

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QIntValidator, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
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
from models.map_library import MapLibraryStore
from models.map_topology import NormalizedMapPoint
from models.monitor_state import MonitorSafeZone, SafeZoneStabilizer
from ui.monitor_panel import MonitorPanel
from ui.main_window import MainWindow as LegacyMainWindow
from ui.virtual_keyboard import VirtualKeyboardDialog
from utils.screen_utils import get_screen_resolution
from workers.monitor_worker import MonitorWorker
from workers.rope_party_worker import RopePartyWorker
from workers.lounge_worker import LoungeWorker
from utils.account_manager import AccountError


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

    def __init__(self, account_manager=None, remote_monitor_client=None):
        self.account_manager = account_manager
        self.remote_monitor_client = remote_monitor_client
        self.monitor_worker = None
        self.map_library_store = MapLibraryStore()
        self.map_topologies = self.map_library_store.load()
        self.monitor_matched_topology = None
        self.monitor_safe_zone = None
        self.monitor_zone_stabilizer = SafeZoneStabilizer()
        self._monitor_verification_present = False
        super().__init__()

    def init_ui(self):
        self._loading_settings = True
        self.buffs = [BuffConfig() for _ in range(DEFAULT_BUFF_SLOT_COUNT)]
        self.mode = "dead"
        self.pre_skill_move_mode = "right_only"
        self.follow_heal_key = ""
        self.follow_heal_teleport_key = ""
        self.follow_heal_anchor_pos = None
        self.follow_heal_minimap_region = None
        self.follow_heal_boundary_tolerance = 6.0
        self.follow_heal_return_strategy = "walk"
        self.temple_function = "rope_party"
        self.lounge_move_min_minutes = 15
        self.lounge_move_max_minutes = 30
        self.character_name = ""
        self.rope_party_team_id = 0
        self.pending_rope_party_disband_team_id = 0
        self.rope_party_is_leader = False
        self.rope_party_first_creation = False
        self.rope_party_invite_role_names = []
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
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(150)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 14)
        sidebar_layout.setSpacing(9)
        self._create_sidebar_brand(sidebar_layout)
        self._create_mode_tabs(sidebar_layout)
        sidebar_layout.addStretch(1)
        self._create_status_bar(sidebar_layout)
        root.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("contentPane")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self._create_header(content_layout)

        self.content_stack = QStackedWidget()
        config_page = QWidget()
        config_page_layout = QVBoxLayout(config_page)
        config_page_layout.setContentsMargins(0, 0, 0, 0)
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setFrameShape(QFrame.Shape.NoFrame)
        config_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        config_scroll.setObjectName("mainScroll")
        config_body = QWidget()
        config_body.setObjectName("scrollBody")
        config_body_layout = QVBoxLayout(config_body)
        config_body_layout.setContentsMargins(22, 18, 22, 18)
        config_body_layout.setSpacing(12)
        self.create_settings_section(config_body_layout)
        config_body_layout.addStretch(1)
        config_scroll.setWidget(config_body)
        config_page_layout.addWidget(config_scroll)
        self.content_stack.addWidget(config_page)

        log_page = QWidget()
        log_page_layout = QVBoxLayout(log_page)
        log_page_layout.setContentsMargins(22, 18, 22, 18)
        log_page_layout.setSpacing(12)
        self.create_log_section(log_page_layout)
        log_page_layout.addStretch(1)
        self.content_stack.addWidget(log_page)

        tools_page = QWidget()
        tools_page_layout = QVBoxLayout(tools_page)
        tools_page_layout.setContentsMargins(22, 18, 22, 18)
        tools_page_layout.setSpacing(12)
        self._create_debug_section(tools_page_layout)
        tools_page_layout.addStretch(1)
        self.content_stack.addWidget(tools_page)

        content_layout.addWidget(self.content_stack, 1)
        self.create_control_section(content_layout)
        root.addWidget(content, 1)

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

    def _create_sidebar_brand(self, parent_layout):
        brand = QHBoxLayout()
        brand.setSpacing(10)
        icon = QLabel()
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_icon = QIcon(resource_path(os.path.join("resources", "app_icon.ico")))
        icon.setPixmap(app_icon.pixmap(40, 40))
        brand.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel("AutoBuff")
        name.setStyleSheet("font-size:14px;font-weight:700;color:#172033;")
        caption = QLabel("自动辅助")
        caption.setToolTip("Power by 小新")
        caption.setStyleSheet("font-size:9px;color:#778195;")
        text.addWidget(name)
        text.addWidget(caption)
        brand.addLayout(text)
        brand.addStretch(1)
        parent_layout.addLayout(brand)
        parent_layout.addSpacing(12)

    def _apply_light_theme(self):
        self.setStyleSheet(
            """
            QMainWindow, #appRoot, #contentPane, #scrollBody, #mainScroll {
                background: #F5F8FD;
            }
            QWidget {
                color: #171E30;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                font-size: 11px;
            }
            QFrame#card {
                background: white;
                border: 1px solid #DDE5F0;
                border-radius: 16px;
            }
            QFrame#sidebar {
                background: #FFFFFF;
                border-right: 1px solid #DDE5F0;
            }
            QFrame#contentHeader {
                background: #FFFFFF;
                border-bottom: 1px solid #DDE5F0;
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
                padding: 8px 12px;
                border-radius: 11px;
                min-height: 34px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#primaryAction {
                background: #1675F8;
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
            QPushButton#sectionTab {
                border:none;
                border-radius:8px;
                padding:5px 18px;
                min-height:18px;
                background:transparent;
                color:#4F596B;
                font-weight:600;
            }
            """
        )

    def _create_header(self, parent_layout):
        header_frame = QFrame()
        header_frame.setObjectName("contentHeader")
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(24, 16, 24, 14)
        header.setSpacing(12)
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        self.mode_heading = QLabel(self._mode_title(self.mode))
        self.mode_heading.setStyleSheet("font-size:19px;font-weight:700;color:#172033;")
        self.mode_subtitle = QLabel(self._mode_description(self.mode))
        self.mode_subtitle.setStyleSheet("font-size:10px;color:#778195;")
        title_column.addWidget(self.mode_heading)
        title_column.addWidget(self.mode_subtitle)
        header.addLayout(title_column)
        header.addStretch(1)
        tabs = QFrame()
        tabs.setStyleSheet("background:#EEF1F5;border-radius:9px;")
        tabs_layout = QHBoxLayout(tabs)
        tabs_layout.setContentsMargins(2, 2, 2, 2)
        tabs_layout.setSpacing(0)
        self.config_page_btn = QPushButton("配置")
        self.log_page_btn = QPushButton("日志")
        self.tools_page_btn = QPushButton("工具")
        for button in (
            self.config_page_btn,
            self.log_page_btn,
            self.tools_page_btn,
        ):
            button.setObjectName("sectionTab")
            tabs_layout.addWidget(button)
        self.config_page_btn.clicked.connect(lambda: self._show_content_page(0))
        self.log_page_btn.clicked.connect(lambda: self._show_content_page(1))
        self.tools_page_btn.clicked.connect(lambda: self._show_content_page(2))
        header.addWidget(tabs)
        parent_layout.addWidget(header_frame)
        QTimer.singleShot(0, lambda: self._show_content_page(0))

    def _show_content_page(self, index: int):
        if hasattr(self, "content_stack"):
            self.content_stack.setCurrentIndex(index)
        selected = "background:#AEB0B3;color:white;border-radius:7px;"
        normal = "background:transparent;color:#4F596B;"
        if hasattr(self, "config_page_btn"):
            self.config_page_btn.setStyleSheet(selected if index == 0 else normal)
            self.log_page_btn.setStyleSheet(selected if index == 1 else normal)
            self.tools_page_btn.setStyleSheet(selected if index == 2 else normal)

    def _create_status_bar(self, parent_layout):
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color:#E3E8F2;")
        parent_layout.addWidget(divider)

        if self.account_manager:
            credentials = self.account_manager.session_credentials()
            account_title = QLabel("软件账号")
            account_title.setStyleSheet("font-size:10px;font-weight:700;color:#263044;")
            parent_layout.addWidget(account_title)
            account_name = QLabel(credentials.get("username") or "未登录")
            account_name.setStyleSheet("font-size:10px;color:#1675F8;font-weight:600;")
            parent_layout.addWidget(account_name)
            client_name = QLabel(credentials.get("clientName") or "本机客户端")
            client_name.setStyleSheet("font-size:9px;color:#778195;")
            client_name.setWordWrap(True)
            parent_layout.addWidget(client_name)

        self.admin_status = QLabel()
        self._refresh_admin_status()
        parent_layout.addWidget(self.admin_status)

        self.identify_btn = QPushButton("游戏窗口")
        self.identify_btn.setObjectName("statusChip")
        self.identify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.identify_btn.clicked.connect(self.on_identify_window)
        self.identify_btn.setEnabled(self.window_selector is not None)
        self._set_game_status_chip(False)
        parent_layout.addWidget(self.identify_btn)

        self.window_status_label = QLabel("未识别")
        self.window_status_label.setStyleSheet("color:#747D8D;font-size:10px;")
        self.window_status_label.setWordWrap(True)
        self.window_status_label.setMaximumHeight(34)
        parent_layout.addWidget(self.window_status_label)

        self.portal_marker_btn = QPushButton("地图标注")
        self.portal_marker_btn.setToolTip("标记传送门")
        self.portal_marker_btn.clicked.connect(self.on_mark_portal)
        parent_layout.addWidget(self.portal_marker_btn)

        library = QPushButton("地图仓库")
        library.setObjectName("linkButton")
        library.setStyleSheet(
            "QPushButton{border:none;background:transparent;color:#1370F7;"
            "text-align:left;font-weight:600;padding:3px;}"
        )
        library.clicked.connect(self.on_manage_maps)
        parent_layout.addWidget(library)

        version = QLabel(f"版本 v{APP_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet(
            "color:#1675F8;background:#EAF3FF;border:1px solid #9EC4FB;"
            "border-radius:9px;padding:6px;font-size:10px;font-weight:700;"
        )
        parent_layout.addWidget(version)

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
        self.dead_flower_tab = QPushButton("死花模式")
        self.live_flower_tab = QPushButton("活花模式")
        self.temple_tab = QPushButton("神殿模式")
        self.follow_heal_tab = QPushButton("跟补模式")
        self.monitor_tab = QPushButton("监控模式")
        self.mode_icon_specs = (
            (self.dead_flower_tab, QStyle.StandardPixmap.SP_ArrowBack),
            (self.live_flower_tab, QStyle.StandardPixmap.SP_BrowserReload),
            (self.temple_tab, QStyle.StandardPixmap.SP_DirHomeIcon),
            (self.follow_heal_tab, QStyle.StandardPixmap.SP_DialogYesButton),
            (self.monitor_tab, QStyle.StandardPixmap.SP_ComputerIcon),
        )
        for button, standard_icon in self.mode_icon_specs:
            button.setIcon(self._tinted_standard_icon(standard_icon, "#748096"))
            button.setIconSize(QSize(16, 16))
        for button in (
            self.dead_flower_tab,
            self.live_flower_tab,
            self.temple_tab,
            self.follow_heal_tab,
            self.monitor_tab,
        ):
            button.setObjectName("modeCard")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            parent_layout.addWidget(button)
        self.dead_flower_tab.clicked.connect(
            lambda: self._switch_mode_tab("dead")
        )
        self.live_flower_tab.clicked.connect(
            lambda: self._switch_mode_tab("live")
        )
        self.follow_heal_tab.clicked.connect(
            lambda: self._switch_mode_tab("follow_heal")
        )
        self.monitor_tab.clicked.connect(
            lambda: self._switch_mode_tab("monitor")
        )
        self.temple_tab.clicked.connect(
            lambda: self._switch_mode_tab("temple")
        )
        self._update_mode_tab_style()

    def _tinted_standard_icon(self, standard_icon, color: str) -> QIcon:
        pixmap = self.style().standardIcon(standard_icon).pixmap(18, 18)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color))
        painter.end()
        return QIcon(pixmap)

    def _switch_mode_tab(self, mode):
        if self.is_worker_running:
            return
        if isinstance(mode, bool):
            mode = "dead" if mode else "live"
        self.mode = mode
        self.return_to_market = self.mode == "dead"
        self._update_mode_tab_style()
        self._update_movement_mode_visibility()
        if self.remote_monitor_client:
            self.remote_monitor_client.publish_client_state(self.mode, False)
        self.logger.log(f"切换到: {self._mode_title(self.mode)}")
        self.update_log_display()
        self._schedule_save()

    def _mode_title(self, mode: str) -> str:
        return {
            "dead": "死花模式",
            "live": "活花模式",
            "follow_heal": "跟补模式",
            "monitor": "监控模式",
            "temple": "神殿模式",
        }.get(mode, "活花模式")

    def _mode_description(self, mode: str) -> str:
        return {
            "dead": "释放 BUFF 后自动进入自由市场",
            "live": "在当前地图循环释放 BUFF",
            "follow_heal": "自动补血、位置修正并回到基准点",
            "monitor": "只读取游戏画面并显示实时地图",
            "temple": "为时间神殿地图配置专用 BUFF 行为",
        }.get(mode, "在当前地图循环释放 BUFF")

    def _update_mode_tab_style(self):
        selected = (
            "QPushButton{background:#EAF3FF;color:#1675F8;"
            "border:1px solid #78AEF8;border-radius:11px;"
            "padding:8px 12px;text-align:left;min-height:34px;"
            "font-size:12px;font-weight:600;}"
        )
        normal = (
            "QPushButton{background:white;color:#5F6878;"
            "border:1px solid #DDE5F0;border-radius:11px;"
            "padding:8px 12px;text-align:left;min-height:34px;"
            "font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#F8FAFD;border-color:#AFCFFF;}"
        )
        self.dead_flower_tab.setStyleSheet(selected if self.mode == "dead" else normal)
        self.live_flower_tab.setStyleSheet(selected if self.mode == "live" else normal)
        self.follow_heal_tab.setStyleSheet(
            selected if self.mode == "follow_heal" else normal
        )
        self.monitor_tab.setStyleSheet(selected if self.mode == "monitor" else normal)
        self.temple_tab.setStyleSheet(selected if self.mode == "temple" else normal)
        if hasattr(self, "mode_icon_specs"):
            selected_button = {
                "dead": self.dead_flower_tab,
                "live": self.live_flower_tab,
                "temple": self.temple_tab,
                "follow_heal": self.follow_heal_tab,
                "monitor": self.monitor_tab,
            }.get(self.mode)
            for button, standard_icon in self.mode_icon_specs:
                button.setIcon(
                    self._tinted_standard_icon(
                        standard_icon,
                        "#1675F8" if button is selected_button else "#748096",
                    )
                )
        if hasattr(self, "mode_heading"):
            self.mode_heading.setText(self._mode_title(self.mode))
            self.mode_subtitle.setText(self._mode_description(self.mode))
        if hasattr(self, "tools_page_btn"):
            self.tools_page_btn.setVisible(self.mode != "monitor")
            if self.mode == "monitor" and self.content_stack.currentIndex() == 2:
                self._show_content_page(0)
        if hasattr(self, "footer_status_mode"):
            self.footer_status_mode.setText(self._mode_title(self.mode))

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

        self.temple_function_widget = self._create_temple_function_selector()
        self.movement_stack = QStackedWidget()
        self.movement_stack.addWidget(self._create_live_options())
        self.movement_stack.addWidget(self._create_dead_options())
        self.movement_stack.addWidget(self._create_follow_heal_options())
        self.movement_stack.addWidget(self._create_temple_options())
        self.movement_stack.addWidget(self._create_rope_party_options())

        party_row = QHBoxLayout()
        party_title = QLabel("自动同意组队")
        party_title.setStyleSheet("font-size:11px;font-weight:600;")
        party_row.addWidget(party_title)
        self.party_invite_status_label = QLabel("待机")
        self.party_invite_status_label.setStyleSheet(
            "color:#747D8D;font-size:9px;"
        )
        party_row.addWidget(self.party_invite_status_label)
        party_row.addStretch(1)
        self.party_invite_checkbox = QCheckBox()
        self.party_invite_checkbox.toggled.connect(
            self.on_auto_accept_party_invite_toggled
        )
        party_row.addWidget(self.party_invite_checkbox)
        layout.addLayout(party_row)

        map_row = QHBoxLayout()
        map_title = QLabel("地图标注")
        map_title.setStyleSheet("font-size:11px;font-weight:600;")
        map_row.addWidget(map_title)
        self.map_count_label = QLabel(f"已创建 {len(self.map_topologies)} 张地图")
        self.map_count_label.setStyleSheet("color:#747D8D;font-size:9px;")
        map_row.addWidget(self.map_count_label)
        map_row.addStretch(1)
        manage_maps_inline = QPushButton("管理地图")
        manage_maps_inline.clicked.connect(self.on_manage_maps)
        map_row.addWidget(manage_maps_inline)
        layout.addLayout(map_row)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color:#E7EBF2;")
        layout.addWidget(divider)
        layout.addWidget(self.temple_function_widget)
        layout.addWidget(self.movement_stack)

        self.role_widget = QWidget()
        role_row = QHBoxLayout(self.role_widget)
        role_row.setContentsMargins(0, 0, 0, 0)
        role_row.addWidget(QLabel("游戏角色名"))
        self.character_name_input = QLineEdit()
        self.character_name_input.setPlaceholderText("用于网页组队邀请")
        self.character_name_input.setMaxLength(24)
        self.character_name_input.setMinimumWidth(200)
        self.character_name_input.setMaximumWidth(230)
        self.character_name_input.textChanged.connect(self._schedule_save)
        role_row.addWidget(self.character_name_input, 1)
        save_role_btn = QPushButton("保存")
        save_role_btn.clicked.connect(self._save_character_name)
        role_row.addWidget(save_role_btn)
        layout.addWidget(self.role_widget)

        self.role_actions_widget = QWidget()
        role_actions_row = QHBoxLayout(self.role_actions_widget)
        role_actions_row.setContentsMargins(0, 0, 0, 0)
        role_actions_row.addStretch(1)
        clients_btn = QPushButton("客户端管理")
        clients_btn.clicked.connect(self._open_clients_page)
        role_actions_row.addWidget(clients_btn)
        copy_btn = QPushButton("复制链接")
        copy_btn.clicked.connect(self._copy_clients_page)
        role_actions_row.addWidget(copy_btn)
        layout.addWidget(self.role_actions_widget)
        self.settings_card = card
        parent_layout.addWidget(card)
        self.monitor_panel = MonitorPanel()
        self.monitor_panel.manage_maps_button.clicked.connect(self.on_manage_maps)
        self.monitor_panel.action_test_button.clicked.connect(self.on_map_action_test)
        self.monitor_panel.route_test_button.clicked.connect(self.on_map_route_test)
        self.monitor_panel.zone_button.clicked.connect(self.on_mark_monitor_zone)
        self.monitor_panel.clear_zone_button.clicked.connect(self.on_clear_monitor_zone)
        self.monitor_panel.display_mode.currentIndexChanged.connect(self._schedule_save)
        self.monitor_panel.zone_width.valueChanged.connect(self._update_monitor_zone_size)
        self.monitor_panel.zone_height.valueChanged.connect(self._update_monitor_zone_size)
        self.monitor_panel.setVisible(False)
        parent_layout.addWidget(self.monitor_panel)

    def _create_temple_function_selector(self):
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("神殿功能"))
        self.temple_function_combo = QComboBox()
        self.temple_function_combo.addItem("休息室", "lounge")
        self.temple_function_combo.addItem("挂绳组队", "rope_party")
        self.temple_function_combo.addItem("进出自由", "free_entry")
        self.temple_function_combo.currentIndexChanged.connect(self._on_temple_function_changed)
        self.temple_function_combo.setVisible(False)
        self.temple_function_buttons = []
        for index, text in enumerate(("休息室", "挂绳组队", "进出自由")):
            button = QPushButton(text)
            button.clicked.connect(
                lambda _=False, value=index: self.temple_function_combo.setCurrentIndex(value)
            )
            row.addWidget(button, 1)
            self.temple_function_buttons.append(button)
        self.temple_function_combo.currentIndexChanged.connect(
            self._refresh_temple_function_buttons
        )
        self._refresh_temple_function_buttons()
        return panel

    def _refresh_temple_function_buttons(self):
        current = self.temple_function_combo.currentIndex()
        for index, button in enumerate(self.temple_function_buttons):
            button.setStyleSheet(
                (
                    "background:#FFFFFF;color:#171E30;border:1px solid #CCD5E2;"
                    if index == current
                    else "background:#F1F4F8;color:#667085;border:1px solid #E2E7EF;"
                )
                + "border-radius:7px;padding:4px 7px;"
            )

    def _create_temple_options(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("防卡移动间隔"))
        row.addStretch(1)
        self.lounge_move_min_input = QSpinBox()
        self.lounge_move_min_input.setRange(1, 1440)
        self.lounge_move_min_input.setSuffix(" 分钟")
        self.lounge_move_min_input.valueChanged.connect(self._on_lounge_interval_changed)
        row.addWidget(self.lounge_move_min_input)
        row.addWidget(QLabel("至"))
        self.lounge_move_max_input = QSpinBox()
        self.lounge_move_max_input.setRange(1, 1440)
        self.lounge_move_max_input.setSuffix(" 分钟")
        self.lounge_move_max_input.valueChanged.connect(self._on_lounge_interval_changed)
        row.addWidget(self.lounge_move_max_input)
        layout.addLayout(row)
        note = QLabel("启动、人数增加或自动接受组队后释放全部 BUFF；倒计时结束不会释放。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#747D8D;font-size:9px;")
        layout.addWidget(note)
        return panel

    def _create_rope_party_options(self):
        note = QLabel("队伍由客户端管理网页统一创建；保存后会自动切换模式并开始运行。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#747D8D;font-size:9px;")
        return note

    def _on_temple_function_changed(self):
        self.temple_function = self.temple_function_combo.currentData() or "rope_party"
        self._update_movement_mode_visibility()
        self._schedule_save()

    def _on_lounge_interval_changed(self):
        self.lounge_move_min_minutes = self.lounge_move_min_input.value()
        self.lounge_move_max_minutes = self.lounge_move_max_input.value()
        self._schedule_save()

    def _clients_url(self):
        if not self.account_manager:
            return ""
        return f"{self.account_manager.server_base_url}/clients"

    def _open_clients_page(self):
        url = self._clients_url()
        if url:
            webbrowser.open(url)

    def _copy_clients_page(self):
        url = self._clients_url()
        if url:
            QApplication.clipboard().setText(url)
            self.logger.log("已复制客户端管理链接")
            self.update_log_display()

    def _save_character_name(self):
        name = self.character_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "角色名称", "请输入角色名称")
            return
        try:
            self.character_name = self.account_manager.save_role_name(name)
            self.character_name_input.setText(self.character_name)
            self.logger.log("角色名称已保存")
            self.update_log_display()
            self._schedule_save()
        except AccountError as error:
            QMessageBox.warning(self, "保存失败", str(error))

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
            ("只向右（骨龙、忘却）", "right_only"),
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

        portal = QPushButton("标记传送门")
        portal.clicked.connect(self.on_mark_portal)
        row.addWidget(self._option_column("自由市场传送门", portal), 1)
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

        self.follow_heal_return_combo = QComboBox()
        self.follow_heal_return_combo.addItem("左右走防卡", "walk")
        self.follow_heal_return_combo.addItem("瞬移回位", "teleport")
        self.follow_heal_return_combo.currentIndexChanged.connect(
            self._on_follow_heal_return_strategy_changed
        )
        row.addWidget(self._option_column("回位方案", self.follow_heal_return_combo), 1)

        self.teleport_key_btn = QPushButton("选键")
        self.teleport_key_btn.setFixedWidth(54)
        self.teleport_key_btn.clicked.connect(self.on_select_teleport_key)
        row.addWidget(self._option_column("瞬移技能键", self.teleport_key_btn), 1)

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

    def create_log_section(self, parent_layout):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(5)

        header = QHBoxLayout()
        self.log_toggle_btn = QPushButton("运行日志")
        self.log_toggle_btn.setObjectName("linkButton")
        self.log_toggle_btn.setStyleSheet(
            "QPushButton{border:none;background:transparent;color:#171E30;"
            "font-weight:700;text-align:left;padding:2px;}"
        )
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
        self.log_preview.setVisible(False)
        layout.addWidget(self.log_preview)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMinimumHeight(420)
        self.log_display.setVisible(True)
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
        self.debug_toggle_btn.setVisible(False)
        parent_layout.addWidget(self.debug_toggle_btn)

        self.debug_widget = QFrame()
        self.debug_widget.setObjectName("card")
        self.debug_widget.setVisible(True)
        row = QHBoxLayout(self.debug_widget)
        row.setContentsMargins(14, 14, 14, 14)
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
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(22, 10, 22, 11)
        layout.setSpacing(14)
        self.is_worker_running = False
        status = QVBoxLayout()
        status.setSpacing(0)
        self.footer_status_title = QLabel("●  准备就绪")
        self.footer_status_title.setStyleSheet(
            "color:#4F596B;font-size:10px;font-weight:700;"
        )
        self.footer_status_mode = QLabel(self._mode_title(self.mode))
        self.footer_status_mode.setStyleSheet("color:#8791A3;font-size:9px;")
        status.addWidget(self.footer_status_title)
        status.addWidget(self.footer_status_mode)
        layout.addLayout(status)
        self.toggle_btn = QPushButton("▶  开始运行")
        self.toggle_btn.setObjectName("primaryAction")
        self.toggle_btn.setProperty("running", False)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.on_toggle_worker)
        layout.addWidget(self.toggle_btn, 1)
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
        self.follow_heal_teleport_key = settings.get("teleport_skill_key", "")
        self.follow_heal_anchor_pos = settings.get("follow_heal_anchor_pos")
        self.follow_heal_minimap_region = settings.get("follow_heal_minimap_region")
        self.follow_heal_boundary_tolerance = settings.get(
            "follow_heal_boundary_tolerance", 6.0
        )
        self.follow_heal_return_strategy = settings.get(
            "follow_heal_return_strategy", "walk"
        )
        self.sit_chair_enabled = settings.get("sit_chair_enabled", False)
        self.selected_chair_key = settings.get("chair_key", "=")
        self.movement_mode = settings.get("movement_mode", "none")
        self.pre_skill_move_mode = settings.get(
            "pre_skill_move_mode", "right_only"
        )
        self.manual_portal_pos = settings.get("manual_portal_pos")
        self.auto_accept_party_invite = settings.get(
            "auto_accept_party_invite", False
        )
        self.temple_function = settings.get("temple_function", "rope_party")
        self.lounge_move_min_minutes = max(1, min(1440, int(settings.get("lounge_move_min_minutes", 15))))
        self.lounge_move_max_minutes = max(1, min(1440, int(settings.get("lounge_move_max_minutes", 30))))
        if self.lounge_move_max_minutes < self.lounge_move_min_minutes:
            self.lounge_move_max_minutes = max(30, self.lounge_move_min_minutes)
        self.character_name = settings.get("character_name", "")
        if self.account_manager:
            self.character_name = self.account_manager.session_credentials().get("roleName") or self.character_name
        self.rope_party_team_id = settings.get("rope_party_team_id", 0)
        self.rope_party_is_leader = settings.get("rope_party_is_leader", False)
        self.rope_party_invite_role_names = settings.get("rope_party_invite_role_names", [])
        self.monitor_safe_zone = (
            MonitorSafeZone.from_dict(settings["monitor_safe_zone"])
            if settings.get("monitor_safe_zone")
            else None
        )
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
        self.teleport_key_btn.setText(self.follow_heal_teleport_key or "选键")
        strategy_index = self.follow_heal_return_combo.findData(
            self.follow_heal_return_strategy
        )
        self.follow_heal_return_combo.setCurrentIndex(max(0, strategy_index))
        self.teleport_key_btn.setEnabled(True)
        self._update_follow_heal_anchor_label()
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
        self.party_invite_checkbox.blockSignals(True)
        self.party_invite_checkbox.setChecked(self.auto_accept_party_invite)
        self.party_invite_checkbox.blockSignals(False)
        self.character_name_input.setText(self.character_name)
        index = self.temple_function_combo.findData(self.temple_function)
        self.temple_function_combo.setCurrentIndex(max(0, index))
        self.lounge_move_min_input.blockSignals(True)
        self.lounge_move_max_input.blockSignals(True)
        self.lounge_move_min_input.setValue(self.lounge_move_min_minutes)
        self.lounge_move_max_input.setValue(self.lounge_move_max_minutes)
        self.lounge_move_min_input.blockSignals(False)
        self.lounge_move_max_input.blockSignals(False)
        display_mode = settings.get(
            "monitor_display_mode",
            "minimap_with_annotations",
        )
        display_index = self.monitor_panel.display_mode.findData(display_mode)
        self.monitor_panel.display_mode.setCurrentIndex(max(0, display_index))
        if self.monitor_safe_zone:
            self.monitor_panel.zone_width.setValue(
                round(self.monitor_safe_zone.width * 100)
            )
            self.monitor_panel.zone_height.setValue(
                round(self.monitor_safe_zone.height * 100)
            )

    def _apply_default_settings(self):
        self.mode = "dead"
        self.return_to_market = True
        self.movement_mode = "none"
        self.pre_skill_move_mode = "right_only"
        self.selected_jump_key = "Alt"
        self.follow_heal_key = ""
        self.follow_heal_teleport_key = ""
        self.follow_heal_anchor_pos = None
        self.follow_heal_minimap_region = None
        self.follow_heal_boundary_tolerance = 6.0
        self.follow_heal_return_strategy = "walk"
        self.sit_chair_enabled = False
        self.selected_chair_key = "="
        self.manual_portal_pos = None
        self.auto_accept_party_invite = False
        self.temple_function = "rope_party"
        self.lounge_move_min_minutes = 15
        self.lounge_move_max_minutes = 30
        self.character_name = self.account_manager.session_credentials().get("roleName", "") if self.account_manager else ""
        self.rope_party_team_id = 0
        self.rope_party_is_leader = False
        self.rope_party_invite_role_names = []
        self.monitor_safe_zone = None
        self.monitor_zone_stabilizer.reset()
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
        self.teleport_key_btn.setText("选键")
        self.follow_heal_return_combo.setCurrentIndex(0)
        self.teleport_key_btn.setEnabled(True)
        self._update_follow_heal_anchor_label()
        self._sync_chair_controls()
        self.random_behavior_checkbox.setChecked(True)
        self.random_behavior_input.setText("20")
        self._set_movement_mode_radio("none")
        self._set_pre_skill_move_mode_radio("right_only")
        self._update_mode_tab_style()
        self.party_invite_checkbox.blockSignals(True)
        self.party_invite_checkbox.setChecked(False)
        self.party_invite_checkbox.blockSignals(False)
        self.character_name_input.setText(self.character_name)
        self.temple_function_combo.setCurrentIndex(max(0, self.temple_function_combo.findData("rope_party")))
        self.lounge_move_min_input.blockSignals(True)
        self.lounge_move_max_input.blockSignals(True)
        self.lounge_move_min_input.setValue(15)
        self.lounge_move_max_input.setValue(30)
        self.lounge_move_min_input.blockSignals(False)
        self.lounge_move_max_input.blockSignals(False)

    def _persist_settings(self):
        if self._loading_settings:
            return
        self._sync_buff_values_from_inputs()
        try:
            random_value = int(self.random_behavior_input.text() or "20")
        except ValueError:
            random_value = 20
        self.settings_manager.save_settings(
            buffs=self.buffs,
            mode=self.mode,
            return_to_market=self.return_to_market,
            jump_key=self.selected_jump_key,
            heal_skill_key=self.follow_heal_key,
            teleport_skill_key=self.follow_heal_teleport_key,
            follow_heal_anchor_pos=self.follow_heal_anchor_pos,
            follow_heal_minimap_region=self.follow_heal_minimap_region,
            follow_heal_boundary_tolerance=self.follow_heal_boundary_tolerance,
            follow_heal_return_strategy=self.follow_heal_return_strategy,
            sit_chair_enabled=self.sit_chair_enabled,
            chair_key=self.selected_chair_key,
            random_behavior_enabled=self.random_behavior_checkbox.isChecked(),
            random_behavior_value=random_value,
            movement_mode=self.movement_mode,
            pre_skill_move_mode=self.pre_skill_move_mode,
            auto_accept_party_invite=self.auto_accept_party_invite,
            temple_function=self.temple_function,
            lounge_move_min_minutes=self.lounge_move_min_input.value(),
            lounge_move_max_minutes=self.lounge_move_max_input.value(),
            character_name=self.character_name_input.text().strip(),
            rope_party_team_id=self.rope_party_team_id,
            rope_party_is_leader=self.rope_party_is_leader,
            rope_party_invite_role_names=self.rope_party_invite_role_names,
            manual_portal_pos=self.manual_portal_pos,
            monitor_display_mode=self.monitor_panel.display_mode.currentData(),
            monitor_safe_zone=(
                self.monitor_safe_zone.to_dict()
                if self.monitor_safe_zone is not None
                else None
            ),
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

    def on_select_teleport_key(self):
        previous = self.follow_heal_teleport_key
        super().on_select_teleport_key()
        if self.follow_heal_teleport_key != previous:
            self.teleport_key_btn.setText(
                self.follow_heal_teleport_key or "选键"
            )
            self._schedule_save()

    def _on_follow_heal_return_strategy_changed(self):
        strategy = self.follow_heal_return_combo.currentData() or "walk"
        self.follow_heal_return_strategy = strategy
        self.teleport_key_btn.setEnabled(not self.is_worker_running)
        self._schedule_save()

    def on_mark_follow_anchor(self):
        previous_anchor = self.follow_heal_anchor_pos
        previous_region = self.follow_heal_minimap_region
        previous_tolerance = self.follow_heal_boundary_tolerance
        super().on_mark_follow_anchor()
        if (
            self.follow_heal_anchor_pos != previous_anchor
            or self.follow_heal_minimap_region != previous_region
            or self.follow_heal_boundary_tolerance != previous_tolerance
        ):
            self._update_follow_heal_anchor_label()
            self._schedule_save()

    def _update_follow_heal_anchor_label(self):
        if not hasattr(self, "follow_anchor_label"):
            return
        if self.follow_heal_anchor_pos:
            x, _ = self.follow_heal_anchor_pos
            tolerance = f"{self.follow_heal_boundary_tolerance:g}"
            self.follow_anchor_label.setText(f"X={x} · ±{tolerance}")
        else:
            self.follow_anchor_label.setText("未标记")

    def _update_movement_mode_visibility(self):
        is_temple = self.mode == "temple"
        self.temple_function_widget.setVisible(is_temple)
        self.role_widget.setVisible(is_temple)
        self.role_actions_widget.setVisible(is_temple)
        if self.mode == "dead":
            self.movement_stack.setCurrentIndex(1)
        elif self.mode == "follow_heal":
            self.movement_stack.setCurrentIndex(2)
        elif self.mode == "temple":
            self.movement_stack.setCurrentIndex({
                "free_entry": 1,
                "lounge": 3,
                "rope_party": 4,
            }.get(self.temple_function, 4))
        else:
            self.movement_stack.setCurrentIndex(0)
        is_monitor = self.mode == "monitor"
        self.settings_card.setVisible(not is_monitor)
        self.monitor_panel.setVisible(is_monitor)
        self.portal_marker_btn.setVisible(
            self.mode == "dead"
            or (self.mode == "temple" and self.temple_function == "free_entry")
        )

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
        if self.mode == "monitor":
            self._start_monitor_worker()
            return
        if self.mode == "temple":
            self._start_temple_worker()
            return
        self._sync_buff_values_from_inputs()
        errors = []
        enabled = [buff for buff in self.buffs if buff.enabled]
        if not enabled and self.mode != "follow_heal":
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
            if not self.follow_heal_teleport_key:
                errors.append("请设置瞬移技能键")
            elif (
                self.follow_heal_teleport_key.lower() in keys
            ):
                errors.append("瞬移技能键不能和 BUFF 按键重复")
            elif (
                self.follow_heal_key
                and self.follow_heal_teleport_key.lower()
                == self.follow_heal_key.lower()
            ):
                errors.append("瞬移技能键不能和加血技能键重复")
            if not self.follow_heal_anchor_pos:
                errors.append("请先标记跟补基准点")
            if not 1.0 <= self.follow_heal_boundary_tolerance <= 50.0:
                errors.append("跟补左右界限值必须在 1 到 50 之间")
        if errors:
            QMessageBox.warning(self, "配置有误", "\n".join(errors))
            return
        self._persist_settings()
        super().start_worker()
        self.temple_tab.setEnabled(False)
        if self.is_worker_running and self.remote_monitor_client:
            self.remote_monitor_client.publish_client_state(self.mode, True)
        self._refresh_primary_action()

    def _start_temple_worker(self):
        self._sync_buff_values_from_inputs()
        enabled = [buff for buff in self.buffs if buff.enabled]
        errors = []
        if self.temple_function != "rope_party" and not enabled:
            errors.append("请至少启用一个 BUFF")
        for index, buff in enumerate(self.buffs):
            if not buff.enabled:
                continue
            if not buff.key:
                errors.append(f"BUFF {index + 1} 尚未选择按键")
            if self.temple_function != "lounge" and buff.duration <= 0:
                errors.append(f"BUFF {index + 1} 的持续时间必须大于 0")
        keys = [buff.key.lower() for buff in enabled if buff.key]
        if len(keys) != len(set(keys)):
            errors.append("启用的 BUFF 按键不能重复")
        if self.temple_function == "lounge":
            if self.lounge_move_min_input.value() > self.lounge_move_max_input.value():
                errors.append("休息室防卡最短间隔不能大于最长间隔")
        elif self.temple_function == "rope_party" and not self.character_name_input.text().strip():
            errors.append("挂绳组队需要先填写并保存角色名称")
        if errors:
            QMessageBox.warning(self, "配置有误", "\n".join(errors))
            return
        if not self.is_window_identified:
            self.auto_identify_on_startup()
        if not self.is_window_identified or not self.game_window_hwnd:
            QMessageBox.warning(self, "神殿模式", "未找到游戏窗口")
            return
        self._persist_settings()

        if self.temple_function == "free_entry":
            self._start_temple_free_entry()
        elif self.temple_function == "lounge":
            self._start_lounge_worker()
        else:
            self._start_rope_party_worker()

    def _start_rope_party_worker(self):
        worker = RopePartyWorker(
            self.game_window_hwnd,
            self.rope_party_is_leader,
            self.rope_party_first_creation,
            self.rope_party_invite_role_names,
            buffs=self.buffs,
        )
        worker.log_update.connect(self.on_status_update)
        worker.error_signal.connect(self.on_error)
        worker.finished_signal.connect(lambda worker=worker: self.on_worker_finished(worker))
        worker.buff_due.connect(self._on_rope_party_buff_due)
        worker.boss_joined.connect(self._on_rope_party_boss_joined)
        worker.boss_buffs_completed.connect(self._on_rope_party_buffs_completed)
        worker.party_commands_finished.connect(self._on_rope_party_commands_finished)
        worker.party_rebuild_commands_finished.connect(self._on_rope_party_rebuild_commands_finished)
        worker.countdown_update.connect(self.on_countdown_update)
        self.worker = worker
        self.is_worker_running = True
        worker.start()
        self.rope_party_first_creation = False
        self._set_temple_running_ui()

    def _on_rope_party_commands_finished(self):
        if self.remote_monitor_client and self.rope_party_team_id > 0:
            self.remote_monitor_client.publish_rope_party_progress(self.rope_party_team_id, "party_commands_finished")
            self.logger.log("建队和邀请命令已全部执行")
            self.update_log_display()

    def _on_rope_party_rebuild_commands_finished(self, cycle_id):
        if self.remote_monitor_client and self.rope_party_team_id > 0:
            self.remote_monitor_client.publish_rope_party_progress(
                self.rope_party_team_id, "party_rebuild_commands_finished", cycle_id=cycle_id
            )
            self.logger.log("解散、重建和邀请命令已全部执行")
            self.update_log_display()

    def _on_rope_party_buff_due(self):
        if self.remote_monitor_client and self.rope_party_team_id > 0:
            self.remote_monitor_client.publish_rope_party_progress(
                self.rope_party_team_id,
                "buff_due",
            )
            self.logger.log("BUFF 即将到期，已请求老板邀请周期")
            self.update_log_display()

    def _on_rope_party_boss_joined(self, cycle_id):
        if self.remote_monitor_client and self.rope_party_team_id > 0:
            self.remote_monitor_client.publish_rope_party_progress(
                self.rope_party_team_id,
                "boss_joined",
                cycle_id=cycle_id,
            )
            self.logger.log("已向服务器上报老板进队")
            self.update_log_display()

    def _on_rope_party_buffs_completed(self, cycle_id):
        if self.remote_monitor_client and self.rope_party_team_id > 0:
            self.remote_monitor_client.publish_rope_party_progress(
                self.rope_party_team_id,
                "buff_finished",
                cycle_id=cycle_id,
            )
            self.logger.log("本客户端老板 BUFF 已释放完毕并上报")
            self.update_log_display()

    def _start_lounge_worker(self):
        worker = LoungeWorker(
            self.game_window_hwnd,
            self.buffs,
            self.lounge_move_min_input.value(),
            self.lounge_move_max_input.value(),
        )
        worker.log_update.connect(self.on_status_update)
        worker.error_signal.connect(self.on_error)
        worker.finished_signal.connect(lambda worker=worker: self.on_worker_finished(worker))
        self.worker = worker
        self.is_worker_running = True
        worker.start()
        self._set_temple_running_ui()

    def _start_temple_free_entry(self):
        original_mode = self.mode
        original_return = self.return_to_market
        self.mode = "dead"
        self.return_to_market = True
        super().start_worker()
        self.mode = original_mode
        self.return_to_market = original_return
        self._update_mode_tab_style()
        self._update_movement_mode_visibility()
        if self.is_worker_running:
            self.logger.log("神殿模式 · 进出自由已启动")
            self.update_log_display()
            self._set_temple_running_ui()

    def _set_temple_running_ui(self):
        self._set_buff_settings_enabled(False)
        self.temple_function_combo.setEnabled(False)
        for button in self.temple_function_buttons:
            button.setEnabled(False)
        self.lounge_move_min_input.setEnabled(False)
        self.lounge_move_max_input.setEnabled(False)
        for tab in (self.dead_flower_tab, self.live_flower_tab, self.follow_heal_tab, self.monitor_tab, self.temple_tab):
            tab.setEnabled(False)
        if self.remote_monitor_client:
            self.remote_monitor_client.publish_client_state(self.mode, True)
        self._refresh_primary_action()

    def on_worker_finished(self, worker=None):
        """Handle completion only for the worker that is currently active.

        A remote configuration can stop one worker and start its replacement
        before Qt delivers the old worker's finished signal.  Without the
        identity check below, that stale signal calls ``stop_worker`` and
        immediately stops the replacement as well.
        """
        if worker is not None and self.worker is not worker:
            return
        self.logger.log("Worker已停止")
        self.update_log_display()
        self.stop_worker()

    def stop_worker(self):
        monitor_worker = self.monitor_worker
        if monitor_worker is not None:
            monitor_worker.stop()
            # ``stopped`` is delivered through the Qt event loop. Keep the
            # worker registered until cleanup runs, and restore the controls
            # synchronously as a fallback when the user clicks Stop.
            if self.monitor_worker is monitor_worker:
                self._on_monitor_stopped(monitor_worker)
        super().stop_worker()
        if hasattr(self, "monitor_tab"):
            self.monitor_tab.setEnabled(True)
        if hasattr(self, "temple_tab"):
            self.temple_tab.setEnabled(True)
        if hasattr(self, "temple_function_combo"):
            self.temple_function_combo.setEnabled(True)
            for button in self.temple_function_buttons:
                button.setEnabled(True)
            self.lounge_move_min_input.setEnabled(True)
            self.lounge_move_max_input.setEnabled(True)
        if hasattr(self, "monitor_panel") and self.mode == "monitor":
            self.monitor_panel.reset()
        if self.remote_monitor_client:
            self.remote_monitor_client.publish_client_state(self.mode, False)
        self._sync_party_invite_worker()
        self._refresh_primary_action()

    def _refresh_primary_action(self):
        self.toggle_btn.setStyleSheet("")
        self.toggle_btn.setProperty("running", self.is_worker_running)
        self.toggle_btn.setText(
            (
                "■  停止监控" if self.is_worker_running else "▶  开始监控"
            )
            if self.mode == "monitor"
            else ("■  停止运行" if self.is_worker_running else "▶  开始运行")
        )
        self.toggle_btn.style().unpolish(self.toggle_btn)
        self.toggle_btn.style().polish(self.toggle_btn)
        if hasattr(self, "footer_status_title"):
            self.footer_status_title.setText(
                "●  正在运行" if self.is_worker_running else "●  准备就绪"
            )
            self.footer_status_title.setStyleSheet(
                (
                    "color:#19A866;font-size:10px;font-weight:700;"
                    if self.is_worker_running
                    else "color:#4F596B;font-size:10px;font-weight:700;"
                )
            )
            self.footer_status_mode.setText(self._mode_title(self.mode))

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
        self.follow_heal_return_combo.setEnabled(enabled)
        self.teleport_key_btn.setEnabled(enabled)
        self.follow_anchor_btn.setEnabled(enabled)

    def _start_monitor_worker(self):
        if not self.is_window_identified:
            self.auto_identify_on_startup()
        if not self.is_window_identified or not self.game_window_hwnd:
            QMessageBox.warning(self, "警告", "未找到游戏窗口，请确保游戏已启动！")
            return
        if self.window_selector and not self.window_selector.is_window_valid(
            self.game_window_hwnd
        ):
            QMessageBox.warning(self, "警告", "游戏窗口已关闭，请重新识别！")
            return

        self._stop_party_invite_worker()
        worker = MonitorWorker(
            self.game_window_hwnd,
            maps=self.map_topologies,
            window_selector=self.window_selector,
            parent=self,
        )
        self.monitor_worker = worker
        worker.frame_ready.connect(self._on_monitor_frame)
        worker.status_update.connect(self._on_monitor_status)
        worker.rune_update.connect(self._on_monitor_rune)
        worker.verification_update.connect(self._on_monitor_verification)
        worker.verification_recording_update.connect(self._on_monitor_recording_update)
        worker.exp_update.connect(self._on_monitor_exp)
        worker.error_signal.connect(self._on_monitor_error)
        worker.stopped.connect(lambda current=worker: self._on_monitor_stopped(current))
        self.is_worker_running = True
        self.dead_flower_tab.setEnabled(False)
        self.live_flower_tab.setEnabled(False)
        self.follow_heal_tab.setEnabled(False)
        self.monitor_tab.setEnabled(False)
        self.monitor_panel.manage_maps_button.setEnabled(False)
        self.monitor_panel.action_test_button.setEnabled(False)
        self.monitor_panel.route_test_button.setEnabled(False)
        self.logger.log("只读监控已启动")
        self.update_log_display()
        worker.start()
        if self.remote_monitor_client:
            self.remote_monitor_client.publish_client_state("monitor", True)
        self._refresh_primary_action()

    def _on_monitor_frame(self, frame):
        if self.monitor_worker is None:
            return
        image = frame.get("image")
        player = frame.get("player")
        if self.monitor_safe_zone is not None and image is not None and player is not None:
            observed_outside = not self.monitor_safe_zone.contains(
                player,
                (image.shape[1], image.shape[0]),
            )
        else:
            observed_outside = None
        change = self.monitor_zone_stabilizer.update(observed_outside)
        if change == "breached":
            self.logger.log("角色已离开监控安全区")
            self.update_log_display()
        elif change == "returned":
            self.logger.log("角色已回到监控安全区")
            self.update_log_display()
        elif change == "lost_track":
            self.logger.log("持续未识别到角色，已停止安全区报警")
            self.update_log_display()
        frame["safe_zone"] = self.monitor_safe_zone
        frame["zone_outside"] = self.monitor_zone_stabilizer.is_outside
        self.monitor_panel.update_frame(frame)
        topology = frame.get("map")
        if topology is not None:
            self.monitor_matched_topology = topology
        if self.remote_monitor_client and image is not None:
            size = (image.shape[1], image.shape[0])
            if topology is not None:
                self.remote_monitor_client.publish_map(topology, size)
            self.remote_monitor_client.publish_frame(
                frame.get("player"),
                frame.get("teammates", []),
                frame.get("others", []),
                size,
                frame.get("fps", 0),
                frame.get("capturedAt"),
            )
            self.remote_monitor_client.publish_zone(
                self.monitor_zone_stabilizer.is_outside,
                self.monitor_safe_zone,
            )

    def _on_monitor_status(self, message):
        self.monitor_panel.status_label.setText(message)

    def _on_monitor_rune(self, present, detection):
        self.monitor_panel.set_rune(present, detection)
        if self.remote_monitor_client:
            confidence = detection.confidence if detection is not None else None
            self.remote_monitor_client.publish_rune(present, confidence)

    def _on_monitor_verification(self, present, detection):
        self.monitor_panel.set_verification(present, detection)
        if present != self._monitor_verification_present:
            self.logger.log(
                "检测到鼠标跟随验证，请立即人工处理"
                if present
                else "鼠标跟随验证已解除"
            )
            self.update_log_display()
        self._monitor_verification_present = present
        if self.remote_monitor_client:
            confidence = detection.confidence if detection is not None else None
            self.remote_monitor_client.publish_verification(present, confidence)

    def _on_monitor_recording_update(self, message):
        self.logger.log(message)
        self.update_log_display()

    def _on_monitor_exp(self, reading, status):
        self.monitor_panel.set_exp(reading, status)
        if self.remote_monitor_client:
            self.remote_monitor_client.publish_exp(reading, status)

    def _on_monitor_error(self, message):
        self.logger.log(f"监控错误：{message}")
        self.update_log_display()
        self.monitor_panel.status_label.setText(message)

    def _on_monitor_stopped(self, worker):
        if self.monitor_worker is not worker:
            return
        self.monitor_worker = None
        self.is_worker_running = False
        self.monitor_tab.setEnabled(True)
        self.dead_flower_tab.setEnabled(True)
        self.live_flower_tab.setEnabled(True)
        self.follow_heal_tab.setEnabled(True)
        self.temple_tab.setEnabled(True)
        self.monitor_panel.manage_maps_button.setEnabled(True)
        self.monitor_panel.action_test_button.setEnabled(True)
        self.monitor_panel.route_test_button.setEnabled(True)
        self.monitor_panel.set_verification(False)
        self._monitor_verification_present = False
        if self.remote_monitor_client:
            self.remote_monitor_client.publish_verification(False)
            self.remote_monitor_client.publish_client_state("monitor", False)
        self._sync_party_invite_worker()
        self._refresh_primary_action()

    def handle_remote_command(self, command):
        action = command.get("action") if isinstance(command, dict) else command
        if action == "start" and not self.is_worker_running:
            self.logger.log("收到网页远程开始指令")
            self.update_log_display()
            self.start_worker()
        elif action == "stop" and self.is_worker_running:
            self.logger.log("收到网页远程停止指令")
            self.update_log_display()
            self.stop_worker()
        elif action == "configure_rope_party":
            team_id = int(command.get("teamId") or 0)
            if team_id <= 0:
                self.logger.log("收到的挂绳组队配置缺少队伍编号")
                self.update_log_display()
                return
            if self.is_worker_running:
                self.stop_worker()
            self.mode = "temple"
            self.temple_function = "rope_party"
            self.rope_party_team_id = team_id
            self.rope_party_is_leader = bool(command.get("isLeader"))
            self.rope_party_first_creation = self.rope_party_is_leader
            self.rope_party_invite_role_names = list(command.get("inviteRoleNames") or [])
            self.character_name = str(command.get("roleName") or self.character_name).strip()
            self.character_name_input.setText(self.character_name)
            self.temple_function_combo.setCurrentIndex(max(0, self.temple_function_combo.findData("rope_party")))
            self.auto_accept_party_invite = True
            self.party_invite_checkbox.setChecked(True)
            self._update_mode_tab_style()
            self._update_movement_mode_visibility()
            self._persist_settings()
            self._sync_party_invite_worker(log_missing_requirements=True)
            self.logger.log("已切换为神殿模式 · 挂绳组队，并开启自动同意组队")
            self.update_log_display()
            self.start_worker()
        elif action == "disband_rope_party":
            team_id = int(command.get("teamId") or 0)
            if team_id <= 0:
                self.logger.log("收到的解散队伍指令缺少队伍编号")
                self.update_log_display()
                return
            self.logger.log("收到网页解散队伍指令，正在停止当前模式")
            if self.is_worker_running:
                self.stop_worker()
            self.auto_accept_party_invite = False
            self.party_invite_checkbox.setChecked(False)
            self.rope_party_team_id = 0
            self.rope_party_is_leader = False
            self.rope_party_invite_role_names = []
            self.pending_rope_party_disband_team_id = team_id
            self._persist_settings()
            self._start_rope_party_disband()
        elif action == "clear_rope_party":
            if self.is_worker_running:
                self.stop_worker()
            self.auto_accept_party_invite = False
            self.party_invite_checkbox.setChecked(False)
            self.rope_party_team_id = 0
            self.rope_party_is_leader = False
            self.rope_party_first_creation = False
            self.rope_party_invite_role_names = []
            self._persist_settings()
            self._sync_party_invite_worker()
            self.logger.log("网页队伍已解散或本角色已被移除，挂绳组队状态已清理")
            self.update_log_display()
        elif action in {"remove_rope_party_member", "remove_member"}:
            role_name = str(command.get("targetRoleName") or "").strip()
            if not role_name:
                self.logger.log("收到的移除成员指令缺少角色名称")
                self.update_log_display()
                return
            self.logger.log(f"收到网页移除成员指令：{role_name}")
            self.update_log_display()
            if (self.mode == "temple" and self.temple_function == "rope_party"
                    and isinstance(self.worker, RopePartyWorker) and self.worker.isRunning()):
                self.worker.enqueue_remove_member(role_name)
                self.logger.log(f"移除成员指令已加入发送队列：{role_name}")
                self.update_log_display()
                return
            if self.is_worker_running:
                self.stop_worker()
            self._start_rope_party_remove_member(role_name)
        elif action in {"start_boss_invite_cycle", "invite_boss"}:
            cycle_id = int(command.get("cycleId") or 0)
            role_name = str(command.get("targetRoleName") or "").strip()
            if isinstance(self.worker, RopePartyWorker) and self.worker.isRunning() and cycle_id > 0 and role_name:
                self.logger.log(f"收到老板邀请周期 {cycle_id}，已加入执行队列：{role_name}")
                self.update_log_display()
                self.worker.start_boss_invite_cycle(cycle_id, role_name)
        elif action in {"cast_boss_buffs", "cast_buffs"}:
            cycle_id = int(command.get("cycleId") or 0)
            if isinstance(self.worker, RopePartyWorker) and self.worker.isRunning() and cycle_id > 0:
                self.worker.cast_boss_buffs(cycle_id)
        elif action in {"disband_boss_party", "rebuild_party", "restart_party_and_buff"}:
            cycle_id = int(command.get("cycleId") or 0)
            if action == "restart_party_and_buff" and not (
                isinstance(self.worker, RopePartyWorker) and self.worker.isRunning()
            ):
                self.rope_party_first_creation = False
                self.start_worker()
                if not (isinstance(self.worker, RopePartyWorker) and self.worker.isRunning()):
                    self.logger.log("重新组队失败：挂绳组队未能启动，请检查游戏窗口和配置")
                    self.update_log_display()
                    return
            if isinstance(self.worker, RopePartyWorker) and self.worker.isRunning() and cycle_id > 0:
                self.worker.disband_boss_party(cycle_id)
        elif action == "prepare_for_rebuild":
            self.logger.log("队长正在重新组队，本机等待新的组队邀请")
            self.update_log_display()

    def _start_rope_party_disband(self):
        if not self.is_window_identified:
            self.auto_identify_on_startup()
        if not self.is_window_identified or not self.game_window_hwnd:
            self.logger.log("游戏窗口未识别，无法发送 /退出隊伍")
            self.update_log_display()
            return
        worker = RopePartyWorker(self.game_window_hwnd, False, False, [], disband_only=True)
        worker.log_update.connect(self.on_status_update)
        worker.error_signal.connect(self.on_error)
        worker.finished_signal.connect(lambda worker=worker: self.on_worker_finished(worker))
        worker.team_disbanded.connect(self._on_rope_party_team_disbanded)
        self.worker = worker
        self.is_worker_running = True
        worker.start()
        if self.remote_monitor_client:
            self.remote_monitor_client.publish_client_state(self.mode, True)
        self._refresh_primary_action()

    def _on_rope_party_team_disbanded(self):
        team_id = self.pending_rope_party_disband_team_id
        self.pending_rope_party_disband_team_id = 0
        if self.remote_monitor_client and team_id > 0:
            self.remote_monitor_client.publish_rope_party_progress(
                team_id,
                "team_disbanded",
            )
            self.logger.log("已向服务器上报游戏队伍解散成功")
            self.update_log_display()

    def _start_rope_party_remove_member(self, role_name):
        if not self.is_window_identified:
            self.auto_identify_on_startup()
        if not self.is_window_identified or not self.game_window_hwnd:
            self.logger.log(f"游戏窗口未识别，无法发送 /踢出隊伍 {role_name}")
            self.update_log_display()
            return
        worker = RopePartyWorker(self.game_window_hwnd, False, False, [], remove_role_name=role_name)
        worker.log_update.connect(self.on_status_update)
        worker.error_signal.connect(self.on_error)
        worker.finished_signal.connect(lambda worker=worker: self.on_worker_finished(worker))
        self.worker = worker
        self.is_worker_running = True
        worker.start()
        if self.remote_monitor_client:
            self.remote_monitor_client.publish_client_state(self.mode, True)
        self._refresh_primary_action()

    def _on_party_invite_accepted(self):
        if self.mode == "temple" and self.temple_function == "lounge" and isinstance(self.worker, LoungeWorker):
            self.worker.party_invite_accepted()
        elif self.mode == "temple" and self.temple_function == "rope_party" and self.rope_party_team_id > 0:
            role_name = self.character_name_input.text().strip()
            if self.remote_monitor_client and role_name:
                self.remote_monitor_client.publish_team_joined(self.rope_party_team_id, role_name)
                self.logger.log("已向服务器上报成功进队")
                self.update_log_display()

    def on_manage_maps(self):
        from ui.map_library_dialog import MapLibraryDialog

        frame = getattr(self.monitor_panel.canvas, "_frame", None)
        current_image = frame.get("image") if frame else None
        dialog = MapLibraryDialog(
            self.map_library_store,
            current_image=current_image,
            hwnd=self.game_window_hwnd,
            window_selector=self.window_selector,
            account_manager=self.account_manager,
            parent=self,
        )
        dialog.exec()
        self.map_topologies = self.map_library_store.load()
        if hasattr(self, "map_count_label"):
            self.map_count_label.setText(f"已创建 {len(self.map_topologies)} 张地图")
        if (
            self.monitor_matched_topology is not None
            and not any(
                item.id == self.monitor_matched_topology.id
                for item in self.map_topologies
            )
        ):
            self.monitor_matched_topology = None

    def on_map_action_test(self):
        if not self.game_window_hwnd:
            QMessageBox.information(self, "提示", "请先识别游戏窗口")
            return
        from ui.map_action_test_dialog import MapActionTestDialog

        MapActionTestDialog(
            jump_key=self.selected_jump_key,
            hwnd=self.game_window_hwnd,
            window_selector=self.window_selector,
            parent=self,
        ).exec()

    def on_map_route_test(self):
        if not self.game_window_hwnd:
            QMessageBox.information(self, "提示", "请先识别游戏窗口")
            return
        topology = self.monitor_matched_topology
        if topology is None:
            QMessageBox.information(
                self,
                "提示",
                "尚未匹配到当前地图，请先监控并确认地图标注。",
            )
            return
        from ui.map_route_dialog import MapRouteDialog

        MapRouteDialog(
            hwnd=self.game_window_hwnd,
            topology=topology,
            maps=self.map_topologies,
            jump_key=self.selected_jump_key,
            window_selector=self.window_selector,
            parent=self,
        ).exec()

    def on_mark_monitor_zone(self):
        frame = getattr(self.monitor_panel.canvas, "_frame", None)
        image = frame.get("image") if frame else None
        if image is None:
            QMessageBox.information(self, "提示", "请先开始监控并识别小地图")
            return
        from ui.portal_marker_dialog import PortalMarkerDialog

        current = None
        if self.monitor_safe_zone is not None:
            current = tuple(
                round(value)
                for value in self.monitor_safe_zone.center.to_pixel(
                    (image.shape[1], image.shape[0])
                )
            )
        dialog = PortalMarkerDialog(
            self,
            image,
            current_manual_pos=current,
            title="设置监控安全区基准点",
            hint_text="点击小地图选择安全区中心，长宽在监控面板中按百分比设置。",
            show_auto_portal=False,
            confirm_button_text="使用此基准点",
            clear_button_text="清除安全区",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        point = dialog.get_marked_position()
        if point is None:
            self.on_clear_monitor_zone()
            return
        self.monitor_safe_zone = MonitorSafeZone(
            NormalizedMapPoint.from_pixel(
                point,
                (image.shape[1], image.shape[0]),
            ),
            self.monitor_panel.zone_width.value() / 100,
            self.monitor_panel.zone_height.value() / 100,
        )
        self.monitor_zone_stabilizer.reset()
        self._schedule_save()

    def on_clear_monitor_zone(self):
        self.monitor_safe_zone = None
        self.monitor_zone_stabilizer.reset()
        if self.remote_monitor_client:
            self.remote_monitor_client.publish_zone(False, None)
        self._schedule_save()

    def _update_monitor_zone_size(self, *_):
        if self.monitor_safe_zone is None:
            return
        self.monitor_safe_zone = MonitorSafeZone(
            self.monitor_safe_zone.center,
            self.monitor_panel.zone_width.value() / 100,
            self.monitor_panel.zone_height.value() / 100,
        )
        self.monitor_zone_stabilizer.reset()
        self._schedule_save()

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
        monitor_worker = self.monitor_worker
        if monitor_worker is not None:
            monitor_worker.stop()
            monitor_worker.wait(2000)
            self.monitor_worker = None
        super().closeEvent(event)
