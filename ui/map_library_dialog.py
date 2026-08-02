"""Windows 多地图库与基础标注编辑器。"""

from __future__ import annotations

import copy

import cv2
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from models.map_topology import (
    MapPlatform,
    MapPortal,
    MapRope,
    MapTopology,
    MapTopologyValidator,
    MapTransferService,
    MinimapVisualMatcher,
    NormalizedMapPoint,
    PlatformTraceBuilder,
    RopeTraceBuilder,
)
from workers.map_trace_worker import MapTraceWorker


class PortalEditDialog(QDialog):
    TYPES = (
        ("普通传送门", "normal"),
        ("地图出口", "mapExit"),
        ("特殊入口", "specialEntrance"),
        ("当前地图传送", "intraMap"),
    )

    def __init__(self, portal, maps, current_map_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑传送点")
        layout = QFormLayout(self)
        self.type_combo = QComboBox()
        for title, value in self.TYPES:
            self.type_combo.addItem(title, value)
        type_index = self.type_combo.findData(portal.type)
        self.type_combo.setCurrentIndex(max(0, type_index))
        layout.addRow("类型", self.type_combo)
        self.map_combo = QComboBox()
        self.map_combo.addItem("不连接", None)
        for topology in maps:
            self.map_combo.addItem(topology.map_name, topology.map_name)
        map_index = self.map_combo.findData(portal.destination_map_name)
        self.map_combo.setCurrentIndex(max(0, map_index))
        layout.addRow("目标地图", self.map_combo)
        self.portal_combo = QComboBox()
        layout.addRow("目标传送点", self.portal_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.maps = maps
        self.portal = portal
        self.current_map_name = current_map_name
        self.map_combo.currentIndexChanged.connect(self._reload_portals)
        self._reload_portals()
        portal_index = self.portal_combo.findData(portal.destination_portal_id)
        self.portal_combo.setCurrentIndex(max(0, portal_index))

    def _reload_portals(self):
        selected = self.portal_combo.currentData()
        self.portal_combo.clear()
        self.portal_combo.addItem("不指定", None)
        target_name = self.map_combo.currentData()
        topology = next(
            (item for item in self.maps if item.map_name == target_name),
            None,
        )
        if topology is not None:
            for index, item in enumerate(topology.portals):
                if item.id != self.portal.id:
                    self.portal_combo.addItem(f"T{index + 1}", item.id)
        index = self.portal_combo.findData(selected)
        self.portal_combo.setCurrentIndex(max(0, index))

    def apply(self):
        self.portal.type = self.type_combo.currentData()
        self.portal.destination_map_name = self.map_combo.currentData()
        self.portal.destination_portal_id = self.portal_combo.currentData()


class MapEditorCanvas(QLabel):
    SCALE = 2

    def __init__(self, image, topology, parent=None, on_changed=None):
        super().__init__(parent)
        self.image = image
        self.topology = topology
        self.on_changed = on_changed
        self.tool = "platform"
        self.pending = []
        self.show_navigation = False
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.redraw()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = (
            max(0, min(self.image.shape[1] - 1, round(event.position().x() / self.SCALE))),
            max(0, min(self.image.shape[0] - 1, round(event.position().y() / self.SCALE))),
        )
        normalized = NormalizedMapPoint.from_pixel(
            point,
            (self.image.shape[1], self.image.shape[0]),
        )
        if self.tool == "portal":
            self.topology.portals.append(MapPortal(normalized))
            self.pending.clear()
        else:
            self.pending.append(normalized)
            if len(self.pending) == 2:
                if self.tool == "platform":
                    self.topology.platforms.append(MapPlatform(points=list(self.pending)))
                else:
                    first, second = self.pending
                    self.topology.ropes.append(
                        MapRope(
                            (first.x + second.x) / 2,
                            min(first.y, second.y),
                            max(first.y, second.y),
                        )
                    )
                self.pending.clear()
        self.redraw()
        if self.on_changed is not None:
            self.on_changed()

    def redraw(self):
        display = cv2.resize(
            self.image,
            None,
            fx=self.SCALE,
            fy=self.SCALE,
            interpolation=cv2.INTER_NEAREST,
        )
        width, height = self.image.shape[1], self.image.shape[0]

        def pixel(point):
            return (
                round(point.x * width * self.SCALE),
                round(point.y * height * self.SCALE),
            )

        for index, platform in enumerate(self.topology.platforms):
            points = np.array([pixel(point) for point in platform.points], dtype=np.int32)
            if len(points) >= 2:
                cv2.polylines(display, [points], False, (60, 210, 105), 2)
                cv2.putText(
                    display,
                    f"P{index + 1}",
                    tuple(points[0]),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (60, 210, 105),
                    1,
                )
        for index, rope in enumerate(self.topology.ropes):
            start = pixel(NormalizedMapPoint(rope.x, rope.top_y))
            end = pixel(NormalizedMapPoint(rope.x, rope.bottom_y))
            cv2.line(display, start, end, (30, 155, 245), 2)
            cv2.putText(
                display,
                f"R{index + 1}",
                start,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (30, 155, 245),
                1,
            )
        for index, portal in enumerate(self.topology.portals):
            point = pixel(portal.point)
            cv2.circle(display, point, 6, (245, 145, 40), 2)
            cv2.putText(
                display,
                f"T{index + 1}",
                (point[0] + 5, point[1] - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (245, 145, 40),
                1,
            )
        for point in self.pending:
            cv2.circle(display, pixel(point), 4, (0, 255, 255), -1)
        if self.show_navigation:
            from models.map_navigation import MapNavigationGraphBuilder

            graph = MapNavigationGraphBuilder.build(self.topology)
            colors = {
                "walk": (70, 200, 100),
                "climb": (40, 155, 245),
                "drop": (210, 80, 210),
                "jump": (230, 170, 50),
                "approach": (140, 140, 140),
                "approach_rope": (230, 170, 50),
                "portal": (245, 145, 40),
            }
            for edge in graph.edges:
                source = graph.node(edge.source_id)
                destination = graph.node(edge.destination_id)
                if source is None or destination is None:
                    continue
                cv2.arrowedLine(
                    display,
                    pixel(source.point),
                    pixel(destination.point),
                    colors.get(edge.kind, (180, 180, 180)),
                    1,
                    tipLength=0.14,
                )
        qimage = QImage(
            display.data,
            display.shape[1],
            display.shape[0],
            display.shape[1] * display.shape[2],
            QImage.Format.Format_BGR888,
        ).copy()
        self.setPixmap(QPixmap.fromImage(qimage))
        self.setFixedSize(qimage.size())


class MapEditorDialog(QDialog):
    def __init__(
        self,
        topology: MapTopology,
        maps=None,
        hwnd=None,
        window_selector=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"地图标注 · {topology.map_name}")
        self.topology = copy.deepcopy(topology)
        self.maps = list(maps or [])
        self.hwnd = hwnd
        self.window_selector = window_selector
        self.trace_worker = None
        self.trace_samples = []
        self.image = self._reference_image(self.topology)
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("工具"))
        self.tool = QComboBox()
        self.tool.addItem("平台（点击两个端点）", "platform")
        self.tool.addItem("绳索（点击顶部和底部）", "rope")
        self.tool.addItem("传送点（点击一次）", "portal")
        toolbar.addWidget(self.tool)
        self.undo_button = QPushButton("撤销最后一个")
        toolbar.addWidget(self.undo_button)
        self.clear_button = QPushButton("清空标注")
        toolbar.addWidget(self.clear_button)
        layout.addLayout(toolbar)

        tools = QHBoxLayout()
        self.trace_button = QPushButton("开始自动采集")
        self.portal_edit_button = QPushButton("编辑传送点")
        self.preview_button = QPushButton("显示路径预览")
        tools.addWidget(self.trace_button)
        tools.addWidget(self.portal_edit_button)
        tools.addWidget(self.preview_button)
        tools.addStretch(1)
        layout.addLayout(tools)

        self.canvas = MapEditorCanvas(
            self.image,
            self.topology,
            on_changed=self._refresh_summary,
        )
        layout.addWidget(self.canvas, alignment=Qt.AlignmentFlag.AlignCenter)
        self.summary = QLabel()
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.tool.currentIndexChanged.connect(self._change_tool)
        self.undo_button.clicked.connect(self._undo)
        self.clear_button.clicked.connect(self._clear)
        self.trace_button.clicked.connect(self._toggle_trace)
        self.portal_edit_button.clicked.connect(self._edit_portal)
        self.preview_button.clicked.connect(self._toggle_preview)
        self._refresh_summary()

    @staticmethod
    def _reference_image(topology):
        expected = topology.reference_width * topology.reference_height * 3
        if topology.reference_bgr and len(topology.reference_bgr) == expected:
            return np.frombuffer(topology.reference_bgr, dtype=np.uint8).reshape(
                topology.reference_height,
                topology.reference_width,
                3,
            ).copy()
        return np.full(
            (max(40, topology.reference_height), max(70, topology.reference_width), 3),
            24,
            dtype=np.uint8,
        )

    def _change_tool(self):
        self.canvas.tool = self.tool.currentData()
        self.canvas.pending.clear()
        self.canvas.redraw()

    def _undo(self):
        self.canvas.pending.clear()
        collections = {
            "platform": self.topology.platforms,
            "rope": self.topology.ropes,
            "portal": self.topology.portals,
        }
        target = collections[self.tool.currentData()]
        if target:
            target.pop()
        self.canvas.redraw()
        self._refresh_summary()

    def _clear(self):
        if QMessageBox.question(self, "清空地图", "确定清空全部平台、绳索和传送点吗？") != QMessageBox.StandardButton.Yes:
            return
        self.topology.platforms.clear()
        self.topology.ropes.clear()
        self.topology.portals.clear()
        self.topology.traversal_connections.clear()
        self.canvas.pending.clear()
        self.canvas.redraw()
        self._refresh_summary()

    def _refresh_summary(self):
        warning_count = len(MapTopologyValidator.messages(self.topology))
        self.summary.setText(
            f"平台 {len(self.topology.platforms)} · 绳索 {len(self.topology.ropes)}"
            f" · 传送点 {len(self.topology.portals)} · 校验提示 {warning_count}"
        )

    def _toggle_trace(self):
        if self.trace_worker is not None:
            self._finish_trace()
            return
        if not self.hwnd:
            QMessageBox.information(self, "提示", "请先识别游戏窗口")
            return
        self.trace_samples = []
        worker = MapTraceWorker(self.hwnd, self.window_selector, self)
        worker.sample_ready.connect(self.trace_samples.append)
        worker.status_update.connect(self.summary.setText)
        worker.error_signal.connect(
            lambda message: QMessageBox.warning(self, "采集失败", message)
        )
        worker.finished.connect(lambda current=worker: self._trace_finished(current))
        self.trace_worker = worker
        self.trace_button.setText("完成自动采集")
        self.summary.setText(
            "请在游戏中手动"
            + ("上下攀爬绳索" if self.tool.currentData() == "rope" else "左右走过平台")
        )
        worker.start()

    def _finish_trace(self):
        worker = self.trace_worker
        self.trace_worker = None
        if worker is not None:
            worker.stop()
            worker.wait(1500)
        size = (self.image.shape[1], self.image.shape[0])
        if self.tool.currentData() == "rope":
            result = RopeTraceBuilder.build_rope(self.trace_samples, size)
            if result is not None:
                self.topology.ropes.append(result)
        else:
            points = PlatformTraceBuilder.build_polyline(self.trace_samples, size)
            if points:
                self.topology.platforms.append(MapPlatform(points))
        self.trace_button.setText("开始自动采集")
        self.canvas.redraw()
        self._refresh_summary()
        if len(self.trace_samples) < 5:
            QMessageBox.information(self, "采集不足", "有效黄点样本不足，请重新采集")

    def _trace_finished(self, worker):
        if self.trace_worker is worker:
            self.trace_worker = None
            self.trace_button.setText("开始自动采集")

    def _edit_portal(self):
        if not self.topology.portals:
            QMessageBox.information(self, "提示", "请先标注传送点")
            return
        labels = [f"T{index + 1}" for index in range(len(self.topology.portals))]
        selected, ok = QInputDialog.getItem(
            self,
            "选择传送点",
            "传送点",
            labels,
            0,
            False,
        )
        if not ok:
            return
        portal = self.topology.portals[labels.index(selected)]
        maps = [
            self.topology if item.map_name == self.topology.map_name else item
            for item in self.maps
        ]
        if not any(item.map_name == self.topology.map_name for item in maps):
            maps.append(self.topology)
        dialog = PortalEditDialog(
            portal,
            maps,
            self.topology.map_name,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply()
            self.canvas.redraw()

    def _toggle_preview(self):
        self.canvas.show_navigation = not self.canvas.show_navigation
        self.preview_button.setText(
            "隐藏路径预览" if self.canvas.show_navigation else "显示路径预览"
        )
        self.canvas.redraw()

    def closeEvent(self, event):
        if self.trace_worker is not None:
            self._finish_trace()
        super().closeEvent(event)

    def accept(self):
        if self.trace_worker is not None:
            self._finish_trace()
        messages = MapTopologyValidator.messages(self.topology)
        if messages:
            answer = QMessageBox.question(
                self,
                "地图校验提示",
                "\n".join(messages) + "\n\n仍然保存吗？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        super().accept()


class MapLibraryDialog(QDialog):
    def __init__(
        self,
        store,
        current_image=None,
        hwnd=None,
        window_selector=None,
        account_manager=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("地图管理")
        self.resize(520, 430)
        self.store = store
        self.maps = store.load()
        self.current_image = current_image.copy() if current_image is not None else None
        self.hwnd = hwnd
        self.window_selector = window_selector
        self.account_manager = account_manager

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._edit)
        layout.addWidget(self.list_widget)

        first_row = QHBoxLayout()
        self.create_button = QPushButton("从当前小地图创建")
        self.edit_button = QPushButton("编辑")
        self.rename_button = QPushButton("重命名")
        self.delete_button = QPushButton("删除")
        for button in (
            self.create_button,
            self.edit_button,
            self.rename_button,
            self.delete_button,
        ):
            first_row.addWidget(button)
        layout.addLayout(first_row)

        second_row = QHBoxLayout()
        self.import_button = QPushButton("导入")
        self.export_button = QPushButton("导出全部")
        second_row.addWidget(self.import_button)
        second_row.addWidget(self.export_button)
        self.cloud_upload_button = QPushButton("上传所选")
        self.cloud_upload_all_button = QPushButton("上传全部")
        self.cloud_download_button = QPushButton("云端下载")
        if self.account_manager and self.account_manager.session_credentials()["isSuperAdmin"]:
            second_row.addWidget(self.cloud_upload_button)
            second_row.addWidget(self.cloud_upload_all_button)
            second_row.addWidget(self.cloud_download_button)
        else:
            self.cloud_upload_button.hide()
            self.cloud_upload_all_button.hide()
            self.cloud_download_button.hide()
        second_row.addStretch(1)
        close_button = QPushButton("完成")
        close_button.clicked.connect(self.accept)
        second_row.addWidget(close_button)
        layout.addLayout(second_row)

        self.create_button.clicked.connect(self._create)
        self.edit_button.clicked.connect(self._edit)
        self.rename_button.clicked.connect(self._rename)
        self.delete_button.clicked.connect(self._delete)
        self.import_button.clicked.connect(self._import)
        self.export_button.clicked.connect(self._export)
        self.cloud_upload_button.clicked.connect(self._cloud_upload)
        self.cloud_upload_all_button.clicked.connect(self._cloud_upload_all)
        self.cloud_download_button.clicked.connect(self._cloud_download)
        self._reload()

    def _reload(self, selected_name=None):
        self.list_widget.clear()
        for topology in self.maps:
            self.list_widget.addItem(
                f"{topology.map_name}  ·  平台 {len(topology.platforms)}"
                f" / 绳索 {len(topology.ropes)} / 传送点 {len(topology.portals)}"
            )
        if self.maps:
            index = next(
                (
                    index
                    for index, item in enumerate(self.maps)
                    if item.map_name == selected_name
                ),
                0,
            )
            self.list_widget.setCurrentRow(index)

    def _selected_index(self):
        index = self.list_widget.currentRow()
        return index if 0 <= index < len(self.maps) else None

    def _create(self):
        if self.current_image is None:
            QMessageBox.information(self, "提示", "请先启动监控并取得当前小地图画面")
            return
        name, ok = QInputDialog.getText(self, "创建地图", "地图名称")
        name = name.strip()
        if not ok or not name:
            return
        if any(item.map_name.casefold() == name.casefold() for item in self.maps):
            QMessageBox.warning(self, "名称重复", "已经存在同名地图")
            return
        height, width = self.current_image.shape[:2]
        topology = MapTopology(
            name,
            width,
            height,
            visual_signature=MinimapVisualMatcher.signature(self.current_image),
            reference_bgr=self.current_image.tobytes(),
        )
        editor = MapEditorDialog(
            topology,
            self.maps + [topology],
            self.hwnd,
            self.window_selector,
            self,
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.maps.append(editor.topology)
            self.store.save(self.maps)
            self._reload(name)

    def _edit(self, *_):
        index = self._selected_index()
        if index is None:
            return
        editor = MapEditorDialog(
            self.maps[index],
            self.maps,
            self.hwnd,
            self.window_selector,
            self,
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.maps[index] = editor.topology
            self.store.save(self.maps)
            self._reload(editor.topology.map_name)

    def _rename(self):
        index = self._selected_index()
        if index is None:
            return
        current = self.maps[index].map_name
        name, ok = QInputDialog.getText(self, "重命名地图", "地图名称", text=current)
        name = name.strip()
        if not ok or not name or name == current:
            return
        if any(i != index and item.map_name.casefold() == name.casefold() for i, item in enumerate(self.maps)):
            QMessageBox.warning(self, "名称重复", "已经存在同名地图")
            return
        for topology in self.maps:
            for portal in topology.portals:
                if portal.destination_map_name == current:
                    portal.destination_map_name = name
        self.maps[index].map_name = name
        self.store.save(self.maps)
        self._reload(name)

    def _delete(self):
        index = self._selected_index()
        if index is None:
            return
        name = self.maps[index].map_name
        if QMessageBox.question(self, "删除地图", f"确定删除“{name}”吗？") != QMessageBox.StandardButton.Yes:
            return
        self.maps.pop(index)
        self.store.save(self.maps) if self.maps else self.store.path.unlink(missing_ok=True)
        self._reload()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入地图",
            "",
            "AutoBuff 地图 (*.json);;所有文件 (*)",
        )
        if not path:
            return
        try:
            self.maps, added, replaced = self.store.import_file(path)
            self._reload()
            QMessageBox.information(self, "导入完成", f"新增 {added} 张，替换 {replaced} 张")
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "导入失败", str(error))

    def _export(self):
        if not self.maps:
            QMessageBox.information(self, "提示", "当前没有可导出的地图")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出地图",
            "autobuff-maps.json",
            "AutoBuff 地图 (*.json)",
        )
        if path:
            try:
                self.store.export_file(path, self.maps)
            except OSError as error:
                QMessageBox.warning(self, "导出失败", str(error))

    def _cloud_upload(self):
        index = self._selected_index()
        if index is None:
            QMessageBox.information(self, "提示", "请先选择要上传的地图")
            return
        self._upload_maps([self.maps[index]])

    def _cloud_upload_all(self):
        if not self.maps:
            QMessageBox.information(self, "提示", "当前没有可上传的地图")
            return
        self._upload_maps(self.maps)

    def _upload_maps(self, maps):
        try:
            count = self.account_manager.upload_cloud_maps(maps)
            QMessageBox.information(self, "上传完成", f"已上传 {count} 张地图到云端")
        except Exception as error:
            QMessageBox.warning(self, "上传失败", str(error))

    def _cloud_download(self):
        try:
            items = self.account_manager.list_cloud_maps()
            if not items:
                QMessageBox.information(self, "云端地图", "云端还没有地图")
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("云端地图")
            dialog.resize(480, 360)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("选择要按需下载的地图"))
            cloud_list = QListWidget()
            for item in items:
                cloud_list.addItem(
                    f"{item['name']}  ·  上传者：{item.get('uploadedBy', '')}"
                )
            cloud_list.setCurrentRow(0)
            cloud_list.itemDoubleClicked.connect(lambda _: dialog.accept())
            layout.addWidget(cloud_list)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Cancel
                | QDialogButtonBox.StandardButton.Ok
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            selected_index = cloud_list.currentRow()
            if not 0 <= selected_index < len(items):
                return
            downloaded = self.account_manager.download_cloud_map(
                items[selected_index]["id"]
            )
            self.maps, added, replaced = MapTransferService.merge(downloaded, self.maps)
            self.store.save(self.maps)
            self._reload(downloaded[0].map_name if downloaded else None)
            QMessageBox.information(
                self, "下载完成", f"新增 {added} 张，替换 {replaced} 张"
            )
        except Exception as error:
            QMessageBox.warning(self, "下载失败", str(error))
