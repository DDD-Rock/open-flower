"""Fixed-layout Artale mobile market recognition (960 x 540 stream space)."""

import sys
from pathlib import Path

import cv2
import numpy as np

from detection.emulator_frame_analysis import detect_emulator_map_title_region

MENU_POINT = (882, 83)
MARKET_POINT = (864, 340)


class EmulatorMarketRecognizer:
    REGIONS = {
        "market_icon": (8, 23, 30, 30),
        "menu_title": (782, 99, 124, 16),
        "menu_button": (872, 71, 56, 23),
    }

    def __init__(self):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        self.templates = {}
        for name in self.REGIONS:
            path = base / "templates" / "emulator" / f"{name}.png"
            # OpenCV's Windows filename handling does not support all Unicode
            # paths. Read with Python, then decode the image from memory.
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise RuntimeError(f"无法读取模拟器市场识别模板：{path}") from exc
            template = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR) if data else None
            if template is None:
                raise RuntimeError(f"模拟器市场识别模板损坏：{path}")
            self.templates[name] = template

    def matches(self, frame, name, threshold=0.82):
        if frame is None or frame.shape[:2] != (540, 960):
            return False
        x, y, w, h = self.REGIONS[name]
        crop = frame[y:y + h, x:x + w]
        template = self.templates[name]
        # Correlation alone also matches a dimmed icon behind a modal/loading
        # overlay. Require comparable brightness before allowing any input.
        if float(crop.mean()) < float(template.mean()) * 0.72:
            return False
        score = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)[0, 0]
        return bool(np.isfinite(score) and score >= threshold)

    def scene(self, frame):
        if frame is None or frame.shape[:2] != (540, 960):
            return "unknown"
        if self.matches(frame, "menu_title"):
            return "menu"
        if self.matches(frame, "market_icon"):
            return "market"
        if self.matches(frame, "menu_button", 0.65) and detect_emulator_map_title_region(frame):
            return "field"
        return "unknown"
