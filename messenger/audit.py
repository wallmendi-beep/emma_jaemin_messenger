"""Append-only, human-readable collaboration audit records."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping, Sequence


AUDIT_KINDS = {"instruction", "response", "review", "decision", "hold_request", "error"}
AUDIT_PARTICIPANTS = {"user", "emma", "prof_emma", "jaemin"}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_SECRET_KEY_PARTS = ("password", "passwd", "token", "apikey", "secret", "credential", "privatekey")


def _contains_secret_key(value):
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(part in normalized for part in _SECRET_KEY_PARTS):
                return True
            if _contains_secret_key(nested):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_secret_key(item) for item in value)
    return False


class AuditMixin:
    def initialize_audit(self):
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS collaboration_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    event_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    task_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    body TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    artifact_path TEXT NOT NULL DEFAULT '',
                    artifact_sha256 TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(project_id,event_key)
                );
                CREATE INDEX IF NOT EXISTS collaboration_events_timeline
                    ON collaboration_events(project_id,task_id,id);
                CREATE TRIGGER IF NOT EXISTS collaboration_events_no_update
                BEFORE UPDATE ON collaboration_events
                BEGIN SELECT RAISE(ABORT, 'collaboration audit is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS collaboration_events_no_delete
                BEFORE DELETE ON collaboration_events
                BEGIN SELECT RAISE(ABORT, 'collaboration audit is append-only'); END;
                """
            )

    @staticmethod
    def _audit_text(value, field, maximum, *, allow_empty=False):
        if not isinstance(value, str) or (not allow_empty and not value) or len(value) > maximum:
            qualifier = "string" if allow_empty else "non-empty string"
            raise ValueError(f"{field} must be a {qualifier}, max {maximum} characters")
        return value

    def record_audit_event(
        self,
        *,
        project_id,
        event_key,
        task_id,
        run_id,
        profile,
        sender,
        recipient,
        kind,
        body,
        expected_body_sha256=None,
        conversation_id="",
        artifact_path="",
        artifact_sha256="",
        metadata=None,
    ):
        self.get_project(project_id)
        event_key = self._audit_text(event_key, "event_key", 240)
        task_id = self._audit_text(task_id, "task_id", 100)
        if not _TASK_ID.fullmatch(task_id):
            raise ValueError("invalid task_id")
        run_id = self._audit_text(str(run_id), "run_id", 100)
        profile = self._audit_text(profile, "profile", 100)
        sender = self._audit_text(sender, "sender", 20).lower()
        recipient = self._audit_text(recipient, "recipient", 20).lower()
        kind = self._audit_text(kind, "kind", 30).lower()
        body = self._audit_text(body, "body", 1048576)
        conversation_id = self._audit_text(conversation_id, "conversation_id", 200, allow_empty=True)
        artifact_path = self._audit_text(artifact_path, "artifact_path", 2000, allow_empty=True)
        artifact_sha256 = self._audit_text(artifact_sha256, "artifact_sha256", 64, allow_empty=True)
        if sender not in AUDIT_PARTICIPANTS or recipient not in AUDIT_PARTICIPANTS:
            raise ValueError("unsupported audit participant")
        if kind not in AUDIT_KINDS:
            raise ValueError("unsupported audit kind")
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if expected_body_sha256 is not None and expected_body_sha256 != body_sha256:
            raise ValueError("body SHA-256 mismatch")
        if artifact_sha256 and not _SHA256.fullmatch(artifact_sha256):
            raise ValueError("artifact_sha256 must be lowercase SHA-256 hex")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        if _contains_secret_key(metadata):
            raise ValueError("secret-bearing audit metadata key is forbidden")
        metadata_text = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(metadata_text) > 10000:
            raise ValueError("metadata exceeds 10000 characters")

        values = (
            project_id, event_key, time.time(), task_id, run_id, profile,
            sender, recipient, kind, body, body_sha256, conversation_id,
            artifact_path, artifact_sha256, metadata_text,
        )
        with self._lock, self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            old = con.execute(
                "SELECT * FROM collaboration_events WHERE project_id=? AND event_key=?",
                (project_id, event_key),
            ).fetchone()
            if old is not None:
                if any(old[name] != value for name, value in (
                    ("task_id", task_id), ("run_id", run_id), ("profile", profile),
                    ("sender", sender), ("recipient", recipient), ("kind", kind),
                    ("body", body), ("body_sha256", body_sha256),
                    ("conversation_id", conversation_id), ("artifact_path", artifact_path),
                    ("artifact_sha256", artifact_sha256), ("metadata", metadata_text),
                )):
                    raise ValueError("event_key already exists with different content")
                return dict(old)
            cur = con.execute(
                """
                INSERT INTO collaboration_events(
                    project_id,event_key,created_at,task_id,run_id,profile,sender,
                    recipient,kind,body,body_sha256,conversation_id,artifact_path,
                    artifact_sha256,metadata
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                values,
            )
            return dict(con.execute(
                "SELECT * FROM collaboration_events WHERE id=?", (cur.lastrowid,)
            ).fetchone())

    def audit_events(self, project_id, *, task_id=None, after=0, limit=200):
        self.get_project(project_id)
        after = max(0, int(after))
        limit = min(500, max(1, int(limit)))
        params = [project_id, after]
        task_clause = ""
        if task_id is not None:
            if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
                raise ValueError("invalid task_id")
            task_clause = " AND task_id=?"
            params.append(task_id)
        params.append(limit)
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM collaboration_events WHERE project_id=? AND id>?"
                + task_clause + " ORDER BY id LIMIT ?",
                params,
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            actual = hashlib.sha256(row["body"].encode("utf-8")).hexdigest()
            if actual != row["body_sha256"]:
                raise ValueError(f"audit event {row['id']} body SHA-256 corruption detected")
        return result
