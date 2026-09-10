import unittest
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from messenger.courier import CourierStore


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CourierStore(Path(self.tmp.name) / 'test.db')
        self.project = self.store.create_project('test', self.tmp.name)['id']

    def test_parallel_tasks_persist_exact_ids_and_zero_progress(self):
        self.assertTrue(hasattr(self.store, 'create_task'), 'task persistence missing')
        self.assertEqual(self.store.task_summary(self.project)['total'], 0)
        for key in ['RM-BIND-003', 'other-task']:
            self.store.create_task(self.project, key, 'Review', 'Scope only')
        reopened = CourierStore(self.store.path)
        self.assertEqual([t['task_id'] for t in reopened.tasks(self.project)], ['RM-BIND-003', 'other-task'])
        self.assertEqual(reopened.task_summary(self.project)['completed'], 0)
        self.assertEqual(reopened.task_summary(self.project)['total'], 2)
        with self.assertRaises(ValueError):
            self.store.create_task(self.project, ' RM-BIND-004 ', 'bad')

    def test_transition_history_and_worker_claim_provenance(self):
        import hashlib
        self.store.create_task(self.project, 'T-1', 'Work')
        self.assertTrue(hasattr(self.store, 'transition_task'), 'transition missing')
        t = self.store.transition_task(self.project, 'T-1', 'in_progress', 1)
        self.assertEqual(t['history'][-1]['provenance'], 'manual')
        with self.assertRaises(ValueError):
            self.store.transition_task(self.project, 'T-1', 'done', 1)
        path = Path(self.tmp.name) / 'memo.md'
        path.write_bytes(b'fixture')
        digest = hashlib.sha256(b'fixture').hexdigest()
        n = self.store.notify(self.project, 'emma', str(path), digest, task_id='T-1')
        self.assertEqual(n['task_id'], 'T-1')
        with self.assertRaises(ValueError):
            self.store.notify(self.project, 'emma', str(path), digest, task_id='other')
        with self.assertRaises(ValueError):
            self.store.transition_task(self.project, 'T-1', 'done', 2, notification_id=n['id'], claim_token='bad')
        claim = self.store.claim(self.project, 'emma', 'fixture-worker')
        t = self.store.transition_task(self.project, 'T-1', 'review', 2, notification_id=n['id'], claim_token=claim['claim_token'])
        self.assertEqual(t['history'][-1]['provenance'], 'worker_reported')
        self.assertEqual(t['history'][-1]['actor'], 'fixture-worker')
        self.assertNotIn('claim_token', str(t))
        self.store.transition_task(self.project, 'T-1', 'done', 3)
        self.assertEqual(self.store.task_summary(self.project)['completed'], 1)

    def test_http_dashboard_contract(self):
        import json, threading
        from urllib.request import Request, build_opener, ProxyHandler
        from messenger.server import build_server
        server = build_server(port=0, db_path=self.store.path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = build_opener(ProxyHandler({}))
        base = f'http://127.0.0.1:{server.server_port}'
        def request(path, body=None):
            with opener.open(Request(base+path, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type':'application/json'})) as r:
                return json.load(r)
        try:
            with opener.open(base) as r:
                html = r.read().decode()
            self.assertIn('const changed=', html)
            self.assertIn('id="kanban"', html)
            self.assertIn('localStorage', html)
            self.assertIn('자동 깨우기 미구현', html)
            t = request('/api/tasks', dict(project_id=self.project, task_id='HTTP-1', title='HTTP'))
            self.assertEqual(t['task_id'], 'HTTP-1')
            t = request('/api/tasks/transition', dict(project_id=self.project, task_id='HTTP-1', state='done', expected_revision=1))
            self.assertEqual(t['revision'], 2)
            self.assertEqual(request(f'/api/tasks?project_id={self.project}')['summary']['completed'], 1)
            self.assertEqual(len(request(f'/api/tasks/detail?project_id={self.project}&task_id=HTTP-1')['history']), 2)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_http_transition_rejects_malformed_notification_id_as_json(self):
        import json, threading
        from urllib.error import HTTPError
        from urllib.request import Request, build_opener, ProxyHandler
        from messenger.server import build_server
        self.store.create_task(self.project, 'HTTP-BAD-ID', 'Malformed worker report')
        server = build_server(port=0, db_path=self.store.path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = build_opener(ProxyHandler({}))
        body = json.dumps(dict(
            project_id=self.project, task_id='HTTP-BAD-ID', state='done',
            expected_revision=1, notification_id=[], claim_token='claim-token',
        )).encode()
        try:
            request = Request(
                f'http://127.0.0.1:{server.server_port}/api/tasks/transition',
                data=body, headers={'Content-Type': 'application/json'},
            )
            with self.assertRaises(HTTPError) as caught:
                opener.open(request)
            self.assertEqual(caught.exception.code, 400)
            with caught.exception as response:
                payload = json.load(response)
            self.assertIsInstance(payload.get('error'), str)
            self.assertTrue(payload['error'])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_task_detail_uses_one_read_snapshot(self):
        self.store.create_task(self.project, 'SNAPSHOT-1', 'Snapshot detail')
        original_connect = self.store._connect
        main_thread = threading.current_thread()
        start_writer = threading.Event()
        writer_done = threading.Event()

        class CursorProxy:
            def __init__(self, cursor):
                self.cursor = cursor

            def fetchone(self):
                row = self.cursor.fetchone()
                start_writer.set()
                time.sleep(0.15)
                return row

            def __getattr__(self, name):
                return getattr(self.cursor, name)

        class ConnectionProxy:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, parameters=()):
                cursor = self.connection.execute(sql, parameters)
                if sql.startswith('SELECT * FROM tasks WHERE project_id='):
                    return CursorProxy(cursor)
                return cursor

            def __getattr__(self, name):
                return getattr(self.connection, name)

        @contextmanager
        def controlled_connect():
            with original_connect() as connection:
                if threading.current_thread() is main_thread:
                    yield ConnectionProxy(connection)
                else:
                    yield connection

        def writer():
            start_writer.wait(2)
            self.store.transition_task(self.project, 'SNAPSHOT-1', 'in_progress', 1)
            writer_done.set()

        self.store._connect = controlled_connect
        thread = threading.Thread(target=writer)
        thread.start()
        try:
            detail = self.store.task_detail(self.project, 'SNAPSHOT-1')
        finally:
            thread.join(2)
            self.store._connect = original_connect
        self.assertTrue(writer_done.is_set())
        self.assertEqual(len(detail['history']), detail['revision'])

    def test_http_task_rows_and_summary_share_one_snapshot(self):
        import json
        from urllib.request import build_opener, ProxyHandler
        from messenger.server import build_server
        self.store.create_task(self.project, 'BOARD-1', 'Snapshot board')
        original_tasks = self.store.tasks
        transitioned = False

        def transition_between_reads(project_id):
            nonlocal transitioned
            rows = original_tasks(project_id)
            if not transitioned:
                transitioned = True
                self.store.transition_task(self.project, 'BOARD-1', 'done', 1)
            return rows

        self.store.tasks = transition_between_reads
        server = build_server(port=0, db_path=self.store.path)
        server.RequestHandlerClass = __import__('messenger.server', fromlist=['_handler_factory'])._handler_factory(
            self.store, Path(__file__).resolve().parents[1] / 'static' / 'index.html'
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(f'http://127.0.0.1:{server.server_port}/api/tasks?project_id={self.project}') as response:
                payload = json.load(response)
        finally:
            server.shutdown(); server.server_close(); thread.join()
            self.store.tasks = original_tasks
        row_counts = {state: sum(task['state'] == state for task in payload['tasks'])
                      for state in ('todo', 'in_progress', 'review', 'blocked', 'done')}
        self.assertEqual(payload['summary']['states'], row_counts)
        self.assertEqual(payload['summary']['completed'], row_counts['done'])

if __name__ == '__main__':
    unittest.main()
