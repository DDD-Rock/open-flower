"""Opt-in, bounded real-device test: market -> BUFF -> MENU -> market."""

import argparse
import threading
import time
from pathlib import Path

import cv2

from utils.mumu_adb import resolve_adb_path
from utils.mumu_manager import list_mumu_instances
from utils.mumu_scrcpy_stream import ScrcpyVideoStream
from workers.mumu_dead_flower_worker import MumuDeadFlowerWorker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial", help="Explicit ADB serial of the instance to control")
    parser.add_argument("keys", nargs="+", help="Existing in-game BUFF key mappings")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    instance = next(item for item in list_mumu_instances()
                    if item.get("adb_serial") == args.serial and item.get("is_android_started"))
    hwnd = int(instance["render_wnd"], 16)
    adb = resolve_adb_path()
    lock = threading.Lock()
    latest = {"frame": None, "at": 0.0, "sequence": 0}

    def on_frame(frame):
        with lock:
            latest.update(frame=frame, at=time.monotonic(), sequence=latest["sequence"] + 1)

    def snapshot():
        with lock:
            return {"frame": latest["frame"], "frame_sequence": latest["sequence"],
                    "frame_age_ms": (time.monotonic() - latest["at"]) * 1000}

    stream = ScrcpyVideoStream(args.serial, on_frame, lambda error: print(error, flush=True), adb_path=adb)
    worker = MumuDeadFlowerWorker(args.serial, adb, lambda: None, window_handle=hwnd,
                                  snapshot_provider=snapshot,
                                  status_callback=lambda message: print(message, flush=True))
    worker.update_config({"enabled": True, "random_behavior_enabled": False,
                          "buffs": [{"enabled": True, "key": key, "duration": 270}
                                    for key in args.keys]})
    output = Path("screenshots")
    output.mkdir(exist_ok=True)
    stream.start()
    due, enabled, scenes = {}, False, set()
    last_scene = None
    deadline = time.monotonic() + max(10, min(args.timeout, 180))
    try:
        while time.monotonic() < deadline:
            due, enabled, _ = worker._service_once(due, enabled, False)
            snap = snapshot()
            scene = worker.recognizer.scene(snap["frame"])
            if scene != last_scene:
                print(f"SCENE={scene} phase={worker._phase} due={due}", flush=True)
                if scene != "unknown":
                    cv2.imwrite(str(output / f"mumu_dead_cycle_{scene}.png"), snap["frame"])
                    scenes.add(scene)
                last_scene = scene
            if scene == "field" and worker._phase == "return" and due and all(value > 0 for value in due.values()):
                cv2.imwrite(str(output / "mumu_dead_cycle_cast.png"), snap["frame"])
            if (worker._phase == "locate" and scene == "market" and
                    {"field", "menu"}.issubset(scenes) and
                    len(due) == len(args.keys) and all(value > 0 for value in due.values())):
                print("PASS: left market, sent all BUFFs, opened MENU, returned to market", flush=True)
                return
            time.sleep(0.2)
        raise RuntimeError(f"Cycle timed out: phase={worker._phase}, scenes={scenes}, due={due}")
    finally:
        worker.stop()
        stream.stop()


if __name__ == "__main__":
    main()
