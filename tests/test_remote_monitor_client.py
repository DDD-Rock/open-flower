import importlib.util
import json
import ssl
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
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

    def test_websocket_uses_bundled_ca_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            client = RemoteMonitorClient(self._manager(directory))
            options = client._websocket_ssl_options()

            self.assertEqual(options["cert_reqs"], ssl.CERT_REQUIRED)
            self.assertTrue(options["ca_certs"].endswith("cacert.pem"))

    def test_connection_loop_passes_ssl_options_to_websocket(self):
        calls = []

        class FakeWebSocketApp:
            def __init__(self, *_args, **_kwargs):
                pass

            def run_forever(self, **kwargs):
                calls.append(kwargs)
                client._enabled = False

        with tempfile.TemporaryDirectory() as directory:
            client = RemoteMonitorClient(self._manager(directory))
            client._enabled = True
            globals_map = RemoteMonitorClient._connection_loop.__globals__
            with mock.patch.dict(
                globals_map,
                {"websocket": SimpleNamespace(WebSocketApp=FakeWebSocketApp)},
            ):
                client._connection_loop()

        self.assertEqual(calls[0]["sslopt"], client._websocket_ssl_options())

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
            ("verification", "rune", "zone", "frame", "exp"),
        )

    def test_mouse_follow_verification_payload_matches_server_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            client = RemoteMonitorClient(self._manager(directory))
            client._enabled = True

            client.publish_verification(True, 0.91)
            envelope = json.loads(client._latest_messages["verification"])
            self.assertEqual(envelope["type"], "verification")
            self.assertTrue(envelope["payload"]["detected"])
            self.assertEqual(envelope["payload"]["confidence"], 0.91)
            self.assertGreater(envelope["payload"]["detectedAt"], 0)

            client.publish_verification(False, 0.91)
            cleared = json.loads(client._latest_messages["verification"])["payload"]
            self.assertFalse(cleared["detected"])
            self.assertIsNone(cleared["confidence"])

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

    def test_rope_party_commands_and_one_shot_events_match_server_contract(self):
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
            self.assertEqual(envelope["type"], "rope_party_progress")
            self.assertEqual(envelope["payload"]["teamId"], 7)
            self.assertEqual(envelope["payload"]["event"], "team_joined")
            self.assertIsNone(client._pending_team_joined)
            self.assertIn(envelope["payload"]["messageId"], client._pending_rope_progress)

            client.publish_rope_party_progress(7, "party_commands_finished")
            created = json.loads(client._control_messages[-1])
            self.assertEqual(created["type"], "rope_party_progress")
            self.assertEqual(created["payload"]["teamId"], 7)
            self.assertEqual(created["payload"]["event"], "party_commands_finished")
            self.assertIn("messageId", created["payload"])

            client.publish_rope_party_progress(7, "boss_joined", event_id="event-123")
            boss_joined = json.loads(client._control_messages[-1])
            self.assertEqual(boss_joined["payload"]["eventId"], "event-123")
            self.assertEqual(boss_joined["payload"]["event"], "boss_joined")
            message_id = boss_joined["payload"]["messageId"]
            client._on_message(None, json.dumps({
                "type": "command", "action": "rope_event_ack",
                "teamId": 7, "eventId": "event-123", "messageId": message_id,
            }))
            self.assertNotIn(message_id, client._pending_rope_progress)

            client._on_message(None, json.dumps({
                "type": "command", "action": "restart_party_and_buff",
                "teamId": 7, "eventId": "event-124",
            }))
            self.assertEqual(commands[-1]["action"], "restart_party_and_buff")

            client._on_message(None, json.dumps({
                "type": "command", "action": "cast_buffs",
                "teamId": 7, "eventId": "event-123",
            }))
            self.assertEqual(commands[-1]["eventId"], "event-123")

    def test_forced_logout_commands_are_forwarded_and_disable_reconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = []
            client = RemoteMonitorClient(
                self._manager(directory),
                on_command=commands.append,
            )
            client._enabled = True

            client._on_message(None, json.dumps({
                "type": "command",
                "action": "kick",
                "reason": "管理员已将当前客户端踢下线",
            }))

            self.assertFalse(client._enabled)
            self.assertEqual(commands[-1]["action"], "kick")

            client._enabled = True
            client._on_message(None, json.dumps({
                "type": "command",
                "action": "unbind",
            }))

            self.assertFalse(client._enabled)
            self.assertEqual(commands[-1]["action"], "unbind")

    def test_control_messages_are_not_silently_evicted(self):
        with tempfile.TemporaryDirectory() as directory:
            client = RemoteMonitorClient(self._manager(directory))
            client._enabled = True
            for index in range(8):
                client._enqueue("status", {"online": True, "message": str(index)})
            self.assertEqual(len(client._control_messages), 8)


if __name__ == "__main__":
    unittest.main()
