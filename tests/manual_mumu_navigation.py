"""Explicit, bounded market walk-speed measurement on a running MuMu instance."""

import argparse
import threading
import time

from utils.mumu_adb import resolve_adb_path
from utils.mumu_manager import list_mumu_instances
from utils.mumu_scrcpy_stream import ScrcpyVideoStream
from workers.mumu_dead_flower_worker import MumuDeadFlowerWorker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    args = parser.parse_args()
    instance = next(item for item in list_mumu_instances()
                    if item.get("adb_serial") == args.serial and item.get("is_android_started"))
    lock = threading.Lock()
    latest = {"frame": None, "at": 0, "sequence": 0}

    def on_frame(frame):
        with lock:
            latest.update(frame=frame, at=time.monotonic(), sequence=latest["sequence"] + 1)

    def snapshot():
        with lock:
            return {"frame": latest["frame"], "frame_sequence": latest["sequence"],
                    "frame_age_ms": (time.monotonic() - latest["at"]) * 1000}

    adb = resolve_adb_path()
    worker = MumuDeadFlowerWorker(args.serial, adb, lambda: None,
                                  window_handle=int(instance["render_wnd"], 16),
                                  snapshot_provider=snapshot,
                                  status_callback=lambda message: print(message, flush=True))
    stream = ScrcpyVideoStream(args.serial, on_frame, lambda error: print(error, flush=True), adb_path=adb)
    stream.start()
    try:
        deadline = time.monotonic() + 10
        observation = None
        while time.monotonic() < deadline:
            observation = worker._navigation_observation()
            if observation:
                break
            time.sleep(0.1)
        if not observation:
            raise RuntimeError("No fresh market scene; no keys sent")
        portal = worker._portal(observation[1])
        if not portal:
            raise RuntimeError("Market exit not found; no keys sent")
        worker._navigation_ground_y = portal[1]
        print(f"market={worker._navigation_rect} portal={portal} initial={observation[1].player_position}", flush=True)
        print(f"jump-confirmed position={worker._find_position_with_jump()}", flush=True)
        for direction in ("right", "left"):
            before = worker._find_position_with_jump()
            if before is None:
                raise RuntimeError("Could not establish initial X; no movement sent")
            samples = []
            start = time.monotonic()
            sequence = None
            with worker._hold_navigation_key(direction) as held:
                if not held:
                    raise RuntimeError("Cannot send background movement")
                while time.monotonic() - start < 1.5:
                    observation = worker._navigation_observation()
                    if observation is None:
                        raise RuntimeError("Video unavailable; releasing movement")
                    snap, analysis = observation
                    if snap["frame_sequence"] != sequence:
                        sequence = snap["frame_sequence"]
                        if analysis.player_position:
                            samples.append((time.monotonic() - start, analysis.player_position))
                    time.sleep(0.025)
            held_seconds = time.monotonic() - start
            worker._note_motion("walk")
            worker._wait_until_settled()
            print(f"{direction}: {[(round(t, 3), p) for t, p in samples]}", flush=True)
            worker._learn_walk_speed(direction, [(t, p[0]) for t, p in samples])
            print(f"measured speeds={worker._walk_speeds}", flush=True)
            after = worker._find_position_with_jump()
            if after is not None:
                print(f"confirmed displacement {direction}: {before} -> {after}, held {held_seconds:.3f}s, "
                      f"speed={abs(after[0] - before[0]) / held_seconds:.2f}px/s", flush=True)
    finally:
        worker.stop()
        stream.stop()


if __name__ == "__main__":
    main()
