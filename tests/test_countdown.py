import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "utils" / "countdown.py"
SPEC = importlib.util.spec_from_file_location("countdown", MODULE_PATH)
COUNTDOWN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COUNTDOWN)


class CountdownTimingTests(unittest.TestCase):
    def test_next_release_is_anchored_to_final_press(self):
        self.assertEqual(
            COUNTDOWN.next_release_time(pressed_at=1000.0, interval=200.0),
            1200.0,
        )

    def test_random_early_release_is_applied_from_final_press(self):
        self.assertEqual(
            COUNTDOWN.next_release_time(
                pressed_at=1000.0,
                interval=200.0,
                early_by=7.5,
            ),
            1192.5,
        )

    def test_remaining_seconds_uses_ceiling(self):
        self.assertEqual(COUNTDOWN.remaining_seconds(1200.0, 1000.0), 200)
        self.assertEqual(COUNTDOWN.remaining_seconds(1200.0, 1000.1), 200)
        self.assertEqual(COUNTDOWN.remaining_seconds(1200.0, 1200.1), 0)


if __name__ == "__main__":
    unittest.main()
