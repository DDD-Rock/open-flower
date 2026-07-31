"""EXP 固定字体模板识别及读数防抖。"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


def format_percent(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class EXPRecognitionResult:
    current_exp: int
    percent: float
    confidence: float

    @property
    def key(self):
        return f"{self.current_exp}|{format_percent(self.percent)}"

    @property
    def display_text(self):
        return f"{self.current_exp} ({format_percent(self.percent)}%)"


class EXPRecognitionStabilizer:
    def __init__(self, required_matches: int = 2, tolerated_misses: int = 3):
        self.required_matches = max(1, required_matches)
        self.tolerated_misses = max(0, tolerated_misses)
        self.reset()

    def update(self, reading: Optional[EXPRecognitionResult]):
        if reading is None:
            self.misses += 1
            self.candidate_key = None
            self.consecutive_matches = 0
            if self.misses > self.tolerated_misses:
                self.stable_reading = None
            return self.stable_reading
        self.misses = 0
        if reading.key == self.candidate_key:
            self.consecutive_matches += 1
        else:
            self.candidate_key = reading.key
            self.consecutive_matches = 1
        if self.consecutive_matches >= self.required_matches:
            self.stable_reading = reading
        return self.stable_reading

    def reset(self):
        self.candidate_key = None
        self.consecutive_matches = 0
        self.misses = 0
        self.stable_reading = None


class EXPFixedFontRecognizer:
    """识别游戏窗口中的 ``当前经验 (百分比%)`` 固定字体面板。"""

    SCALE_CANDIDATES = (0.75, 0.875, 1.0, 1.125, 1.25, 1.5, 1.75, 2.0)

    def __init__(self, template_directory: Optional[str] = None):
        base = Path(
            getattr(
                sys,
                "_MEIPASS",
                Path(__file__).resolve().parents[1],
            )
        )
        self.template_directory = Path(template_directory) if template_directory else base / "templates" / "exp"
        self.templates = None

    def recognize(self, frame) -> Optional[EXPRecognitionResult]:
        if cv2 is None or np is None or frame is None or frame.ndim != 3:
            return None
        templates = self._load_templates()
        if not templates:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        anchor = self._find_anchor(gray, templates["anchor"])
        if anchor is None:
            return None
        anchor_x, anchor_y, scale, anchor_score = anchor
        scaled = {
            name: self._resize(template, scale)
            for name, template in templates.items()
            if name != "anchor"
        }
        step = max(1, int(round(7 * scale)))
        digit_start = anchor_x + int(round(33 * scale))

        current_length = self._best_length(
            gray,
            scaled["left_parenthesis"],
            digit_start,
            anchor_y,
            step,
            range(1, 11),
        )
        if current_length is None or current_length[1] < 0.55:
            return None
        current = self._read_digits(
            gray,
            scaled,
            digit_start,
            anchor_y,
            step,
            current_length[0],
        )
        if current is None:
            return None

        left_x = digit_start + current_length[0] * step
        percent_start = left_x + max(1, int(round(4 * scale)))
        integer_length = self._best_length(
            gray,
            scaled["dot"],
            percent_start,
            anchor_y,
            step,
            range(1, 4),
        )
        if integer_length is None or integer_length[1] < 0.5:
            return None
        integer = self._read_digits(
            gray,
            scaled,
            percent_start,
            anchor_y,
            step,
            integer_length[0],
        )
        if integer is None:
            return None

        fraction_start = (
            percent_start
            + integer_length[0] * step
            + max(1, int(round(3 * scale)))
        )
        fraction_length = self._best_length(
            gray,
            scaled["percent"],
            fraction_start,
            anchor_y,
            step,
            range(1, 5),
        )
        if fraction_length is None or fraction_length[1] < 0.5:
            return None
        fraction = self._read_digits(
            gray,
            scaled,
            fraction_start,
            anchor_y,
            step,
            fraction_length[0],
        )
        if fraction is None:
            return None

        percent_x = fraction_start + fraction_length[0] * step
        right_score = self._score_at(
            gray,
            scaled["right_parenthesis"],
            percent_x + max(1, int(round(16 * scale))),
            anchor_y,
        )
        scores = [
            anchor_score,
            current_length[1],
            current[1],
            integer_length[1],
            integer[1],
            fraction_length[1],
            fraction[1],
            right_score,
        ]
        if min(scores) < 0.43:
            return None
        try:
            current_exp = int(current[0])
            percent = float(f"{integer[0]}.{fraction[0]}")
        except ValueError:
            return None
        if current_exp < 0 or not 0 <= percent <= 100:
            return None
        return EXPRecognitionResult(
            current_exp,
            percent,
            sum(scores) / len(scores),
        )

    def _load_templates(self):
        if self.templates is not None:
            return self.templates
        if cv2 is None:
            return None
        names = {
            "anchor": "exp_anchor.png",
            "left_parenthesis": "exp_left_paren.png",
            "right_parenthesis": "exp_right_paren.png",
            "dot": "exp_dot.png",
            "percent": "exp_percent.png",
            **{str(value): f"exp_char_{value}.png" for value in range(10)},
        }
        loaded = {}
        for name, filename in names.items():
            template = cv2.imread(str(self.template_directory / filename), cv2.IMREAD_GRAYSCALE)
            if template is None:
                return None
            loaded[name] = template
        self.templates = loaded
        return loaded

    def _find_anchor(self, image, template):
        best = None
        for scale in self.SCALE_CANDIDATES:
            resized = self._resize(template, scale)
            if resized.shape[0] > image.shape[0] or resized.shape[1] > image.shape[1]:
                continue
            result = cv2.matchTemplate(image, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, point = cv2.minMaxLoc(result)
            if best is None or score > best[3]:
                best = (point[0], point[1], scale, float(score))
        return best if best is not None and best[3] >= 0.68 else None

    @staticmethod
    def _resize(template, scale):
        if scale == 1:
            return template
        return cv2.resize(
            template,
            (
                max(1, int(round(template.shape[1] * scale))),
                max(1, int(round(template.shape[0] * scale))),
            ),
            interpolation=cv2.INTER_NEAREST,
        )

    def _best_length(self, image, template, start_x, y, step, values):
        choices = [
            (count, self._score_at(image, template, start_x + count * step, y))
            for count in values
        ]
        return max(choices, key=lambda item: item[1], default=None)

    def _read_digits(self, image, templates, start_x, y, step, count):
        text = []
        minimum_score = 1.0
        for index in range(count):
            x = start_x + index * step
            choices = [
                (str(value), self._score_at(image, templates[str(value)], x, y))
                for value in range(10)
            ]
            digit, score = max(choices, key=lambda item: item[1])
            if score < 0.43:
                return None
            text.append(digit)
            minimum_score = min(minimum_score, score)
        return "".join(text), minimum_score

    @staticmethod
    def _score_at(image, template, x, y):
        best = -1.0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                left, top = x + dx, y + dy
                right, bottom = left + template.shape[1], top + template.shape[0]
                if left < 0 or top < 0 or right > image.shape[1] or bottom > image.shape[0]:
                    continue
                region = image[top:bottom, left:right]
                score = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)[0, 0]
                best = max(best, float(score))
        return best
