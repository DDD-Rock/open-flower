"""挑衅模式专用测谎观察器；不调用监控模式的识别器或通知链路。"""

from dataclasses import dataclass, replace
import math
import threading
import time

import cv2
import numpy as np

from detection.minimap_monitor import MinimapMonitor
from detection.taunt_answer_detector import TauntAnswerDetector
from detection.taunt_mouse_intro_detector import TauntMouseIntroDetector
from utils.background_window_capture import BackgroundWindowCapture


@dataclass(frozen=True)
class TauntVerificationState:
    ready: bool = False
    candidate: bool = False
    present: bool = False
    episode: int = 0
    sampled_at: float = 0.0
    error: str = ""
    kind: str = ""


def _has_mouse_follow_prompt(image):
    """独立检查金色题面、上下深色栏及标题字形，不进行 OCR 或解题。"""
    if image is None or image.ndim != 3 or image.shape[2] < 3:
        return False
    height, width = image.shape[:2]
    if width < 240 or height < 180:
        return False
    # 无论窗口分辨率多高，连通域分析的长边最多约 640 像素。
    stride = max(2, math.ceil(max(width, height) / 640))
    pixels = image[::stride, ::stride, :3].astype(np.int16)
    blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    gold = ((red >= 105) & (green >= 65) & (red >= green + 10)
            & (green >= blue + 12) & (red >= blue + 42) & (blue <= 175))
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        gold.astype(np.uint8), connectivity=8)
    minimum_cells = max(100, round(150 * 100 * 0.55 / stride ** 2))
    candidate_indices = np.argsort(stats[1:count, cv2.CC_STAT_AREA])[-8:] + 1
    candidates = stats[candidate_indices]

    def coverage(x0, y0, x1, y1, *, bright=False):
        region = pixels[max(0, y0):min(pixels.shape[0], y1),
                        max(0, x0):min(pixels.shape[1], x1)]
        if not region.size:
            return 0.0
        low, high = region.min(axis=2), region.max(axis=2)
        mask = ((low >= 125) & (high - low <= 45) if bright
                else (high <= 92) & (high - low <= 30))
        return float(mask.mean())

    for stat in candidates:
        x, y, w, h, area = map(int, stat)
        if (area < minimum_cells or w * stride < 150 or h * stride < 100
                or not 0.8 <= w / h <= 3.0 or area / (w * h) < 0.55):
            continue
        title_height, footer_height = max(1, round(h * 0.18)), max(1, round(h * 0.22))
        expansion = max(1, round(w * 0.025))
        if y < title_height or y + h + footer_height > pixels.shape[0]:
            continue
        x0, x1 = max(0, x - expansion), min(pixels.shape[1], x + w + expansion)
        if (coverage(x0, y - title_height, x1, y) >= 0.48
                and coverage(x0, y + h, x1, y + h + footer_height) >= 0.48
                and coverage(x0 + round((x1 - x0) * 0.28), y - title_height,
                             x0 + round((x1 - x0) * 0.72), y, bright=True) >= 0.012):
            return True
    return False


