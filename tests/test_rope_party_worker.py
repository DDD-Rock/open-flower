import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "utils" / "rope_party.py"
spec = importlib.util.spec_from_file_location("rope_party_test_helper", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
build_rope_party_commands = module.build_rope_party_commands
build_remove_member_command = module.build_remove_member_command


class RopePartyWorkerTests(unittest.TestCase):
    def test_first_creation_leader_builds_commands_in_order(self):
        self.assertEqual(
            build_rope_party_commands(True, True, ["队员甲", "队员乙"]),
            ["/退出隊伍", "/建立隊伍", "/邀请组队 队员甲", "/邀请组队 队员乙"],
        )

    def test_member_or_team_modification_does_not_recreate_party(self):
        self.assertEqual(build_rope_party_commands(False, True, ["队员"]), [])
        self.assertEqual(build_rope_party_commands(True, False, ["队员"]), [])

    def test_remove_member_command_uses_traditional_game_command(self):
        self.assertEqual(build_remove_member_command(" 队员甲 "), "/踢出隊伍 队员甲")


if __name__ == "__main__":
    unittest.main()
