"""Durable local memo metadata courier. Never runs agents or writes memos."""
import hashlib
import re
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import closing

from .store import MessageStore


class CourierStore(MessageStore):
    def __init__(self, path):
        path = Path(path)
        if path.exists():
            with closing(sqlite3.connect(path)) as source:
                exists = source.execute("SELECT 1 FROM sqlite_master WHERE name='notifications'").fetchone()
                if not exists:
                    backup = path.with_name(path.name + '.pre-courier-' + uuid.uuid4().hex + '.bak')
                    with closing(sqlite3.connect(backup)) as target:
                        source.backup(target)
        super().__init__(path)
        with self._connect() as con:
            # Replace only obsolete built-in rules; preserve user project rules/history.
            con.executemany('DELETE FROM global_rules WHERE text=?', [(text,) for text in (
                '메신저는 127.0.0.1에서만 작동하며 협업 내용을 외부로 전송하지 않는다.',
                '사용자 판단이 필요하면 자동협의를 멈추고 답변을 기다린다.',
                '자동협의는 정해진 왕복 상한 안에서만 진행한다.',
            )])
            con.executescript('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL, recipient TEXT NOT NULL,
                    memo_path TEXT NOT NULL, version_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL,
                    worker_id TEXT, claim_token TEXT, lease_until REAL,
                    attempts INTEGER NOT NULL DEFAULT 0, read_at REAL, completed_at REAL,
                    result_path TEXT, result_hash TEXT, error TEXT,
                    UNIQUE(project_id,recipient,memo_path,version_hash)
                );
                CREATE INDEX IF NOT EXISTS notification_queue ON notifications(project_id,recipient,status,id);
                CREATE TRIGGER IF NOT EXISTS history_no_insert BEFORE INSERT ON messages
                BEGIN SELECT RAISE(ABORT,'legacy history is read-only'); END;
                CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON messages
                BEGIN SELECT RAISE(ABORT,'legacy history is read-only'); END;
                CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON messages
                BEGIN SELECT RAISE(ABORT,'legacy history is read-only'); END;
            ''')

    def get_project(self, project_id):
        # Do not validate int(value) then persist the original fractional ID.
        if type(project_id) is not int or not 1 <= project_id <= 9223372036854775807:
            raise ValueError('project_id must be a positive SQLite integer')
        return super().get_project(project_id)

    def memo(self, project_id, memo_path, version_hash):
        project = self.get_project(project_id)
        if not project['workspace'] or project['archived']:
            raise ValueError('active project with workspace required')
        root = Path(project['workspace']).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('workspace must be a directory')
        if not isinstance(memo_path, str) or not memo_path:
            raise ValueError('memo_path required')
        path = (root / memo_path).resolve(strict=True)
        if not path.is_relative_to(root) or path.suffix.lower() != '.md' or not path.is_file():
            raise ValueError('memo must be an existing .md file inside project workspace')
        if not isinstance(version_hash, str) or not re.fullmatch('[0-9a-f]{64}', version_hash):
            raise ValueError('version_hash must be lowercase SHA-256 hex')
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('memo exceeds 4 MiB')
        if hashlib.sha256(path.read_bytes()).hexdigest() != version_hash:
            raise ValueError('memo version mismatch')
        return str(path)

    def notify(self, project_id, recipient, memo_path, version_hash):
        if recipient not in {'emma', 'jaemin', 'user'}:
            raise ValueError('unsupported recipient')
        path = self.memo(project_id, memo_path, version_hash)
        with self._connect() as con:
            con.execute('INSERT OR IGNORE INTO notifications(project_id,recipient,memo_path,version_hash,created_at) VALUES(?,?,?,?,?)',
                        (project_id, recipient, path, version_hash, time.time()))
            return dict(con.execute('SELECT * FROM notifications WHERE project_id=? AND recipient=? AND memo_path=? AND version_hash=?',
                                    (project_id, recipient, path, version_hash)).fetchone())

    @staticmethod
    def lease_seconds(value):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3600:
            raise ValueError('lease_seconds must be integer 1..3600')
        return value

    def claim(self, project_id, recipient, worker_id, lease_seconds=120):
        if self.get_project(project_id)['archived']:
            raise ValueError('active project required')
        if recipient not in {'emma', 'jaemin', 'user'}:
            raise ValueError('unsupported recipient')
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 200:
            raise ValueError('worker_id required, max 200 characters')
        duration = self.lease_seconds(lease_seconds)
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            now = time.time()
            row = con.execute("SELECT * FROM notifications WHERE project_id=? AND recipient=? AND (status='pending' OR (status IN ('claimed','read') AND lease_until<=?)) ORDER BY id LIMIT 1",
                              (project_id, recipient, now)).fetchone()
            if row is None:
                return None
            con.execute("UPDATE notifications SET status='claimed',worker_id=?,claim_token=?,lease_until=?,attempts=attempts+1,read_at=NULL,error=NULL WHERE id=?",
                        (worker_id, uuid.uuid4().hex, now + duration, row['id']))
            return dict(con.execute('SELECT * FROM notifications WHERE id=?', (row['id'],)).fetchone())

    def ack(self, project_id, notification_id, claim_token, action, **payload):
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM notifications WHERE id=? AND project_id=?', (notification_id, project_id)).fetchone()
            now = time.time()
            if row is None or not claim_token or row['claim_token'] != claim_token or row['status'] not in {'claimed', 'read'} or row['lease_until'] <= now:
                raise ValueError('claim missing, expired, stale, or terminal')
            if action == 'read':
                if payload.get('version_hash') != row['version_hash']:
                    raise ValueError('read hash mismatch')
                self.memo(project_id, row['memo_path'], row['version_hash'])
                con.execute("UPDATE notifications SET status='read',read_at=? WHERE id=?", (now, notification_id))
            elif action == 'complete':
                if row['status'] != 'read':
                    raise ValueError('ack read before completion')
                path = self.memo(project_id, payload.get('result_path'), payload.get('result_hash'))
                con.execute("UPDATE notifications SET status='completed',completed_at=?,result_path=?,result_hash=?,lease_until=NULL WHERE id=?",
                            (now, path, payload['result_hash'], notification_id))
            elif action == 'renew':
                con.execute('UPDATE notifications SET lease_until=? WHERE id=?', (now + self.lease_seconds(payload.get('lease_seconds', 120)), notification_id))
            elif action == 'error':
                error = payload.get('error')
                if not isinstance(error, str) or not error.strip() or len(error) > 2000:
                    raise ValueError('error required, max 2000 characters')
                con.execute("UPDATE notifications SET status='error',error=?,lease_until=NULL WHERE id=?", (error, notification_id))
            else:
                raise ValueError('unsupported acknowledgement')
            return dict(con.execute('SELECT * FROM notifications WHERE id=?', (notification_id,)).fetchone())

    def notifications(self, project_id, after=0, limit=200):
        self.get_project(project_id)
        with self._connect() as con:
            return [dict(r) for r in con.execute('SELECT * FROM notifications WHERE project_id=? AND id>? ORDER BY id LIMIT ?',
                                                (project_id, max(0, int(after)), min(500, max(1, int(limit)))))]
