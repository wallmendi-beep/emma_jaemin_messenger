import tempfile
import unittest
from pathlib import Path

from messenger.bridge import CollaborationBridge
from messenger.store import MessageStore


class ScriptedRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, participant, prompt):
        self.calls.append(participant)
        if participant == "emma":
            return {
                "recipient": "jaemin",
                "type": "QUESTION",
                "body": "읽기 전용 검토가 가능하니?",
            }
        return {
            "recipient": "user",
            "type": "USER_DECISION_REQUIRED",
            "body": "대상 프로젝트를 선택해 주세요.",
        }


class RuleProposalRunner:
    def __init__(self):
        self.prompt = ""

    def __call__(self, participant, prompt):
        self.prompt = prompt
        return {
            "recipient": "user",
            "type": "RULE_PROPOSAL",
            "body": "근거 확인 후 문안을 확정한다.",
        }


class CollaborationBridgeTest(unittest.TestCase):
    def test_agent_rule_proposal_waits_for_user_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MessageStore(Path(tmp) / "messages.db")
            store.add_project_rule(1, "원본은 승인 후 반영한다.", source="user")
            runner = RuleProposalRunner()
            store.post("user", "emma", "TASK", "협업 원칙 문안을 제안해 줘")

            processed = CollaborationBridge(store, runner, max_exchanges=1).drain()

            rules = store.list_project_rules(1)
            self.assertEqual(1, processed)
            self.assertIn("원본은 승인 후 반영한다.", runner.prompt)
            self.assertEqual(2, len(rules))
            self.assertEqual("proposed", rules[-1]["status"])
            self.assertEqual("emma", rules[-1]["source"])

    def test_agents_exchange_messages_until_user_decision_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MessageStore(Path(tmp) / "messages.db")
            runner = ScriptedRunner()
            store.post("user", "emma", "TASK", "재민이와 협의해 줘")

            processed = CollaborationBridge(store, runner, max_exchanges=6).drain()

            messages = store.list_messages()
            self.assertEqual(2, processed)
            self.assertEqual(["user", "emma", "jaemin"], [m["sender"] for m in messages])
            self.assertEqual(["emma", "jaemin"], runner.calls)
            self.assertEqual("USER_DECISION_REQUIRED", messages[-1]["type"])
            self.assertTrue(store.is_paused())


if __name__ == "__main__":
    unittest.main()
