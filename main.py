"""
枫灵 MapleKeeper - 自动技能释放工具
程序入口文件
"""

import sys
import os

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

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from ui.main_window import MainWindow
from config import APP_NAME


def main():
    """主函数"""
    # 设置高DPI缩放策略
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

