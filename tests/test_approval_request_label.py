import unittest
from pathlib import Path


class ApprovalRequestLabelTest(unittest.TestCase):
    def test_review_remains_review_and_is_not_renamed_as_a_user_approval_gate(self):
        html = (Path(__file__).resolve().parents[1] / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn("review:'검수'", html)
        self.assertNotIn("?'승인 요청':states[state]", html)


if __name__ == '__main__':
    unittest.main()
