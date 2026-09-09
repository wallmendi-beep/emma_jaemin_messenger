"""Protocol tests use temporary memos and real loopback HTTP, never AI."""
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from messenger.server import build_server
from messenger.store import MessageStore


class ServerApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / 'messages.db'
        legacy = MessageStore(self.db)
        self.project = legacy.create_project('protocol-test', str(self.root))['id']
        for i in range(205):
            legacy.post('user', 'emma', 'INFO', str(i), project_id=self.project)
        self.server = build_server('127.0.0.1', 0, self.db)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, body=None, headers=None):
        req = urllib.request.Request(self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers or {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_protocol_fake_worker_end_to_end_and_history_readonly(self):
        self.assertEqual('memo-courier-v1', self.request('/api/health').get('mode'))
        memo = self.root / 'memo.md'
        memo.write_bytes(b'protocol fixture, not an AI response')
        h = hashlib.sha256(memo.read_bytes()).hexdigest()
        body = dict(project_id=self.project, recipient='emma', memo_path='memo.md', version_hash=h)
        item = self.request('/api/notifications', body)
        self.assertEqual(item['id'], self.request('/api/notifications', body)['id'])
        claim = self.request('/api/notifications/claim', dict(project_id=self.project, recipient='emma', worker_id='fake-protocol-worker', lease_seconds=60))['notification']
        payload = dict(project_id=self.project, claim_token=claim['claim_token'])
        self.assertEqual('read', self.request(f"/api/notifications/{item['id']}/read", dict(payload, version_hash=h))['status'])
        result = self.root / 'result.md'
        result.write_bytes(b'fake worker completed protocol fixture')
        rh = hashlib.sha256(result.read_bytes()).hexdigest()
        completed = self.request(f"/api/notifications/{item['id']}/complete", dict(payload, result_path='result.md', result_hash=rh))
        self.assertEqual('completed', completed['status'])
        listed = self.request(f'/api/notifications?project_id={self.project}')['notifications']
        self.assertEqual(rh, listed[0]['result_hash'])
        self.assertNotIn('claim_token', listed[0])
        first = self.request(f'/api/messages?project_id={self.project}')
        second = self.request(f"/api/messages?project_id={self.project}&after={first['next_after']}")
        self.assertEqual(205, len(first['messages']) + len(second['messages']))
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/messages', dict(sender='user', recipient='emma', type='INFO', body='no'))
        self.assertEqual(405, error.exception.code)
        error.exception.close()

    def test_existing_worker_adapter_reads_file_and_links_result(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('messenger.worker'), 'polling adapter missing')
        from messenger.worker import WorkerClient
        client = WorkerClient(self.base, self.project, 'emma', 'fake-protocol-worker')
        memo = self.root / 'adapter.md'
        memo.write_bytes(b'actual temporary memo')
        h = hashlib.sha256(memo.read_bytes()).hexdigest()
        client.notify('emma', str(memo), h)
        claim = client.claim()
        self.assertEqual(memo.read_bytes(), client.read(claim))
        renewed = client.renew(claim, 60)
        self.assertEqual('read', renewed['status'])
        result = self.root / 'adapter-result.md'
        result.write_bytes(b'fake worker result; no AI used')
        done = client.complete(claim, str(result), hashlib.sha256(result.read_bytes()).hexdigest())
        self.assertEqual('completed', done['status'])
        self.assertIsNone(client.claim())
        memo.write_bytes(b'new memo version')
        client.notify('emma', str(memo), hashlib.sha256(memo.read_bytes()).hexdigest())
        next_claim = client.claim()
        memo.write_bytes(b'changed after notification')
        with self.assertRaises(ValueError):
            client.read(next_claim)
        error = client.error(next_claim, 'memo changed; author must send new version')
        self.assertEqual('error', error['status'])
        with self.assertRaises(ValueError):
            WorkerClient('https://example.com', self.project, 'emma', 'no')

    def test_security_and_malformed_requests(self):
        for headers, body, status in [
            ({'Origin': 'https://evil.example'}, {}, 403),
            ({'Origin': 'http://localhost:9999'}, {}, 403),
            ({'Host': 'evil.example'}, {}, 403),
            ({'Content-Type': 'application/json'}, [], 400),
            ({'Content-Type': 'application/json'}, {'project_id':1}, 400),
        ]:
            with self.subTest(headers=headers, body=body):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.request('/api/notifications', body, headers)
                self.assertEqual(status, error.exception.code)
                error.exception.close()

    def test_courier_ui_and_loopback_only(self):
        with urllib.request.urlopen(self.base) as response:
            html = response.read().decode()
        for text in ['id="memo-form"', 'id="history"', 'pending', 'claimed', 'read', 'completed', 'error', '기존 작업 세션']:
            self.assertIn(text, html)
        with self.assertRaises(ValueError):
            build_server('0.0.0.0', 0, self.root / 'unsafe.db')


if __name__ == '__main__':
    unittest.main()
