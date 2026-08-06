"""EXP 固定字体模板识别及读数防抖。"""

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

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
    CANONICAL_PANEL_WIDTH = 185
    CANONICAL_PANEL_HEIGHT = 44
    MAXIMUM_PANEL_SEARCH_WIDTH = 260

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
        self._cached_frame_size = None
        self._cached_anchor = None
        self._maximum_panel_width = 0

    def reset_panel_cache(self):
        self._cached_frame_size = None
        self._cached_anchor = None
        self._maximum_panel_width = 0

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

    def locate_panel(self, frame):
        """Locate and crop the complete EXP row without reading its digits.

        The stable ``EXP`` anchor is cached while the window size is unchanged.
        The right edge is still detected in the original full frame on every
        call, so a value that grows from ``0`` to a longer number is not clipped.
        """
        if cv2 is None or np is None or frame is None or frame.ndim != 3:
            return None
        templates = self._load_templates()
        if not templates:
            return None
        frame_size = (int(frame.shape[1]), int(frame.shape[0]))
        if self._cached_frame_size != frame_size:
            self.reset_panel_cache()
            self._cached_frame_size = frame_size

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        anchor = self._find_cached_anchor(gray, templates["anchor"])
        if anchor is None:
            anchor = self._find_anchor(gray, templates["anchor"])
        if anchor is None:
            self._cached_anchor = None
            return None

        anchor_x, anchor_y, scale, anchor_score = anchor
        self._cached_anchor = anchor
        left = int(round(anchor_x - 8 * scale))
        top = int(round(anchor_y - 3 * scale))
        canonical_width = max(1, int(round(self.CANONICAL_PANEL_WIDTH * scale)))
        right_edge = self._find_line_end(gray, templates, anchor)
        detected_width = canonical_width
        if right_edge is not None:
            detected_width = max(
                canonical_width,
                right_edge - left + max(4, int(round(8 * scale))),
            )
        else:
            detected_width = max(
                canonical_width,
                int(round(self.MAXIMUM_PANEL_SEARCH_WIDTH * scale)),
            )
        self._maximum_panel_width = max(self._maximum_panel_width, detected_width)
        width = max(canonical_width, self._maximum_panel_width)
        height = max(1, int(round(self.CANONICAL_PANEL_HEIGHT * scale)))
        right = min(frame.shape[1], left + width)
        bottom = min(frame.shape[0], top + height)
        left = max(0, left)
        top = max(0, top)
        if right <= left or bottom <= top:
            return None
        return frame[top:bottom, left:right].copy(), float(anchor_score), float(scale)

    def _find_cached_anchor(self, image, template):
        if self._cached_anchor is None:
            return None
        anchor_x, anchor_y, scale, _ = self._cached_anchor
        resized = self._resize(template, scale)
        radius = max(4, int(round(8 * scale)))
        left = max(0, anchor_x - radius)
        top = max(0, anchor_y - radius)
        right = min(image.shape[1], anchor_x + resized.shape[1] + radius)
        bottom = min(image.shape[0], anchor_y + resized.shape[0] + radius)
        search = image[top:bottom, left:right]
        if search.shape[0] < resized.shape[0] or search.shape[1] < resized.shape[1]:
            return None
        result = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(result)
        if score < 0.60:
            return None
        return left + point[0], top + point[1], scale, float(score)

    def _find_line_end(self, image, templates, anchor):
        anchor_x, anchor_y, scale, _ = anchor
        percent = self._resize(templates["percent"], scale)
        right_bracket = self._resize(templates["right_parenthesis"], scale)
        panel_left = int(round(anchor_x - 8 * scale))
        minimum_x = max(0, anchor_x + int(round(55 * scale)))
        maximum_x = min(
            image.shape[1] - right_bracket.shape[1],
            panel_left + int(round(self.MAXIMUM_PANEL_SEARCH_WIDTH * scale)),
        )
        y_radius = max(2, int(round(3 * scale)))
        minimum_y = max(0, anchor_y - y_radius)
        maximum_y = min(
            image.shape[0] - right_bracket.shape[0],
            anchor_y + y_radius,
        )
        if minimum_x > maximum_x or minimum_y > maximum_y:
            return None

        search = image[
            minimum_y:maximum_y + right_bracket.shape[0],
            minimum_x:maximum_x + right_bracket.shape[1],
        ]
        result = cv2.matchTemplate(search, right_bracket, cv2.TM_CCOEFF_NORMED)
        flat = result.reshape(-1)
        candidate_count = min(64, flat.size)
        if candidate_count <= 0:
            return None
        indices = np.argpartition(flat, -candidate_count)[-candidate_count:]
        indices = indices[np.argsort(flat[indices])[::-1]]
        percent_offset = int(round(16 * scale))
        best = None
        for index in indices:
            bracket_score = float(flat[index])
            if bracket_score < 0.45:
                break
            y, x = np.unravel_index(int(index), result.shape)
            bracket_x = minimum_x + int(x)
            percent_score = self._score_at(
                image,
                percent,
                bracket_x - percent_offset,
                anchor_y,
            )
            if percent_score < 0.40:
                continue
            score = min(bracket_score, percent_score)
            if best is None or score > best[1]:
                best = (bracket_x + right_bracket.shape[1], score)
        return best[0] if best is not None else None

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
        search = image
        offset_x = 0
        offset_y = 0
        if image.shape[1] > 300 and image.shape[0] > 120:
            offset_x = int(image.shape[1] * 0.20)
            offset_y = int(image.shape[0] * 0.70)
            right = max(offset_x + 1, int(image.shape[1] * 0.80))
            search = image[offset_y:image.shape[0], offset_x:right]

        best = None
        for scale in self.SCALE_CANDIDATES:
            resized = self._resize(template, scale)
            if (
                resized.shape[0] > search.shape[0]
                or resized.shape[1] > search.shape[1]
            ):
                continue
            result = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, point = cv2.minMaxLoc(result)
            if best is None or score > best[3]:
                best = (
                    offset_x + point[0],
                    offset_y + point[1],
                    scale,
                    float(score),
                )
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


