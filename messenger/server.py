from __future__ import annotations

import argparse
import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from .courier import CourierStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / 'data' / 'messages.db'
DEFAULT_INDEX = PROJECT_ROOT / 'static' / 'index.html'


def _handler_factory(store, index_path):
    class MessengerHandler(BaseHTTPRequestHandler):
        server_version = 'MemoCourier/1'

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, fmt, *args):
            pass

        def send(self, payload, status=200, html=False):
            data = payload if html else json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            host = self.headers.get('Host')
            origin = self.headers.get('Origin')
            if host not in hosts or (origin is not None and origin != 'http://' + host):
                self.send({'error': 'foreign origin or host rejected'}, 403)
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == '/api/health':
                    return self.send({'status': 'ok', 'mode': 'memo-courier-v1', 'agent_spawning': False, 'dashboard': 'tasks-v1', 'worker_connection': 'unverified', 'auto_wakeup': False})
                if parsed.path in {'/', '/index.html'}:
                    return self.send(index_path.read_bytes(), html=True)
                if parsed.path == '/api/projects':
                    return self.send({'projects': store.list_projects()})
                project_id = int(query.get('project_id', ['1'])[0])
                store.get_project(project_id)
                if parsed.path == '/api/tasks':
                    return self.send(store.task_board(project_id))
                if parsed.path == '/api/tasks/detail':
                    return self.send(store.task_detail(project_id, query.get('task_id', [''])[0]))
                if parsed.path == '/api/rules':
                    return self.send({'global_rules': store.list_global_rules(), 'project_rules': store.list_project_rules(project_id)})
                after = int(query.get('after', ['0'])[0])
                limit = min(500, max(1, int(query.get('limit', ['200'])[0])))
                if parsed.path == '/api/messages':
                    rows = store.list_messages(after_id=after, limit=limit, project_id=project_id)
                    return self.send({'messages': rows, 'readonly': True, 'next_after': rows[-1]['id'] if rows else after})
                if parsed.path == '/api/notifications':
                    rows = store.notifications(project_id, after, limit)
                    for row in rows:
                        row.pop('claim_token', None)
                    return self.send({'notifications': rows, 'next_after': rows[-1]['id'] if rows else after})
                self.send({'error': 'not found'}, 404)
            except (ValueError, TypeError, OSError) as exc:
                self.send({'error': str(exc)}, 400)

        def do_POST(self):
            if not self.allowed():
                return
            path = urlparse(self.path).path
            if path == '/api/messages':
                return self.send({'error': 'legacy history is read-only; use /api/notifications'}, 405)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('invalid body length')
                payload = json.loads(self.rfile.read(length).decode('utf-8'))
                if not isinstance(payload, dict):
                    raise ValueError('JSON object required')
                if path == '/api/projects':
                    result = store.create_project(payload.get('name', ''), payload.get('workspace', ''))
                elif path == '/api/tasks':
                    result = store.create_task(payload['project_id'], payload['task_id'], payload['title'], payload.get('description', ''))
                elif path == '/api/tasks/transition':
                    result = store.transition_task(payload['project_id'], payload['task_id'], payload['state'], payload['expected_revision'], payload.get('note', ''), payload.get('notification_id'), payload.get('claim_token'))
                elif path == '/api/notifications':
                    result = store.notify(payload['project_id'], payload['recipient'], payload['memo_path'], payload['version_hash'], payload.get('task_id'))
                    result.pop('claim_token', None)
                elif path == '/api/notifications/claim':
                    result = {'notification': store.claim(payload['project_id'], payload['recipient'], payload['worker_id'], payload.get('lease_seconds', 120))}
                elif re.fullmatch(r'/api/notifications/[0-9]+/(read|complete|renew|error)', path):
                    parts = path.split('/')
                    project_id = payload.pop('project_id')
                    token = payload.pop('claim_token')
                    result = store.ack(project_id, int(parts[3]), token, parts[4], **payload)
                elif path == '/api/rules':
                    result = store.add_project_rule(payload['project_id'], payload['text'], source='user', status='active')
                elif re.fullmatch(r'/api/rules/[0-9]+/approve', path):
                    result = store.approve_project_rule(int(path.split('/')[3]))
                else:
                    return self.send({'error': 'not found'}, 404)
                self.send(result, 200)
            except (ValueError, TypeError, KeyError, OSError, sqlite3.IntegrityError) as exc:
                self.send({'error': str(exc)}, 400)
            except sqlite3.OperationalError:
                self.send({'error': 'database unavailable; retry later'}, 503)
    return MessengerHandler


def build_server(host='127.0.0.1', port=8765, db_path=DEFAULT_DB, index_path=DEFAULT_INDEX):
    if host not in {'127.0.0.1', 'localhost'}:
        raise ValueError('courier must bind IPv4 loopback only')
    return ThreadingHTTPServer(('127.0.0.1', int(port)), _handler_factory(CourierStore(db_path), Path(index_path)))


def main():
    parser = argparse.ArgumentParser(description='Local memo courier; no AI spawning')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    server = build_server(args.host, args.port, args.db)
    print(f'Memo courier: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
