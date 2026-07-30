"""Account login dialog shown before the main window."""

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from config import APP_NAME
from utils.account_manager import AccountError, AccountManager


class LoginDialog(QDialog):
    def __init__(self, account_manager: AccountManager, parent=None):
        super().__init__(parent)
        self.account_manager = account_manager
        self.setWindowTitle(f"登录 {APP_NAME}")
        self.setMinimumWidth(400)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        title = QLabel("登录 AutoBuff")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        root.addWidget(title)

        subtitle = QLabel("使用监控网页的同一账号登录")
        subtitle.setStyleSheet("color:#6b7280;")
        root.addWidget(subtitle)

        root.addWidget(QLabel("用户名"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("请输入用户名")
        root.addWidget(self.username_input)

        root.addWidget(QLabel("密码"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("密码（至少 8 位）")
        self.password_input.returnPressed.connect(self._login)
        root.addWidget(self.password_input)

        buttons = QHBoxLayout()
        register_button = QPushButton("网页注册")
        register_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(self.account_manager.registration_url))
        )
        buttons.addWidget(register_button)
        buttons.addStretch(1)

        self.login_button = QPushButton("登录")
        self.login_button.setDefault(True)
        self.login_button.clicked.connect(self._login)
        buttons.addWidget(self.login_button)
        root.addLayout(buttons)

    def _login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            QMessageBox.warning(self, "登录失败", "请输入用户名和密码")
            return

        self.login_button.setEnabled(False)
        self.login_button.setText("正在登录…")
        try:
            self.account_manager.authenticate(username, password)
        except AccountError as error:
            QMessageBox.warning(self, "登录失败", str(error))
        else:
            self.accept()
        finally:
            self.login_button.setEnabled(True)
            self.login_button.setText("登录")
