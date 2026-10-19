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
            template = cv2.imread(str(base / "templates" / "emulator" / f"{name}.png"))
            if template is None:
                raise RuntimeError(f"缺少模拟器市场识别模板：{name}")
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
