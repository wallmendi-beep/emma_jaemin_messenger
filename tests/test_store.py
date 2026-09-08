import tempfile
import unittest
from pathlib import Path

from messenger.store import MessageStore


class MessageStoreTest(unittest.TestCase):
    def test_posted_message_is_listed_in_thread_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MessageStore(Path(tmp) / "messages.db")
            first = store.post("user", "emma", "TASK", "설계를 검토해 줘")
            second = store.post("emma", "jaemin", "QUESTION", "구현 가능해?")

            messages = store.list_messages(after_id=0)

            self.assertEqual([first["id"], second["id"]], [m["id"] for m in messages])
            self.assertEqual("설계를 검토해 줘", messages[0]["body"])
            self.assertEqual("pending", messages[1]["status"])
    def test_projects_isolate_messages_and_preserve_connection_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MessageStore(Path(tmp) / "messages.db")
            macro = store.create_project(
                "업무용 매크로",
                workspace=r"C:\\Work\\Macro",
                hermes_session_id="session-macro",
                jaemin_conversation_id="agy-macro",
            )
            paper = store.create_project("논문 검토")
            store.post("user", "emma", "TASK", "매크로 작업", project_id=macro["id"])
            store.post("user", "emma", "TASK", "논문 작업", project_id=paper["id"])

            self.assertEqual(["매크로 작업"], [m["body"] for m in store.list_messages(project_id=macro["id"])])
            self.assertEqual(["논문 작업"], [m["body"] for m in store.list_messages(project_id=paper["id"])])
            self.assertEqual("session-macro", store.get_project(macro["id"])["hermes_session_id"])
            self.assertEqual("agy-macro", store.get_project(macro["id"])["jaemin_conversation_id"])

    def test_project_rules_require_user_approval_for_agent_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MessageStore(Path(tmp) / "messages.db")
            project = store.create_project("원고 검토")

            global_rules = store.list_global_rules()
            self.assertGreaterEqual(len(global_rules), 5)
            self.assertTrue(all(rule["protected"] for rule in global_rules))

            direct = store.add_project_rule(
                project["id"], "원본 반영 전 사용자 승인을 받는다.", source="user"
            )
            proposed = store.add_project_rule(
                project["id"], "선례 근거를 먼저 확인한다.", source="emma", status="proposed"
            )

            self.assertEqual(direct["status"], "active")
            self.assertEqual(proposed["status"], "proposed")
            store.approve_project_rule(proposed["id"])
            rules = store.list_project_rules(project["id"])
            self.assertEqual([r["status"] for r in rules], ["active", "active"])
            self.assertEqual(rules[1]["approved_by"], "user")

    def test_user_decision_pauses_and_reply_resumes_automation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MessageStore(Path(tmp) / "messages.db")
            pending = store.post("emma", "jaemin", "TASK", "대기 중인 작업")
            question = store.post(
                "emma", "user", "USER_DECISION_REQUIRED", "원본에 반영할까요?"
            )

            self.assertTrue(store.is_paused())
            self.assertIsNone(store.claim_next("jaemin"))

            store.post("user", "emma", "REPLY", "아니요, 검토본만 만드세요", reply_to=question["id"])

            self.assertFalse(store.is_paused())
            self.assertEqual(pending["id"], store.claim_next("jaemin")["id"])


if __name__ == "__main__":
    unittest.main()
