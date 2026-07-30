"""YzY - Auto Buff Windows entry point."""

import sys
import os

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

from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from ui.login_dialog import LoginDialog
from ui.modern_main_window import MainWindow
from config import APP_NAME
from utils.account_manager import AccountManager


def resource_path(relative_path: str) -> str:
    """返回开发环境或 PyInstaller 打包环境中的资源路径。"""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def main():
    """主函数"""
    # 设置高DPI缩放策略
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    app_icon = QIcon(resource_path(os.path.join("resources", "app_icon.ico")))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    account_manager = AccountManager()
    if account_manager.restore() is None:
        login_dialog = LoginDialog(account_manager)
        if not app_icon.isNull():
            login_dialog.setWindowIcon(app_icon)
        if login_dialog.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)

    window = MainWindow()
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
