"""
主窗口UI界面
负责用户界面的显示和交互
按照参考设计重新实现
"""

from typing import List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox, QGroupBox, QCheckBox,
    QTextEdit, QGridLayout, QDialog, QRadioButton, QButtonGroup, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer

from ui.virtual_keyboard import VirtualKeyboardDialog
from ui.portal_marker_dialog import PortalMarkerDialog

from models.skill_config import SkillConfig
from models.buff_config import BuffConfig
from models.game_config import GameConfig
from workers.skill_worker import SkillWorker
from workers.market_worker import MarketWorker
from workers.dead_flower_worker import DeadFlowerWorker
from utils.logger import Logger
from utils.screen_utils import get_screen_resolution
from utils.settings_manager import SettingsManager
from utils import WindowSelector, WINDOW_SELECTOR_AVAILABLE
from config import (
    APP_NAME, APP_VERSION, WINDOW_WIDTH, WINDOW_HEIGHT, WINDOW_X, WINDOW_Y, INITIAL_WAIT_TIME
)


class MainWindow(QMainWindow):
    """主窗口类"""
    
    def __init__(self):
        """初始化主窗口"""
        super().__init__()
        self.skills: List[SkillConfig] = []
        self.buffs: List[BuffConfig] = [BuffConfig() for _ in range(6)]  # 6个buff
        self.game_config = GameConfig()
        self.worker: SkillWorker = None
        self.logger = Logger()
        self.window_selector = None
        self.game_window_hwnd = None  # 游戏窗口句柄
        self.is_window_identified = False  # 是否已识别窗口
        self.return_to_market = True  # 是否释放后回到市场
        self.movement_mode = "none"  # 移动模式: "none"(原地不动), "right"(向右走开buff), "left"(向左走开buff)
        self.pre_skill_move_mode = "right_left"  # 死花出市场后移动: "right_left" 或 "left_only"
        self.manual_portal_pos = None  # 手动标记的传送门位置 (x, y) 或 None
        
        # 初始化窗口选择器
        if WINDOW_SELECTOR_AVAILABLE:
            try:
                self.window_selector = WindowSelector()
            except ImportError:
                self.logger.log("警告: 未安装pywin32，无法使用窗口识别功能")
        
        
        # 设置管理器
        self.settings_manager = SettingsManager()
        
        self.init_ui()
        self.load_default_config()
        # 程序启动后自动查找一次窗口
        self.auto_identify_on_startup()
        
        
        
    
    def load_default_config(self):
        """加载配置（优先加载保存的设置，否则使用默认值）"""
        # 尝试加载保存的设置
        saved_settings = self.settings_manager.load_settings()
        
        if saved_settings:
            self._apply_saved_settings(saved_settings)
            self.logger.log("已加载保存的设置")
        else:
            self._apply_default_settings()
            self.logger.log("使用默认设置")
        
        # 获取当前屏幕分辨率（作为默认值）
        width, height = get_screen_resolution()
        if width > 0 and height > 0:
            self.game_config.set_resolution(width, height)
        
        # 初始化窗口状态显示
        self.update_window_status_display()
    
    def _apply_saved_settings(self, settings: dict):
        """应用保存的设置"""
        # 加载模式设置
        self.return_to_market = settings.get("return_to_market", False)
        self._update_mode_tab_style()
        
        # 加载跳跃键
        self.selected_jump_key = settings.get("jump_key", "Alt")
        if hasattr(self, 'jump_key_btn'):
            self.jump_key_btn.setText(self.selected_jump_key)
            
        # 加载空闲时坐椅子设置
        self.sit_chair_enabled = settings.get("sit_chair_enabled", False)
        self.selected_chair_key = settings.get("chair_key", "=")
        if hasattr(self, 'sit_chair_checkbox'):
            self.sit_chair_checkbox.setChecked(self.sit_chair_enabled)
        if hasattr(self, 'chair_key_btn'):
            self.chair_key_btn.setText(self.selected_chair_key)
        
        # 加载随机行为设置
        self.game_config.random_behavior_enabled = settings.get("random_behavior_enabled", True)
        self.game_config.random_behavior_value = settings.get("random_behavior_value", 20)
        self.random_behavior_checkbox.setChecked(self.game_config.random_behavior_enabled)
        self.random_behavior_input.setText(str(self.game_config.random_behavior_value))
        
        # 加载移动模式设置
        self.movement_mode = settings.get("movement_mode", "none")
        self._set_movement_mode_radio(self.movement_mode)
        
        # 加载死花出市场后移动模式
        self.pre_skill_move_mode = settings.get("pre_skill_move_mode", "right_left")
        self._set_pre_skill_move_mode_radio(self.pre_skill_move_mode)
        
        # 加载 buff 配置
        buff_configs = settings.get("buffs", [])
        for i, buff_cfg in enumerate(buff_configs):
            if i < len(self.buffs):
                self.buffs[i].enabled = buff_cfg.get("enabled", False)
                self.buffs[i].key = buff_cfg.get("key", "")
                self.buffs[i].duration = buff_cfg.get("duration", 0)
                
                self.buff_checkboxes[i].setChecked(self.buffs[i].enabled)
                self.buff_key_btns[i].setText(self.buffs[i].key if self.buffs[i].key else "选择按键")
                self.buff_duration_inputs[i].setText(str(int(self.buffs[i].duration)) if self.buffs[i].duration > 0 else "")
    
    def _apply_default_settings(self):
        """应用默认设置"""
        # buff1: 启用，按键"1"，200秒
        self.buffs[0].enabled = True
        self.buffs[0].key = "1"
        self.buffs[0].duration = 200.0
        self.buff_checkboxes[0].setChecked(True)
        self.buff_key_btns[0].setText("1")
        self.buff_duration_inputs[0].setText("200")
        
        # buff2: 启用，按键"2"，200秒
        self.buffs[1].enabled = True
        self.buffs[1].key = "2"
        self.buffs[1].duration = 200.0
        self.buff_checkboxes[1].setChecked(True)
        self.buff_key_btns[1].setText("2")
        self.buff_duration_inputs[1].setText("200")
        
        # 设置默认速度阈值
        self.speed_threshold_input.setText(str(self.game_config.speed_threshold))
        
        # 默认跳跃键
        if hasattr(self, 'selected_jump_key'):
            self.selected_jump_key = "Alt"
        if hasattr(self, 'jump_key_btn'):
            self.jump_key_btn.setText("Alt")
            
        # 默认空闲时坐椅子设置
        self.sit_chair_enabled = False
        self.selected_chair_key = "="
        if hasattr(self, 'sit_chair_checkbox'):
            self.sit_chair_checkbox.setChecked(False)
        if hasattr(self, 'chair_key_btn'):
            self.chair_key_btn.setText("=")
        
        # 默认开启随机行为，值为20
        self.game_config.random_behavior_enabled = True
        self.game_config.random_behavior_value = 20
        self.random_behavior_checkbox.setChecked(True)
        self.random_behavior_input.setText("20")
    
    def save_settings(self):
        """保存当前设置到文件"""
        try:
            random_value = int(self.random_behavior_input.text()) if self.random_behavior_input.text() else 20
        except ValueError:
            random_value = 20
        
        self.settings_manager.save_settings(
            buffs=self.buffs,
            return_to_market=self.return_to_market,
            jump_key=getattr(self, 'selected_jump_key', 'Alt'),
            sit_chair_enabled=getattr(self, 'sit_chair_enabled', False),
            chair_key=getattr(self, 'selected_chair_key', '='),
            random_behavior_enabled=self.random_behavior_checkbox.isChecked(),
            random_behavior_value=random_value,
            movement_mode=self.movement_mode,
            pre_skill_move_mode=self.pre_skill_move_mode
        )
        self.logger.log("设置已保存")
        self.update_log_display()
    
    def init_ui(self):
        """初始化UI界面 - 暗色主题现代设计"""
        self.setWindowTitle(APP_NAME)
        self.setGeometry(WINDOW_X, WINDOW_Y, 480, 640)
        self.setFixedWidth(480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)
        self._apply_dark_theme()
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)
        central_widget.setLayout(main_layout)
        self._create_header(main_layout)
        self._create_mode_tabs(main_layout)
        self.create_settings_section(main_layout)
        self.create_control_section(main_layout)
        self.create_log_section(main_layout)
    
    def _apply_dark_theme(self):
        """应用暗色主题"""
        self.setStyleSheet("""
            QMainWindow { background-color: #1a1a2e; }
            QWidget { color: #e0e0e0; font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; }
            QGroupBox { background-color: #16213e; border: 1px solid #2a2a4a; border-radius: 8px;
                margin-top: 14px; padding: 12px 8px 8px 8px; font-weight: bold; color: #e94560; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #e94560; }
            QPushButton { background-color: #0f3460; color: #e0e0e0; border: 1px solid #1a4a7a;
                border-radius: 6px; padding: 5px 12px; font-weight: bold; min-height: 22px; }
            QPushButton:hover { background-color: #1a4a7a; border-color: #2a6aaa; }
            QPushButton:pressed { background-color: #0a2540; }
            QPushButton:disabled { background-color: #1a1a2e; color: #444; border-color: #2a2a3a; }
            QLineEdit { background-color: #0d1b2a; color: #e0e0e0; border: 1px solid #2a2a4a;
                border-radius: 4px; padding: 3px 6px; selection-background-color: #0f3460; }
            QLineEdit:focus { border-color: #e94560; }
            QCheckBox { color: #c0c0d0; spacing: 6px; }
            QCheckBox::indicator { width: 15px; height: 15px; border-radius: 3px;
                border: 1px solid #3a3a5a; background-color: #0d1b2a; }
            QCheckBox::indicator:checked { background-color: #e94560; border-color: #e94560; }
            QRadioButton { color: #c0c0d0; spacing: 5px; }
            QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px;
                border: 1px solid #3a3a5a; background-color: #0d1b2a; }
            QRadioButton::indicator:checked { background-color: #e94560; border-color: #e94560; }
            QTextEdit { background-color: #0d1b2a; color: #b0b0c0; border: 1px solid #2a2a4a;
                border-radius: 6px; padding: 6px; font-family: "Consolas", monospace; font-size: 9pt; }
            QLabel { color: #c0c0d0; }
            QScrollBar:vertical { background-color: #0d1b2a; width: 8px; border-radius: 4px; }
            QScrollBar::handle:vertical { background-color: #2a2a4a; border-radius: 4px; min-height: 20px; }
            QScrollBar::handle:vertical:hover { background-color: #3a3a6a; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)
    
    def _create_header(self, parent_layout):
        """标题栏 + 窗口状态"""
        header = QFrame()
        header.setStyleSheet("QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #16213e, stop:1 #0f3460); border-radius: 8px; }")
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(14, 10, 14, 8)
        h_layout.setSpacing(4)
        title_row = QHBoxLayout()
        title = QLabel(f"🍁 {APP_NAME}")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        title_row.addWidget(title)
        title_row.addStretch()
        ver = QLabel(f"v{APP_VERSION}")
        ver.setStyleSheet("font-size: 11px; color: #7a7aaa;")
        title_row.addWidget(ver)
        author = QLabel("by 暗中观察")
        author.setStyleSheet("font-size: 10px; color: #5a5a7a;")
        title_row.addWidget(author)
        h_layout.addLayout(title_row)
        self.window_status_label = QLabel("● 未识别 — 点击「识别窗口」")
        self.window_status_label.setWordWrap(True)
        self.window_status_label.setStyleSheet("font-size: 11px; color: #ff6b6b;")
        h_layout.addWidget(self.window_status_label)
        parent_layout.addWidget(header)
    
    def _create_mode_tabs(self, parent_layout):
        """模式切换Tab"""
        tab_layout = QHBoxLayout()
        tab_layout.setSpacing(0)
        self.dead_flower_tab = QPushButton("🌺 死花模式")
        self.live_flower_tab = QPushButton("🌻 活花模式")
        self.dead_flower_tab.clicked.connect(lambda: self._switch_mode_tab(True))
        self.live_flower_tab.clicked.connect(lambda: self._switch_mode_tab(False))
        tab_layout.addWidget(self.dead_flower_tab)
        tab_layout.addWidget(self.live_flower_tab)
        parent_layout.addLayout(tab_layout)
        self._update_mode_tab_style()
    
    def _switch_mode_tab(self, return_to_market: bool):
        """切换死花/活花模式"""
        self.return_to_market = return_to_market
        self._update_mode_tab_style()
        self._update_movement_mode_visibility()
        self.logger.log(f"切换到: {'死花模式' if return_to_market else '活花模式'}")
        self.update_log_display()
    
    def _update_mode_tab_style(self):
        """更新Tab样式"""
        a = "QPushButton { background-color: #e94560; color: white; border: 1px solid #e94560; padding: 8px 16px; font-weight: bold; font-size: 12px; border-radius: %s; } QPushButton:hover { background-color: #ff5577; }"
        b = "QPushButton { background-color: #16213e; color: #666; border: 1px solid #2a2a4a; padding: 8px 16px; font-weight: bold; font-size: 12px; border-radius: %s; } QPushButton:hover { background-color: #1a2a4e; color: #999; }"
        if self.return_to_market:
            self.dead_flower_tab.setStyleSheet(a % "6px 0px 0px 6px")
            self.live_flower_tab.setStyleSheet(b % "0px 6px 6px 0px")
        else:
            self.dead_flower_tab.setStyleSheet(b % "6px 0px 0px 6px")
            self.live_flower_tab.setStyleSheet(a % "0px 6px 6px 0px")
    
    def create_settings_section(self, parent_layout):
        """设置区域"""
        KS = "QPushButton { background-color: #0d1b2a; border: 1px solid #e94560; border-radius: 4px; font-size: 11px; font-weight: bold; color: #e94560; padding: 2px 8px; } QPushButton:hover { background-color: #1a2a3e; }"
        buff_group = QGroupBox("⚔ 技能配置")
        bl = QGridLayout(); bl.setSpacing(4); bl.setContentsMargins(8,8,8,8)
        self.buff_checkboxes = []; self.buff_key_btns = []; self.buff_duration_inputs = []; self.buff_countdown_labels = []
        for i in range(6):
            cb = QCheckBox(f"buff{i+1}"); self.buff_checkboxes.append(cb); bl.addWidget(cb, i, 0)
            kb = QPushButton("选择按键"); kb.setMaximumHeight(24); kb.setFixedWidth(70); kb.setStyleSheet(KS)
            kb.clicked.connect(lambda c, idx=i: self.on_buff_key_btn_clicked(idx))
            self.buff_key_btns.append(kb); bl.addWidget(kb, i, 1)
            di = QLineEdit(); di.setMaximumHeight(24); di.setFixedWidth(50); di.setPlaceholderText("秒")
            di.setAlignment(Qt.AlignmentFlag.AlignCenter); self.buff_duration_inputs.append(di); bl.addWidget(di, i, 2)
            cl = QLabel("--:--"); cl.setFixedWidth(50)
            cl.setStyleSheet("font-size:10px;padding:2px;background-color:#0d1b2a;border-radius:3px;color:#555;")
            cl.setAlignment(Qt.AlignmentFlag.AlignCenter); self.buff_countdown_labels.append(cl); bl.addWidget(cl, i, 3)
            cb.toggled.connect(lambda c, idx=i: self.on_buff_toggled(idx, c))
            di.textChanged.connect(lambda t, idx=i: self.on_buff_duration_changed(idx, t))
        buff_group.setLayout(bl); parent_layout.addWidget(buff_group)
        og = QGroupBox("⚙ 高级设置"); ol = QVBoxLayout(); ol.setContentsMargins(8,8,8,8); ol.setSpacing(6)
        g = QGridLayout(); g.setSpacing(6)
        self.random_behavior_checkbox = QCheckBox("随机提前(秒)"); g.addWidget(self.random_behavior_checkbox, 0, 0)
        self.random_behavior_input = QLineEdit(); self.random_behavior_input.setFixedWidth(40); self.random_behavior_input.setMaximumHeight(24)
        self.random_behavior_input.setAlignment(Qt.AlignmentFlag.AlignCenter); g.addWidget(self.random_behavior_input, 0, 1)
        jl = QLabel("跳跃键:"); jl.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter); g.addWidget(jl, 0, 2)
        self.selected_jump_key = "Alt"; self.jump_key_btn = QPushButton("Alt")
        self.jump_key_btn.setFixedWidth(55); self.jump_key_btn.setMaximumHeight(24); self.jump_key_btn.setStyleSheet(KS)
        self.jump_key_btn.clicked.connect(self.on_select_jump_key); g.addWidget(self.jump_key_btn, 0, 3)
        self.sit_chair_checkbox = QCheckBox("空闲坐椅子"); self.sit_chair_enabled = False
        self.sit_chair_checkbox.toggled.connect(self.on_sit_chair_toggled); g.addWidget(self.sit_chair_checkbox, 1, 0)
        g.addWidget(QLabel(""), 1, 1)
        chl = QLabel("椅子键:"); chl.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter); g.addWidget(chl, 1, 2)
        self.selected_chair_key = "="; self.chair_key_btn = QPushButton("=")
        self.chair_key_btn.setFixedWidth(55); self.chair_key_btn.setMaximumHeight(24); self.chair_key_btn.setStyleSheet(KS)
        self.chair_key_btn.clicked.connect(self.on_select_chair_key); g.addWidget(self.chair_key_btn, 1, 3)
        ol.addLayout(g)
        self.movement_mode_widget = QWidget()
        mv = QHBoxLayout(self.movement_mode_widget); mv.setContentsMargins(0,2,0,0); mv.addWidget(QLabel("移动:"))
        self.movement_mode_group = QButtonGroup(self)
        self.movement_none_radio = QRadioButton("原地不动"); self.movement_none_radio.setChecked(True)
        self.movement_mode_group.addButton(self.movement_none_radio, 0); mv.addWidget(self.movement_none_radio)
        self.movement_right_radio = QRadioButton("右走(回左)")
        self.movement_mode_group.addButton(self.movement_right_radio, 1); mv.addWidget(self.movement_right_radio)
        self.movement_left_radio = QRadioButton("左走(回右)")
        self.movement_mode_group.addButton(self.movement_left_radio, 2); mv.addWidget(self.movement_left_radio)
        self.movement_mode_group.buttonClicked.connect(self.on_movement_mode_changed); mv.addStretch()
        ol.addWidget(self.movement_mode_widget)
        self.pre_skill_move_widget = QWidget()
        ps = QHBoxLayout(self.pre_skill_move_widget); ps.setContentsMargins(0,2,0,0); ps.addWidget(QLabel("出市场:"))
        self.pre_skill_move_group = QButtonGroup(self)
        self.pre_skill_right_left_radio = QRadioButton("先右再左"); self.pre_skill_right_left_radio.setChecked(True)
        self.pre_skill_move_group.addButton(self.pre_skill_right_left_radio, 0); ps.addWidget(self.pre_skill_right_left_radio)
        self.pre_skill_left_only_radio = QRadioButton("只向左(魚窩)")
        self.pre_skill_move_group.addButton(self.pre_skill_left_only_radio, 1); ps.addWidget(self.pre_skill_left_only_radio)
        self.pre_skill_move_group.buttonClicked.connect(self.on_pre_skill_move_mode_changed); ps.addStretch()
        ol.addWidget(self.pre_skill_move_widget)
        og.setLayout(ol); parent_layout.addWidget(og)
        self.speed_threshold_input = QLineEdit(); self.speed_threshold_input.setVisible(False)
        self.return_to_market_checkbox = QCheckBox(); self.return_to_market_checkbox.setVisible(False)
        self._update_movement_mode_visibility()
    
    def create_control_section(self, parent_layout):
        """控制按钮和调试区域"""
        bl = QHBoxLayout(); bl.setSpacing(6)
        self.identify_btn = QPushButton("🔍 识别窗口")
        self.identify_btn.clicked.connect(self.on_identify_window)
        if not WINDOW_SELECTOR_AVAILABLE: self.identify_btn.setEnabled(False)
        bl.addWidget(self.identify_btn)
        self.portal_marker_btn = QPushButton("📍 标记传送门")
        self.portal_marker_btn.setToolTip("手动标记市场传送门位置")
        self.portal_marker_btn.clicked.connect(self.on_mark_portal); bl.addWidget(self.portal_marker_btn)
        self.is_worker_running = False
        self.toggle_btn = QPushButton("▶ 开始")
        self.toggle_btn.setStyleSheet("QPushButton { background-color: #2ecc71; color: white; font-size: 13px; font-weight: bold; border: none; border-radius: 6px; padding: 6px 20px; } QPushButton:hover { background-color: #27ae60; } QPushButton:pressed { background-color: #1e8449; }")
        self.toggle_btn.clicked.connect(self.on_toggle_worker); bl.addWidget(self.toggle_btn)
        parent_layout.addLayout(bl)
        self.debug_toggle_btn = QPushButton("▶ 调试工具")
        self.debug_toggle_btn.setStyleSheet("QPushButton { background-color: transparent; color: #555; border: none; font-size: 10px; text-align: left; padding: 2px 4px; } QPushButton:hover { color: #888; }")
        self.debug_toggle_btn.clicked.connect(self._toggle_debug_section); parent_layout.addWidget(self.debug_toggle_btn)
        self.debug_widget = QWidget(); self.debug_widget.setVisible(False)
        dl = QHBoxLayout(self.debug_widget); dl.setContentsMargins(0,0,0,0); dl.setSpacing(4)
        ds = "QPushButton { font-size: 10px; padding: 4px 8px; border-radius: 4px; %s } QPushButton:hover { %s }"
        self.test_market_btn = QPushButton("测试离开市场")
        self.test_market_btn.setStyleSheet(ds % ("background-color:#1565C0;color:white;","background-color:#1976D2;"))
        self.test_market_btn.clicked.connect(self.start_test_market_nav); dl.addWidget(self.test_market_btn)
        self.test_return_market_btn = QPushButton("测试回到市场")
        self.test_return_market_btn.setStyleSheet(ds % ("background-color:#7B1FA2;color:white;","background-color:#8E24AA;"))
        self.test_return_market_btn.clicked.connect(self.start_test_return_to_market); dl.addWidget(self.test_return_market_btn)
        self.test_dialog_btn = QPushButton("测试关闭弹窗")
        self.test_dialog_btn.setStyleSheet(ds % ("background-color:#E64A19;color:white;","background-color:#F4511E;"))
        self.test_dialog_btn.clicked.connect(self.start_test_dismiss_dialog); dl.addWidget(self.test_dialog_btn)
        parent_layout.addWidget(self.debug_widget)
    
    def _toggle_debug_section(self):
        """切换调试区域"""
        v = not self.debug_widget.isVisible()
        self.debug_widget.setVisible(v)
        self.debug_toggle_btn.setText("▼ 调试工具" if v else "▶ 调试工具")
    
    def start_test_return_to_market(self):
        """测试回到市场功能（点击自由市场按钮）"""
        if not self.game_window_hwnd:
            QMessageBox.warning(self, "错误", "请先确保游戏窗口已被识别")
            return
        
        # 先检测当前位置
        from detection.market_button import MarketButtonDetector
        detector = MarketButtonDetector(hwnd=self.game_window_hwnd, confidence=0.3)
        has_logo = detector.is_market_logo_visible()
        has_btn = detector.find_market_button_in_game() is not None
        
        if has_logo and has_btn:
            QMessageBox.information(self, "提示", "当前已经在市场中，无需返回")
            return
        
        self.logger.log("开始测试回到市场...")
        self.update_log_display()
        
        # 禁用按钮
        self.test_return_market_btn.setEnabled(False)
        self.test_market_btn.setEnabled(False)
        
        import threading
        
        def run_test():
            try:
                from detection.market_button import MarketButtonDetector
                from detection.minimap_monitor import MinimapMonitor
                from automation.human_input import HumanInput
                import random
                import time
                
                # 初始化组件
                monitor = MinimapMonitor()
                monitor.set_window_handle(self.game_window_hwnd)
                detector = MarketButtonDetector(hwnd=self.game_window_hwnd, confidence=0.3)
                human = HumanInput()
                
                # 初始化小地图
                monitor.auto_detect_dark_region()
                
                self.logger.log("正在查找自由市场按钮...")
                btn_pos = detector.find_market_button()
                
                if not btn_pos:
                    self.logger.log("❌ 未找到自由市场按钮")
                    return
                
                self.logger.log(f"找到按钮位置: {btn_pos}")
                
                # 拟人化多次点击（2-3次）
                click_count = random.randint(2, 3)
                self.logger.log(f"拟人化点击 {click_count} 次...")
                
                for i in range(click_count):
                    human.click_at(btn_pos[0], btn_pos[1], offset_range=8)
                    if i < click_count - 1:
                        time.sleep(random.uniform(0.15, 0.40))
                
                self.logger.log("等待传送...")
                time.sleep(1.0)
                
                # 循环检测是否成功回到市场（最多3次）
                max_retries = 3
                success = False
                
                for retry in range(max_retries):
                    self.logger.log(f"检测是否在市场... (第{retry+1}/{max_retries}次)")
                    has_logo = detector.is_market_logo_visible()
                    has_btn = detector.find_market_button_in_game() is not None
                    
                    if has_logo and has_btn:
                        self.logger.log("✅ 成功回到市场！")
                        success = True
                        break
                    elif not has_logo and not has_btn:
                        # 都没有，可能在加载中
                        self.logger.log("检测到加载中，等待...")
                        time.sleep(1.5)
                    else:
                        # 部分检测到，可能还在过渡
                        self.logger.log(f"检测结果: Logo={has_logo}, 按钮={has_btn}")
                        time.sleep(1.0)
                
                if not success:
                    self.logger.log("⚠️ 检测超时，可能未成功回到市场")
                
                # 释放按键
                human.release_all()
                
            except Exception as e:
                import traceback
                self.logger.log(f"测试出错: {str(e)}")
                traceback.print_exc()
            finally:
                # 直接在主线程恢复按钮
                import time
                time.sleep(0.1)  # 确保线程完成
                
        def on_thread_finished():
            self.test_return_market_btn.setEnabled(True)
            self.test_market_btn.setEnabled(True)
            self.update_log_display()
        
        thread = threading.Thread(target=run_test, daemon=True)
        thread.start()
        
        # 使用定时器检查线程是否完成
        def check_thread():
            if not thread.is_alive():
                on_thread_finished()
            else:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, check_thread)
        
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, check_thread)

    def create_log_section(self, parent_layout):
        h = QHBoxLayout()
        ll = QLabel("📋 日志"); ll.setStyleSheet("font-size: 11px; font-weight: bold; color: #e94560;"); h.addWidget(ll); h.addStretch()
        cb = QPushButton("清空"); cb.setMaximumHeight(20); cb.setMaximumWidth(40)
        cb.setStyleSheet("QPushButton{background-color:transparent;color:#555;border:1px solid #333;border-radius:3px;font-size:10px;}QPushButton:hover{color:#999;border-color:#555;}")
        cb.clicked.connect(self.clear_logs); h.addWidget(cb)
        parent_layout.addLayout(h)
        self.log_display = QTextEdit(); self.log_display.setReadOnly(True); self.log_display.setMinimumHeight(80)
        parent_layout.addWidget(self.log_display, stretch=1)
    
    def on_buff_toggled(self, index: int, checked: bool):
        """Buff启用/禁用"""
        self.buffs[index].enabled = checked
        if checked:
            self.logger.log(f"启用buff{index+1}")
        else:
            self.logger.log(f"禁用buff{index+1}")
        self.update_log_display()
    
    def on_buff_key_btn_clicked(self, index: int):
        """Buff按键按钮点击，弹出虚拟键盘"""
        current_key = self.buffs[index].key or "Ctrl"
        dialog = VirtualKeyboardDialog(self, current_key)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_key = dialog.get_selected_key()
            self.buffs[index].key = selected_key
            self.buff_key_btns[index].setText(selected_key)
            self.logger.log(f"buff{index+1} 按键设置为: {selected_key}")
            self.update_log_display()
    
    def on_buff_duration_changed(self, index: int, text: str):
        """Buff持续时间改变"""
        try:
            duration = float(text) if text else 0.0
            self.buffs[index].duration = duration
        except ValueError:
            pass
    
    def on_movement_mode_changed(self, button):
        """移动模式选项切换"""
        if button == self.movement_none_radio:
            self.movement_mode = "none"
            mode_text = "原地不动(慎选)"
        elif button == self.movement_right_radio:
            self.movement_mode = "right"
            mode_text = "向右走再释放(回左)"
        elif button == self.movement_left_radio:
            self.movement_mode = "left"
            mode_text = "向左走再释放(回右)"
        else:
            return
        
        self.logger.log(f"移动模式: {mode_text}")
        self.update_log_display()
    
    def _set_movement_mode_radio(self, mode: str):
        """根据模式设置单选按钮状态"""
        if mode == "none":
            self.movement_none_radio.setChecked(True)
        elif mode == "right":
            self.movement_right_radio.setChecked(True)
        elif mode == "left":
            self.movement_left_radio.setChecked(True)
        else:
            self.movement_none_radio.setChecked(True)
    
    def on_pre_skill_move_mode_changed(self, button):
        """死花出市场后移动模式切换"""
        if button == self.pre_skill_right_left_radio:
            self.pre_skill_move_mode = "right_left"
            mode_text = "先右挪再左挪"
        elif button == self.pre_skill_left_only_radio:
            self.pre_skill_move_mode = "left_only"
            mode_text = "只向左挪一步(魚窩)"
        else:
            return
        
        self.logger.log(f"出市场移动模式: {mode_text}")
        self.update_log_display()
    
    def _set_pre_skill_move_mode_radio(self, mode: str):
        """根据模式设置死花出市场移动单选按钮状态"""
        if mode == "left_only":
            self.pre_skill_left_only_radio.setChecked(True)
        else:
            self.pre_skill_right_left_radio.setChecked(True)
    
    def auto_identify_on_startup(self):
        """程序启动时自动识别窗口"""
        if not self.window_selector:
            self.update_window_status_display("窗口识别功能不可用（未安装pywin32）")
            return
        
        try:
            # 自动检测游戏窗口
            game_window = self.window_selector.auto_detect_game_window()
            
            if game_window:
                self.game_window_hwnd = game_window['hwnd']
                window_title = game_window['title']
                window_size = game_window['size']
                
                # 设置分辨率
                self.game_config.set_resolution(window_size[0], window_size[1])
                
                
                self.is_window_identified = True
                self.logger.log(f"启动时自动识别成功: {window_title}")
                self.logger.log(f"窗口大小: {window_size[0]}x{window_size[1]}")
                self.logger.log(f"现在游戏分辨率为: {self.game_config.get_resolution_str()}")
                self.update_log_display()
                
                # 更新窗口状态显示
                status_text = f"状态: 已识别\n窗口标题: {window_title}\n分辨率: {window_size[0]}x{window_size[1]}"
                self.update_window_status_display(status_text, success=True)
            else:
                self.logger.log("启动时未找到游戏窗口")
                self.update_log_display()
                self.is_window_identified = False
                self.game_window_hwnd = None
                self.update_window_status_display("状态: 未识别\n提示: 请确保游戏已启动，然后点击'识别'按钮")
                
        except Exception as e:
            error_msg = f"启动时识别窗口出错: {str(e)}"
            self.logger.log(error_msg)
            self.update_log_display()
            self.is_window_identified = False
            self.game_window_hwnd = None
            self.update_window_status_display(f"状态: 识别失败\n错误: {str(e)}")
    
    def on_identify_window(self):
        """手动识别游戏窗口"""
        if not self.window_selector:
            QMessageBox.warning(self, "错误", "窗口识别功能不可用，请安装pywin32库：\npip install pywin32")
            return
        
        try:
            self.logger.log("正在识别游戏窗口...")
            self.update_log_display()
            
            # 自动检测游戏窗口
            game_window = self.window_selector.auto_detect_game_window()
            
            if game_window:
                self.game_window_hwnd = game_window['hwnd']
                window_title = game_window['title']
                window_size = game_window['size']
                
                # 设置分辨率
                self.game_config.set_resolution(window_size[0], window_size[1])
                
                
                self.is_window_identified = True
                self.logger.log(f"识别成功: {window_title}")
                self.logger.log(f"窗口大小: {window_size[0]}x{window_size[1]}")
                self.logger.log(f"现在游戏分辨率为: {self.game_config.get_resolution_str()}")
                self.update_log_display()
                
                # 更新窗口状态显示
                status_text = f"状态: 已识别\n窗口标题: {window_title}\n分辨率: {window_size[0]}x{window_size[1]}"
                self.update_window_status_display(status_text, success=True)
                
                QMessageBox.information(self, "识别成功", 
                    f"已识别游戏窗口：\n标题: {window_title}\n分辨率: {window_size[0]}x{window_size[1]}")
            else:
                self.logger.log("未找到游戏窗口，请确保游戏已启动")
                self.update_log_display()
                self.is_window_identified = False
                self.game_window_hwnd = None
                self.update_window_status_display("状态: 未识别\n提示: 请确保游戏已启动")
                QMessageBox.warning(self, "识别失败", 
                    "未找到游戏窗口，请确保：\n1. 游戏已启动\n2. 游戏窗口可见\n3. 游戏窗口标题包含'冒险岛'、'Maple'等关键词")
                
        except Exception as e:
            error_msg = f"识别窗口时出错: {str(e)}"
            self.logger.log(error_msg)
            self.update_log_display()
            self.is_window_identified = False
            self.game_window_hwnd = None
            self.update_window_status_display(f"状态: 识别失败\n错误: {str(e)}")
            QMessageBox.warning(self, "错误", error_msg)
    
    def on_mark_portal(self):
        """手动标记市场传送门位置"""
        if not self.game_window_hwnd:
            QMessageBox.warning(self, "提示", "请先识别游戏窗口")
            return
        
        try:
            from detection.minimap_monitor import MinimapMonitor
            
            monitor = MinimapMonitor()
            monitor.set_window_handle(self.game_window_hwnd)
            
            # 初始化小地图区域
            result = monitor.auto_detect_dark_region()
            if result is None:
                QMessageBox.warning(self, "错误", "无法检测到小地图区域，请确保游戏窗口可见")
                return
            
            # 检查是否在市场内
            from detection.market_button import MarketButtonDetector
            market_det = MarketButtonDetector(hwnd=self.game_window_hwnd, confidence=0.3)
            if not market_det.is_market_logo_visible():
                QMessageBox.warning(self, "提示", "请在市场内使用此功能")
                return
            
            # 截取小地图
            minimap = monitor.capture_minimap()
            if minimap is None:
                QMessageBox.warning(self, "错误", "截取小地图失败")
                return
            
            # 尝试自动检测传送门
            auto_pos = monitor.find_blue_portal(find_leftmost=True)
            
            # 打开标记对话框
            dialog = PortalMarkerDialog(
                self, minimap,
                auto_portal_pos=auto_pos,
                current_manual_pos=self.manual_portal_pos
            )
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.manual_portal_pos = dialog.get_marked_position()
                if self.manual_portal_pos:
                    self.logger.log(f"已手动标记传送门位置: {self.manual_portal_pos}")
                else:
                    self.logger.log("已清除手动标记，恢复自动检测传送门")
                self.update_log_display()
                
        except Exception as e:
            import traceback
            self.logger.log(f"标记传送门出错: {str(e)}")
            traceback.print_exc()
            self.update_log_display()
    
    def update_window_status_display(self, status_text: str = None, success: bool = False):
        """更新窗口状态显示"""
        if status_text is None:
            if self.is_window_identified and self.game_window_hwnd:
                # 获取当前窗口信息
                if self.window_selector:
                    window_info = self.window_selector.get_window_info(self.game_window_hwnd)
                    if window_info:
                        status_text = f"状态: 已识别\n窗口标题: {window_info['title']}\n分辨率: {window_info['size'][0]}x{window_info['size'][1]}"
                        success = True
                    else:
                        status_text = "状态: 窗口已关闭"
                        success = False
                else:
                    status_text = "状态: 已识别（窗口选择器不可用）"
                    success = True
            else:
                status_text = "状态: 未识别\n提示: 点击'识别'按钮识别游戏窗口"
                success = False
        
        self.window_status_label.setText(status_text)
        
        # 根据状态设置背景色
        if success:
            self.window_status_label.setStyleSheet(
                "padding: 3px; background-color: #d4edda; border-radius: 3px; color: #155724; font-size: 11px;"
            )
        else:
            self.window_status_label.setStyleSheet(
                "padding: 3px; background-color: #f8d7da; border-radius: 3px; color: #721c24; font-size: 11px;"
            )
    
    def clear_logs(self):
        """清空日志"""
        self.logger.clear()
        self.update_log_display()
    
    def update_log_display(self):
        """更新日志显示"""
        logs_text = self.logger.get_logs_text()
        self.log_display.setPlainText(logs_text)
        # 自动滚动到底部
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def on_toggle_worker(self):
        """切换开始/停止"""
        if self.is_worker_running:
            self.stop_worker()
        else:
            self.start_worker()
    
    def start_worker(self):
        """启动技能释放"""
        # 如果之前没有识别到窗口，再次尝试自动识别
        if not self.is_window_identified:
            self.logger.log("未识别窗口，尝试自动识别...")
            self.update_log_display()
            self.auto_identify_on_startup()
        
        # 再次检查是否识别成功
        if not self.is_window_identified:
            QMessageBox.warning(self, "警告", "未找到游戏窗口，请确保游戏已启动！")
            return
        
        # 检查窗口是否仍然有效
        if self.window_selector and self.game_window_hwnd:
            if not self.window_selector.is_window_valid(self.game_window_hwnd):
                self.logger.log("窗口已关闭，尝试重新识别...")
                self.update_log_display()
                self.is_window_identified = False
                self.game_window_hwnd = None
                self.auto_identify_on_startup()
                
                if not self.is_window_identified:
                    QMessageBox.warning(self, "警告", "游戏窗口已关闭，请重新启动游戏！")
                    return
        
        # 收集启用的buff
        enabled_buffs = [buff for buff in self.buffs if buff.enabled and buff.key]
        if not enabled_buffs:
            QMessageBox.warning(self, "警告", "请至少启用一个buff并设置按键！")
            return
        
        # 停止之前的worker（如果存在）
        if self.worker:
            self.worker.stop()
        
        # 根据是否需要回到市场启动不同的worker
        if self.return_to_market:
            # 需要回到市场模式（原死花模式逻辑）
            self.logger.log("启动回市场模式...")
            self.update_log_display()
            
            self.worker = DeadFlowerWorker(
                self.game_window_hwnd, 
                self.buffs, 
                getattr(self, 'selected_jump_key', 'Alt'),
                getattr(self, 'sit_chair_enabled', False),
                getattr(self, 'selected_chair_key', '='),
                getattr(self, 'pre_skill_move_mode', 'right_left'),
                manual_portal_pos=self.manual_portal_pos
            )
            self.worker.log_update.connect(self.on_status_update)
            self.worker.finished_signal.connect(self.on_worker_finished)
            self.worker.error_signal.connect(self.on_error)
            self.worker.countdown_update.connect(self.on_countdown_update)
            
            self.worker.start()
            self.logger.log("回市场模式已启动")
        else:
            # 活花模式（原有逻辑）
            # 将buff转换为技能配置
            skills = []
            for buff in enabled_buffs:
                skill = SkillConfig(
                    key=buff.key,
                    interval=buff.duration if buff.duration > 0 else 5.0,
                    random_delay=2.0
                )
                skills.append(skill)
            
            if not skills:
                QMessageBox.warning(self, "警告", "没有可用的技能！")
                return
            
            # 将游戏窗口置于前台
            if self.window_selector and self.game_window_hwnd:
                try:
                    import time
                    success = self.window_selector.bring_window_to_front(self.game_window_hwnd)
                    if success:
                        self.logger.log(f"成功将游戏窗口置于前台")
                        time.sleep(0.3)
                    else:
                        self.logger.log("警告: 设置游戏窗口焦点失败，请手动点击游戏窗口")
                except Exception as e:
                    self.logger.log(f"将窗口置于前台失败: {str(e)}")
            
            # 获取攻击键配置
            attack_key = "ctrl"
            
            # 创建新的worker，传入移动模式
            self.worker = SkillWorker(
                skills, 
                self.window_selector, 
                self.game_window_hwnd, 
                attack_key, 
                self.movement_mode,
                getattr(self, 'sit_chair_enabled', False),
                getattr(self, 'selected_chair_key', '=')
            )
            self.worker.status_update.connect(self.on_status_update)
            self.worker.skill_pressed.connect(self.on_skill_pressed)
            self.worker.error_occurred.connect(self.on_error)
            self.worker.countdown_update.connect(self.on_countdown_update)
            
            # 保存当前启用的buff信息，用于显示倒计时
            self.active_buff_keys = [buff.key for buff in enabled_buffs]
            
            # 启动worker
            self.worker.start()
            self.logger.log("原地挂机模式已启动")
        
        self.update_log_display()
        
        # 更新按钮状态
        self.is_worker_running = True
        self.toggle_btn.setText("停止")
        self.toggle_btn.setStyleSheet("background-color: #f44336; color: white;")
        
        # 禁用buff设置区域和模式切换
        self._set_buff_settings_enabled(False)
        self.dead_flower_tab.setEnabled(False)
        self.live_flower_tab.setEnabled(False)
        self._update_movement_mode_visibility()
        
        # 显示buff倒计时区域
        self._show_buff_countdown(True)
    
    def on_worker_finished(self):
        """Worker完成回调（用于死花模式）"""
        self.logger.log("Worker已停止")
        self.update_log_display()
        self.stop_worker()
    
    def start_test_market_nav(self):
        """开始市场移动测试"""
        if not self.game_window_hwnd:
             QMessageBox.warning(self, "错误", "请先确保游戏窗口已被识别")
             return
        
        # 先检测当前位置
        from detection.market_button import MarketButtonDetector
        detector = MarketButtonDetector(hwnd=self.game_window_hwnd, confidence=0.3)
        has_logo = detector.is_market_logo_visible()
        has_btn = detector.find_market_button_in_game() is not None
        
        if not (has_logo and has_btn):
            QMessageBox.information(self, "提示", "当前不在市场中，无法离开市场")
            return
             
        self.logger.log("正在初始化市场导航模块...")
        self.update_log_display()
        
        # 禁用按钮
        self.test_market_btn.setEnabled(False)
        self.test_return_market_btn.setEnabled(False)
        self.toggle_btn.setEnabled(False)
        
        # 创建并启动worker
        self.market_worker = MarketWorker(self.game_window_hwnd)
        self.market_worker.log_update.connect(self.on_status_update)
        self.market_worker.finished_signal.connect(self.on_test_market_finished)
        self.market_worker.error_signal.connect(self.on_error)
        self.market_worker.start()

    def start_test_dismiss_dialog(self):
        """测试检测并关闭游戏内弹窗"""
        if not self.game_window_hwnd:
            QMessageBox.warning(self, "错误", "请先确保游戏窗口已被识别")
            return
        
        self.test_dialog_btn.setEnabled(False)
        self.logger.log("正在检测游戏内弹窗...")
        self.update_log_display()
        
        import threading
        
        def run_test():
            try:
                from detection.dialog_detector import DialogDetector
                from automation.human_input import HumanInput
                
                detector = DialogDetector(hwnd=self.game_window_hwnd, confidence=0.5)
                pos = detector.find_confirm_button()
                
                if pos:
                    self.logger.log(f"✅ 检测到确定按钮，位置: {pos}，正在点击...")
                    human = HumanInput()
                    human.click_at(pos[0], pos[1], offset_range=5)
                    import time
                    time.sleep(0.3)
                    human.release_all()
                    self.logger.log("已点击确定按钮")
                else:
                    self.logger.log("❌ 未检测到弹窗中的确定按钮")
                    
            except Exception as e:
                import traceback
                self.logger.log(f"测试出错: {str(e)}")
                traceback.print_exc()
        
        def on_finished():
            self.test_dialog_btn.setEnabled(True)
            self.update_log_display()
        
        thread = threading.Thread(target=run_test, daemon=True)
        thread.start()
        
        from PyQt6.QtCore import QTimer
        def check_thread():
            if not thread.is_alive():
                on_finished()
            else:
                QTimer.singleShot(100, check_thread)
        QTimer.singleShot(100, check_thread)

    def on_test_market_finished(self):
        """市场测试完成回调"""
        self.logger.log("市场导航测试结束")
        self.update_log_display()
        
        # 恢复按钮
        self.test_market_btn.setEnabled(True)
        self.test_return_market_btn.setEnabled(True)
        self.toggle_btn.setEnabled(True)
        self.market_worker = None

    def stop_worker(self):
        """停止技能释放"""
        if self.worker:
            self.worker.stop()
            self.worker = None
        
        self.logger.log("已停止运行")
        self.update_log_display()
        
        # 更新按钮状态
        self.is_worker_running = False
        self.toggle_btn.setText("开始")
        self.toggle_btn.setStyleSheet("QPushButton{background-color:#2ecc71;color:white;font-size:13px;font-weight:bold;border:none;border-radius:6px;padding:6px 20px;}QPushButton:hover{background-color:#27ae60;}")
        
        # 启用buff设置区域和模式切换
        self._set_buff_settings_enabled(True)
        self.dead_flower_tab.setEnabled(True)
        self.live_flower_tab.setEnabled(True)
        self._update_movement_mode_visibility()
        
        # 隐藏buff倒计时区域
        self._show_buff_countdown(False)
    
    def _show_buff_countdown(self, show: bool):
        """显示/隐藏buff倒计时"""
        if show:
            # 初始化倒计时显示
            for i, label in enumerate(self.buff_countdown_labels):
                if i < len(self.buffs) and self.buffs[i].enabled:
                    label.setText("--:--")
                else:
                    label.setText("--:--")
    
    def on_countdown_update(self, countdown_info: dict):
        """倒计时更新回调"""
        for i, buff in enumerate(self.buffs):
            if i < len(self.buff_countdown_labels):
                if buff.enabled and buff.key in countdown_info:
                    remaining = countdown_info[buff.key]
                    mins = remaining // 60
                    secs = remaining % 60
                    self.buff_countdown_labels[i].setText(f"{mins:02d}:{secs:02d}")
                    
                    # 根据剩余时间设置颜色
                    if remaining <= 10:
                        self.buff_countdown_labels[i].setStyleSheet("""
                            font-size: 10px; padding: 2px;
                            background-color: #ffcdd2; border-radius: 2px;
                            color: #c62828; font-weight: bold;
                        """)
                    elif remaining <= 30:
                        self.buff_countdown_labels[i].setStyleSheet("""
                            font-size: 10px; padding: 2px;
                            background-color: #ffe0b2; border-radius: 2px;
                            color: #e65100;
                        """)
                    else:
                        self.buff_countdown_labels[i].setStyleSheet("""
                            font-size: 10px; padding: 2px;
                            background-color: #c8e6c9; border-radius: 2px;
                            color: #2e7d32;
                        """)
    
    def _set_buff_settings_enabled(self, enabled: bool):
        """设置buff设置区域的启用/禁用状态"""
        # 禁用/启用buff配置控件
        for checkbox in self.buff_checkboxes:
            checkbox.setEnabled(enabled)
        for key_btn in self.buff_key_btns:
            key_btn.setEnabled(enabled)
        for duration_input in self.buff_duration_inputs:
            duration_input.setEnabled(enabled)
        
        # 禁用/启用其他设置
        self.random_behavior_checkbox.setEnabled(enabled)
        self.random_behavior_input.setEnabled(enabled)

    
    def _update_movement_mode_visibility(self):
        """根据模式切换显示/隐藏移动选项"""
        if self.return_to_market:
            self.movement_mode_widget.setVisible(False)
            self.pre_skill_move_widget.setVisible(True)
        else:
            self.movement_mode_widget.setVisible(True)
            self.pre_skill_move_widget.setVisible(False)
    
    def update_window_status_display(self, status_text: str = None, success: bool = False):
        """更新窗口状态显示"""
        if status_text is None:
            if self.is_window_identified and self.game_window_hwnd:
                if self.window_selector:
                    wi = self.window_selector.get_window_info(self.game_window_hwnd)
                    if wi:
                        status_text = f"● {wi['title']} | {wi['size'][0]}x{wi['size'][1]}"
                        success = True
                    else:
                        status_text = "● 窗口已关闭"; success = False
                else:
                    status_text = "● 已识别"; success = True
            else:
                status_text = "● 未识别 — 点击「识别窗口」"; success = False
        self.window_status_label.setText(status_text)
        self.window_status_label.setStyleSheet(f"font-size: 11px; color: {'#2ecc71' if success else '#ff6b6b'};")
    
    def clear_logs(self):
        """清空日志"""
        self.logger.clear()
        self.update_log_display()
    
    def update_log_display(self):
        """更新日志显示"""
        logs_text = self.logger.get_logs_text()
        self.log_display.setPlainText(logs_text)
        # 自动滚动到底部
        scrollbar = self.log_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def on_toggle_worker(self):
        """切换开始/停止"""
        if self.is_worker_running:
            self.stop_worker()
        else:
            self.start_worker()
    
    def start_worker(self):
        """启动技能释放"""
        # 如果之前没有识别到窗口，再次尝试自动识别
        if not self.is_window_identified:
            self.logger.log("未识别窗口，尝试自动识别...")
            self.update_log_display()
            self.auto_identify_on_startup()
        
        # 再次检查是否识别成功
        if not self.is_window_identified:
            QMessageBox.warning(self, "警告", "未找到游戏窗口，请确保游戏已启动！")
            return
        
        # 检查窗口是否仍然有效
        if self.window_selector and self.game_window_hwnd:
            if not self.window_selector.is_window_valid(self.game_window_hwnd):
                self.logger.log("窗口已关闭，尝试重新识别...")
                self.update_log_display()
                self.is_window_identified = False
                self.game_window_hwnd = None
                self.auto_identify_on_startup()
                
                if not self.is_window_identified:
                    QMessageBox.warning(self, "警告", "游戏窗口已关闭，请重新启动游戏！")
                    return
        
        # 收集启用的buff
        enabled_buffs = [buff for buff in self.buffs if buff.enabled and buff.key]
        if not enabled_buffs:
            QMessageBox.warning(self, "警告", "请至少启用一个buff并设置按键！")
            return
        
        # 停止之前的worker（如果存在）
        if self.worker:
            self.worker.stop()
        
        # 根据是否需要回到市场启动不同的worker
        if self.return_to_market:
            # 需要回到市场模式（原死花模式逻辑）
            self.logger.log("启动回市场模式...")
            self.update_log_display()
            
            self.worker = DeadFlowerWorker(
                self.game_window_hwnd, 
                self.buffs, 
                getattr(self, 'selected_jump_key', 'Alt'),
                getattr(self, 'sit_chair_enabled', False),
                getattr(self, 'selected_chair_key', '='),
                getattr(self, 'pre_skill_move_mode', 'right_left'),
                manual_portal_pos=self.manual_portal_pos
            )
            self.worker.log_update.connect(self.on_status_update)
            self.worker.finished_signal.connect(self.on_worker_finished)
            self.worker.error_signal.connect(self.on_error)
            self.worker.countdown_update.connect(self.on_countdown_update)
            
            self.worker.start()
            self.logger.log("回市场模式已启动")
        else:
            # 活花模式（原有逻辑）
            # 将buff转换为技能配置
            skills = []
            for buff in enabled_buffs:
                skill = SkillConfig(
                    key=buff.key,
                    interval=buff.duration if buff.duration > 0 else 5.0,
                    random_delay=2.0
                )
                skills.append(skill)
            
            if not skills:
                QMessageBox.warning(self, "警告", "没有可用的技能！")
                return
            
            # 将游戏窗口置于前台
            if self.window_selector and self.game_window_hwnd:
                try:
                    import time
                    success = self.window_selector.bring_window_to_front(self.game_window_hwnd)
                    if success:
                        self.logger.log(f"成功将游戏窗口置于前台")
                        time.sleep(0.3)
                    else:
                        self.logger.log("警告: 设置游戏窗口焦点失败，请手动点击游戏窗口")
                except Exception as e:
                    self.logger.log(f"将窗口置于前台失败: {str(e)}")
            
            # 获取攻击键配置
            attack_key = "ctrl"
            
            # 创建新的worker，传入移动模式
            self.worker = SkillWorker(
                skills, 
                self.window_selector, 
                self.game_window_hwnd, 
                attack_key, 
                self.movement_mode,
                getattr(self, 'sit_chair_enabled', False),
                getattr(self, 'selected_chair_key', '=')
            )
            self.worker.status_update.connect(self.on_status_update)
            self.worker.skill_pressed.connect(self.on_skill_pressed)
            self.worker.error_occurred.connect(self.on_error)
            self.worker.countdown_update.connect(self.on_countdown_update)
            
            # 保存当前启用的buff信息，用于显示倒计时
            self.active_buff_keys = [buff.key for buff in enabled_buffs]
            
            # 启动worker
            self.worker.start()
            self.logger.log("原地挂机模式已启动")
        
        self.update_log_display()
        
        # 更新按钮状态
        self.is_worker_running = True
        self.toggle_btn.setText("停止")
        self.toggle_btn.setStyleSheet("background-color: #f44336; color: white;")
        
        # 禁用buff设置区域和模式切换
        self._set_buff_settings_enabled(False)
        self.return_to_market_checkbox.setEnabled(False)
        self._update_movement_mode_visibility()
        
        # 显示buff倒计时区域
        self._show_buff_countdown(True)
    
    def on_worker_finished(self):
        """Worker完成回调（用于死花模式）"""
        self.logger.log("Worker已停止")
        self.update_log_display()
        self.stop_worker()
    
    def start_test_market_nav(self):
        """开始市场移动测试"""
        if not self.game_window_hwnd:
             QMessageBox.warning(self, "错误", "请先确保游戏窗口已被识别")
             return
        
        # 先检测当前位置
        from detection.market_button import MarketButtonDetector
        detector = MarketButtonDetector(hwnd=self.game_window_hwnd, confidence=0.3)
        has_logo = detector.is_market_logo_visible()
        has_btn = detector.find_market_button_in_game() is not None
        
        if not (has_logo and has_btn):
            QMessageBox.information(self, "提示", "当前不在市场中，无法离开市场")
            return
             
        self.logger.log("正在初始化市场导航模块...")
        self.update_log_display()
        
        # 禁用按钮
        self.test_market_btn.setEnabled(False)
        self.test_return_market_btn.setEnabled(False)
        self.toggle_btn.setEnabled(False)
        
        # 创建并启动worker
        self.market_worker = MarketWorker(self.game_window_hwnd)
        self.market_worker.log_update.connect(self.on_status_update)
        self.market_worker.finished_signal.connect(self.on_test_market_finished)
        self.market_worker.error_signal.connect(self.on_error)
        self.market_worker.start()

    def start_test_dismiss_dialog(self):
        """测试检测并关闭游戏内弹窗"""
        if not self.game_window_hwnd:
            QMessageBox.warning(self, "错误", "请先确保游戏窗口已被识别")
            return
        
        self.test_dialog_btn.setEnabled(False)
        self.logger.log("正在检测游戏内弹窗...")
        self.update_log_display()
        
        import threading
        
        def run_test():
            try:
                from detection.dialog_detector import DialogDetector
                from automation.human_input import HumanInput
                
                detector = DialogDetector(hwnd=self.game_window_hwnd, confidence=0.5)
                pos = detector.find_confirm_button()
                
                if pos:
                    self.logger.log(f"✅ 检测到确定按钮，位置: {pos}，正在点击...")
                    human = HumanInput()
                    human.click_at(pos[0], pos[1], offset_range=5)
                    import time
                    time.sleep(0.3)
                    human.release_all()
                    self.logger.log("已点击确定按钮")
                else:
                    self.logger.log("❌ 未检测到弹窗中的确定按钮")
                    
            except Exception as e:
                import traceback
                self.logger.log(f"测试出错: {str(e)}")
                traceback.print_exc()
        
        def on_finished():
            self.test_dialog_btn.setEnabled(True)
            self.update_log_display()
        
        thread = threading.Thread(target=run_test, daemon=True)
        thread.start()
        
        from PyQt6.QtCore import QTimer
        def check_thread():
            if not thread.is_alive():
                on_finished()
            else:
                QTimer.singleShot(100, check_thread)
        QTimer.singleShot(100, check_thread)

    def on_test_market_finished(self):
        """市场测试完成回调"""
        self.logger.log("市场导航测试结束")
        self.update_log_display()
        
        # 恢复按钮
        self.test_market_btn.setEnabled(True)
        self.test_return_market_btn.setEnabled(True)
        self.toggle_btn.setEnabled(True)
        self.market_worker = None

    def stop_worker(self):
        """停止技能释放"""
        if self.worker:
            self.worker.stop()
            self.worker = None
        
        self.logger.log("已停止运行")
        self.update_log_display()
        
        # 更新按钮状态
        self.is_worker_running = False
        self.toggle_btn.setText("开始")
        self.toggle_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        
        # 启用buff设置区域和模式切换
        self._set_buff_settings_enabled(True)
        self.return_to_market_checkbox.setEnabled(True)
        self._update_movement_mode_visibility()
        
        # 隐藏buff倒计时区域
        self._show_buff_countdown(False)
    
    def _show_buff_countdown(self, show: bool):
        """显示/隐藏buff倒计时"""
        if show:
            # 初始化倒计时显示
            for i, label in enumerate(self.buff_countdown_labels):
                if i < len(self.buffs) and self.buffs[i].enabled:
                    label.setText("--:--")
                else:
                    label.setText("--:--")
    
    def on_countdown_update(self, countdown_info: dict):
        """倒计时更新回调"""
        for i, buff in enumerate(self.buffs):
            if i < len(self.buff_countdown_labels):
                if buff.enabled and buff.key in countdown_info:
                    remaining = countdown_info[buff.key]
                    mins = remaining // 60
                    secs = remaining % 60
                    self.buff_countdown_labels[i].setText(f"{mins:02d}:{secs:02d}")
                    
                    # 根据剩余时间设置颜色
                    if remaining <= 10:
                        self.buff_countdown_labels[i].setStyleSheet("""
                            font-size: 10px; padding: 2px;
                            background-color: #ffcdd2; border-radius: 2px;
                            color: #c62828; font-weight: bold;
                        """)
                    elif remaining <= 30:
                        self.buff_countdown_labels[i].setStyleSheet("""
                            font-size: 10px; padding: 2px;
                            background-color: #ffe0b2; border-radius: 2px;
                            color: #e65100;
                        """)
                    else:
                        self.buff_countdown_labels[i].setStyleSheet("""
                            font-size: 10px; padding: 2px;
                            background-color: #c8e6c9; border-radius: 2px;
                            color: #2e7d32;
                        """)
    
    def _set_buff_settings_enabled(self, enabled: bool):
        """设置buff设置区域的启用/禁用状态"""
        for checkbox in self.buff_checkboxes:
            checkbox.setEnabled(enabled)
        for key_btn in self.buff_key_btns:
            key_btn.setEnabled(enabled)
        for duration_input in self.buff_duration_inputs:
            duration_input.setEnabled(enabled)
        self.random_behavior_checkbox.setEnabled(enabled)
        self.random_behavior_input.setEnabled(enabled)
    
    def _update_movement_mode_visibility(self):
        """根据 return_to_market 状态显示/隐藏移动模式选项"""
        show_radios = not self.return_to_market
        self.movement_none_radio.setVisible(show_radios)
        self.movement_right_radio.setVisible(show_radios)
        self.movement_left_radio.setVisible(show_radios)
        # 勾选回市场时显示死花出市场移动选项
        self.pre_skill_right_left_radio.setVisible(not show_radios)
        self.pre_skill_left_only_radio.setVisible(not show_radios)
    

    def on_select_jump_key(self):
        """弹出虚拟键盘选择跳跃键"""
        dialog = VirtualKeyboardDialog(self, self.selected_jump_key)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_jump_key = dialog.get_selected_key()
            self.jump_key_btn.setText(self.selected_jump_key)
            self.logger.log(f"跳跃键已设置为: {self.selected_jump_key}")
            self.update_log_display()
            
    def on_sit_chair_toggled(self, checked: bool):
        """空闲时坐椅子开启/关闭"""
        self.sit_chair_enabled = checked
        status = "开启" if checked else "关闭"
        self.logger.log(f"空闲时坐椅子: {status}")
        self.update_log_display()
        
    def on_select_chair_key(self):
        """弹出虚拟键盘选择椅子快捷键"""
        dialog = VirtualKeyboardDialog(self, self.selected_chair_key)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_chair_key = dialog.get_selected_key()
            self.chair_key_btn.setText(self.selected_chair_key)
            self.logger.log(f"椅子快捷键已设置为: {self.selected_chair_key}")
            self.update_log_display()
    
    def on_status_update(self, message: str):
        """状态更新回调"""
        self.logger.log(message)
        self.update_log_display()
    
    def on_skill_pressed(self, key: str):
        """技能释放回调"""
        # 查找对应的buff编号
        buff_index = -1
        for i, buff in enumerate(self.buffs):
            if buff.enabled and buff.key == key:
                buff_index = i
                break
        
        if buff_index >= 0:
            self.logger.log(f"按下buff{buff_index+1}")
        else:
            self.logger.log(f"按下{key}")
        self.update_log_display()
    
    def on_error(self, error_msg: str):
        """错误回调"""
        self.logger.log(f"错误: {error_msg}")
        self.update_log_display()
        QMessageBox.warning(self, "错误", error_msg)
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        self.save_settings()
        if self.worker:
            if hasattr(self.worker, 'is_running'):
                self.worker.is_running = False
            if hasattr(self.worker, 'stop'):
                self.worker.stop()
        event.accept()
