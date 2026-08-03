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
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QDoubleSpinBox,
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
    
    def __init__(
        self,
        parent,
        minimap_image: np.ndarray,
        auto_portal_pos=None,
        current_manual_pos=None,
        title: str = "标记传送门位置",
        hint_text: str = "点击小地图标记传送门位置（红色=手动标记，蓝色=自动检测）",
        show_auto_portal: bool = True,
        confirm_button_text: str = "使用此位置",
        clear_button_text: str = "清除标记（恢复自动）",
        boundary_tolerance: float = None,
        boundary_title: str = "左右界限值（基准点 ±）",
    ):
        """
        Args:
            parent: 父窗口
            minimap_image: 小地图截图 (BGR numpy array)
            auto_portal_pos: 自动检测到的传送门位置 (x, y) 或 None
            current_manual_pos: 当前已有的手动标记位置 (x, y) 或 None
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.minimap_image = minimap_image
        self.auto_portal_pos = auto_portal_pos
        self.manual_pos = current_manual_pos  # 用户标记的位置（小地图原始坐标）
        self.result_pos = current_manual_pos  # 最终返回的位置
        self.hint_text = hint_text
        self.show_auto_portal = show_auto_portal
        self.confirm_button_text = confirm_button_text
        self.clear_button_text = clear_button_text
        self.boundary_tolerance = (
            None if boundary_tolerance is None else float(boundary_tolerance)
        )
        self.boundary_title = boundary_title
        
        self._init_ui()
        self._update_image()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # 提示文字
        hint_label = QLabel(self.hint_text)
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

        if self.boundary_tolerance is not None:
            boundary_layout = QHBoxLayout()
            boundary_layout.addWidget(QLabel(self.boundary_title))
            boundary_layout.addStretch(1)
            self.boundary_input = QDoubleSpinBox()
            self.boundary_input.setRange(1.0, 50.0)
            self.boundary_input.setSingleStep(0.5)
            self.boundary_input.setDecimals(1)
            self.boundary_input.setValue(self.boundary_tolerance)
            self.boundary_input.setSuffix(" 点")
            self.boundary_input.setObjectName("followHealBoundaryTolerance")
            self.boundary_input.valueChanged.connect(self._on_boundary_changed)
            boundary_layout.addWidget(self.boundary_input)
            layout.addLayout(boundary_layout)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.confirm_btn = QPushButton(self.confirm_button_text)
        self.confirm_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px 16px;")
        self.confirm_btn.clicked.connect(self._on_confirm)
        self.confirm_btn.setEnabled(self.manual_pos is not None)
        btn_layout.addWidget(self.confirm_btn)
        
        self.clear_btn = QPushButton(self.clear_button_text)
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
        if self.show_auto_portal and self.auto_portal_pos:
            parts.append(f"自动检测: ({self.auto_portal_pos[0]}, {self.auto_portal_pos[1]})")
        elif self.show_auto_portal:
            parts.append("自动检测: 未找到")
        
        if self.manual_pos:
            parts.append(f"手动标记: ({self.manual_pos[0]}, {self.manual_pos[1]})")
            if self.boundary_tolerance is not None:
                parts.append(f"允许范围: ±{self.boundary_tolerance:.1f}")
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
        if self.show_auto_portal and self.auto_portal_pos:
            ax, ay = self.auto_portal_pos
            cx, cy = int(ax * self.SCALE + self.SCALE // 2), int(ay * self.SCALE + self.SCALE // 2)
            cv2.circle(display_img, (cx, cy), 8, (255, 100, 0), 2)       # 蓝色空心圆
            cv2.circle(display_img, (cx, cy), 3, (255, 100, 0), -1)      # 蓝色实心小点
        
        # 画手动标记的红色圆点
        if self.manual_pos:
            mx, my = self.manual_pos
            cx, cy = int(mx * self.SCALE + self.SCALE // 2), int(my * self.SCALE + self.SCALE // 2)
            if self.boundary_tolerance is not None:
                display_h, display_w = display_img.shape[:2]
                left = max(0, int((mx - self.boundary_tolerance) * self.SCALE))
                right = min(
                    display_w - 1,
                    int((mx + self.boundary_tolerance) * self.SCALE),
                )
                overlay = display_img.copy()
                cv2.rectangle(overlay, (left, 0), (right, display_h - 1), (0, 0, 255), -1)
                cv2.addWeighted(overlay, 0.16, display_img, 0.84, 0, display_img)
                cv2.line(display_img, (left, 0), (left, display_h - 1), (0, 0, 255), 2)
                cv2.line(display_img, (right, 0), (right, display_h - 1), (0, 0, 255), 2)
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

    def _on_boundary_changed(self, value: float):
        self.boundary_tolerance = float(value)
        self._update_image()
        self._update_info_text()
    
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

    def get_boundary_tolerance(self) -> float:
        """获取跟补基准点的左右允许范围。"""
        return 6.0 if self.boundary_tolerance is None else self.boundary_tolerance