def _has_rune_prompt(image):
    """独立识别紫色符文提示的两条横线及中间紫色题面。"""
    if image is None or image.ndim != 3 or min(image.shape[:2]) < 64:
        return False
    pixels = image[::max(1, math.ceil(image.shape[0] / 900)),
                   ::max(1, math.ceil(image.shape[1] / 640)), :3].astype(np.int16)
    height, width = pixels.shape[:2]
    b, g, r = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    border = ((b >= 90) & (b >= g + 45) & (r >= g + 20)
              & (b >= r + 5) & (r >= 40))
    rows = np.flatnonzero(border.mean(axis=1) >= 0.32)
    if not rows.size:
        return False
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 2) + 1)
    lines = []
    for group in groups:
        start, end = int(group[0]), int(group[-1]) + 1
        columns = np.flatnonzero(border[start:end].any(axis=0))
        runs = np.split(columns, np.flatnonzero(np.diff(columns) > max(2, width // 128)) + 1)
        run = max(runs, key=lambda part: part[-1] - part[0])
        if run[-1] - run[0] + 1 >= width * 0.30:
            lines.append((start, end, int(run[0]), int(run[-1]) + 1))
    if len(lines) > 24:
        # 噪声很多时限制横线配对次数，避免 Python 循环挤占动作调度。
        lines = sorted(sorted(lines, key=lambda line: line[3] - line[2], reverse=True)[:24])
    for index, top in enumerate(lines):
        for bottom in lines[index + 1:]:
            if not height * 0.06 <= bottom[1] - top[0] <= height * 0.22:
                continue
            left, right = max(top[2], bottom[2]), min(top[3], bottom[3])
            if right - left < min(top[3] - top[2], bottom[3] - bottom[2]) * 0.80:
                continue
            region = pixels[top[1]:bottom[0], left:right]
            if region.shape[0] < 4 or not region.size:
                continue
            blue, green, red = region[:, :, 0], region[:, :, 1], region[:, :, 2]
            if float(((blue >= green + 25) & (red >= green + 8) & (blue >= 40)).mean()) >= 0.25:
                return True
    return False


class TauntVerificationWatch(threading.Thread):
    """只截图及发布状态，绝不发送按键；只有勾选选项才创建此线程。"""

    SCAN_INTERVAL = 0.75
    REQUIRED_HITS = 2
    REQUIRED_MISSES = 4

    def __init__(self, hwnd, window_selector=None):
        super().__init__(name="taunt-verification", daemon=True)
        self.hwnd = hwnd
        self.window_selector = window_selector
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._state = TauntVerificationState()

    def snapshot(self):
        with self._lock:
            return self._state

    def _publish(self, **changes):
        with self._lock:
            self._state = replace(self._state, **changes)

    def stop(self):
        self._stop_event.set()

    def _foreground(self):
        return (self.window_selector is None
                or self.window_selector.is_window_foreground(self.hwnd))

    def run(self):
        capture = MinimapMonitor()
        capture.set_window_handle(self.hwnd)
        background_capture = None
        answer_detector = TauntAnswerDetector()
        mouse_intro_detector = TauntMouseIntroDetector()
        hits = dict(mouse=0, rune=0, answer=0)
        misses = dict(mouse=0, rune=0, answer=0)
        active = dict(mouse=False, rune=False, answer=False)
        labels = dict(mouse="鼠标跟随／寻找透明图形", rune="符文诅咒", answer="输入答案")
        try:
            while not self._stop_event.is_set():
                try:
                    try:
                        if background_capture is None:
                            background_capture = BackgroundWindowCapture(self.hwnd)
                        image = background_capture.capture()
                    except Exception:
                        # 后台失败时只能在游戏处于前台时回退，不能识别其他程序的覆盖画面。
                        if not self._foreground():
                            raise
                        capture.start_capture()
                        image = capture.capture_game_screen()
                        if image is None:
                            raise RuntimeError("无法截取游戏画面")
                    intro_detection = mouse_intro_detector.detect(image)
                    mouse_intro = intro_detection is not None
                    observations = {"mouse": mouse_intro or _has_mouse_follow_prompt(image),
                                    "rune": _has_rune_prompt(image),
                                    "answer": answer_detector.detect(image) is not None}
                    del image
                    if self._stop_event.is_set():
                        break
                    state = self.snapshot()
                    for source, detected in observations.items():
                        if detected:
                            hits[source], misses[source] = hits[source] + 1, 0
                            immediate = (source == "mouse" and mouse_intro
                                         and intro_detection.strong_match)
                            required_hits = 1 if immediate else self.REQUIRED_HITS
                            if hits[source] >= required_hits:
                                active[source] = True
                        else:
                            hits[source], misses[source] = 0, misses[source] + 1
                            if misses[source] >= self.REQUIRED_MISSES:
                                active[source] = False
                    present = any(active.values())
                    episode = state.episode + int(present and not state.present)
                    kind = "／".join(dict.fromkeys(labels[source] for source in active
                                               if active[source] or hits[source]))
                    self._publish(ready=True, candidate=any(hits.values()),
                                  present=present, kind=kind, episode=episode,
                                  sampled_at=time.monotonic(), error="")
                except Exception as error:
                    hits = dict.fromkeys(hits, 0)
                    misses = dict.fromkeys(misses, 0)
                    # 截图失败不是弹窗消失，不能据此重新触发同一弹窗的喊话。
                    self._publish(candidate=False, error=str(error))
                if self._stop_event.wait(self.SCAN_INTERVAL):
                    break
        finally:
            capture.close_capture()
