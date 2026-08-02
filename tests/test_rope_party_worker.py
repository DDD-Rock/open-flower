import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "utils" / "rope_party.py"
spec = importlib.util.spec_from_file_location("rope_party_test_helper", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
build_rope_party_commands = module.build_rope_party_commands


class RopePartyWorkerTests(unittest.TestCase):
    def test_first_creation_leader_builds_commands_in_order(self):
        self.assertEqual(
            build_rope_party_commands(True, True, ["队员甲", "队员乙"]),
            ["/退出队伍", "/建立队伍", "/邀请组队 队员甲", "/邀请组队 队员乙"],
        )

    def test_member_or_team_modification_does_not_recreate_party(self):
        self.assertEqual(build_rope_party_commands(False, True, ["队员"]), [])
        self.assertEqual(build_rope_party_commands(True, False, ["队员"]), [])


if __name__ == "__main__":
    unittest.main()
