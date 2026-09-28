"""Opt-in MuMu-0 end-to-end smoke check; changes the current in-game channel."""

import subprocess
import sys
import time

import cv2
import numpy as np

from detection.emulator_frame_analysis import analyze_emulator_frame
from utils.mumu_adb import resolve_adb_path
from utils.mumu_manager import list_mumu_instances
from workers.mumu_smoke_worker import MumuSmokeWorker


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m tests.manual_mumu_smoke FRIEND_NAME")
    serial = "127.0.0.1:16384"
    instance = next(item for item in list_mumu_instances() if item["vm_index"] == "0")
    if instance.get("adb_serial") != serial:
        raise RuntimeError("MuMu-0 serial changed")
    hwnd = int(instance["render_wnd"], 16)
    adb = resolve_adb_path()

    def snapshot():
        image = subprocess.check_output(
            [adb, "-s", serial, "exec-out", "screencap", "-p"], timeout=15,
        )
        native = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        frame = cv2.resize(native, (960, 540), interpolation=cv2.INTER_AREA)
        analysis = analyze_emulator_frame(frame)
        return {"frame": frame, "frame_age_ms": 0,
                "analysis": analysis, "analysis_age_ms": 0}

    first = snapshot()
    rect = first["analysis"].minimap_rect
    position = first["analysis"].player_position
    if rect is None or position is None or rect != (3, 65, 135, 80):
        raise RuntimeError(f"MuMu-0 has no full minimap: rect={rect} pos={position}")
    print(f"start minimap: {position}, region: {rect}", flush=True)
    finished = []
    worker = MumuSmokeWorker(
        serial, adb, snapshot, lambda: hwnd,
        status_callback=lambda message: print(message, flush=True),
        finished_callback=lambda success: finished.append(success),
    )
    worker.start({"anchor": (position[0] + 5, position[1]), "half_width": 3,
                  "half_height": 3, "jump_key": "Alt", "smoke_key": "Shift",
                  "friend_name": sys.argv[1]})
    try:
        while not finished:
            time.sleep(0.2)
        if not finished[0]:
            raise RuntimeError("smoke flow did not complete successfully")
        print("smoke flow complete", flush=True)
    finally:
        worker.stop()


if __name__ == "__main__":
    main()
