"""
冒险岛世界祭司自动技能释放工具
功能：自动按照设定的时间间隔和随机延迟释放技能
"""

import sys
import time
import random
import threading
from typing import List, Dict

# UI界面库
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QMessageBox, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject

# 按键模拟库
import keyboard

# 未来拓展所需的包（已导入，暂未使用）
# import cv2  # opencv-contrib-python
# import numpy as np  # numpy
# import mss  # mss
# import pyautogui  # pyautogui
# from PIL import Image  # pillow
# from pynput import mouse, keyboard as pynput_keyboard  # pynput
# from ultralytics import YOLO  # ultralytics
# import psutil  # psutil
# import screeninfo  # screeninfo


class SkillConfig:
    """技能配置类"""
    def __init__(self, key: str, interval: float, random_delay: float):
        """
        初始化技能配置
        
        参数:
            key: 技能按键（如 '1', '2', 'F1' 等）
            interval: 释放间隔（秒）
            random_delay: 随机延迟最大秒数
        """
        self.key = key
        self.interval = interval
        self.random_delay = random_delay
    
    def __str__(self):
        """返回技能配置的字符串表示"""
        return f"按键: {self.key}, 间隔: {self.interval}秒, 随机延迟: {self.random_delay}秒"


class SkillWorker(QObject):
    """技能释放工作线程类"""
    # 定义信号，用于更新UI状态
    status_update = pyqtSignal(str)
    skill_pressed = pyqtSignal(str)
    
    def __init__(self, skills: List[SkillConfig]):
        """
        初始化工作线程
        
        参数:
            skills: 技能配置列表
        """
        super().__init__()
        self.skills = skills
        self.is_running = False
        self.thread = None
    
    def start(self):
        """启动技能释放线程"""
        if self.is_running:
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.status_update.emit("运行中...")
    
    def stop(self):
        """停止技能释放线程"""
        self.is_running = False
        self.status_update.emit("已停止")
    
    def _run_loop(self):
        """技能释放循环（在后台线程中运行）"""
        try:
            while self.is_running:
                # 遍历所有技能
                for skill in self.skills:
                    if not self.is_running:
                        break
                    
                    # 发送状态更新
                    self.status_update.emit(f"准备释放技能: {skill.key}")
                    
                    # 模拟按键
                    try:
                        keyboard.press_and_release(skill.key)
                        self.skill_pressed.emit(f"已释放: {skill.key}")
                    except Exception as e:
                        self.status_update.emit(f"按键错误: {str(e)}")
                    
                    # 计算等待时间：间隔 + 随机延迟
                    random_delay = random.uniform(0, skill.random_delay)
                    wait_time = skill.interval + random_delay
                    
                    # 等待（分段等待，以便能够及时响应停止信号）
                    elapsed = 0
                    while elapsed < wait_time and self.is_running:
                        time.sleep(0.1)
                        elapsed += 0.1
                    
                    if not self.is_running:
                        break
                
                # 所有技能释放完成，重置计时，准备下一轮循环
                if self.is_running:
                    self.status_update.emit("一轮技能释放完成，准备下一轮...")
                    time.sleep(0.5)  # 短暂停顿，避免过于频繁
                    
        except Exception as e:
            self.status_update.emit(f"运行错误: {str(e)}")
        finally:
            self.is_running = False
            self.status_update.emit("已停止")


