"""Contract for the action-first Doorbell dashboard."""
import unittest
from pathlib import Path


class DashboardRedesignContractTest(unittest.TestCase):
    def test_dashboard_prioritizes_actionable_collaboration_state(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
        for required in [
            'id="action-now"',
            "setup.dataset.surface='project-workspace'",
            "detail.id='artifact-review'",
            "audit.id='doorbell-flow'",
            '현재 할 일',
            '초인종 흐름',
            '산출물 · 검수',
            'function selectDoorbell',
        ]:
            self.assertIn(required, html)


if __name__ == "__main__":
    unittest.main()
