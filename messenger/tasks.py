"""Project-scoped task metadata. No execution permissions or worker presence."""
import re
import time

STATES = ('todo', 'in_progress', 'review', 'blocked', 'done')


class TaskMixin:
    def initialize_tasks(self):
        with self._connect() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS tasks (
                    project_id INTEGER NOT NULL, task_id TEXT NOT NULL,
                    title TEXT NOT NULL, description TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'todo', revision INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(project_id, task_id)
                );
                CREATE TABLE IF NOT EXISTS task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
                    task_id TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL,
                    provenance TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
            ''')

    @staticmethod
    def validate_task_id(task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', task_id):
            raise ValueError('task_id must be 1..100 ASCII letters/digits/._-; IDs are never normalized')

    def create_task(self, project_id, task_id, title, description=''):
        if self.get_project(project_id)['archived']:
            raise ValueError('active project required')
        self.validate_task_id(task_id)
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError('title required, max 200 characters')
        if not isinstance(description, str) or len(description) > 10000:
            raise ValueError('description max 10000 characters')
        now = time.time()
        with self._connect() as con:
            con.execute('INSERT INTO tasks(project_id,task_id,title,description,created_at,updated_at) VALUES(?,?,?,?,?,?)', (project_id, task_id, title, description, now, now))
            con.execute("INSERT INTO task_history(project_id,task_id,to_state,provenance,actor,note,created_at) VALUES(?,?,'todo','manual','user','created',?)", (project_id, task_id, now))
        return self.task_detail(project_id, task_id)

    def transition_task(self, project_id, task_id, state, expected_revision, note='', notification_id=None, claim_token=None):
        if self.get_project(project_id)['archived']:
            raise ValueError('active project required')
        self.validate_task_id(task_id)
        if state not in STATES or type(expected_revision) is not int:
            raise ValueError('valid state and integer expected_revision required')
        if not isinstance(note, str) or len(note) > 2000:
            raise ValueError('note max 2000 characters')
        worker_report = notification_id is not None or claim_token is not None
        if worker_report:
            if type(notification_id) is not int or notification_id <= 0:
                raise ValueError('notification_id must be a positive integer for worker report')
            if not isinstance(claim_token, str) or not claim_token or len(claim_token) > 128:
                raise ValueError('claim_token must be a nonempty string, max 128 characters')
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM tasks WHERE project_id=? AND task_id=?', (project_id, task_id)).fetchone()
            if row is None or row['revision'] != expected_revision:
                raise ValueError('task missing or stale revision; reload')
            provenance, actor = 'manual', 'user'
            now = time.time()
            if worker_report:
                claim = con.execute('SELECT * FROM notifications WHERE id=? AND project_id=? AND task_id=?', (notification_id, project_id, task_id)).fetchone()
                if not claim or not claim_token or claim['claim_token'] != claim_token or claim['status'] not in ('claimed', 'read') or claim['lease_until'] <= now:
                    raise ValueError('live linked claim required for worker report')
                provenance, actor = 'worker_reported', claim['worker_id']
            if row['state'] == state:
                raise ValueError('state unchanged')
            con.execute('UPDATE tasks SET state=?, revision=revision+1, updated_at=? WHERE project_id=? AND task_id=?', (state, now, project_id, task_id))
            con.execute('INSERT INTO task_history(project_id,task_id,from_state,to_state,provenance,actor,note,created_at) VALUES(?,?,?,?,?,?,?,?)', (project_id, task_id, row['state'], state, provenance, actor, note, now))
        return self.task_detail(project_id, task_id)

    def tasks(self, project_id):
        self.get_project(project_id)
        with self._connect() as con:
            return [dict(r) for r in con.execute('SELECT * FROM tasks WHERE project_id=? ORDER BY created_at,task_id', (project_id,))]

    @staticmethod
    def _task_summary(rows):
        counts = {s: sum(t['state'] == s for t in rows) for s in STATES}
        return dict(total=len(rows), completed=counts['done'], states=counts)

    def task_summary(self, project_id):
        rows = self.tasks(project_id)
        return self._task_summary(rows)

    def task_board(self, project_id):
        self.get_project(project_id)
        with self._connect() as con:
            con.execute('BEGIN')
            rows = [dict(r) for r in con.execute('SELECT * FROM tasks WHERE project_id=? ORDER BY created_at,task_id', (project_id,))]
            return {'tasks': rows, 'summary': self._task_summary(rows)}

    def task_detail(self, project_id, task_id):
        self.get_project(project_id)
        self.validate_task_id(task_id)
        with self._connect() as con:
            con.execute('BEGIN')
            row = con.execute('SELECT * FROM tasks WHERE project_id=? AND task_id=?', (project_id, task_id)).fetchone()
            if row is None:
                raise ValueError('task not found in project')
            result = dict(row)
            result['history'] = [dict(r) for r in con.execute('SELECT * FROM task_history WHERE project_id=? AND task_id=? ORDER BY id', (project_id, task_id))]
            return result