class EXPRapidOCRRecognizer:
    """Read an EXP row with RapidOCR after template-based panel localization."""

    _PATTERNS = (
        re.compile(
            r"(?<![0-9,])(?:[A-Z\u00c0-\u024f]*XP[\s:._-]*)?"
            r"([0-9][0-9,]*)\s*[\(\[\{]\s*"
            r"([0-9]{1,3}(?:[\.,][0-9]{1,4})?)\s*%",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?<![0-9,])(?:[A-Z\u00c0-\u024f]*XP[\s:._-]*)?"
            r"([0-9][0-9,]*)\s+"
            r"([0-9]{1,3}(?:[\.,][0-9]{1,4})?)\s*%",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?<![0-9,])(?:[A-Z\u00c0-\u024f]*XP[\s:._-]*)"
            r"([0-9][0-9,]*?)\s*[\(\[\{]?\s*"
            r"((?:100[\.,]0{1,4}|[0-9]{1,2}[\.,][0-9]{1,4}))\s*%",
            re.IGNORECASE,
        ),
    )

    def __init__(
        self,
        locator: Optional[EXPFixedFontRecognizer] = None,
        engine_directory: Optional[str] = None,
        minimum_confidence: float = 0.80,
        runner: Optional[Callable] = None,
    ):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        self.locator = locator or EXPFixedFontRecognizer()
        self.engine_directory = (
            Path(engine_directory)
            if engine_directory
            else base / "resources" / "rapidocr"
        )
        self.minimum_confidence = min(1.0, max(0.0, minimum_confidence))
        self.runner = runner

    @property
    def is_available(self):
        return self.runner is not None or (
            (self.engine_directory / "RapidOCR-json.exe").is_file()
            and (self.engine_directory / "models").is_dir()
        )

    def recognize(self, frame) -> Optional[EXPRecognitionResult]:
        located = self.locator.locate_panel(frame)
        if located is None:
            return None
        panel, anchor_confidence, _ = located
        enlarged = cv2.resize(
            panel,
            (panel.shape[1] * 4, panel.shape[0] * 4),
            interpolation=cv2.INTER_NEAREST,
        )
        payload = self.runner(enlarged) if self.runner else self._run_engine(enlarged)
        parsed = self.parse_payload(payload)
        if parsed is None:
            return None
        current_exp, percent, ocr_confidence = parsed
        if ocr_confidence < self.minimum_confidence:
            return None
        return EXPRecognitionResult(
            current_exp=current_exp,
            percent=percent,
            confidence=min(float(anchor_confidence), float(ocr_confidence)),
        )

    @classmethod
    def parse_payload(cls, payload):
        if not isinstance(payload, dict) or payload.get("code") != 100:
            return None
        blocks = payload.get("data")
        if not isinstance(blocks, list):
            return None

        candidates = []
        texts = []
        scores = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "")
            try:
                score = float(block.get("score", 0))
            except (TypeError, ValueError):
                score = 0.0
            texts.append(text)
            scores.append(score)
            parsed = cls.parse_text(text)
            if parsed is not None:
                candidates.append((*parsed, score))

        if texts:
            joined = "".join(texts)
            parsed = cls.parse_text(joined)
            if parsed is not None:
                joined_score = min(scores) if scores else 0.0
                candidates.append((*parsed, joined_score))
        return max(candidates, key=lambda item: item[2], default=None)

    @classmethod
    def parse_text(cls, text):
        normalized = (
            str(text)
            .replace("（", "(")
            .replace("）", ")")
            .replace("【", "[")
            .replace("】", "]")
            .replace("％", "%")
        )
        for pattern in cls._PATTERNS:
            match = pattern.search(normalized)
            if match is None:
                continue
            try:
                current_exp = int(match.group(1).replace(",", ""))
                percent = float(match.group(2).replace(",", "."))
            except ValueError:
                continue
            if current_exp >= 0 and 0 <= percent <= 100:
                return current_exp, percent
        return None

    def _run_engine(self, image):
        if not self.is_available:
            return None
        encoded, png = cv2.imencode(".png", image)
        if not encoded:
            return None

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="autobuff-exp-",
                suffix=".png",
                delete=False,
            ) as temp_file:
                temp_file.write(png.tobytes())
                temp_path = temp_file.name

            executable = self.engine_directory / "RapidOCR-json.exe"
            models = self.engine_directory / "models"
            command = [
                str(executable),
                "--models",
                str(models),
                "--det",
                "ch_PP-OCRv4_det_infer.onnx",
                "--cls",
                "ch_ppocr_mobile_v2.0_cls_infer.onnx",
                "--rec",
                "rec_ch_PP-OCRv4_infer.onnx",
                "--keys",
                "ppocr_keys_v1.txt",
                "--doAngle",
                "0",
                "--mostAngle",
                "0",
                "--padding",
                "20",
                "--image_path",
                temp_path,
            ]
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            completed = subprocess.run(
                command,
                cwd=str(self.engine_directory),
                capture_output=True,
                timeout=8,
                check=False,
                creationflags=creation_flags,
            )
            output = completed.stdout.decode("utf-8", errors="replace")
            match = re.search(r"\{[\s\S]*\}", output)
            return json.loads(match.group(0)) if match else None
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return None
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
