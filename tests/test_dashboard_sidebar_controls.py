"""Project-wide controls remain in the unused lower sidebar, not above the kanban."""
import unittest
from pathlib import Path


class DashboardSidebarControlsContractTest(unittest.TestCase):
    def test_mode_and_result_controls_are_grouped_at_sidebar_bottom(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("controls.id='project-controls'", html)
        self.assertIn("setup.appendChild(controls)", html)
        self.assertIn("#project-controls{margin-top:auto", html)
        self.assertIn("controls.setAttribute('aria-label','프로젝트 제어')", html)


if __name__ == "__main__":
    unittest.main()
