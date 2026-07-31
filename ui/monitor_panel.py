"""Windows 监控模式面板及只读地图叠加绘制。"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)


class MonitorCanvas(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#151A24;border-radius:9px;color:#AAB2C0;")
        self.setText("开始监控后显示实时小地图")
        self._source = None
        self._frame = None
        self._display_mode = "minimap_with_annotations"

    def set_display_mode(self, mode):
        self._display_mode = mode
        self.update()

    def set_frame(self, frame):
        self._frame = frame
        image = frame.get("image") if frame else None
        if image is None:
            self._source = None
        else:
            height, width, channels = image.shape
            self._source = QImage(
                image.data,
                width,
                height,
                channels * width,
                QImage.Format.Format_BGR888,
            ).copy()
        self.setText("")
        self.update()

    def clear_frame(self):
        self._source = None
        self._frame = None
        self.setText("开始监控后显示实时小地图")
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._frame or not self._source:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        source_size = self._source.size()
        target = QRectF(self.rect())
        scaled = source_size.scaled(
            int(target.width()),
            int(target.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        canvas = QRectF(
            (target.width() - scaled.width()) / 2,
            (target.height() - scaled.height()) / 2,
            scaled.width(),
            scaled.height(),
        )
        if self._display_mode != "annotations_only":
            painter.drawImage(canvas, self._source)
        else:
            painter.fillRect(canvas, QColor("#151A24"))
        if self._display_mode != "minimap_only":
            self._draw_annotations(painter, canvas, source_size.width(), source_size.height())

    def _draw_annotations(self, painter, canvas, source_width, source_height):
        topology = self._frame.get("map")

        def normalized(point):
            return QPointF(
                canvas.left() + point.x * canvas.width(),
                canvas.top() + point.y * canvas.height(),
            )

        if topology is not None:
            painter.setPen(QPen(QColor("#27C66F"), 2))
            for platform in topology.platforms:
                points = [normalized(point) for point in platform.points]
                if len(points) >= 2:
                    painter.drawPolyline(QPolygonF(points))
            painter.setPen(QPen(QColor("#F39A2B"), 2))
            for rope in topology.ropes:
                painter.drawLine(
                    normalized(type("P", (), {"x": rope.x, "y": rope.top_y})()),
                    normalized(type("P", (), {"x": rope.x, "y": rope.bottom_y})()),
                )
            painter.setPen(QPen(QColor("#3A8DFF"), 2))
            painter.setBrush(QColor("#3A8DFF"))
            for portal in topology.portals:
                point = normalized(portal.point)
                painter.drawEllipse(point, 4, 4)

        safe_zone = self._frame.get("safe_zone")
        if safe_zone is not None:
            x, y, width, height = safe_zone.normalized_rect
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(
                    QColor("#E9404A" if self._frame.get("zone_outside") else "#25B96B"),
                    2,
                    Qt.PenStyle.DashLine,
                )
            )
            painter.drawRect(
                QRectF(
                    canvas.left() + x * canvas.width(),
                    canvas.top() + y * canvas.height(),
                    width * canvas.width(),
                    height * canvas.height(),
                )
            )

        def pixel(point):
            return QPointF(
                canvas.left() + point[0] / max(source_width, 1) * canvas.width(),
                canvas.top() + point[1] / max(source_height, 1) * canvas.height(),
            )

        painter.setPen(QPen(QColor("#151515"), 2))
        painter.setBrush(QColor("#FFE500"))
        if self._frame.get("player") is not None:
            point = pixel(self._frame["player"])
            painter.drawEllipse(point, 5, 5)
            painter.setBrush(QColor("#FFE500"))
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(point.x(), point.y() - 7),
                        QPointF(point.x() - 4, point.y() - 13),
                        QPointF(point.x() + 4, point.y() - 13),
                    ]
                )
            )
        painter.setBrush(QColor("#F18A28"))
        for value in self._frame.get("teammates", []):
            painter.drawEllipse(pixel(value), 4, 4)
        painter.setBrush(QColor("#EF3F48"))
        for value in self._frame.get("others", []):
            painter.drawEllipse(pixel(value), 4, 4)


class MonitorPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("地图监控")
        title.setStyleSheet("font-size:14px;font-weight:700;")
        header.addWidget(title)
        header.addStretch(1)
        self.manage_maps_button = QPushButton("管理地图")
        header.addWidget(self.manage_maps_button)
        self.action_test_button = QPushButton("动作测试")
        header.addWidget(self.action_test_button)
        self.route_test_button = QPushButton("路径执行")
        header.addWidget(self.route_test_button)
        layout.addLayout(header)

        self.status_label = QLabel("尚未开始监控")
        self.status_label.setStyleSheet("color:#747D8D;")
        layout.addWidget(self.status_label)

        self.display_mode = QComboBox()
        self.display_mode.addItem("纯小地图", "minimap_only")
        self.display_mode.addItem("小地图 + 标注", "minimap_with_annotations")
        self.display_mode.addItem("纯标注", "annotations_only")
        self.display_mode.setCurrentIndex(1)
        layout.addWidget(self.display_mode)

        self.canvas = MonitorCanvas()
        self.display_mode.currentIndexChanged.connect(
            lambda: self.canvas.set_display_mode(self.display_mode.currentData())
        )
        layout.addWidget(self.canvas)

        self.metrics_label = QLabel("X -- · Y -- · 队友 0 · 其他玩家 0 · 0 FPS")
        self.metrics_label.setStyleSheet("color:#5F6878;font-family:Consolas;")
        layout.addWidget(self.metrics_label)

        self.rune_label = QLabel("符文：未检测")
        self.rune_label.setStyleSheet("color:#747D8D;")
        layout.addWidget(self.rune_label)

        self.exp_label = QLabel("EXP：尚未识别")
        self.exp_label.setStyleSheet("color:#747D8D;")
        layout.addWidget(self.exp_label)

        zone_row = QHBoxLayout()
        self.zone_button = QPushButton("设置安全区基准点")
        zone_row.addWidget(self.zone_button)
        self.zone_width = QSpinBox()
        self.zone_height = QSpinBox()
        for control in (self.zone_width, self.zone_height):
            control.setRange(2, 100)
            control.setSingleStep(5)
            control.setValue(20)
            control.setSuffix("%")
        zone_row.addWidget(QLabel("宽"))
        zone_row.addWidget(self.zone_width)
        zone_row.addWidget(QLabel("高"))
        zone_row.addWidget(self.zone_height)
        self.clear_zone_button = QPushButton("清除")
        zone_row.addWidget(self.clear_zone_button)
        layout.addLayout(zone_row)

    def update_frame(self, frame):
        self.canvas.set_frame(frame)
        player = frame.get("player")
        coordinate = f"X {player[0]} · Y {player[1]}" if player else "X -- · Y --"
        self.metrics_label.setText(
            f"{coordinate} · 队友 {len(frame.get('teammates', []))}"
            f" · 其他玩家 {len(frame.get('others', []))}"
            f" · {frame.get('fps', 0):.1f} FPS"
        )

    def set_rune(self, present, detection=None):
        self.rune_label.setText("符文：需要解除" if present else "符文：未检测")
        self.rune_label.setStyleSheet(
            "color:#E9404A;font-weight:700;" if present else "color:#747D8D;"
        )

    def set_exp(self, reading, status):
        self.exp_label.setText(f"EXP：{status}")

    def reset(self):
        self.status_label.setText("尚未开始监控")
        self.metrics_label.setText("X -- · Y -- · 队友 0 · 其他玩家 0 · 0 FPS")
        self.set_rune(False)
        self.set_exp(None, "尚未识别")
        self.canvas.clear_frame()
