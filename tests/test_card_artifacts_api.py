"""Completed card selection exposes only its audited, workspace-contained artifacts."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler

from messenger.courier import CourierStore
from messenger.server import build_server


class CardArtifactsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = CourierStore(self.root / 'messages.db')
        self.project = self.store.create_project('artifacts', str(self.root))['id']
        self.store.create_task(self.project, 'CARD-1', 'result')
        self.store.transition_task(self.project, 'CARD-1', 'done', 1, note='accepted')
        run = self.root / 'CARD-1-run1'
        run.mkdir()
        (run / 'result.html').write_text('<!doctype html><title>result</title>', encoding='utf-8')
        (run / 'report-v2.md').write_text('final report', encoding='utf-8')
        self.store.record_audit_event(
            project_id=self.project, event_key='artifact:approval', task_id='CARD-1', run_id='run-1',
            profile='test', sender='emma', recipient='jaemin', kind='decision', body='APPROVE',
            artifact_path='CARD-1-run1/report-v2.md', artifact_sha256='a' * 64,
        )
        self.opened = []
        self.server = build_server('127.0.0.1', 0, self.store.path, folder_opener=self.opened.append)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()

    def request(self, path, body=None):
        request = Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with self.opener.open(request) as response:
            return json.load(response)

    def test_lists_and_opens_only_audited_card_artifacts(self):
        artifacts = self.request(f'/api/tasks/artifacts?project_id={self.project}&task_id=CARD-1')['artifacts']
        self.assertEqual(['CARD-1-run1/report-v2.md', 'CARD-1-run1/result.html'], [row['path'] for row in artifacts])
        opened = self.request('/api/tasks/open-artifact', {'project_id': self.project, 'task_id': 'CARD-1', 'path': 'CARD-1-run1/result.html'})
        self.assertEqual('CARD-1-run1/result.html', opened['path'])
        self.assertEqual((self.root / 'CARD-1-run1' / 'result.html').resolve(), self.opened[-1])


if __name__ == '__main__':
    unittest.main()
