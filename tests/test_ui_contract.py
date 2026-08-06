import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class ModernUIContractTests(unittest.TestCase):
    def test_modern_window_source_is_valid_and_contains_required_controls(self):
        source = (ROOT / "ui" / "modern_main_window.py").read_text(
            encoding="utf-8"
        )
        ast.parse(source)
        for text in (
            "YzY - Auto Buff",
            "Power by 小新",
            "BUFF 配置",
            "出市场后移动方式",
            "只向右（骨龙、忘却）",
            "跟补模式",
            "加血技能键",
            "瞬移技能键",
            "跟补基准点",
            "空闲时坐椅子",
            "自动同意组队",
            "休息室",
            "进出自由",
            "防卡移动间隔",
            "运行日志",
            "开始运行",
        ):
            self.assertIn(text, source)
        self.assertNotIn("修正按住", source)

    def test_entrypoint_uses_modern_window(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("from ui.modern_main_window import MainWindow", source)

    def test_header_uses_packaged_icon_instead_of_emoji(self):
        source = (ROOT / "ui" / "modern_main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('resources", "app_icon.ico"', source)
        self.assertNotIn('QLabel("⚡")', source)


    def test_monitor_stop_restores_controls_before_clearing_worker(self):
        source = (ROOT / "ui" / "modern_main_window.py").read_text(
            encoding="utf-8"
        )
        stop_worker = source[source.index("    def stop_worker(self):") :]
        stop_worker = stop_worker[: stop_worker.index("    def _refresh_primary_action")]
        self.assertNotIn("self.monitor_worker = None\n        if monitor_worker", stop_worker)
        self.assertIn("self._on_monitor_stopped(monitor_worker)", stop_worker)


if __name__ == "__main__":
    unittest.main()
