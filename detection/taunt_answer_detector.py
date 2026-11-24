"""挑衅专用输入答案弹窗识别：白色输入框、Check 按钮及半透明蓝边。"""

from dataclasses import dataclass
from pathlib import Path
import sys

import cv2
import numpy as np


@dataclass(frozen=True)
class TauntAnswerDetection:
    input_rect: tuple[int, int, int, int]
    check_score: float
    blue_edge_strength: float


class TauntAnswerDetector:
    """只识别验证面板，不分析中间的物体或填写答案，不调用 OCR。"""

    MAX_IMAGE_SIDE = 1600
    MIN_CHECK_SCORE = 0.62
    MAX_INPUT_CANDIDATES = 24
    LABEL_SCALE_FACTORS = (0.80, 0.90, 1.00, 1.10, 1.20)

    def __init__(self):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        self.template_directory = base / "templates" / "verification"
        self._templates = None

    def _load_templates(self):
        if self._templates is None:
            templates = []
            for name in ("answer_check_1.png", "answer_check_2.png"):
                path = self.template_directory / name
                if path.is_file():
                    template = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8),
                                            cv2.IMREAD_GRAYSCALE)
                    if template is not None and template.size:
                        templates.append(template)
            if not templates:
                raise RuntimeError("缺少输入答案验证的 Check 按钮模板")
            self._templates = templates
        return self._templates

    def detect(self, image):
        if image is None or image.ndim != 3 or image.shape[2] < 3:
            return None
        if min(image.shape[:2]) < 150:
            return None
        scale = min(1.0, self.MAX_IMAGE_SIDE / max(image.shape[:2]))
        frame = image[:, :, :3]
        if scale < 1.0:
            frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        # 输入框可为空，也可已经打字；只约束外形与浅色底，不要求内部全白。
        # 用原生逐通道阈值，避免为整帧分配三通道 int16 数组及做 NumPy 归约。
        white = cv2.inRange(frame, (205, 205, 205), (255, 255, 255))
        contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if not (60 <= width <= frame.shape[1] * 0.58 and 6 <= height <= 72
                    and 5.5 <= width / height <= 18.0):
                continue
            if cv2.contourArea(contour) / (width * height) < 0.78:
                continue
            if float(np.mean(white[y:y + height, x:x + width] > 0)) < 0.60:
                continue
            candidates.append((x, y, width, height))
        if not candidates:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blue_bias = cv2.subtract(frame[:, :, 0], frame[:, :, 2], dtype=cv2.CV_16S)
        for rect in sorted(candidates, key=lambda item: item[2] * item[3], reverse=True)[
                :self.MAX_INPUT_CANDIDATES]:
            # 先检查轻量的相对边界；背景不同会改变面板颜色，但蓝色叠加仍产生边缘。
            edge_strength = self._blue_edges(blue_bias, rect)
            if edge_strength < 1.0:
                continue
            check_score = self._match_check(gray, rect)
            if check_score >= self.MIN_CHECK_SCORE:
                return TauntAnswerDetection(
                    tuple(round(value / scale) for value in rect), check_score, edge_strength)
        return None

    def _match_check(self, gray, rect):
        x, y, width, height = rect
        # 两张参考图里，Check 都在输入框左下方；不固定整个面板在屏幕中的坐标。
        left, right = max(0, round(x - width * 0.27)), min(gray.shape[1], round(x + width * 0.32))
        top = max(0, round(y + height * 0.92))
        bottom = min(gray.shape[0], round(y + height * 2.85))
        search = gray[top:bottom, left:right]
        if not search.size:
            return 0.0
        best = 0.0
        for template in self._load_templates():
            for factor in self.LABEL_SCALE_FACTORS:
                label_scale = height / 24.0 * factor
                target_width = max(1, round(template.shape[1] * label_scale))
                target_height = max(1, round(template.shape[0] * label_scale))
                if (target_width < 14 or target_height < 6
                        or target_width > search.shape[1] or target_height > search.shape[0]):
                    continue
                label = cv2.resize(template, (target_width, target_height),
                                   interpolation=cv2.INTER_AREA if label_scale < 1 else cv2.INTER_CUBIC)
                result = cv2.matchTemplate(search, label, cv2.TM_CCOEFF_NORMED)
                best = max(best, float(cv2.minMaxLoc(result)[1]))
        return best

    @staticmethod
    def _blue_edges(blue_bias, rect):
        x, y, width, height = rect
        top, bottom = max(0, round(y - width * 1.05)), max(0, y - round(height * 0.25))
        if bottom - top < width * 0.45:
            return 0.0
        band, gap = max(2, round(height * 0.25)), max(1, round(height * 0.125))
        tolerance = max(2, round(width * 0.04))
        best = 0.0
        for edge, orientation in ((x - width * 0.16, 1), (x + width * 1.16, -1)):
            for offset in range(-tolerance, tolerance + 1, max(1, tolerance // 2)):
                position = round(edge + offset)
                if position - gap - band < 0 or position + gap + band > blue_bias.shape[1]:
                    continue
                outside = blue_bias[top:bottom, position - gap - band:position - gap].mean(axis=1)
                inside = blue_bias[top:bottom, position + gap:position + gap + band].mean(axis=1)
                shift = (inside - outside) * orientation
                # 至少一侧大部分行都有向蓝色的跃迁，避免只按背景整体颜色判断。
                strength = min(float(np.median(shift)) / 10.0, float(np.mean(shift >= 8)) / 0.60)
                best = max(best, strength)
        return best
