"""挂绳组队的纯协议辅助函数。"""


def build_rope_party_commands(is_leader: bool, first_creation: bool, role_names: list[str]) -> list[str]:
    if not is_leader or not first_creation:
        return []
    return ["/退出隊伍", "/建立隊伍", *[f"/邀请组队 {name.strip()}" for name in role_names if name.strip()]]


def build_remove_member_command(role_name: str) -> str:
    return f"/踢出隊伍 {role_name.strip()}"
