"""
Buff配置数据模型
定义Buff配置的数据结构
"""


class BuffConfig:
    """Buff配置类"""
    
    def __init__(self, enabled: bool = False, key: str = "", duration: float = 0.0):
        """
        初始化Buff配置
        
        参数:
            enabled: 是否启用
            key: Buff按键（如 'S', 'T' 等）
            duration: Buff持续时间（秒）
        """
        self.enabled = enabled
        self.key = key
        self.duration = duration
    
    def __str__(self):
        """返回Buff配置的字符串表示"""
        status = "启用" if self.enabled else "禁用"
        return f"{status} - 按键: {self.key}, 持续时间: {self.duration}秒"
    
    def to_dict(self):
        """转换为字典格式（用于保存配置）"""
        return {
            'enabled': self.enabled,
            'key': self.key,
            'duration': self.duration
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """从字典创建Buff配置（用于加载配置）"""
        return cls(
            enabled=data.get('enabled', False),
            key=data.get('key', ''),
            duration=data.get('duration', 0.0)
        )

