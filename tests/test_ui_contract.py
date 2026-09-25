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
            "混合模式",
            "左右走模式",
            "智能走",
            "识别并标记",
            "触发间隔",
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
        self.assertNotIn("左右走防卡", source)

        walking_worker = (ROOT / "workers" / "follow_heal_walking_worker.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("teleport_key", walking_worker)
        self.assertNotIn("perform_directional_skill", walking_worker)

    def test_entrypoint_uses_modern_window(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("from ui.modern_main_window import MainWindow", source)
        self.assertIn('action in {"unbind", "kick"}', source)

    def test_window_identification_prompt_does_not_name_game_keywords(self):
        source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
        self.assertNotIn("冒险岛", source)
        self.assertNotIn("'Maple'等关键词", source)

    def test_modes_are_gated_by_account_authorization(self):
        source = (ROOT / "ui" / "modern_main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def apply_authorized_modes", source)
        self.assertIn("if self.mode not in self.authorized_modes", source)
        self.assertIn("button.setVisible(mode in self.authorized_modes)", source)
        self.assertNotIn('self.authorized_modes.add("emulator")', source)
        self.assertIn('"emulator"', (ROOT / "utils" / "account_manager.py").read_text(encoding="utf-8"))

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

    def test_emulator_mode_scans_automatically_without_footer_action(self):
        window_source = (ROOT / "ui" / "modern_main_window.py").read_text(
            encoding="utf-8"
        )
        panel_source = (ROOT / "ui" / "emulator_panel.py").read_text(
            encoding="utf-8"
        )

        switch_mode = window_source[
            window_source.index("    def _switch_mode_tab(self, mode):") :
        ]
        switch_mode = switch_mode[: switch_mode.index("    def apply_authorized_modes")]
        self.assertIn("self._start_emulator_worker()", switch_mode)
        self.assertIn(
            'self.control_footer.setVisible(self.mode != "emulator")',
            window_source,
        )
        self.assertNotIn("停止识别", window_source)
        self.assertIn("ScrollBarAlwaysOff", panel_source)
        self.assertNotIn("emulator_page_layout.addStretch", window_source)


if __name__ == "__main__":
    unittest.main()
