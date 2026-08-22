"""YzY - Auto Buff Windows entry point."""

import sys
import os
import threading

# Windows 控制台默认 GBK，避免 print 含 emoji 时启动崩溃
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

# 设置DPI感知（在创建QApplication之前）
if sys.platform == 'win32':
    try:
        # 尝试设置DPI感知，避免警告
        import ctypes
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        # 如果失败，尝试旧的方法
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon

from ui.login_dialog import LoginDialog
from ui.modern_main_window import MainWindow
from config import APP_NAME
from utils.account_manager import AccountError, AccountManager
from utils.remote_monitor_client import RemoteMonitorClient


def resource_path(relative_path: str) -> str:
    """返回开发环境或 PyInstaller 打包环境中的资源路径。"""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class ClientAuthorizationWatcher(QObject):
    authorization_lost = pyqtSignal(str)
    authorization_updated = pyqtSignal(object)

    def __init__(self, account_manager: AccountManager, parent=None):
        super().__init__(parent)
        self.account_manager = account_manager
        self._checking = False
        self._active = False
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self._check)

    def start(self):
        self._active = True
        self.timer.start()

    def stop(self):
        self._active = False
        self.timer.stop()

    def _check(self):
        if self._checking:
            return
        self._checking = True
        threading.Thread(target=self._run_check, daemon=True).start()

    def _run_check(self):
        try:
            authorization = self.account_manager.validate_session()
            if self._active:
                self.authorization_updated.emit(authorization)
        except AccountError as error:
            if self._active and error.code in {
                "client_unbound",
                "invalid_token",
                "account_disabled",
                "client_version_disabled",
            }:
                self.authorization_lost.emit(str(error))
        finally:
            self._checking = False


class ApplicationController(QObject):
    remote_command_received = pyqtSignal(object)
    remote_identity_received = pyqtSignal(str)
    remote_status_received = pyqtSignal(str)

    def __init__(self, app: QApplication, app_icon: QIcon):
        super().__init__()
        self.app = app
        self.app_icon = app_icon
        self.account_manager = AccountManager()
        self.remote_monitor_client = RemoteMonitorClient(
            self.account_manager,
            on_command=self.remote_command_received.emit,
            on_identity=self.remote_identity_received.emit,
            on_status=self.remote_status_received.emit,
        )
        self.window = None
        self._returning_to_login = False
        self.watcher = ClientAuthorizationWatcher(self.account_manager, self)
        self.watcher.authorization_lost.connect(self._return_to_login)
        self.watcher.authorization_updated.connect(self._apply_authorization)
        self.remote_command_received.connect(self._handle_remote_command)
        self.remote_status_received.connect(self._handle_remote_status)
        self.remote_identity_received.connect(self._handle_remote_identity)
        self.app.aboutToQuit.connect(self.remote_monitor_client.stop)

    def start(self) -> bool:
        if self.account_manager.restore() is None and not self._show_login():
            return False
        self._show_main_window()
        return True

    def _show_login(self) -> bool:
        dialog = LoginDialog(self.account_manager)
        if not self.app_icon.isNull():
            dialog.setWindowIcon(self.app_icon)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _show_main_window(self):
        credentials = self.account_manager.session_credentials()
        self.window = MainWindow(
            account_manager=self.account_manager,
            remote_monitor_client=self.remote_monitor_client,
            authorized_modes=credentials["authorizedModes"],
        )
        if not self.app_icon.isNull():
            self.window.setWindowIcon(self.app_icon)
        self.window.show()
        self.watcher.start()
        self.remote_monitor_client.start()
        self.remote_monitor_client.publish_client_state(self.window.mode, False)

    def _handle_remote_command(self, command: dict):
        action = str(command.get("action") or "")
        if action in {"unbind", "kick"}:
            default_message = (
                "当前客户端已被管理员解绑，请重新登录"
                if action == "unbind"
                else "管理员已将当前客户端踢下线"
            )
            self._return_to_login(str(command.get("reason") or default_message))
            return
        if self.window is not None:
            self.window.handle_remote_command(command)

    def _handle_remote_status(self, message: str):
        if self.window is not None:
            self.window.logger.log(message)
            self.window.update_log_display()

    def _handle_remote_identity(self, name: str):
        if self.window is not None:
            self.window.setWindowTitle(f"{APP_NAME} · {name}")

    def _apply_authorization(self, authorization: dict):
        if self.window is not None:
            self.window.apply_authorized_modes(
                authorization.get("authorizedModes") or []
            )

    def _return_to_login(self, message: str):
        if self._returning_to_login:
            return
        self._returning_to_login = True
        self.watcher.stop()
        self.remote_monitor_client.stop()
        previous_window = self.window
        if previous_window is not None:
            if getattr(previous_window, "is_worker_running", False):
                previous_window.stop_worker()
            if hasattr(previous_window, "_stop_party_invite_worker"):
                previous_window._stop_party_invite_worker()
            previous_window.hide()
        self.account_manager.logout()
        QMessageBox.warning(None, "客户端登录已失效", message)
        if self._show_login():
            self._show_main_window()
            if previous_window is not None:
                previous_window.close()
        else:
            if previous_window is not None:
                previous_window.close()
            self.app.quit()
        self._returning_to_login = False


def main():
    """主函数"""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    app_icon = QIcon(resource_path(os.path.join("resources", "app_icon.ico")))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    controller = ApplicationController(app, app_icon)
    if not controller.start():
        sys.exit(0)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
