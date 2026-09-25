import unittest
from types import SimpleNamespace
from unittest import mock

from ui.main_window import MainWindow


class WindowReidentificationTests(unittest.TestCase):
    @staticmethod
    def _window(selector, hwnd=None, identified=False):
        return SimpleNamespace(
            window_selector=selector,
            game_window_hwnd=hwnd,
            is_window_identified=identified,
            logger=mock.Mock(),
            update_log_display=mock.Mock(),
            _stop_party_invite_worker=mock.Mock(),
            auto_identify_on_startup=mock.Mock(),
        )

    def test_valid_cached_window_is_reused_without_scanning(self):
        selector = mock.Mock()
        selector.is_window_valid.return_value = True
        window = self._window(selector, hwnd=101, identified=True)

        available = MainWindow._ensure_game_window_available(window, "测试")

        self.assertTrue(available)
        window.auto_identify_on_startup.assert_not_called()
        window._stop_party_invite_worker.assert_not_called()

    def test_missing_window_is_automatically_identified(self):
        selector = mock.Mock()
        selector.is_window_valid.side_effect = lambda hwnd: hwnd == 202
        window = self._window(selector)

        def identify():
            window.game_window_hwnd = 202
            window.is_window_identified = True

        window.auto_identify_on_startup.side_effect = identify

        available = MainWindow._ensure_game_window_available(window, "标记")

        self.assertTrue(available)
        window.auto_identify_on_startup.assert_called_once_with()
        self.assertEqual(window.game_window_hwnd, 202)

    def test_stale_window_is_cleared_and_reidentified(self):
        selector = mock.Mock()
        selector.is_window_valid.side_effect = lambda hwnd: hwnd == 303
        window = self._window(selector, hwnd=101, identified=True)

        def identify():
            window.game_window_hwnd = 303
            window.is_window_identified = True

        window.auto_identify_on_startup.side_effect = identify

        available = MainWindow._ensure_game_window_available(window, "监控")

        self.assertTrue(available)
        window._stop_party_invite_worker.assert_called_once_with()
        window.auto_identify_on_startup.assert_called_once_with()
        self.assertEqual(window.game_window_hwnd, 303)

    def test_failed_scan_returns_false(self):
        selector = mock.Mock()
        selector.is_window_valid.return_value = False
        window = self._window(selector, hwnd=101, identified=True)

        available = MainWindow._ensure_game_window_available(window, "运行")

        self.assertFalse(available)
        self.assertIsNone(window.game_window_hwnd)
        self.assertFalse(window.is_window_identified)


if __name__ == "__main__":
    unittest.main()
