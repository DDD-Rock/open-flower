"""
设置管理器 - 使用 INI 文件保存和加载 UI 配置
"""

import os
import configparser
import re
import sys
from typing import Optional, Tuple

from config import DEFAULT_BUFF_SLOT_COUNT, MAX_BUFF_SLOT_COUNT


class SettingsManager:
    """设置管理器，负责保存和加载用户配置"""
    
    DEFAULT_CONFIG_PATH = "settings.ini"
    
    def __init__(self, config_path: Optional[str] = None):
        default_path = self.DEFAULT_CONFIG_PATH
        if os.name == "nt":
            app_data = os.environ.get("APPDATA") or os.path.expanduser("~")
            settings_dir = os.path.join(app_data, "YzY-Auto-Buff")
            os.makedirs(settings_dir, exist_ok=True)
            default_path = os.path.join(settings_dir, self.DEFAULT_CONFIG_PATH)
        self.config_path = (
            config_path
            or os.environ.get("AUTOBUFF_SETTINGS_PATH")
            or default_path
        )
        self.legacy_config_path = os.path.join(
            os.path.dirname(os.path.abspath(sys.argv[0])),
            self.DEFAULT_CONFIG_PATH,
        )
        self.config = configparser.ConfigParser()
    
    def save_settings(self, 
                      buffs: list,
                      return_to_market: bool = False,
                      jump_key: str = "Alt",
                      sit_chair_enabled: bool = False,
                      chair_key: str = "=",
                      random_behavior_enabled: bool = True,
                      random_behavior_value: int = 20,
                      movement_mode: str = "none",
                      pre_skill_move_mode: str = "right_only",
                      manual_portal_pos: Optional[Tuple[int, int]] = None):
        """
        保存设置到 INI 文件
        
        Args:
            buffs: BuffConfig 列表，包含 enabled, key, duration 属性
            return_to_market: 是否释放后回到市场
            jump_key: 跳跃键
            sit_chair_enabled: 是否空闲时坐椅子
            chair_key: 椅子按键
            random_behavior_enabled: 是否启用随机提前释放
            random_behavior_value: 随机提前释放秒数
            movement_mode: 移动模式 - "none"(原地不动), "right"(向右走开buff), "left"(向左走开buff)
            pre_skill_move_mode: 死花出市场后移动模式
            manual_portal_pos: 手动传送门小地图坐标，None 表示自动识别
        """
        # 清空旧配置
        self.config.clear()
        
        # 保存通用设置
        self.config["General"] = {
            "return_to_market": str(return_to_market),
            "jump_key": jump_key,
            "sit_chair_enabled": str(sit_chair_enabled),
            "chair_key": chair_key,
            "random_behavior_enabled": str(random_behavior_enabled),
            "random_behavior_value": str(random_behavior_value),
            "movement_mode": movement_mode,
            "pre_skill_move_mode": pre_skill_move_mode,
            "manual_portal_x": "" if manual_portal_pos is None else str(manual_portal_pos[0]),
            "manual_portal_y": "" if manual_portal_pos is None else str(manual_portal_pos[1]),
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
            parent = os.path.dirname(os.path.abspath(self.config_path))
            os.makedirs(parent, exist_ok=True)
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
        load_path = self.config_path
        if (
            not os.path.exists(load_path)
            and os.name == "nt"
            and os.path.exists(self.legacy_config_path)
        ):
            load_path = self.legacy_config_path
        if not os.path.exists(load_path):
            print(f"配置文件不存在: {self.config_path}")
            return None
        
        try:
            self.config.read(load_path, encoding='utf-8')
            
            settings = {
                "return_to_market": self.config.getboolean("General", "return_to_market", fallback=True),
                "jump_key": self.config.get("General", "jump_key", fallback="Alt"),
                "sit_chair_enabled": self.config.getboolean("General", "sit_chair_enabled", fallback=False),
                "chair_key": self.config.get("General", "chair_key", fallback="="),
                "random_behavior_enabled": self.config.getboolean("General", "random_behavior_enabled", fallback=True),
                "random_behavior_value": self.config.getint("General", "random_behavior_value", fallback=20),
                "movement_mode": self.config.get("General", "movement_mode", fallback="none"),
                "pre_skill_move_mode": self.config.get("General", "pre_skill_move_mode", fallback="right_only"),
                "manual_portal_pos": self._load_manual_portal_pos(),
                "buffs": []
            }
            
            sections = []
            for section in self.config.sections():
                match = re.fullmatch(r"Buff(\d+)", section, re.IGNORECASE)
                if match:
                    sections.append((int(match.group(1)), section))
            sections.sort()

            # 兼容旧版固定六槽配置：保留实际配置过的附加槽，
            # 但把尾部全空槽折叠回默认三个。
            slot_count = DEFAULT_BUFF_SLOT_COUNT
            for number, section in sections:
                if number > MAX_BUFF_SLOT_COUNT:
                    continue
                enabled = self.config.getboolean(section, "enabled", fallback=False)
                key = self.config.get(section, "key", fallback="").strip()
                duration = self.config.getfloat(section, "duration", fallback=0)
                if number <= DEFAULT_BUFF_SLOT_COUNT or enabled or key or duration > 0:
                    slot_count = max(slot_count, number)

            for i in range(slot_count):
                section = f"Buff{i + 1}"
                if self.config.has_section(section):
                    buff_config = {
                        "enabled": self.config.getboolean(section, "enabled", fallback=False),
                        "key": self.config.get(section, "key", fallback=""),
                        "duration": self.config.getfloat(section, "duration", fallback=0)
                    }
                    settings["buffs"].append(buff_config)
                else:
                    settings["buffs"].append({"enabled": False, "key": "", "duration": 0})
            
            print(f"✅ 设置已从 {load_path} 加载")
            return settings
            
        except Exception as e:
            print(f"❌ 加载设置失败: {e}")
            return None

    def _load_manual_portal_pos(self):
        x = self.config.get("General", "manual_portal_x", fallback="").strip()
        y = self.config.get("General", "manual_portal_y", fallback="").strip()
        if not x or not y:
            return None
        try:
            return (int(x), int(y))
        except ValueError:
            return None
