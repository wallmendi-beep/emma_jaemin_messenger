import unittest
from pathlib import Path


class SerialWaitLabelTest(unittest.TestCase):
    def test_unstarted_serial_cards_are_waiting_and_post_completion_holds_are_distinct(self):
        html = (Path(__file__).resolve().parents[1] / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn("blocked:'보류'", html)
        self.assertIn("const displayLanes=[['waiting','대기',['todo']]", html)
        self.assertIn("['blocked','보류',['blocked']]", html)


if __name__ == '__main__':
    unittest.main()
