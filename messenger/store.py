from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


PARTICIPANTS = {"user", "emma", "jaemin"}
MESSAGE_TYPES = {
    "TASK",
    "QUESTION",
    "REPLY",
    "READY_FOR_REVIEW",
    "CHANGES_REQUESTED",
    "USER_DECISION_REQUIRED",
    "STOP",
    "INFO",
    "RULE_PROPOSAL",
}

GLOBAL_RULES = (
    "메신저는 127.0.0.1에서만 작동하며 협업 내용을 외부로 전송하지 않는다.",
    "파괴적 명령과 원본 최종 반영은 사용자의 명시적 승인을 받은 뒤 수행한다.",
    "사용자 판단이 필요하면 자동협의를 멈추고 답변을 기다린다.",
    "자동협의는 정해진 왕복 상한 안에서만 진행한다.",
    "프로젝트 생성은 파일 수정이나 명령 실행 권한을 부여하지 않는다.",
)


class MessageStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _initialize(self):
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    workspace TEXT NOT NULL DEFAULT '',
                    hermes_session_id TEXT NOT NULL DEFAULT '',
                    jaemin_conversation_id TEXT NOT NULL DEFAULT '',
                    archived INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            con.execute(
                """
                INSERT OR IGNORE INTO projects(
                    id,created_at,name,workspace,hermes_session_id,jaemin_conversation_id
                ) VALUES(1,?,?,?,?,?)
                """,
                (time.time(), "기본 프로젝트", "", "", ""),
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    type TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reply_to INTEGER,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    project_id INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            message_columns = {
                row["name"] for row in con.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "project_id" not in message_columns:
                con.execute(
                    "ALTER TABLE messages ADD COLUMN project_id INTEGER NOT NULL DEFAULT 1"
                )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_project_id ON messages(project_id,id)"
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS project_state (
                    project_id INTEGER PRIMARY KEY,
                    paused INTEGER NOT NULL DEFAULT 0,
                    pause_message_id INTEGER
                )
                """
            )
            con.execute(
                "INSERT OR IGNORE INTO project_state(project_id,paused) VALUES(1,0)"
            )
            legacy = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='room_state'"
            ).fetchone()
            if legacy:
                old = con.execute(
                    "SELECT paused,pause_message_id FROM room_state WHERE singleton=1"
                ).fetchone()
                if old and old["paused"]:
                    con.execute(
                        "UPDATE project_state SET paused=?,pause_message_id=? WHERE project_id=1",
                        (old["paused"], old["pause_message_id"]),
                    )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS global_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    text TEXT NOT NULL UNIQUE,
                    protected INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            for text in GLOBAL_RULES:
                con.execute(
                    "INSERT OR IGNORE INTO global_rules(created_at,text,protected) VALUES(?,?,1)",
                    (time.time(), text),
                )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS project_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approved_by TEXT,
                    proposal_message_id INTEGER,
                    UNIQUE(project_id,text)
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_rules_project ON project_rules(project_id,status,id)"
            )

    def create_project(
        self,
        name: str,
        workspace: str = "",
        hermes_session_id: str = "",
        jaemin_conversation_id: str = "",
    ):
        name = str(name).strip()
        if not name or len(name) > 120:
            raise ValueError("project name is required and must be at most 120 characters")
        values = (
            time.time(),
            name,
            str(workspace).strip(),
            str(hermes_session_id).strip(),
            str(jaemin_conversation_id).strip(),
        )
        try:
            with self._lock, self._connect() as con:
                cur = con.execute(
                    """
                    INSERT INTO projects(
                        created_at,name,workspace,hermes_session_id,jaemin_conversation_id
                    ) VALUES(?,?,?,?,?)
                    """,
                    values,
                )
                project_id = cur.lastrowid
                con.execute(
                    "INSERT INTO project_state(project_id,paused) VALUES(?,0)",
                    (project_id,),
                )
                row = con.execute(
                    "SELECT * FROM projects WHERE id=?", (project_id,)
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            raise ValueError("a project with that name already exists") from exc
        return dict(row)

    def list_projects(self, include_archived: bool = False):
        where = "" if include_archived else "WHERE archived=0"
        with self._connect() as con:
            rows = con.execute(
                f"""
                SELECT p.*,
                       COALESCE(s.paused,0) AS paused,
                       COUNT(m.id) AS message_count
                FROM projects p
                LEFT JOIN project_state s ON s.project_id=p.id
                LEFT JOIN messages m ON m.project_id=p.id
                {where}
                GROUP BY p.id
                ORDER BY p.archived,p.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_project(self, project_id: int):
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM projects WHERE id=?", (int(project_id),)
            ).fetchone()
        if row is None:
            raise ValueError("project not found")
        return dict(row)

    def list_global_rules(self):
        with self._connect() as con:
            rows = con.execute("SELECT * FROM global_rules ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def add_project_rule(
        self,
        project_id: int,
        text: str,
        source: str = "user",
        status: str = "active",
        proposal_message_id=None,
    ):
        project_id = int(project_id)
        text = str(text).strip()
        source = str(source).strip().lower()
        status = str(status).strip().lower()
        if not text or len(text) > 2000:
            raise ValueError("rule text is required and must be at most 2000 characters")
        if source not in PARTICIPANTS:
            raise ValueError("unsupported rule source")
        if status not in {"active", "proposed"}:
            raise ValueError("unsupported rule status")
        if source != "user" and status == "active":
            raise ValueError("agent rules require user approval")
        approved_by = "user" if source == "user" and status == "active" else None
        with self._lock, self._connect() as con:
            if con.execute(
                "SELECT id FROM projects WHERE id=? AND archived=0", (project_id,)
            ).fetchone() is None:
                raise ValueError("active project not found")
            try:
                cur = con.execute(
                    """
                    INSERT INTO project_rules(
                        project_id,created_at,text,source,status,approved_by,proposal_message_id
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        project_id,
                        time.time(),
                        text,
                        source,
                        status,
                        approved_by,
                        proposal_message_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("that rule already exists in this project") from exc
            row = con.execute(
                "SELECT * FROM project_rules WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return dict(row)

    def approve_project_rule(self, rule_id: int):
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT * FROM project_rules WHERE id=?", (int(rule_id),)
            ).fetchone()
            if row is None:
                raise ValueError("project rule not found")
            if row["status"] != "proposed":
                raise ValueError("only proposed rules can be approved")
            con.execute(
                "UPDATE project_rules SET status='active',approved_by='user' WHERE id=?",
                (int(rule_id),),
            )
            updated = con.execute(
                "SELECT * FROM project_rules WHERE id=?", (int(rule_id),)
            ).fetchone()
        return dict(updated)

    def list_project_rules(self, project_id: int, include_proposed: bool = True):
        where = "" if include_proposed else "AND status='active'"
        with self._connect() as con:
            rows = con.execute(
                f"""
                SELECT * FROM project_rules
                WHERE project_id=? {where}
                ORDER BY id
                """,
                (int(project_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def post(
        self,
        sender: str,
        recipient: str,
        message_type: str,
        body: str,
        reply_to=None,
        project_id: int = 1,
    ):
        sender = sender.strip().lower()
        recipient = recipient.strip().lower()
        message_type = message_type.strip().upper()
        body = body.strip()
        project_id = int(project_id)
        if sender not in PARTICIPANTS or recipient not in PARTICIPANTS:
            raise ValueError("sender and recipient must be user, emma, or jaemin")
        if message_type not in MESSAGE_TYPES:
            raise ValueError("unsupported message type")
        if not body:
            raise ValueError("message body is required")
        now = time.time()
        with self._lock, self._connect() as con:
            project = con.execute(
                "SELECT id FROM projects WHERE id=? AND archived=0", (project_id,)
            ).fetchone()
            if project is None:
                raise ValueError("active project not found")
            cur = con.execute(
                """
                INSERT INTO messages(
                    created_at,sender,recipient,type,body,reply_to,project_id
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (now, sender, recipient, message_type, body, reply_to, project_id),
            )
            message_id = cur.lastrowid
            if message_type == "USER_DECISION_REQUIRED" and recipient == "user":
                con.execute(
                    """
                    UPDATE project_state SET paused=1,pause_message_id=?
                    WHERE project_id=?
                    """,
                    (message_id, project_id),
                )
            elif sender == "user" and message_type == "REPLY" and reply_to is not None:
                state = con.execute(
                    "SELECT pause_message_id FROM project_state WHERE project_id=?",
                    (project_id,),
                ).fetchone()
                if state and state["pause_message_id"] == int(reply_to):
                    con.execute(
                        """
                        UPDATE project_state SET paused=0,pause_message_id=NULL
                        WHERE project_id=?
                        """,
                        (project_id,),
                    )
                    con.execute(
                        "UPDATE messages SET status='answered' WHERE id=? AND project_id=?",
                        (int(reply_to), project_id),
                    )
            row = con.execute(
                "SELECT * FROM messages WHERE id=?", (message_id,)
            ).fetchone()
        return dict(row)

    def is_paused(self, project_id: int = 1):
        with self._connect() as con:
            row = con.execute(
                "SELECT paused FROM project_state WHERE project_id=?", (int(project_id),)
            ).fetchone()
        return bool(row["paused"]) if row else False

    def claim_next(self, recipient: str, project_id: int = 1):
        recipient = recipient.strip().lower()
        project_id = int(project_id)
        if recipient not in PARTICIPANTS:
            raise ValueError("unsupported recipient")
        with self._lock, self._connect() as con:
            state = con.execute(
                "SELECT paused FROM project_state WHERE project_id=?", (project_id,)
            ).fetchone()
            if state is None or state["paused"]:
                return None
            row = con.execute(
                """
                SELECT * FROM messages
                WHERE project_id=? AND recipient=? AND status='pending'
                ORDER BY id LIMIT 1
                """,
                (project_id, recipient),
            ).fetchone()
            if row is None:
                return None
            con.execute(
                "UPDATE messages SET status='processing' WHERE id=?", (row["id"],)
            )
            claimed = dict(row)
            claimed["status"] = "processing"
            return claimed

    def mark_status(self, message_id: int, status: str):
        if status not in {"pending", "processing", "delivered", "answered", "failed"}:
            raise ValueError("unsupported status")
        with self._lock, self._connect() as con:
            con.execute(
                "UPDATE messages SET status=? WHERE id=?", (status, int(message_id))
            )

    def list_messages(self, after_id: int = 0, limit: int = 200, project_id: int = 1):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT * FROM messages
                WHERE project_id=? AND id>? ORDER BY id LIMIT ?
                """,
                (
                    int(project_id),
                    max(0, int(after_id)),
                    min(max(1, int(limit)), 500),
                ),
            ).fetchall()
        return [dict(row) for row in rows]
