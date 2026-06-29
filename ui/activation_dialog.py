"""Activation dialog shown before the main window."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from config import APP_NAME
from utils.license_manager import LicenseManager


class ActivationDialog(QDialog):
    def __init__(self, license_manager: LicenseManager, parent=None):
        super().__init__(parent)
        self.license_manager = license_manager
        self.setWindowTitle(f"激活 {APP_NAME}")
        self.setFixedSize(420, 250)
        self.setModal(True)
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("激活 AutoBuff")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:20px;font-weight:700;color:#171E30;")
        root.addWidget(title)

        machine_label = QLabel("机器码")
        machine_label.setStyleSheet("color:#5F6878;font-weight:600;")
        root.addWidget(machine_label)

        machine_row = QHBoxLayout()
        self.machine_code_input = QLineEdit(self.license_manager.current_machine_code())
        self.machine_code_input.setReadOnly(True)
        self.machine_code_input.setStyleSheet("font-family:Consolas, monospace;")
        machine_row.addWidget(self.machine_code_input, 1)

        copy_button = QPushButton("复制")
        copy_button.clicked.connect(self._copy_machine_code)
        machine_row.addWidget(copy_button)
        root.addLayout(machine_row)

        code_label = QLabel("激活码")
        code_label.setStyleSheet("color:#5F6878;font-weight:600;")
        root.addWidget(code_label)

        self.activation_code_input = QLineEdit()
        self.activation_code_input.setPlaceholderText("粘贴激活码")
        self.activation_code_input.setStyleSheet("font-family:Consolas, monospace;")
        self.activation_code_input.returnPressed.connect(self._activate)
        root.addWidget(self.activation_code_input)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        exit_button = QPushButton("退出")
        exit_button.clicked.connect(self.reject)
        button_row.addWidget(exit_button)

        activate_button = QPushButton("激活")
        activate_button.clicked.connect(self._activate)
        activate_button.setDefault(True)
        button_row.addWidget(activate_button)
        root.addLayout(button_row)

        self.setStyleSheet(
            """
            QDialog { background: #F4F7FC; }
            QLabel { color: #171E30; font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; }
            QLineEdit {
                background: white;
                color: #171E30;
                border: 1px solid #D9E0EB;
                border-radius: 6px;
                padding: 6px 8px;
                min-height: 22px;
            }
            QPushButton {
                background: white;
                color: #171E30;
                border: 1px solid #DDE3EE;
                border-radius: 8px;
                padding: 6px 14px;
            }
            QPushButton:hover { background: #F2F7FF; border-color: #7FB1FF; }
            QPushButton:default { background: #1370F7; color: white; border: none; }
            """
        )

    def _copy_machine_code(self):
        QApplication.clipboard().setText(self.machine_code_input.text())

    def _activate(self):
        if self.license_manager.save_activation_code(self.activation_code_input.text()):
            self.accept()
            return
        QMessageBox.warning(self, "激活失败", "激活码不正确")
