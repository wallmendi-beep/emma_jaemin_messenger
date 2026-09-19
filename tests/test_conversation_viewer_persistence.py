"""Conversation viewers must stay open across the dashboard polling refresh."""
import unittest
from pathlib import Path


class ConversationViewerPersistenceContractTest(unittest.TestCase):
    def test_open_audit_record_is_preserved_when_timeline_rerenders(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("let expandedAuditKeys", html)
        self.assertIn("expandedAuditKeys.add(event.event_key)", html)
        self.assertIn("box.open=expandedAuditKeys.has(event.event_key)", html)


if __name__ == "__main__":
    unittest.main()
