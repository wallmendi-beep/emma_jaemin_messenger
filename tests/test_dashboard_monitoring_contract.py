"""The human dashboard is a monitor, not an instruction console."""
import unittest
from pathlib import Path


class DashboardMonitoringContractTest(unittest.TestCase):
    def test_redesign_removes_manual_instruction_controls_from_monitor_surface(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function monitoringOnlyDashboard", html)
        self.assertIn("projectForm.closest('details').remove()", html)
        self.assertIn("taskForm.remove()", html)
        self.assertIn("memoForm.closest('details').remove()", html)
        self.assertIn("자동 기록을 보는 화면", html)


if __name__ == "__main__":
    unittest.main()
