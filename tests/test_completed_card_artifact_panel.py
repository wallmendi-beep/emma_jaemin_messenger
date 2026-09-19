import unittest
from pathlib import Path


class CompletedCardArtifactPanelTest(unittest.TestCase):
    def test_selected_card_loads_its_artifacts_and_opens_an_explicit_choice(self):
        html = (Path(__file__).resolve().parents[1] / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn("id=\"task-artifacts\"", html)
        self.assertIn('/api/tasks/artifacts?project_id=', html)
        self.assertIn('/api/tasks/open-artifact', html)
        self.assertIn('부분 결과물', html)


if __name__ == '__main__':
    unittest.main()
