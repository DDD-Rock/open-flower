"""
键盘按键名称规范化。

界面使用大写字母展示按键，但 Windows 下 pynput 会把大写字符当作
需要文本输入的 Unicode 字符发送。部分游戏不会响应这种事件，因此在
发送单个英文字母前统一转换为小写，让输入库使用物理虚拟键码。
"""


def normalize_key_name(key: str) -> str:
    """将单个大写英文字母转换为对应的小写物理按键名称。"""
    if isinstance(key, str) and len(key) == 1 and "A" <= key <= "Z":
        return key.lower()
    return key