class MainWindow(QMainWindow):
    """主窗口类"""
    
    def __init__(self):
        """初始化主窗口"""
        super().__init__()
        self.skills: List[SkillConfig] = []
        self.worker: SkillWorker = None
        self.init_ui()
    
    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle("冒险岛世界 - 祭司自动技能释放工具")
        self.setGeometry(100, 100, 600, 500)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # 技能配置区域
        config_group = QGroupBox("技能配置")
        config_layout = QVBoxLayout()
        
        # 技能按键输入
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel("技能按键:"))
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("例如: 1, 2, F1, F2 等")
        key_layout.addWidget(self.key_input)
        config_layout.addLayout(key_layout)
        
        # 释放间隔输入
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("释放间隔(秒):"))
        self.interval_input = QLineEdit()
        self.interval_input.setPlaceholderText("例如: 5.0")
        interval_layout.addWidget(self.interval_input)
        config_layout.addLayout(interval_layout)
        
        # 随机延迟输入
        random_layout = QHBoxLayout()
        random_layout.addWidget(QLabel("随机延迟(秒):"))
        self.random_input = QLineEdit()
        self.random_input.setPlaceholderText("例如: 2.0 (0到2.0秒之间随机)")
        random_layout.addWidget(self.random_input)
        config_layout.addLayout(random_layout)
        
        # 添加技能按钮
        add_btn = QPushButton("添加技能")
        add_btn.clicked.connect(self.add_skill)
        config_layout.addWidget(add_btn)
        
        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)
        
        # 技能列表区域
        list_group = QGroupBox("已添加的技能列表")
        list_layout = QVBoxLayout()
        
        self.skill_list = QListWidget()
        list_layout.addWidget(self.skill_list)
        
        # 删除技能按钮
        delete_btn = QPushButton("删除选中的技能")
        delete_btn.clicked.connect(self.delete_skill)
        list_layout.addWidget(delete_btn)
        
        list_group.setLayout(list_layout)
        main_layout.addWidget(list_group)
        
        # 控制按钮区域
        control_group = QGroupBox("控制")
        control_layout = QVBoxLayout()
        
        # 开始/停止按钮
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始运行")
        self.start_btn.clicked.connect(self.start_worker)
        self.stop_btn = QPushButton("停止运行")
        self.stop_btn.clicked.connect(self.stop_worker)
        self.stop_btn.setEnabled(False)
        
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        control_layout.addLayout(button_layout)
        
        # 状态显示
        self.status_label = QLabel("状态: 未运行")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        control_layout.addWidget(self.status_label)
        
        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)
        
        # 提示信息
        tip_label = QLabel("提示: 请确保游戏窗口处于活动状态，程序会自动按照设定的间隔释放技能")
        tip_label.setWordWrap(True)
        tip_label.setStyleSheet("color: gray; font-size: 10px; padding: 5px;")
        main_layout.addWidget(tip_label)
    
    def add_skill(self):
        """添加技能到列表"""
        key = self.key_input.text().strip()
        interval_str = self.interval_input.text().strip()
        random_str = self.random_input.text().strip()
        
        # 验证输入
        if not key:
            QMessageBox.warning(self, "警告", "请输入技能按键！")
            return
        
        try:
            interval = float(interval_str)
            if interval <= 0:
                raise ValueError("间隔必须大于0")
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的释放间隔（大于0的数字）！")
            return
        
        try:
            random_delay = float(random_str)
            if random_delay < 0:
                raise ValueError("随机延迟不能为负数")
        except ValueError:
            QMessageBox.warning(self, "警告", "请输入有效的随机延迟（大于等于0的数字）！")
            return
        
        # 创建技能配置
        skill = SkillConfig(key, interval, random_delay)
        self.skills.append(skill)
        
        # 更新列表显示
        self.skill_list.addItem(str(skill))
        
        # 清空输入框
        self.key_input.clear()
        self.interval_input.clear()
        self.random_input.clear()
        
        QMessageBox.information(self, "成功", f"已添加技能: {key}")
    
    def delete_skill(self):
        """删除选中的技能"""
        current_item = self.skill_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请先选择要删除的技能！")
            return
        
        # 获取选中项的索引
        index = self.skill_list.currentRow()
        if 0 <= index < len(self.skills):
            removed_skill = self.skills.pop(index)
            self.skill_list.takeItem(index)
            QMessageBox.information(self, "成功", f"已删除技能: {removed_skill.key}")
    
    def start_worker(self):
        """启动技能释放"""
        if not self.skills:
            QMessageBox.warning(self, "警告", "请至少添加一个技能！")
            return
        
        # 停止之前的worker（如果存在）
        if self.worker:
            self.worker.stop()
        
        # 创建新的worker
        self.worker = SkillWorker(self.skills.copy())
        self.worker.status_update.connect(self.update_status)
        self.worker.skill_pressed.connect(self.on_skill_pressed)
        
        # 启动worker
        self.worker.start()
        
        # 更新按钮状态
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
    
    def stop_worker(self):
        """停止技能释放"""
        if self.worker:
            self.worker.stop()
            self.worker = None
        
        # 更新按钮状态
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("状态: 已停止")
    
    def update_status(self, message: str):
        """更新状态显示"""
        self.status_label.setText(f"状态: {message}")
    
    def on_skill_pressed(self, message: str):
        """技能释放时的回调"""
        # 可以在这里添加额外的日志或提示
        pass
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        if self.worker and self.worker.is_running:
            self.worker.stop()
            # 等待线程结束
            if self.worker.thread:
                self.worker.thread.join(timeout=1.0)
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

