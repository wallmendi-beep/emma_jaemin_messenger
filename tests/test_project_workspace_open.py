"""The monitor may open only the selected project's registered workspace."""
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from messenger.server import build_server
from messenger.store import MessageStore


class ProjectWorkspaceOpenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "approved-output"
        self.workspace.mkdir()
        self.db = self.root / "messages.db"
        self.project_id = MessageStore(self.db).create_project("serial project", str(self.workspace))["id"]
        self.opened = []
        self.server = build_server("127.0.0.1", 0, self.db, folder_opener=self.opened.append)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def test_open_workspace_uses_only_the_registered_project_path(self):
        request = urllib.request.Request(
            self.base + "/api/projects/open-workspace",
            data=json.dumps({"project_id": self.project_id}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            result = json.load(response)
        self.assertEqual(str(self.workspace.resolve()), result["workspace"])
        self.assertEqual([self.workspace.resolve()], self.opened)


if __name__ == "__main__":
    unittest.main()
