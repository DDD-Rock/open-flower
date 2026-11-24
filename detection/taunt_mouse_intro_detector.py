"""挑衅专用透明图形预告识别：暗色说明框、准备标题及安全提示，不调用 OCR。"""

from dataclasses import dataclass
from pathlib import Path
import sys

import cv2
import numpy as np


@dataclass(frozen=True)
class TauntMouseIntroDetection:
    rect: tuple[int, int, int, int]
    title_score: float
    instruction_score: float
    strong_match: bool


class TauntMouseIntroDetector:
    """在整张游戏画面寻找说明框；位置、尺寸均不绑定游戏分辨率。"""

    MAX_IMAGE_SIDE = 1280
    MAX_PANEL_CANDIDATES = 12
    NORMALIZED_PANEL_WIDTH = 360
    REFERENCE_PANEL_WIDTH = 680
    MIN_TITLE_SCORE = 0.70
    MIN_INSTRUCTION_SCORE = 0.64
    STRONG_TITLE_SCORE = 0.80
    STRONG_INSTRUCTION_SCORE = 0.75
    LABEL_SCALE_FACTORS = tuple(0.45 + index * 0.05 for index in range(21))

    def __init__(self):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        self.template_directory = base / "templates" / "verification"
        self._templates = None
        self._scaled_templates = {}

    def _load_templates(self):
        if self._templates is None:
            templates = {}
            for label in ("title", "safety"):
                path = self.template_directory / f"mouse_intro_{label}.png"
                template = (cv2.imdecode(np.fromfile(str(path), dtype=np.uint8),
                                       cv2.IMREAD_GRAYSCALE) if path.is_file() else None)
                if template is None or not template.size:
                    raise RuntimeError(f"缺少透明图形准备提示模板：{path.name}")
                templates[label] = template
            # 全句略有模糊、局部遮挡时，仍可匹配较长的关键短语。
            # 不是逐字 OCR：这些局部图像分别保留“尋找透明圖形”和“移動到安全的地方”。
            templates["title_key"] = templates["title"][:, round(templates["title"].shape[1] * 0.24):]
            templates["safety_key"] = templates["safety"][:, round(templates["safety"].shape[1] * 0.39):]
            self._templates = templates
        return self._templates

    def _scaled_label(self, label, scale):
        template = self._load_templates()[label]
        size = (max(1, round(template.shape[1] * scale)),
                max(1, round(template.shape[0] * scale)))
        key = (label, size)
        if key not in self._scaled_templates:
            self._scaled_templates[key] = cv2.resize(
                template, size,
                interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)
        return self._scaled_templates[key]

    def _match_label(self, gray, label, scales):
        best = (0.0, None, 0.0)
        for scale in scales:
            template = self._scaled_label(label, scale)
            height, width = template.shape
            if height > gray.shape[0] or width > gray.shape[1] or min(height, width) < 8:
                continue
            result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            if score > best[0]:
                best = (float(score), (*location, width, height), scale)
        return best

    def _match_tolerant_label(self, gray, label, scales):
        full = self._match_label(gray, label, scales)
        if full[0] >= 0.85:
            return full
        keyword = self._match_label(gray, f"{label}_key", scales)
        return max((full, keyword), key=lambda result: result[0])

    def _match_title(self, gray, scales):
        # 先找文字行再匹配，避免每个缩放模板反复扫描整个说明框。
        # 行在候选框内可以位于任何位置，不使用固定的屏幕或面板坐标。
        dark_columns = np.mean(gray <= 95, axis=0) >= 0.60
        rows = np.flatnonzero(np.count_nonzero(gray[:, dark_columns] >= 135, axis=1) >= 5)
        if not rows.size:
            return 0.0, None, 0.0
        groups = np.split(rows, np.flatnonzero(np.diff(rows) > 2) + 1)
        template_height = self._load_templates()["title"].shape[0]
        best = (0.0, None, 0.0)
        for group in groups[:24]:
            start, end = int(group[0]), int(group[-1]) + 1
            height = end - start
            if not 6 <= height <= 42:
                continue
            padding = max(3, round(height * 0.4))
            top, bottom = max(0, start - padding), min(gray.shape[0], end + padding)
            line_scales = [scale for scale in scales
                           if height * 0.55 <= template_height * scale <= height * 1.7]
            score, rect, scale = self._match_tolerant_label(gray[top:bottom], "title", line_scales)
            if rect is not None and score > best[0]:
                x, y, width, height = rect
                best = (score, (x, y + top, width, height), scale)
                if score >= 0.90:
                    break
        return best

    def detect(self, image):
        if image is None or image.ndim != 3 or image.shape[2] < 3:
            return None
        if min(image.shape[:2]) < 180:
            return None
        scale = min(1.0, self.MAX_IMAGE_SIDE / max(image.shape[:2]))
        source = image[:, :, :3]
        frame = source
        if scale < 1.0:
            frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        # 先在全画面找暗色连通区域，不假定在右侧或任何固定屏幕比例位置。
        dark = cv2.inRange(frame, (18, 18, 18), (86, 86, 86))
        for channel in (0, 1):
            neutral = cv2.inRange(cv2.absdiff(frame[:, :, channel], frame[:, :, 2]), 0, 14)
            dark = cv2.bitwise_and(dark, neutral)
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
        _, _, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
        candidates = []
        for stat in stats[1:]:
            x, y, width, height, area = map(int, stat)
            if (width >= 90 and height >= 90 and 0.40 <= width / height <= 2.5
                    and area / (width * height) >= 0.45):
                candidates.append((x, y, width, height))
        if not candidates:
            return None

        base_scale = self.NORMALIZED_PANEL_WIDTH / self.REFERENCE_PANEL_WIDTH
        title_scales = [base_scale * factor for factor in self.LABEL_SCALE_FACTORS]
        for rect in sorted(candidates, key=lambda item: item[2] * item[3], reverse=True)[
                :self.MAX_PANEL_CANDIDATES]:
            x, y, width, height = rect
            # 缩略图仅用于定位暗框；文字从原图裁剪，避免大窗口中的小 UI 被缩糊。
            left, top = max(0, int(x / scale)), max(0, int(y / scale))
            right = min(source.shape[1], int(np.ceil((x + width) / scale)))
            bottom = min(source.shape[0], int(np.ceil((y + height) / scale)))
            panel = source[top:bottom, left:right]
            native_rect = (left, top, right - left, bottom - top)
            normalized_height = round(panel.shape[0] * self.NORMALIZED_PANEL_WIDTH / panel.shape[1])
            panel = cv2.resize(panel, (self.NORMALIZED_PANEL_WIDTH, normalized_height),
                               interpolation=cv2.INTER_AREA if panel.shape[1] > self.NORMALIZED_PANEL_WIDTH
                               else cv2.INTER_CUBIC)
            gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)
            title_score, title, title_scale = self._match_title(gray, title_scales)
            if title is None or title_score < self.MIN_TITLE_SCORE:
                continue
            tx, ty, tw, th = title
            # 只使用说明框自身的标题/说明布局；跳过会从 2 变 1 的倒计时行。
            top = min(gray.shape[0], round(ty + th * 1.2))
            bottom = min(gray.shape[0], round(ty + th * 6.0))
            if bottom <= top:
                continue
            instruction_score, instruction, _ = self._match_tolerant_label(
                gray[top:bottom], "safety",
                [title_scale * factor for factor in (0.90, 0.95, 1.0, 1.05, 1.10)])
            if instruction is None or instruction_score < self.MIN_INSTRUCTION_SCORE:
                continue
            if max(title_score, instruction_score) < 0.78:
                continue
            ix, _, iw, _ = instruction
            if abs((tx + tw / 2) - (ix + iw / 2)) > gray.shape[1] * 0.15:
                continue
            return TauntMouseIntroDetection(
                native_rect, title_score, instruction_score,
                title_score >= self.STRONG_TITLE_SCORE
                and instruction_score >= self.STRONG_INSTRUCTION_SCORE)
        return None
