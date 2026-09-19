"""A completed card can return to hold only with a durable user reason and Emma audit request."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler

from messenger.courier import CourierStore
from messenger.server import build_server


class CompletedCardHoldApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = CourierStore(root / 'messages.db')
        self.project = self.store.create_project('hold', str(root))['id']
        self.store.create_task(self.project, 'CARD-1', 'completed')
        self.store.transition_task(self.project, 'CARD-1', 'done', 1, note='accepted')
        self.server = build_server('127.0.0.1', 0, self.store.path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()

    def request(self, path, body):
        request = Request(self.base + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with self.opener.open(request) as response:
            return json.load(response)

    def test_completed_card_hold_persists_reason_and_emma_action_request(self):
        reason = '그래프의 초기값 표시가 요구사항과 다릅니다.'
        result = self.request('/api/tasks/hold', {'project_id': self.project, 'task_id': 'CARD-1', 'reason': reason})
        self.assertEqual('blocked', result['task']['state'])
        self.assertEqual(reason, result['task']['history'][-1]['note'])
        self.assertEqual('user_hold', result['task']['history'][-1]['provenance'])
        events = self.store.audit_events(self.project, task_id='CARD-1', after=0, limit=20)
        self.assertEqual('hold_request', events[-1]['kind'])
        self.assertEqual(reason, events[-1]['body'])


if __name__ == '__main__':
    unittest.main()
