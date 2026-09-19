"""Monitoring shows a project only as complete after every registered card completes."""
import unittest
from pathlib import Path


class ProjectCompletionDashboardContractTest(unittest.TestCase):
    def test_completion_marker_and_workspace_button_are_project_bound(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
        for text in [
            'id="project-complete"',
            'id="open-workspace"',
            'function renderProjectCompletion',
            's.completed===s.total',
            '/api/projects/open-workspace',
        ]:
            self.assertIn(text, html)


if __name__ == "__main__":
    unittest.main()
