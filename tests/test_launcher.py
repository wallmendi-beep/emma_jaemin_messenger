import tempfile
import unittest
from pathlib import Path

from messenger.launcher import build_runtime


class LauncherTest(unittest.TestCase):
    def test_windows_launcher_reopens_browser_when_server_is_already_running(self):
        launcher = Path(__file__).resolve().parent.parent / "Start Messenger.bat"
        text = launcher.read_text(encoding="utf-8")
        self.assertIn("curl.exe", text)
        self.assertIn("http://127.0.0.1:8765/api/health", text)
        self.assertIn('start "" "http://127.0.0.1:8765"', text)

    def test_runtime_is_server_only_no_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "messages.db"
            runtime = build_runtime(db, port=0)
            try:
                self.assertFalse(isinstance(runtime, tuple), 'launcher still creates a bridge')
                self.assertGreater(runtime.server_port, 0)
            finally:
                (runtime[0] if isinstance(runtime, tuple) else runtime).server_close()


if __name__ == "__main__":
    unittest.main()
