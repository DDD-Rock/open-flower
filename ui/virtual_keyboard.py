"""
虚拟键盘对话框
按照游戏内键盘布局设计
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QWidget, QFrame
)
from PyQt6.QtCore import Qt


class VirtualKeyboardDialog(QDialog):
    """虚拟键盘对话框 - 按照游戏键盘布局"""
    
    def __init__(self, parent=None, current_key: str = "Ctrl"):
        super().__init__(parent)
        self.selected_key = current_key
        self.key_buttons = {}
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("选择攻击按键")
        self.setModal(True)
        self.setFixedSize(750, 380)
        self.setStyleSheet("background-color: #e8e8e8;")
        
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 键盘主体
        keyboard_layout = QHBoxLayout()
        keyboard_layout.setSpacing(10)
        
        # 左侧主键盘区域
        main_keyboard = self.create_main_keyboard()
        keyboard_layout.addWidget(main_keyboard)
        
        # 右侧功能区（含方向键）
        right_section = self.create_right_section()
        keyboard_layout.addWidget(right_section)
        
        layout.addLayout(keyboard_layout)
        
        # 当前选择显示
        self.current_label = QLabel(f"当前选择: {self.selected_key}")
        self.current_label.setStyleSheet("""
            font-size: 16px; 
            font-weight: bold; 
            color: #1976d2;
            padding: 8px;
            background-color: #e3f2fd;
            border-radius: 5px;
            border: 2px solid #1976d2;
        """)
        self.current_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.current_label)
        
        # 确认按钮
        confirm_btn = QPushButton("确认选择")
        confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        confirm_btn.clicked.connect(self.accept)
        layout.addWidget(confirm_btn)
        
        self.setLayout(layout)
    
    def create_main_keyboard(self) -> QWidget:
        """创建主键盘区域"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(3)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 第一行: Esc, F1-F12
        row1 = QHBoxLayout()
        row1.setSpacing(2)
        self.add_key(row1, "Esc", 40)
        self.add_spacer(row1, 10)
        for i in range(1, 13):
            self.add_key(row1, f"F{i}", 38)
            if i == 4 or i == 8:
                self.add_spacer(row1, 8)
        row1.addStretch()
        layout.addLayout(row1)
        
        # 第二行: `, 1-0, -, =, Backspace
        row2 = QHBoxLayout()
        row2.setSpacing(2)
        self.add_key(row2, "`", 38)
        for c in "1234567890":
            self.add_key(row2, c, 38)
        self.add_key(row2, "-", 38)
        self.add_key(row2, "=", 38)
        self.add_key(row2, "Backspace", 65, display="←")
        row2.addStretch()
        layout.addLayout(row2)
        
        # 第三行: Tab, Q-P, [, ], \
        row3 = QHBoxLayout()
        row3.setSpacing(2)
        self.add_key(row3, "Tab", 55)
        for c in "QWERTYUIOP":
            self.add_key(row3, c, 38)
        self.add_key(row3, "[", 38)
        self.add_key(row3, "]", 38)
        self.add_key(row3, "\\", 50)
        row3.addStretch()
        layout.addLayout(row3)
        
        # 第四行: Caps, A-L, ;, ', Enter
        row4 = QHBoxLayout()
        row4.setSpacing(2)
        self.add_key(row4, "Caps", 65)
        for c in "ASDFGHJKL":
            self.add_key(row4, c, 38)
        self.add_key(row4, ";", 38)
        self.add_key(row4, "'", 38)
        self.add_key(row4, "Enter", 75)
        row4.addStretch()
        layout.addLayout(row4)
        
        # 第五行: Shift, Z-M, ,, ., /, Shift
        row5 = QHBoxLayout()
        row5.setSpacing(2)
        self.add_key(row5, "Shift", 85, display="Shift")
        for c in "ZXCVBNM":
            self.add_key(row5, c, 38)
        self.add_key(row5, ",", 38)
        self.add_key(row5, ".", 38)
        self.add_key(row5, "/", 38)
        self.add_key(row5, "RShift", 85, display="Shift", actual_key="Shift")
        row5.addStretch()
        layout.addLayout(row5)
        
        # 第六行: Ctrl, Alt, Space, Alt, Ctrl
        row6 = QHBoxLayout()
        row6.setSpacing(2)
        self.add_key(row6, "Ctrl", 55)
        self.add_spacer(row6, 38)  # Windows键位置留空
        self.add_key(row6, "Alt", 50)
        self.add_key(row6, "Space", 220)
        self.add_key(row6, "RAlt", 50, display="Alt", actual_key="Alt")
        self.add_spacer(row6, 38)  # Windows键位置留空
        self.add_key(row6, "RCtrl", 55, display="Ctrl", actual_key="Ctrl")
        row6.addStretch()
        layout.addLayout(row6)
        
        widget.setLayout(layout)
        return widget
    
    def create_right_section(self) -> QWidget:
        """创建右侧功能区"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(3)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 第一行: PrtSc, ScrLk, Pause
        row1 = QHBoxLayout()
        row1.setSpacing(2)
        self.add_key(row1, "PrtSc", 38, display="Psc")
        self.add_key(row1, "ScrLk", 38, display="Slk")
        self.add_key(row1, "Pause", 38, display="Pse")
        layout.addLayout(row1)
        
        # 第二行: Insert, Home, PageUp
        row2 = QHBoxLayout()
        row2.setSpacing(2)
        self.add_key(row2, "Insert", 38, display="Ins")
        self.add_key(row2, "Home", 38)
        self.add_key(row2, "PageUp", 38, display="PgU")
        layout.addLayout(row2)
        
        # 第三行: Delete, End, PageDown
        row3 = QHBoxLayout()
        row3.setSpacing(2)
        self.add_key(row3, "Delete", 38, display="Del")
        self.add_key(row3, "End", 38)
        self.add_key(row3, "PageDown", 38, display="PgD")
        layout.addLayout(row3)
        
        # 空行
        layout.addSpacing(20)
        
        # 方向键
        arrow_widget = QWidget()
        arrow_layout = QGridLayout()
        arrow_layout.setSpacing(2)
        arrow_layout.setContentsMargins(0, 0, 0, 0)
        
        # 上
        up_btn = self.create_key_button("Up", 38, "↑")
        arrow_layout.addWidget(up_btn, 0, 1)
        # 左 下 右
        left_btn = self.create_key_button("Left", 38, "←")
        arrow_layout.addWidget(left_btn, 1, 0)
        down_btn = self.create_key_button("Down", 38, "↓")
        arrow_layout.addWidget(down_btn, 1, 1)
        right_btn = self.create_key_button("Right", 38, "→")
        arrow_layout.addWidget(right_btn, 1, 2)
        
        arrow_widget.setLayout(arrow_layout)
        layout.addWidget(arrow_widget)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def add_key(self, layout: QHBoxLayout, key: str, width: int, display: str = None, actual_key: str = None):
        """添加按键"""
        btn = self.create_key_button(key if actual_key is None else actual_key, width, display or key)
        layout.addWidget(btn)
    
    def add_spacer(self, layout: QHBoxLayout, width: int):
        """添加间隔"""
        spacer = QWidget()
        spacer.setFixedWidth(width)
        layout.addWidget(spacer)
    
    def create_key_button(self, key: str, width: int, display: str = None) -> QPushButton:
        """创建按键按钮"""
        btn = QPushButton(display or key)
        btn.setFixedSize(width, 35)
        
        is_selected = key.lower() == self.selected_key.lower()
        btn.setStyleSheet(self.get_key_style(is_selected))
        btn.clicked.connect(lambda checked, k=key: self.on_key_clicked(k))
        
        self.key_buttons[key] = btn
        return btn
    
    def get_key_style(self, selected: bool) -> str:
        """获取按键样式"""
        if selected:
            return """
                QPushButton {
                    background-color: #d4a5a5;
                    border: 2px solid #c08080;
                    border-radius: 4px;
                    font-size: 10px;
                    font-weight: bold;
                    color: #5a3030;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: #f8f8f8;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    font-size: 10px;
                    color: #333;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                    border: 1px solid #999;
                }
                QPushButton:pressed {
                    background-color: #d0d0d0;
                }
            """
    
    def on_key_clicked(self, key: str):
        """按键点击处理"""
        # 更新旧按钮样式
        old_key = self.selected_key
        if old_key in self.key_buttons:
            self.key_buttons[old_key].setStyleSheet(self.get_key_style(False))
        # 处理别名键（如RShift对应Shift）
        for k, btn in self.key_buttons.items():
            if k.lower() == old_key.lower():
                btn.setStyleSheet(self.get_key_style(False))
        
        self.selected_key = key
        self.current_label.setText(f"当前选择: {key}")
        
        # 更新新按钮样式
        if key in self.key_buttons:
            self.key_buttons[key].setStyleSheet(self.get_key_style(True))
        # 处理别名键
        for k, btn in self.key_buttons.items():
            if k.lower() == key.lower():
                btn.setStyleSheet(self.get_key_style(True))
    
    def get_selected_key(self) -> str:
        """获取选择的按键"""
        return self.selected_key
