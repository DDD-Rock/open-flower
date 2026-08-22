import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class DeadFlowerNavigationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "workers" / "dead_flower_worker.py").read_text(
            encoding="utf-8"
        )
        cls.tree = ast.parse(cls.source)
        cls.worker = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "DeadFlowerWorker"
        )

    def _class_constant(self, name):
        assignment = next(
            node
            for node in self.worker.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        )
        return ast.literal_eval(assignment.value)

    def test_navigation_targets_thirty_frames_per_second(self):
        assignment = next(
            node
            for node in self.worker.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "NAVIGATION_TARGET_INTERVAL"
        )
        self.assertIsInstance(assignment.value, ast.BinOp)
        self.assertIsInstance(assignment.value.op, ast.Div)
        self.assertEqual(ast.literal_eval(assignment.value.left), 1.0)
        self.assertEqual(ast.literal_eval(assignment.value.right), 30.0)

    def test_fine_adjustment_is_longer_and_always_tries_portal(self):
        self.assertEqual(self._class_constant("FINE_ADJUST_DURATION_MS"), (180, 280))
        leave_market = next(
            node
            for node in self.worker.body
            if isinstance(node, ast.FunctionDef) and node.name == "_leave_market"
        )
        calls = [
            node.func.attr
            for node in ast.walk(leave_market)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertIn("tap_direction", calls)
        self.assertIn("_try_enter_portal", calls)


if __name__ == "__main__":
    unittest.main()
