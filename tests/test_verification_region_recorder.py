from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np

from utils.verification_region_recorder import VerificationRegionRecorder


class FakeWriter:
    def __init__(self, *_args):
        self.frames = []
        self.released = False

    def isOpened(self):
        return True

    def write(self, frame):
        self.frames.append(frame.copy())

    def release(self):
        self.released = True


def test_records_clamped_even_sized_body_and_timestamped_name(tmp_path):
    writer = FakeWriter()
    image = np.zeros((101, 121, 3), dtype=np.uint8)
    recorder = VerificationRegionRecorder(
        tmp_path,
        now=lambda: datetime(2026, 8, 7, 14, 5, 9),
    )

    with patch("utils.verification_region_recorder.cv2.VideoWriter", return_value=writer):
        path = recorder.start(image, (-3, 5, 124, 97))
        assert path == tmp_path / "鼠标跟随验证_2026-08-07_14-05-09.mp4"
        assert writer.frames[0].shape == (96, 120, 3)
        assert recorder.append(image)
        assert recorder.stop() == path

    assert writer.released
    assert len(writer.frames) == 2


def test_resizes_moving_detection_to_initial_video_dimensions(tmp_path):
    writer = FakeWriter()
    image = np.zeros((200, 300, 3), dtype=np.uint8)
    recorder = VerificationRegionRecorder(tmp_path)

    with patch("utils.verification_region_recorder.cv2.VideoWriter", return_value=writer):
        recorder.start(image, (10, 20, 100, 80))
        assert recorder.append(image, (20, 25, 120, 90))
        recorder.stop()

    assert [frame.shape for frame in writer.frames] == [(80, 100, 3), (80, 100, 3)]


def test_source_application_root_is_project_directory():
    expected = Path(__file__).resolve().parents[1]
    with patch("utils.verification_region_recorder.sys.frozen", False, create=True):
        from utils.verification_region_recorder import application_root

        assert application_root() == expected
