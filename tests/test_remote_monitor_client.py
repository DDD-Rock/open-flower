import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from models.map_topology import MapPlatform, MapTopology, NormalizedMapPoint

ROOT = Path(__file__).resolve().parents[1]


def load_type(module_name, relative_path, type_name):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, type_name)


AccountManager = load_type(
    "remote_test_account_manager",
    "utils/account_manager.py",
    "AccountManager",
)
RemoteMonitorClient = load_type(
    "remote_test_client",
    "utils/remote_monitor_client.py",
    "RemoteMonitorClient",
)


class RemoteMonitorClientTests(unittest.TestCase):
    def _manager(self, directory):
        manager = AccountManager(
            storage_path=str(Path(directory) / "account.json"),
            server_base_url="https://monitor.example.test",
        )
        manager._save("token", "alice", "client-id-1234", "测试电脑")
        return manager

    def test_builds_authenticated_device_url_and_protocol_envelope(self):
        with tempfile.TemporaryDirectory() as directory:
            client = RemoteMonitorClient(self._manager(directory))
            client._enabled = True

            self.assertEqual(
                client._websocket_url("https://monitor.example.test/", "client id"),
                "wss://monitor.example.test/ws/device?client_id=client%20id",
            )
            body = json.loads(client._encode("client_state", {"mode": "monitor", "running": True}))
            self.assertEqual(body["type"], "client_state")
            self.assertEqual(body["sequence"], 1)
            self.assertEqual(body["payload"]["mode"], "monitor")

    def test_frame_coordinates_are_normalized_and_coalesced(self):
        with tempfile.TemporaryDirectory() as directory:
            client = RemoteMonitorClient(self._manager(directory))
            client._enabled = True
            client._last_frame_at = -1

            client.publish_frame((50, 25), [(10, 5)], [], (100, 50), 29.5)
            encoded = client._latest_messages["frame"]
            payload = json.loads(encoded)["payload"]

            self.assertEqual(payload["player"], {"x": 0.5, "y": 0.5})
            self.assertEqual(payload["teammates"], [{"x": 0.1, "y": 0.1}])

    def test_realtime_publish_policy_prioritizes_frames_over_exp(self):
        self.assertEqual(RemoteMonitorClient.FRAME_INTERVAL_SECONDS, 0.05)
        self.assertEqual(
            RemoteMonitorClient.SEND_PRIORITY,
            ("rune", "zone", "frame", "exp"),
        )

    def test_map_payload_matches_server_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            client = RemoteMonitorClient(self._manager(directory))
            client._enabled = True
            topology = MapTopology(
                "测试地图",
                200,
                100,
                platforms=[
                    MapPlatform(
                        points=[NormalizedMapPoint(0.1, 0.5), NormalizedMapPoint(0.9, 0.5)]
                    )
                ],
            )

            client.publish_map(topology, (200, 100))
            payload = json.loads(client._control_messages[-1])["payload"]

            self.assertEqual(payload["id"], "测试地图")
            self.assertEqual(payload["aspectRatio"], 2)
            self.assertEqual(payload["platforms"][0]["points"][1]["x"], 0.9)

    def test_rope_party_command_and_join_receipt_match_server_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = []
            client = RemoteMonitorClient(self._manager(directory), on_command=commands.append)
            client._enabled = True
            client._on_message(None, json.dumps({
                "type": "command", "action": "configure_rope_party",
                "teamId": 7, "isLeader": True, "firstCreation": True,
                "roleName": "队长", "inviteRoleNames": ["队员"],
            }))
            self.assertEqual(commands[0]["teamId"], 7)

            client.publish_team_joined(7, "队长")
            envelope = json.loads(client._control_messages[-1])
            self.assertEqual(envelope["type"], "team_joined")
            self.assertEqual(envelope["payload"], {"teamId": 7, "roleName": "队长"})

            client._on_message(None, json.dumps({"type": "command", "action": "disband_rope_party", "teamId": 7}))
            self.assertEqual(commands[-1]["action"], "disband_rope_party")


if __name__ == "__main__":
    unittest.main()
