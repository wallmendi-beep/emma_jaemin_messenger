import tempfile
import unittest
from pathlib import Path

from messenger.launcher import build_runtime


class LauncherTest(unittest.TestCase):
    def test_runtime_builds_server_and_bridge_on_the_same_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "messages.db"
            server, bridge = build_runtime(db, port=0)
            try:
                self.assertGreater(server.server_port, 0)
                self.assertEqual(db, bridge.store.path)
                self.assertEqual(6, bridge.max_exchanges)
            finally:
                server.server_close()


if __name__ == "__main__":
    unittest.main()
