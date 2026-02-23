"""
设置管理器 - 使用 INI 文件保存和加载 UI 配置
"""

import os
import configparser
from typing import Optional


class SettingsManager:
    """设置管理器，负责保存和加载用户配置"""
    
    DEFAULT_CONFIG_PATH = "settings.ini"
    
    def __init__(self, config_path: str = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.config = configparser.ConfigParser()
    
    def save_settings(self, 
                      buffs: list,
                      return_to_market: bool = False,
                      manual_countdown: bool = False,
                      attack_key: str = "Ctrl",
                      jump_key: str = "Alt",
                      random_behavior_enabled: bool = True,
                      random_behavior_value: int = 20,
                      movement_mode: str = "none"):
        """
        保存设置到 INI 文件
        
        Args:
            buffs: BuffConfig 列表，包含 enabled, key, duration 属性
            return_to_market: 是否释放后回到市场
            manual_countdown: 是否需要手动打怪倒计时
            attack_key: 攻击键
            random_behavior_enabled: 是否启用随机提前释放
            random_behavior_value: 随机提前释放秒数
            movement_mode: 移动模式 - "none"(原地不动), "right"(向右走开buff), "left"(向左走开buff)
        """
        # 清空旧配置
        self.config.clear()
        
        # 保存通用设置
        self.config["General"] = {
            "return_to_market": str(return_to_market),
            "manual_countdown": str(manual_countdown),
            "attack_key": attack_key,
            "jump_key": jump_key,
            "random_behavior_enabled": str(random_behavior_enabled),
            "random_behavior_value": str(random_behavior_value),
            "movement_mode": movement_mode
        }
        
        # 保存每个 buff 配置
        for i, buff in enumerate(buffs):
            section = f"Buff{i+1}"
            self.config[section] = {
                "enabled": str(getattr(buff, 'enabled', False)),
                "key": str(getattr(buff, 'key', '')),
                "duration": str(getattr(buff, 'duration', 0))
            }
        
        # 写入文件
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                self.config.write(f)
            print(f"✅ 设置已保存到 {self.config_path}")
            return True
        except Exception as e:
            print(f"❌ 保存设置失败: {e}")
            return False
    
    def load_settings(self) -> Optional[dict]:
        """
        从 INI 文件加载设置
        
        Returns:
            设置字典，如果文件不存在或读取失败返回 None
        """
        if not os.path.exists(self.config_path):
            print(f"配置文件不存在: {self.config_path}")
            return None
        
        try:
            self.config.read(self.config_path, encoding='utf-8')
            
            settings = {
                "return_to_market": self.config.getboolean("General", "return_to_market", fallback=False),
                "manual_countdown": self.config.getboolean("General", "manual_countdown", fallback=False),
                "attack_key": self.config.get("General", "attack_key", fallback="Ctrl"),
                "jump_key": self.config.get("General", "jump_key", fallback="Alt"),
                "random_behavior_enabled": self.config.getboolean("General", "random_behavior_enabled", fallback=True),
                "random_behavior_value": self.config.getint("General", "random_behavior_value", fallback=20),
                "movement_mode": self.config.get("General", "movement_mode", fallback="none"),
                "buffs": []
            }
            
            # 加载 buff 配置
            for i in range(6):  # 最多6个buff
                section = f"Buff{i+1}"
                if self.config.has_section(section):
                    buff_config = {
                        "enabled": self.config.getboolean(section, "enabled", fallback=False),
                        "key": self.config.get(section, "key", fallback=""),
                        "duration": self.config.getfloat(section, "duration", fallback=0)
                    }
                    settings["buffs"].append(buff_config)
                else:
                    # 默认值
                    settings["buffs"].append({
                        "enabled": False,
                        "key": "",
                        "duration": 0
                    })
            
            print(f"✅ 设置已从 {self.config_path} 加载")
            return settings
            
        except Exception as e:
            print(f"❌ 加载设置失败: {e}")
            return None
