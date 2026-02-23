"""
主窗口UI界面
负责用户界面的显示和交互
按照参考设计重新实现
"""

from typing import List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox, QGroupBox, QCheckBox,
    QTextEdit, QGridLayout, QDialog, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer

from ui.virtual_keyboard import VirtualKeyboardDialog

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
    APP_NAME, WINDOW_WIDTH, WINDOW_HEIGHT, WINDOW_X, WINDOW_Y, INITIAL_WAIT_TIME
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
        self.manual_countdown = False  # 是否需要手动打怪倒计时
        self.movement_mode = "none"  # 移动模式: "none"(原地不动), "right"(向右走开buff), "left"(向左走开buff)
        
        # 初始化窗口选择器
        if WINDOW_SELECTOR_AVAILABLE:
            try:
                self.window_selector = WindowSelector()
            except ImportError:
                self.logger.log("警告: 未安装pywin32，无法使用窗口识别功能")
        
        # 5分钟检测相关
        self.last_detect_key_time = None  # 上次按检测键的时间
        self.countdown_seconds = 270  # 4分30秒 = 270秒
        self.keyboard_hook = None  # 键盘钩子
        
        # 设置管理器
        self.settings_manager = SettingsManager()
        
        self.init_ui()
        self.load_default_config()
        # 程序启动后自动查找一次窗口
        self.auto_identify_on_startup()
        
        # 初始化倒计时定时器（根据 manual_countdown 设置决定是否启动）
        self.countdown_timer = QTimer()
        self.countdown_timer.timeout.connect(self.update_countdown_display)
        # 默认不启动，等待 load_default_config 后根据设置启动
        
        # 初始化键盘监听（根据 manual_countdown 设置决定是否启动）
        self.setup_keyboard_listener()
        
        # 根据默认设置初始化UI可见性
        self._update_manual_countdown_ui()
    
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
        self.manual_countdown = settings.get("manual_countdown", False)
        self.return_to_market_checkbox.setChecked(self.return_to_market)
        self.manual_countdown_checkbox.setChecked(self.manual_countdown)
        
        # 加载攻击键
        self.selected_attack_key = settings.get("attack_key", "Ctrl")
        self.attack_key_btn.setText(self.selected_attack_key)
        
        # 加载跳跃键
        self.selected_jump_key = settings.get("jump_key", "Alt")
        if hasattr(self, 'jump_key_btn'):
            self.jump_key_btn.setText(self.selected_jump_key)
        
        # 加载随机行为设置
        self.game_config.random_behavior_enabled = settings.get("random_behavior_enabled", True)
        self.game_config.random_behavior_value = settings.get("random_behavior_value", 20)
        self.random_behavior_checkbox.setChecked(self.game_config.random_behavior_enabled)
        self.random_behavior_input.setText(str(self.game_config.random_behavior_value))
        
        # 加载移动模式设置
        self.movement_mode = settings.get("movement_mode", "none")
        self._set_movement_mode_radio(self.movement_mode)
        
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
            manual_countdown=self.manual_countdown,
            attack_key=self.selected_attack_key,
            jump_key=getattr(self, 'selected_jump_key', 'Alt'),
            random_behavior_enabled=self.random_behavior_checkbox.isChecked(),
            random_behavior_value=random_value,
            movement_mode=self.movement_mode
        )
        self.logger.log("设置已保存")
        self.update_log_display()
    
    def init_ui(self):
        """初始化UI界面 - 瘦长垂直布局"""
        self.setWindowTitle(APP_NAME)
        self.setGeometry(WINDOW_X, WINDOW_Y, WINDOW_WIDTH, 550)
        self.setFixedWidth(WINDOW_WIDTH)  # 固定宽度，防止切换模式时窗口大小变化
        # 去掉最大化按钮
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(5, 5, 5, 5)
        central_widget.setLayout(main_layout)
        
        # 0. 版本信息（最顶部）
        version_label = QLabel("Author: 暗中观察  |  Version: 1.0.0")
        version_label.setStyleSheet("font-size: 10px; color: #666; padding: 2px;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(version_label)
        
        # 1. 窗口识别状态（顶部）
        self.create_status_section(main_layout)
        
        # 2. 设置区域
        self.create_settings_section(main_layout)
        
        # 3. 控制按钮
        self.create_control_section(main_layout)
        
        # 4. 日志区域（底部）
        self.create_log_section(main_layout)
    
    def create_status_section(self, parent_layout):
        """创建窗口识别状态区域（顶部）"""
        status_group = QGroupBox("窗口识别状态")
        status_layout = QVBoxLayout()
        status_layout.setContentsMargins(3, 3, 3, 3)
        status_layout.setSpacing(2)
        
        self.window_status_label = QLabel("状态: 未识别")
        self.window_status_label.setWordWrap(True)
        self.window_status_label.setStyleSheet("padding: 3px; background-color: #f0f0f0; border-radius: 3px; font-size: 10px;")
        status_layout.addWidget(self.window_status_label)
        
        # 5分钟检测倒计时显示（醒目）
        self.countdown_label = QLabel("手动打怪倒计时: --:--")
        self.countdown_label.setStyleSheet("""
            font-size: 14px; 
            font-weight: bold; 
            color: #ff6600; 
            padding: 5px; 
            background-color: #fff3e0; 
            border-radius: 3px;
            border: 1px solid #ff6600;
        """)
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.countdown_label)
        
        status_group.setLayout(status_layout)
        parent_layout.addWidget(status_group)
    
    def create_settings_section(self, parent_layout):
        """创建设置区域"""
        # 运行模式选项区域
        mode_layout = QHBoxLayout()
        mode_layout.setContentsMargins(5, 0, 5, 5)
        
        mode_label = QLabel("运行模式:")
        mode_label.setStyleSheet("font-weight: bold;")
        mode_layout.addWidget(mode_label)
        
        # 是否释放后回到市场
        self.return_to_market_checkbox = QCheckBox("释放后回到市场")
        self.return_to_market_checkbox.setChecked(True)
        self.return_to_market_checkbox.setToolTip("勾选后，释放技能后自动返回市场等待下次CD")
        self.return_to_market_checkbox.toggled.connect(self.on_return_to_market_changed)
        mode_layout.addWidget(self.return_to_market_checkbox)
        
        # 是否需要手动打怪倒计时
        self.manual_countdown_checkbox = QCheckBox("需要手动打怪倒计时")
        self.manual_countdown_checkbox.setChecked(False)
        self.manual_countdown_checkbox.setToolTip("勾选后，监听攻击键并显示5分钟手动打怪倒计时")
        self.manual_countdown_checkbox.toggled.connect(self.on_manual_countdown_changed)
        mode_layout.addWidget(self.manual_countdown_checkbox)
        
        mode_layout.addStretch()
        parent_layout.addLayout(mode_layout)
        
        # 移动模式选项区域（单选按钮组）
        movement_layout = QHBoxLayout()
        movement_layout.setContentsMargins(5, 0, 5, 5)
        
        movement_label = QLabel("移动模式:")
        movement_label.setStyleSheet("font-weight: bold;")
        movement_layout.addWidget(movement_label)
        
        # 创建单选按钮组
        self.movement_mode_group = QButtonGroup(self)
        
        self.movement_none_radio = QRadioButton("原地不动(慎选)")
        self.movement_none_radio.setToolTip("释放技能时不移动")
        self.movement_none_radio.setChecked(True)  # 默认选中
        self.movement_mode_group.addButton(self.movement_none_radio, 0)
        movement_layout.addWidget(self.movement_none_radio)
        
        self.movement_right_radio = QRadioButton("向右走再释放(回左)")
        self.movement_right_radio.setToolTip("向右移动后释放技能，然后向左回到边缘")
        self.movement_mode_group.addButton(self.movement_right_radio, 1)
        movement_layout.addWidget(self.movement_right_radio)
        
        self.movement_left_radio = QRadioButton("向左走再释放(回右)")
        self.movement_left_radio.setToolTip("向左移动后释放技能，然后向右回到边缘")
        self.movement_mode_group.addButton(self.movement_left_radio, 2)
        movement_layout.addWidget(self.movement_left_radio)
        
        # 连接信号
        self.movement_mode_group.buttonClicked.connect(self.on_movement_mode_changed)
        
        # 回到市场模式下的提示标签
        self.movement_auto_label = QLabel("自动移动（离开市场→释放技能→返回市场）")
        self.movement_auto_label.setStyleSheet("color: #666; font-style: italic;")
        movement_layout.addWidget(self.movement_auto_label)
        
        movement_layout.addStretch()
        parent_layout.addLayout(movement_layout)
        
        # 根据默认的 return_to_market 状态设置移动模式显示
        self._update_movement_mode_visibility()
        
        # Buff配置区域
        buff_group = QGroupBox("Buff/Skill配置")
        buff_layout = QGridLayout()
        buff_layout.setSpacing(3)
        buff_layout.setContentsMargins(5, 5, 5, 5)
        
        self.buff_checkboxes = []
        self.buff_key_btns = []  # 改为按钮
        self.buff_duration_inputs = []
        self.buff_countdown_labels = []  # 倒计时标签
        
        for i in range(6):
            checkbox = QCheckBox(f"buff{i+1}")
            self.buff_checkboxes.append(checkbox)
            buff_layout.addWidget(checkbox, i, 0)
            
            # 按键选择按钮（点击弹出虚拟键盘）
            key_btn = QPushButton("选择按键")
            key_btn.setMaximumHeight(22)
            key_btn.setFixedWidth(70)
            key_btn.setStyleSheet("""
                QPushButton {
                    background-color: #e3f2fd;
                    border: 1px solid #1976d2;
                    border-radius: 3px;
                    font-size: 11px;
                    font-weight: bold;
                    color: #1976d2;
                    padding: 2px 8px;
                    outline: none;
                }
                QPushButton:hover {
                    background-color: #bbdefb;
                }
                QPushButton:focus {
                    outline: none;
                    border: 1px solid #1976d2;
                }
            """)
            key_btn.clicked.connect(lambda checked, idx=i: self.on_buff_key_btn_clicked(idx))
            self.buff_key_btns.append(key_btn)
            buff_layout.addWidget(key_btn, i, 1)
            
            # 秒数输入框（固定宽度，能写4位数）
            duration_input = QLineEdit()
            duration_input.setMaximumHeight(22)
            duration_input.setFixedWidth(45)
            duration_input.setPlaceholderText("秒")
            self.buff_duration_inputs.append(duration_input)
            buff_layout.addWidget(duration_input, i, 2)
            
            # 倒计时显示标签
            countdown_label = QLabel("--:--")
            countdown_label.setFixedWidth(50)
            countdown_label.setStyleSheet("""
                font-size: 10px;
                padding: 2px;
                background-color: #e8e8e8;
                border-radius: 2px;
                color: #666;
            """)
            countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.buff_countdown_labels.append(countdown_label)
            buff_layout.addWidget(countdown_label, i, 3)
            
            checkbox.toggled.connect(lambda checked, idx=i: self.on_buff_toggled(idx, checked))
            duration_input.textChanged.connect(lambda text, idx=i: self.on_buff_duration_changed(idx, text))
        
        buff_group.setLayout(buff_layout)
        parent_layout.addWidget(buff_group)
        
        # 其他设置（一行布局）
        options_layout = QHBoxLayout()
        
        # 随机提前释放
        self.random_behavior_checkbox = QCheckBox("随机提前释放（秒）")
        self.random_behavior_input = QLineEdit()
        self.random_behavior_input.setMaximumWidth(40)
        self.random_behavior_input.setMaximumHeight(22)
        options_layout.addWidget(self.random_behavior_checkbox)
        options_layout.addWidget(self.random_behavior_input)
        
        # 跳跃按键
        jump_label = QLabel("  离开市场跳跃键:")
        options_layout.addWidget(jump_label)
        
        self.selected_jump_key = "Alt"
        self.jump_key_btn = QPushButton(self.selected_jump_key)
        self.jump_key_btn.setStyleSheet("""
            QPushButton {
                background-color: #e3f2fd;
                border: 1px solid #1976d2;
                border-radius: 3px;
                font-size: 11px;
                font-weight: bold;
                color: #1976d2;
                padding: 2px 8px;
                min-width: 50px;
                max-height: 22px;
                outline: none;
            }
            QPushButton:hover {
                background-color: #bbdefb;
            }
            QPushButton:focus {
                outline: none;
                border: 1px solid #1976d2;
            }
        """)
        self.jump_key_btn.clicked.connect(self.on_select_jump_key)
        options_layout.addWidget(self.jump_key_btn)
        
        options_layout.addStretch()
        
        parent_layout.addLayout(options_layout)
        
        # 设置攻击按键（点击按钮弹出虚拟键盘）- 可隐藏，死花模式不需要
        self.attack_key_widget = QWidget()
        detect_layout = QHBoxLayout(self.attack_key_widget)
        detect_layout.setContentsMargins(0, 0, 0, 0)
        detect_label = QLabel("监听攻击按键:")
        detect_layout.addWidget(detect_label)
        
        self.selected_attack_key = "Ctrl"  # 默认攻击键
        self.attack_key_btn = QPushButton(self.selected_attack_key)
        self.attack_key_btn.setStyleSheet("""
            QPushButton {
                background-color: #e3f2fd;
                border: 1px solid #1976d2;
                border-radius: 3px;
                font-size: 11px;
                font-weight: bold;
                color: #1976d2;
                padding: 2px 8px;
                min-width: 50px;
                max-height: 22px;
                outline: none;
            }
            QPushButton:hover {
                background-color: #bbdefb;
            }
            QPushButton:focus {
                outline: none;
                border: 1px solid #1976d2;
            }
        """)
        self.attack_key_btn.clicked.connect(self.on_select_attack_key)
        detect_layout.addWidget(self.attack_key_btn)
        detect_layout.addStretch()
        parent_layout.addWidget(self.attack_key_widget)
        
        # 隐藏的速度阈值输入（保留功能但不显示）
        self.speed_threshold_input = QLineEdit()
        self.speed_threshold_input.setVisible(False)
    
    def create_control_section(self, parent_layout):
        """创建控制按钮区域"""
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(5)
        
        self.identify_btn = QPushButton("识别窗口")
        self.identify_btn.clicked.connect(self.on_identify_window)
        if not WINDOW_SELECTOR_AVAILABLE:
            self.identify_btn.setEnabled(False)
        btn_layout.addWidget(self.identify_btn)
        
        self.start_btn = QPushButton("开始")
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        self.start_btn.clicked.connect(self.start_worker)
        btn_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setStyleSheet("background-color: #f44336; color: white;")
        self.stop_btn.clicked.connect(self.stop_worker)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)
        
        parent_layout.addLayout(btn_layout)

        # 测试按钮
        test_layout = QHBoxLayout()
        test_layout.setContentsMargins(5, 5, 5, 5)
        self.test_market_btn = QPushButton("测试离开市场")
        self.test_market_btn.setStyleSheet("background-color: #2196F3; color: white;")
        self.test_market_btn.clicked.connect(self.start_test_market_nav)
        test_layout.addWidget(self.test_market_btn)
        
        self.test_return_market_btn = QPushButton("测试回到市场")
        self.test_return_market_btn.setStyleSheet("background-color: #9C27B0; color: white;")
        self.test_return_market_btn.clicked.connect(self.start_test_return_to_market)
        test_layout.addWidget(self.test_return_market_btn)
        
        parent_layout.addLayout(test_layout)

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
        log_header = QHBoxLayout()
        log_label = QLabel("日志")
        log_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        log_header.addWidget(log_label)
        log_header.addStretch()
        
        clear_btn = QPushButton("清空")
        clear_btn.setMaximumHeight(20)
        clear_btn.setMaximumWidth(40)
        clear_btn.setStyleSheet("font-size: 10px; padding: 2px;")
        clear_btn.clicked.connect(self.clear_logs)
        log_header.addWidget(clear_btn)
        
        parent_layout.addLayout(log_header)
        
        # 日志显示区域（可伸缩，随窗口高度变化）
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        font = QApplication.font()
        font.setPointSize(9)
        self.log_display.setFont(font)
        self.log_display.setMinimumHeight(85)  # 最小高度约5条日志
        # 让日志区域可以伸展
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
    
    def on_return_to_market_changed(self, checked: bool):
        """释放后回到市场选项切换"""
        self.return_to_market = checked
        status = "开启" if checked else "关闭"
        self.logger.log(f"释放后回到市场: {status}")
        self.update_log_display()
        
        # 更新移动模式显示
        self._update_movement_mode_visibility()
    
    def on_manual_countdown_changed(self, checked: bool):
        """手动打怪倒计时选项切换"""
        self.manual_countdown = checked
        self._update_manual_countdown_ui()
        
        status = "开启" if checked else "关闭"
        self.logger.log(f"手动打怪倒计时: {status}")
        self.update_log_display()
    
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
    
    def _update_manual_countdown_ui(self):
        """更新手动打怪倒计时相关UI和功能"""
        enabled = self.manual_countdown
        
        # 显示/隐藏攻击键设置和倒计时显示
        self.attack_key_widget.setVisible(enabled)
        self.countdown_label.setVisible(enabled)
        
        # 启动/停止倒计时定时器
        if enabled:
            if not self.countdown_timer.isActive():
                self.countdown_timer.start(1000)
        else:
            self.countdown_timer.stop()
            # 重置倒计时状态
            self.last_detect_key_time = None
    
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
            
            self.worker = DeadFlowerWorker(self.game_window_hwnd, self.buffs, getattr(self, 'selected_jump_key', 'Alt'))
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
            attack_key = self.selected_attack_key.lower()
            
            # 创建新的worker，传入移动模式
            self.worker = SkillWorker(skills, self.window_selector, self.game_window_hwnd, attack_key, self.movement_mode)
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
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        
        # 禁用buff设置区域和模式切换
        self._set_buff_settings_enabled(False)
        self.return_to_market_checkbox.setEnabled(False)
        self.manual_countdown_checkbox.setEnabled(False)
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
        self.start_btn.setEnabled(False)
        
        # 创建并启动worker
        self.market_worker = MarketWorker(self.game_window_hwnd)
        self.market_worker.log_update.connect(self.on_status_update)
        self.market_worker.finished_signal.connect(self.on_test_market_finished)
        self.market_worker.error_signal.connect(self.on_error)
        self.market_worker.start()

    def on_test_market_finished(self):
        """市场测试完成回调"""
        self.logger.log("市场导航测试结束")
        self.update_log_display()
        
        # 恢复按钮
        self.test_market_btn.setEnabled(True)
        self.test_return_market_btn.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.market_worker = None

    def stop_worker(self):
        """停止技能释放"""
        if self.worker:
            self.worker.stop()
            self.worker = None
        
        self.logger.log("已停止运行")
        self.update_log_display()
        
        # 更新按钮状态
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        # 启用buff设置区域和模式切换
        self._set_buff_settings_enabled(True)
        self.return_to_market_checkbox.setEnabled(True)
        self.manual_countdown_checkbox.setEnabled(True)
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
        self.attack_key_btn.setEnabled(enabled)
    
    def _update_movement_mode_visibility(self):
        """根据 return_to_market 状态显示/隐藏移动模式选项"""
        show_radios = not self.return_to_market
        self.movement_none_radio.setVisible(show_radios)
        self.movement_right_radio.setVisible(show_radios)
        self.movement_left_radio.setVisible(show_radios)
        self.movement_auto_label.setVisible(not show_radios)
    
    def on_select_attack_key(self):
        """弹出虚拟键盘选择攻击键"""
        dialog = VirtualKeyboardDialog(self, self.selected_attack_key)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_attack_key = dialog.get_selected_key()
            self.attack_key_btn.setText(self.selected_attack_key)
            self.logger.log(f"攻击键已设置为: {self.selected_attack_key}")
            self.update_log_display()
            # 更新键盘钩子
            self.update_keyboard_hook()
            
    def on_select_jump_key(self):
        """弹出虚拟键盘选择跳跃键"""
        dialog = VirtualKeyboardDialog(self, self.selected_jump_key)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_jump_key = dialog.get_selected_key()
            self.jump_key_btn.setText(self.selected_jump_key)
            self.logger.log(f"跳跃键已设置为: {self.selected_jump_key}")
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
        # 保存设置
        self.save_settings()
        
        # 停止键盘监听
        self.stop_keyboard_listener()
        
        # 停止倒计时定时器
        if self.countdown_timer:
            self.countdown_timer.stop()
        
        # 停止worker（非阻塞）
        if self.worker:
            if hasattr(self.worker, 'is_running'):
                self.worker.is_running = False
            if hasattr(self.worker, 'stop'):
                self.worker.stop()
        
        event.accept()
    
    def setup_keyboard_listener(self):
        """设置键盘监听"""
        try:
            import keyboard
            # 监听检测键
            self.update_keyboard_hook()
        except ImportError:
            self.logger.log("警告: 未安装keyboard库，5分钟检测功能不可用")
            self.update_log_display()
    
    def update_keyboard_hook(self):
        """更新键盘钩子"""
        try:
            import keyboard
            import time
            
            # 移除旧的钩子
            if self.keyboard_hook:
                try:
                    keyboard.unhook(self.keyboard_hook)
                except:
                    pass
            
            # 获取攻击键
            detect_key = self.selected_attack_key.lower() if hasattr(self, 'selected_attack_key') else "ctrl"
            
            def on_key_release(e):
                # 检测按键松开时才开始计时
                if e.name.lower() == detect_key.lower() or \
                   (detect_key == "ctrl" and e.name in ["ctrl", "left ctrl", "right ctrl"]):
                    self.last_detect_key_time = time.time()
            
            self.keyboard_hook = keyboard.on_release(on_key_release)
        except Exception as e:
            pass
    
    def stop_keyboard_listener(self):
        """停止键盘监听"""
        try:
            import keyboard
            if self.keyboard_hook:
                keyboard.unhook(self.keyboard_hook)
                self.keyboard_hook = None
        except:
            pass
    
    def update_countdown_display(self):
        """更新倒计时显示"""
        import time
        
        # 如果还没有按过检测键
        if self.last_detect_key_time is None:
            self.countdown_label.setText("手动打怪倒计时: 等待按键...")
            self.countdown_label.setStyleSheet("""
                font-size: 14px; 
                color: #666; 
                padding: 5px; 
                background-color: #e0e0e0; 
                border-radius: 5px;
            """)
            return
        
        # 计算剩余时间
        elapsed = time.time() - self.last_detect_key_time
        remaining = self.countdown_seconds - elapsed
        
        if remaining <= 0:
            # 时间到了，显示警告
            self.countdown_label.setText("⚠️ 请立即手动打怪！⚠️")
            self.countdown_label.setStyleSheet("""
                font-size: 18px; 
                font-weight: bold; 
                color: white; 
                padding: 10px; 
                background-color: #f44336; 
                border-radius: 5px;
                border: 3px solid #d32f2f;
            """)
        elif remaining <= 60:
            # 剩余不到1分钟，显示警告色
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            self.countdown_label.setText(f"手动打怪倒计时: {mins:02d}:{secs:02d}")
            self.countdown_label.setStyleSheet("""
                font-size: 16px; 
                font-weight: bold; 
                color: white; 
                padding: 8px; 
                background-color: #ff5722; 
                border-radius: 5px;
                border: 2px solid #e64a19;
            """)
        else:
            # 正常显示
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            self.countdown_label.setText(f"手动打怪倒计时: {mins:02d}:{secs:02d}")
            self.countdown_label.setStyleSheet("""
                font-size: 16px; 
                font-weight: bold; 
                color: #ff6600; 
                padding: 8px; 
                background-color: #fff3e0; 
                border-radius: 5px;
                border: 2px solid #ff6600;
            """)
