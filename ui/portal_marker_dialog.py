"""
传送门位置标记对话框

功能：
1. 显示小地图截图（放大3倍便于点击）
2. 自动检测到的传送门位置用蓝色圆点标记
3. 用户点击标记位置用红色圆点标记
4. 支持确认使用或清除标记
"""

import cv2
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox
)


class ClickableImageLabel(QLabel):
    """可点击的图片标签，支持获取点击位置"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.click_callback = None
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.click_callback:
            self.click_callback(event.pos().x(), event.pos().y())


class PortalMarkerDialog(QDialog):
    """传送门位置标记对话框"""
    
    SCALE = 2  # 小地图放大倍数
    
    def __init__(self, parent, minimap_image: np.ndarray, 
                 auto_portal_pos=None, current_manual_pos=None):
        """
        Args:
            parent: 父窗口
            minimap_image: 小地图截图 (BGR numpy array)
            auto_portal_pos: 自动检测到的传送门位置 (x, y) 或 None
            current_manual_pos: 当前已有的手动标记位置 (x, y) 或 None
        """
        super().__init__(parent)
        self.setWindowTitle("标记传送门位置")
        self.minimap_image = minimap_image
        self.auto_portal_pos = auto_portal_pos
        self.manual_pos = current_manual_pos  # 用户标记的位置（小地图原始坐标）
        self.result_pos = current_manual_pos  # 最终返回的位置
        
        self._init_ui()
        self._update_image()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # 提示文字
        hint_label = QLabel("点击小地图标记传送门位置（红色=手动标记，蓝色=自动检测）")
        hint_label.setStyleSheet("font-size: 12px; color: #333; padding: 5px;")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)
        
        # 小地图显示区域
        self.image_label = ClickableImageLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.click_callback = self._on_image_clicked
        self.image_label.setCursor(Qt.CursorShape.CrossCursor)
        self.image_label.setStyleSheet("border: 2px solid #ccc; background-color: #222;")
        layout.addWidget(self.image_label)
        
        # 坐标信息
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("font-size: 11px; color: #666; padding: 3px;")
        layout.addWidget(self.info_label)
        self._update_info_text()
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.confirm_btn = QPushButton("使用此位置")
        self.confirm_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px 16px;")
        self.confirm_btn.clicked.connect(self._on_confirm)
        self.confirm_btn.setEnabled(self.manual_pos is not None)
        btn_layout.addWidget(self.confirm_btn)
        
        self.clear_btn = QPushButton("清除标记（恢复自动）")
        self.clear_btn.setStyleSheet("background-color: #FF9800; color: white; padding: 8px 16px;")
        self.clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(self.clear_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("padding: 8px 16px;")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
    
    def _on_image_clicked(self, display_x, display_y):
        """用户点击图片时，换算回小地图原始坐标"""
        # 放大图的坐标 → 原始小地图坐标
        orig_x = int(display_x / self.SCALE)
        orig_y = int(display_y / self.SCALE)
        
        # 边界检查
        h, w = self.minimap_image.shape[:2]
        orig_x = max(0, min(orig_x, w - 1))
        orig_y = max(0, min(orig_y, h - 1))
        
        self.manual_pos = (orig_x, orig_y)
        self.confirm_btn.setEnabled(True)
        self._update_image()
        self._update_info_text()
    
    def _update_info_text(self):
        """更新坐标信息文字"""
        parts = []
        if self.auto_portal_pos:
            parts.append(f"自动检测: ({self.auto_portal_pos[0]}, {self.auto_portal_pos[1]})")
        else:
            parts.append("自动检测: 未找到")
        
        if self.manual_pos:
            parts.append(f"手动标记: ({self.manual_pos[0]}, {self.manual_pos[1]})")
        else:
            parts.append("手动标记: 未设置")
        
        self.info_label.setText("  |  ".join(parts))
    
    def _update_image(self):
        """重绘小地图图片（带标记点）"""
        # 复制原图并放大
        display_img = cv2.resize(
            self.minimap_image, None, 
            fx=self.SCALE, fy=self.SCALE, 
            interpolation=cv2.INTER_NEAREST
        )
        
        # 画自动检测的蓝色圆点
        if self.auto_portal_pos:
            ax, ay = self.auto_portal_pos
            cx, cy = int(ax * self.SCALE + self.SCALE // 2), int(ay * self.SCALE + self.SCALE // 2)
            cv2.circle(display_img, (cx, cy), 8, (255, 100, 0), 2)       # 蓝色空心圆
            cv2.circle(display_img, (cx, cy), 3, (255, 100, 0), -1)      # 蓝色实心小点
        
        # 画手动标记的红色圆点
        if self.manual_pos:
            mx, my = self.manual_pos
            cx, cy = int(mx * self.SCALE + self.SCALE // 2), int(my * self.SCALE + self.SCALE // 2)
            cv2.circle(display_img, (cx, cy), 8, (0, 0, 255), 2)         # 红色空心圆
            cv2.circle(display_img, (cx, cy), 3, (0, 0, 255), -1)        # 红色实心小点
        
        # OpenCV BGR → Qt QPixmap
        h, w, ch = display_img.shape
        bytes_per_line = ch * w
        rgb_img = cv2.cvtColor(display_img, cv2.COLOR_BGR2RGB)
        q_image = QImage(rgb_img.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        self.image_label.setPixmap(QPixmap.fromImage(q_image))
    
    def _on_confirm(self):
        """确认使用手动标记的位置"""
        if self.manual_pos:
            self.result_pos = self.manual_pos
            self.accept()
    
    def _on_clear(self):
        """清除手动标记，恢复自动检测"""
        self.manual_pos = None
        self.result_pos = None  # None 表示恢复自动
        self.confirm_btn.setEnabled(False)
        self._update_image()
        self._update_info_text()
        self.accept()
    
    def get_marked_position(self):
        """获取最终标记的位置，None 表示使用自动检测"""
        return self.result_pos
