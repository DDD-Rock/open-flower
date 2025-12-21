"""
游戏配置数据模型
定义游戏相关的配置（分辨率、快捷键等）
"""


class GameConfig:
    """游戏配置类"""
    
    def __init__(self):
        """初始化游戏配置"""
        # 游戏分辨率
        self.resolution_width = 0
        self.resolution_height = 0
        
        # 快捷键
        self.backpack_hotkey = "B"  # 背包快捷键
        self.ability_hotkey = "Y"   # 能力值快捷键
        self.skill_hotkey = "K"     # 技能快捷键
        
        # 速度阈值
        self.speed_threshold = 1400
        
        # 随机行为
        self.random_behavior_enabled = False
        self.random_behavior_value = 20
    
    def set_resolution(self, width: int, height: int):
        """设置游戏分辨率"""
        self.resolution_width = width
        self.resolution_height = height
    
    def get_resolution_str(self) -> str:
        """获取分辨率字符串"""
        if self.resolution_width > 0 and self.resolution_height > 0:
            return f"{self.resolution_width}, {self.resolution_height}"
        return "未设置"
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'resolution_width': self.resolution_width,
            'resolution_height': self.resolution_height,
            'backpack_hotkey': self.backpack_hotkey,
            'ability_hotkey': self.ability_hotkey,
            'skill_hotkey': self.skill_hotkey,
            'speed_threshold': self.speed_threshold,
            'random_behavior_enabled': self.random_behavior_enabled,
            'random_behavior_value': self.random_behavior_value
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """从字典创建游戏配置"""
        config = cls()
        config.resolution_width = data.get('resolution_width', 0)
        config.resolution_height = data.get('resolution_height', 0)
        config.backpack_hotkey = data.get('backpack_hotkey', 'B')
        config.ability_hotkey = data.get('ability_hotkey', 'Y')
        config.skill_hotkey = data.get('skill_hotkey', 'K')
        config.speed_threshold = data.get('speed_threshold', 1400)
        config.random_behavior_enabled = data.get('random_behavior_enabled', False)
        config.random_behavior_value = data.get('random_behavior_value', 20)
        return config

