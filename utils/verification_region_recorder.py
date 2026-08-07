"""Record the ochre body of a mouse-follow verification while it is visible."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def application_root() -> Path:
    """Return the writable directory beside the packaged app or the source root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


class VerificationRegionRecorder:
    FPS = 10.0

    def __init__(self, output_directory: Optional[Path] = None, now=None):
        self.output_directory = Path(output_directory or application_root())
        self._now = now or datetime.now
        self._writer = None
        self._body_rect = None
        self._frame_size = None
        self.output_path: Optional[Path] = None

    @property
    def is_recording(self) -> bool:
        return self._writer is not None

    def start(self, image: np.ndarray, body_rect) -> Path:
        if self.is_recording:
            return self.output_path
        crop, normalized_rect = self._crop(image, body_rect)
        if crop is None:
            raise ValueError("验证区域超出游戏画面")

        self.output_directory.mkdir(parents=True, exist_ok=True)
        timestamp = self._now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = self.output_directory / f"鼠标跟随验证_{timestamp}.mp4"
        height, width = crop.shape[:2]
        writer = cv2.VideoWriter(
            os.fspath(output_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            self.FPS,
            (width, height),
        )
        if not writer.isOpened():
            writer.release()
            raise RuntimeError("无法创建验证录像文件")

        self._writer = writer
        self._body_rect = normalized_rect
        self._frame_size = (width, height)
        self.output_path = output_path
        writer.write(crop)
        return output_path

    def append(self, image: np.ndarray, body_rect=None) -> bool:
        if not self.is_recording:
            return False
        if body_rect is not None:
            self._body_rect = self._normalize_rect(body_rect, image)
        crop, _ = self._crop(image, self._body_rect)
        if crop is None:
            return False
        if (crop.shape[1], crop.shape[0]) != self._frame_size:
            crop = cv2.resize(crop, self._frame_size, interpolation=cv2.INTER_AREA)
        self._writer.write(crop)
        return True

    def stop(self) -> Optional[Path]:
        if self._writer is None:
            return None
        writer = self._writer
        completed_path = self.output_path
        self._writer = None
        self._body_rect = None
        self._frame_size = None
        self.output_path = None
        writer.release()
        return completed_path

    @classmethod
    def _crop(cls, image, body_rect):
        if image is None or image.ndim != 3 or image.shape[2] < 3 or body_rect is None:
            return None, None
        rect = cls._normalize_rect(body_rect, image)
        if rect is None:
            return None, None
        x, y, width, height = rect
        return image[y : y + height, x : x + width, :3].copy(), rect

    @staticmethod
    def _normalize_rect(body_rect, image):
        try:
            x, y, width, height = (int(round(value)) for value in body_rect)
        except (TypeError, ValueError):
            return None
        image_height, image_width = image.shape[:2]
        x0 = max(0, min(image_width, x))
        y0 = max(0, min(image_height, y))
        x1 = max(x0, min(image_width, x + width))
        y1 = max(y0, min(image_height, y + height))
        # MPEG-4 encoders are most portable with even frame dimensions.
        crop_width = (x1 - x0) // 2 * 2
        crop_height = (y1 - y0) // 2 * 2
        if crop_width < 2 or crop_height < 2:
            return None
        return x0, y0, crop_width, crop_height
