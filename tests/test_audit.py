import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

from messenger.courier import CourierStore
from messenger.server import build_server


class CollaborationAuditStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = CourierStore(self.root / "messages.db")
        self.project = self.store.create_project("audit-test", str(self.root))["id"]
        self.store.create_task(self.project, "WRITE-001", "원고 검토")

    def test_exact_human_messages_are_immutable_and_separate_from_worker_context(self):
        body = "  제3절의 확정성 수준을 유지해 주세요.\n각주 17도 확인하세요.  "
        expected_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        event = self.store.record_audit_event(
            project_id=self.project,
            event_key="WRITE-001:run-1:instruction",
            task_id="WRITE-001",
            run_id="run-1",
            profile="prof_emma",
            sender="emma",
            recipient="jaemin",
            kind="instruction",
            body=body,
            expected_body_sha256=expected_hash,
        )

        self.assertEqual(body, event["body"])
        self.assertEqual(expected_hash, event["body_sha256"])
        self.assertNotIn(body, json.dumps(self.store.task_detail(self.project, "WRITE-001"), ensure_ascii=False))
        self.assertEqual([], self.store.list_messages(project_id=self.project))

        same = self.store.record_audit_event(
            project_id=self.project,
            event_key="WRITE-001:run-1:instruction",
            task_id="WRITE-001",
            run_id="run-1",
            profile="prof_emma",
            sender="emma",
            recipient="jaemin",
            kind="instruction",
            body=body,
            expected_body_sha256=expected_hash,
        )
        self.assertEqual(event["id"], same["id"])
        with self.assertRaisesRegex(ValueError, "event_key already exists with different content"):
            self.store.record_audit_event(
                project_id=self.project,
                event_key="WRITE-001:run-1:instruction",
                task_id="WRITE-001",
                run_id="run-1",
                profile="prof_emma",
                sender="emma",
                recipient="jaemin",
                kind="instruction",
                body="변조된 본문",
            )

        with closing(sqlite3.connect(self.store.path)) as con:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                con.execute("UPDATE collaboration_events SET body='직접 변조' WHERE id=?", (event["id"],))
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                con.execute("DELETE FROM collaboration_events WHERE id=?", (event["id"],))

    def test_task_timeline_is_ordered_and_filters_by_exact_task_id(self):
        for key, task, kind, sender, recipient, body in [
            ("a", "WRITE-001", "instruction", "emma", "jaemin", "초안 검토"),
            ("b", "OTHER-001", "response", "jaemin", "emma", "다른 작업"),
            ("c", "WRITE-001", "review", "emma", "user", "검수 완료"),
        ]:
            self.store.record_audit_event(
                project_id=self.project,
                event_key=key,
                task_id=task,
                run_id="1",
                profile="prof_emma",
                sender=sender,
                recipient=recipient,
                kind=kind,
                body=body,
            )
        rows = self.store.audit_events(self.project, task_id="WRITE-001")
        self.assertEqual(["초안 검토", "검수 완료"], [row["body"] for row in rows])
        self.assertEqual(["instruction", "review"], [row["kind"] for row in rows])

    def test_read_rejects_body_hash_corruption(self):
        event = self.store.record_audit_event(
            project_id=self.project, event_key="corrupt-me", task_id="WRITE-001", run_id="1",
            profile="prof_emma", sender="emma", recipient="jaemin", kind="instruction",
            body="original",
        )
        with closing(sqlite3.connect(self.store.path)) as con:
            con.execute("DROP TRIGGER collaboration_events_no_update")
            con.execute("UPDATE collaboration_events SET body='corrupted' WHERE id=?", (event["id"],))
            con.commit()
        with self.assertRaisesRegex(ValueError, "body SHA-256 corruption"):
            self.store.audit_events(self.project)

    def test_secret_bearing_metadata_keys_are_rejected_recursively(self):
        for index, metadata in enumerate([
            {"password": "secret"},
            {"api_key": "secret"},
            {"nested": {"claim_token": "secret"}},
            {"items": [{"clientSecret": "secret"}]},
            {"credentials": ["secret"]},
            {"safe": ({"claim_token": "secret"},)},
        ]):
            with self.subTest(metadata=metadata), self.assertRaisesRegex(ValueError, "secret-bearing"):
                self.store.record_audit_event(
                    project_id=self.project, event_key=f"secret-{index}", task_id="WRITE-001",
                    run_id="1", profile="prof_emma", sender="emma", recipient="jaemin",
                    kind="instruction", body="safe body", metadata=metadata,
                )


class CollaborationAuditApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        store = CourierStore(self.root / "messages.db")
        self.project = store.create_project("audit-api", str(self.root))["id"]
        store.create_task(self.project, "CODE-001", "코드 검수")
        self.server = build_server("127.0.0.1", 0, self.root / "messages.db")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, body=None):
        req = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_post_and_read_audit_timeline_without_exposing_secret_fields(self):
        body = "재민에게 전달된 실제 자연어 작업지시"
        payload = {
            "project_id": self.project,
            "event_key": "CODE-001:7:instruction",
            "task_id": "CODE-001",
            "run_id": "7",
            "profile": "prof_emma",
            "sender": "emma",
            "recipient": "jaemin",
            "kind": "instruction",
            "body": body,
            "expected_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "conversation_id": "",
            "artifact_path": "",
            "artifact_sha256": "",
        }
        created = self.request("/api/audit/events", payload)
        listed = self.request(f"/api/audit/events?project_id={self.project}&task_id=CODE-001")
        self.assertEqual(created["id"], listed["events"][0]["id"])
        self.assertEqual(body, listed["events"][0]["body"])
        self.assertNotIn("claim_token", json.dumps(listed))
        self.assertNotIn("approval", json.dumps(listed).lower())

        bad = dict(payload, event_key="bad-hash", expected_body_sha256="0" * 64)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/audit/events", bad)
        self.assertEqual(400, caught.exception.code)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
