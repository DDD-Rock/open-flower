"""
技能配置数据模型
定义技能配置的数据结构
"""


class SkillConfig:
    """技能配置类"""
    
    def __init__(self, key: str, interval: float, random_delay: float):
        """
        初始化技能配置
        
        参数:
            key: 技能按键（如 '1', '2', 'F1' 等）
            interval: 释放间隔（秒）
            random_delay: 随机延迟最大秒数
        """
        self.key = key
        self.interval = interval
        self.random_delay = random_delay
    
    def __str__(self):
        """返回技能配置的字符串表示"""
        return f"按键: {self.key}, 间隔: {self.interval}秒, 随机延迟: {self.random_delay}秒"
    
    def __repr__(self):
        """返回技能配置的详细表示"""
        return f"SkillConfig(key='{self.key}', interval={self.interval}, random_delay={self.random_delay})"
    
    def to_dict(self):
        """转换为字典格式（用于保存配置）"""
        return {
            'key': self.key,
            'interval': self.interval,
            'random_delay': self.random_delay
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """从字典创建技能配置（用于加载配置）"""
        return cls(
            key=data['key'],
            interval=data['interval'],
            random_delay=data['random_delay']
        )

