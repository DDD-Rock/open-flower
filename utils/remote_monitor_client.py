"""Windows 客户端到监控服务的持久 WebSocket 发布通道。"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Callable, Optional
from urllib.parse import quote, urlsplit, urlunsplit

try:
    import websocket
except ImportError:
    websocket = None

from models.map_topology import MapTopology, NormalizedMapPoint


class RemoteMonitorClient:
    MAX_MESSAGE_BYTES = 16 * 1024
    FRAME_INTERVAL_SECONDS = 0.05
    STATE_HEARTBEAT_SECONDS = 3.0
    SEND_PRIORITY = ("verification", "rune", "zone", "frame", "exp")

    def __init__(
        self,
        account_manager,
        on_command: Optional[Callable[[dict], None]] = None,
        on_identity: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ):
        self.account_manager = account_manager
        self.on_command = on_command
        self.on_identity = on_identity
        self.on_status = on_status
        self._enabled = False
        self._connected = False
        self._socket_app = None
        self._connection_thread = None
        self._sender_thread = None
        self._reconnect_attempt = 0
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        self._condition = threading.Condition()
        self._control_messages = deque(maxlen=4)
        self._latest_messages = {}
        self._last_frame_at = 0.0
        self._last_map_id = None
        self._last_state = {"mode": "dead", "running": False}
        self._last_boolean_state = {"verification": None, "rune": None, "zone": None}
        self._last_boolean_sent_at = {"verification": 0.0, "rune": 0.0, "zone": 0.0}

    @property
    def is_connected(self):
        return self._connected

    def start(self):
        if websocket is None:
            self._notify("缺少 websocket-client，远程监控连接未启动")
            return False
        credentials = self.account_manager.session_credentials()
        if not credentials["accessToken"] or not credentials["clientId"]:
            self._notify("登录信息不完整，远程监控连接未启动")
            return False
        if self._enabled:
            return True
        self._enabled = True
        self._connection_thread = threading.Thread(
            target=self._connection_loop,
            name="RemoteMonitorConnection",
            daemon=True,
        )
        self._connection_thread.start()
        return True

    def stop(self, send_offline: bool = False):
        if send_offline and self._connected:
            self.publish_status(False, "本机监控已停止")
            time.sleep(0.05)
        self._enabled = False
        with self._condition:
            self._condition.notify_all()
        socket_app = self._socket_app
        self._socket_app = None
        if socket_app is not None:
            try:
                socket_app.close()
            except Exception:
                pass
        self._connected = False
        self._reset_send_queue()

    def publish_client_state(self, mode: str, running: bool):
        self._last_state = {"mode": mode, "running": bool(running)}
        self._enqueue("client_state", self._last_state)

    def publish_status(self, online: bool, message: str):
        self._enqueue("status", {"online": bool(online), "message": message})

    def publish_team_joined(self, team_id: int, role_name: str):
        if int(team_id) > 0 and role_name.strip():
            self._enqueue("team_joined", {"teamId": int(team_id), "roleName": role_name.strip()})

    def publish_map(self, topology: MapTopology, content_size: tuple[int, int]):
        map_id = topology.map_name or f"map-{content_size[0]}x{content_size[1]}"
        if self._last_map_id == map_id:
            return
        width, height = content_size
        payload = {
            "id": map_id,
            "name": topology.map_name or "未命名地图",
            "aspectRatio": width / height if height > 0 else 1,
            "platforms": [item.to_dict() for item in topology.platforms],
            "ropes": [item.to_dict() for item in topology.ropes],
            "portals": [
                {"id": item.id, "point": item.point.to_dict(), "type": item.type}
                for item in topology.portals
            ],
        }
        if self._enqueue("map", payload):
            self._last_map_id = map_id

    def publish_frame(
        self,
        player,
        teammates,
        others,
        content_size: tuple[int, int],
        source_fps: float,
        captured_at: Optional[int] = None,
    ):
        now = time.monotonic()
        if now - self._last_frame_at < self.FRAME_INTERVAL_SECONDS:
            return
        self._last_frame_at = now

        def normalize(point):
            if point is None:
                return None
            return NormalizedMapPoint.from_pixel(point, content_size).to_dict()

        self._enqueue(
            "frame",
            {
                "player": normalize(player),
                "teammates": [normalize(point) for point in teammates],
                "others": [normalize(point) for point in others],
                "sourceFPS": max(0.0, float(source_fps)),
                "capturedAt": captured_at or int(time.time() * 1000),
            },
        )

    def publish_exp(self, reading, status: str):
        self._enqueue(
            "exp",
            {
                "currentEXP": reading.current_exp if reading else None,
                "percent": reading.percent if reading else None,
                "confidence": reading.confidence if reading else None,
                "status": status,
                "recognizedAt": int(time.time() * 1000),
            },
        )

    def publish_rune(self, detected: bool, confidence: Optional[float] = None):
        if not self._should_publish_boolean("rune", detected):
            return
        self._enqueue(
            "rune",
            {
                "detected": bool(detected),
                "confidence": float(confidence) if detected and confidence is not None else None,
                "detectedAt": int(time.time() * 1000),
            },
        )

    def publish_verification(self, detected: bool, confidence: Optional[float] = None):
        if not self._should_publish_boolean("verification", detected):
            return
        self._enqueue(
            "verification",
            {
                "detected": bool(detected),
                "confidence": float(confidence) if detected and confidence is not None else None,
                "detectedAt": int(time.time() * 1000),
            },
        )

    def publish_zone(self, outside: bool, zone=None):
        if not self._should_publish_boolean("zone", outside):
            return
        rect = None
        if zone is not None:
            x, y, width, height = zone.normalized_rect
            rect = {"x": x, "y": y, "width": width, "height": height}
        self._enqueue(
            "zone",
            {
                "outside": bool(outside),
                "rect": rect,
                "detectedAt": int(time.time() * 1000),
            },
        )

    def _should_publish_boolean(self, kind: str, state: bool):
        now = time.monotonic()
        previous = self._last_boolean_state[kind]
        if previous == state and now - self._last_boolean_sent_at[kind] < self.STATE_HEARTBEAT_SECONDS:
            return False
        self._last_boolean_state[kind] = state
        self._last_boolean_sent_at[kind] = now
        return True

    def _connection_loop(self):
        while self._enabled:
            credentials = self.account_manager.session_credentials()
            token, client_id = credentials["accessToken"], credentials["clientId"]
            if not token or not client_id:
                return
            url = self._websocket_url(credentials["serverBaseURL"], client_id)
            app = websocket.WebSocketApp(
                url,
                header=[f"Authorization: Bearer {token}"],
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=lambda _app, error: self._notify(f"远程监控连接异常：{error}"),
                on_close=self._on_close,
            )
            self._socket_app = app
            try:
                app.run_forever(ping_interval=0)
            except Exception as error:
                self._notify(f"远程监控连接异常：{error}")
            self._connected = False
            if not self._enabled:
                break
            delay = min(15, 2 ** min(self._reconnect_attempt, 4))
            self._reconnect_attempt += 1
            self._notify(f"远程监控已断开，{delay} 秒后重连")
            deadline = time.monotonic() + delay
            while self._enabled and time.monotonic() < deadline:
                time.sleep(0.1)

    def _on_open(self, app):
        if not self._enabled or app is not self._socket_app:
            return
        self._connected = True
        with self._sequence_lock:
            self._sequence = 0
        self._last_map_id = None
        self._reset_send_queue()
        self._sender_thread = threading.Thread(
            target=self._sender_loop,
            args=(app,),
            name="RemoteMonitorSender",
            daemon=True,
        )
        self._sender_thread.start()
        self.publish_status(True, "Windows 客户端已连接")
        self.publish_client_state(**self._last_state)
        self._notify("远程监控已连接")

    def _on_message(self, app, message):
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return
        if payload.get("type") == "identity":
            self._reconnect_attempt = 0
            name = str(payload.get("name") or "")
            if name:
                self.account_manager.save_client_name(name)
                if self.on_identity:
                    self.on_identity(name)
        elif payload.get("type") == "command":
            action = str(payload.get("action") or "")
            if action in {"start", "stop", "configure_rope_party", "disband_rope_party"} and self.on_command:
                self.on_command(payload)

    def _on_close(self, app, _status_code, _message):
        if app is self._socket_app:
            self._connected = False
            with self._condition:
                self._condition.notify_all()

    def _enqueue(self, message_type: str, payload: dict) -> bool:
        if not self._enabled:
            return False
        encoded = self._encode(message_type, payload)
        if len(encoded) > self.MAX_MESSAGE_BYTES:
            self._notify(f"{message_type} 消息超过 16KB，已停止发送该条数据")
            return False
        with self._condition:
            if message_type in {"frame", "exp", "verification", "rune", "zone"}:
                self._latest_messages[message_type] = encoded
            else:
                self._control_messages.append(encoded)
            self._condition.notify()
        return True

    def _encode(self, message_type: str, payload: dict) -> str:
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        return json.dumps(
            {"type": message_type, "sequence": sequence, "payload": payload},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _sender_loop(self, app):
        while self._enabled and self._connected and app is self._socket_app:
            with self._condition:
                if self._control_messages:
                    message = self._control_messages.popleft()
                else:
                    message = next(
                        (
                            self._latest_messages.pop(kind)
                            for kind in self.SEND_PRIORITY
                            if kind in self._latest_messages
                        ),
                        None,
                    )
                if message is None:
                    self._condition.wait(timeout=1)
                    continue
            try:
                app.send(message)
            except Exception:
                try:
                    app.close()
                except Exception:
                    pass
                return

    def _reset_send_queue(self):
        with self._condition:
            self._control_messages.clear()
            self._latest_messages.clear()
            self._last_boolean_state = {"verification": None, "rune": None, "zone": None}
            self._last_boolean_sent_at = {
                "verification": 0.0,
                "rune": 0.0,
                "zone": 0.0,
            }
            self._condition.notify_all()

    @staticmethod
    def _websocket_url(base_url: str, client_id: str) -> str:
        parsed = urlsplit(base_url.rstrip("/"))
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunsplit((scheme, parsed.netloc, "/ws/device", f"client_id={quote(client_id)}", ""))

    def _notify(self, message: str):
        if self.on_status:
            self.on_status(message)
