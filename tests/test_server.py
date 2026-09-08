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
    def test_home_page_contains_three_participants_and_decision_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "messages.db"
            server = build_server("127.0.0.1", 0, db)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/") as response:
                    html = response.read().decode("utf-8")
                self.assertIn('data-participant="user"', html)
                self.assertIn('data-participant="emma"', html)
                self.assertIn('data-participant="jaemin"', html)
                self.assertIn('id="decision-banner"', html)
                self.assertIn('id="project-list"', html)
                self.assertIn('id="global-rules"', html)
                self.assertIn('id="project-rules"', html)
                self.assertIn('id="rule-form"', html)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_project_api_creates_room_and_filters_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = build_server("127.0.0.1", 0, Path(tmp) / "messages.db")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                project_body = json.dumps(
                    {
                        "name": "새 프로젝트",
                        "workspace": r"C:\\Work\\New",
                        "hermes_session_id": "h-1",
                        "jaemin_conversation_id": "j-1",
                    }
                ).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/projects",
                    data=project_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request) as response:
                    project = json.load(response)
                with urllib.request.urlopen(base + "/api/projects") as response:
                    projects = json.load(response)["projects"]

                message_body = json.dumps(
                    {
                        "project_id": project["id"],
                        "sender": "user",
                        "recipient": "emma",
                        "type": "TASK",
                        "body": "새 방 메시지",
                    }
                ).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/messages",
                    data=message_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(request).close()
                with urllib.request.urlopen(
                    base + f"/api/messages?project_id={project['id']}&after=0"
                ) as response:
                    room = json.load(response)

                self.assertEqual(["기본 프로젝트", "새 프로젝트"], [p["name"] for p in projects])
                self.assertEqual(["새 방 메시지"], [m["body"] for m in room["messages"]])
                self.assertEqual(project["id"], room["project"]["id"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_rule_api_adds_user_rule_and_approves_agent_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "messages.db"
            server = build_server("127.0.0.1", 0, db)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                proposed = MessageStore(db).add_project_rule(
                    1, "엠마가 정리한 제안", source="emma", status="proposed"
                )
                direct_request = urllib.request.Request(
                    base + "/api/rules",
                    data=json.dumps(
                        {"project_id": 1, "text": "오빠가 직접 추가한 원칙"}
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(direct_request) as response:
                    direct = json.load(response)
                approve_request = urllib.request.Request(
                    base + f"/api/rules/{proposed['id']}/approve",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(approve_request) as response:
                    approved = json.load(response)
                with urllib.request.urlopen(base + "/api/rules?project_id=1") as response:
                    listed = json.load(response)

                self.assertEqual("active", direct["status"])
                self.assertEqual("active", approved["status"])
                self.assertGreaterEqual(len(listed["global_rules"]), 5)
                self.assertEqual(
                    ["엠마가 정리한 제안", "오빠가 직접 추가한 원칙"],
                    [rule["text"] for rule in listed["project_rules"]],
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_foreign_origin_cannot_post_to_local_room(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = build_server("127.0.0.1", 0, Path(tmp) / "messages.db")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/messages",
                    data=b'{"sender":"user","recipient":"emma","type":"TASK","body":"x"}',
                    headers={"Content-Type": "text/plain", "Origin": "https://evil.example"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(403, caught.exception.code)
                caught.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_health_and_message_round_trip_over_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "messages.db"
            server = build_server("127.0.0.1", 0, db)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(base + "/api/health") as response:
                    health = json.load(response)
                self.assertEqual("ok", health["status"])

                body = json.dumps(
                    {
                        "sender": "user",
                        "recipient": "emma",
                        "type": "TASK",
                        "body": "재민이와 협의해 줘",
                    }
                ).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/messages",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request) as response:
                    posted = json.load(response)
                with urllib.request.urlopen(base + "/api/messages?after=0") as response:
                    listed = json.load(response)

                self.assertEqual(posted["id"], listed["messages"][0]["id"])
                self.assertEqual("재민이와 협의해 줘", listed["messages"][0]["body"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
