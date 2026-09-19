import unittest
from pathlib import Path


class CompletedCardHoldPanelTest(unittest.TestCase):
    def test_completed_card_can_submit_a_required_hold_reason(self):
        html = (Path(__file__).resolve().parents[1] / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="hold-card"', html)
        self.assertIn('보류 사유', html)
        self.assertIn('/api/tasks/hold', html)
        self.assertIn("hold.hidden=t.state!=='done'", html)


if __name__ == '__main__':
    unittest.main()
