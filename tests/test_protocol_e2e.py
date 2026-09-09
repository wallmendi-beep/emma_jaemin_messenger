"""Real HTTP + temporary SQLite/files; protocol fixtures, NOT AI execution."""
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from messenger.server import build_server
from messenger.worker import WorkerClient


class DurableProtocolE2E(unittest.TestCase):
    def test_roundtrip_restart_and_security(self):
        with tempfile.TemporaryDirectory(prefix='memo-courier-e2e-') as tmp:
            root = Path(tmp)
            db = root / 'temporary.db'
            workspace = root / 'workspace'
            workspace.mkdir()
            (root / 'outside.md').write_bytes(b'outside project fixture')
            opener = build_opener(ProxyHandler({}))
            server = None
            thread = None

            def start():
                nonlocal server, thread, base
                server = build_server('127.0.0.1', 0, db)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'

            def stop():
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

            def request(path, payload=None, headers=None):
                req = Request(base + path,
                    data=None if payload is None else json.dumps(payload).encode(),
                    headers=headers or {'Content-Type': 'application/json'})
                with opener.open(req, timeout=10) as response:
                    return json.load(response)

            def memo(name, text):
                p = workspace / name
                p.write_text(text, encoding='utf-8')
                return p, hashlib.sha256(p.read_bytes()).hexdigest()

            base = ''
            start()
            try:
                self.assertFalse(request('/api/health')['agent_spawning'])
                project = request('/api/projects', {'name': 'HTTP E2E fixture', 'workspace': str(workspace)})['id']
                emma = WorkerClient(base, project, 'emma', 'fixture-emma')
                first, first_hash = memo('request-v1.md', '# 프로토콜 시험\nAI 작업 아님\n')
                n = emma.notify('emma', str(first), first_hash)
                self.assertEqual(n['id'], emma.notify('emma', str(first), first_hash)['id'])
                claim = emma.claim(60)
                self.assertIsNone(emma.claim())
                stop()
                start()  # Real server restart against the SAME temporary database.
                emma = WorkerClient(base, project, 'emma', 'fixture-emma')
                self.assertEqual(first.read_bytes(), emma.read(claim))
                self.assertEqual('read', emma.renew(claim, 60)['status'])
                review, review_hash = memo('review-v1.md', '# Fixture review\nNo AI used.\n')
                emma.complete(claim, str(review), review_hash)
                emma.notify('jaemin', str(review), review_hash)
                jaemin = WorkerClient(base, project, 'jaemin', 'fixture-jaemin')
                second = jaemin.claim(60)
                self.assertEqual(review.read_bytes(), jaemin.read(second))
                reply, reply_hash = memo('reply-v1.md', '# Fixture reply\nNo project work performed.\n')
                jaemin.complete(second, str(reply), reply_hash)
                jaemin.notify('emma', str(reply), reply_hash)
                third = emma.claim(60)
                self.assertEqual(reply.read_bytes(), emma.read(third))
                final, final_hash = memo('final-v1.md', '# Fixture receipt\nProtocol roundtrip only.\n')
                emma.complete(third, str(final), final_hash)
                rows = request(f'/api/notifications?project_id={project}')['notifications']
                self.assertEqual(['completed'] * 3, [r['status'] for r in rows])
                self.assertEqual([review_hash, reply_hash, final_hash], [r['result_hash'] for r in rows])
                self.assertTrue(all('claim_token' not in r for r in rows))
                self.assertEqual([], request('/api/notifications?project_id=1')['notifications'])
                invalid = dict(project_id=project, recipient='emma', memo_path=str(first), version_hash='0' * 64)
                for path, payload, headers, expected in [
                    ('/api/notifications', invalid, None, 400),
                    ('/api/notifications', dict(invalid, project_id=project + .5), None, 400),
                    ('/api/notifications', dict(invalid, memo_path='../outside.md', version_hash=hashlib.sha256(b'outside project fixture').hexdigest()), None, 400),
                    ('/api/notifications', {}, {'Origin': 'https://evil.example'}, 403),
                    ('/api/health', None, {'Host': 'evil.example'}, 403),
                    ('/api/messages', {}, None, 405),
                ]:
                    with self.assertRaises(HTTPError) as error:
                        request(path, payload, headers)
                    self.assertEqual(expected, error.exception.code)
                    error.exception.close()
                self.assertIsNone(emma.claim())
                self.assertIsNone(jaemin.claim())
                print('HTTP E2E: 3 completed handoffs; 4 actual UTF-8 temp memos; '
                      'restart preserved claim; dedupe/isolation/token-redaction verified; '
                      '6 rejection checks passed; no AI or live DB used.', flush=True)
            finally:
                stop()


if __name__ == '__main__':
    unittest.main()
