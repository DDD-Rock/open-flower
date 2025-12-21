"""
日志工具模块
提供日志记录功能
"""

from datetime import datetime
from typing import Optional


class Logger:
    """日志记录器"""
    
    def __init__(self):
        """初始化日志记录器"""
        self.logs = []
        self.max_logs = 1000  # 最大保存日志数量
    
    def log(self, message: str, level: str = "INFO"):
        """
        记录日志
        
        参数:
            message: 日志消息
            level: 日志级别（INFO, WARNING, ERROR等）
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}]{message}"
        self.logs.append(log_entry)
        
        # 限制日志数量
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)
        
        return log_entry
    
    def get_logs(self) -> list:
        """获取所有日志"""
        return self.logs.copy()
    
    def get_logs_text(self) -> str:
        """获取所有日志的文本形式"""
        return "\n".join(self.logs)
    
    def clear(self):
        """清空日志"""
        self.logs.clear()
    
    def get_last_log(self) -> Optional[str]:
        """获取最后一条日志"""
        if self.logs:
            return self.logs[-1]
        return None

