import hashlib
import tempfile
import unittest
from pathlib import Path

from messenger.courier import CourierStore
from messenger.agents import AgentRegistry


class AgentRegistryContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'memo.md').write_text('approved scope', encoding='utf-8')
        self.digest = hashlib.sha256((self.root / 'memo.md').read_bytes()).hexdigest()

    def test_known_disabled_agent_cannot_receive_work(self):
        registry = AgentRegistry([
            {'id': 'emma', 'provider': 'hermes', 'role': 'reviewer', 'enabled': True},
            {'id': 'opencode', 'provider': 'opencode', 'role': 'executor', 'enabled': False},
        ])
        courier = CourierStore(self.root / 'db.sqlite', agents=registry)
        project_id = courier.create_project('test', str(self.root))['id']
        with self.assertRaisesRegex(ValueError, 'not enabled'):
            courier.notify(project_id, 'opencode', 'memo.md', self.digest)

    def test_enabled_registered_agent_uses_existing_courier_protocol(self):
        registry = AgentRegistry([
            {'id': 'opencode', 'provider': 'opencode', 'role': 'executor', 'enabled': True},
        ])
        courier = CourierStore(self.root / 'db.sqlite', agents=registry)
        project_id = courier.create_project('test', str(self.root))['id']
        notification = courier.notify(project_id, 'opencode', 'memo.md', self.digest)
        claim = courier.claim(project_id, 'opencode', 'opencode-session-7')
        self.assertEqual(notification['id'], claim['id'])
        self.assertEqual('opencode-session-7', claim['worker_id'])

    def test_worker_cli_accepts_a_registered_future_agent_id(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, '-m', 'messenger.worker', '--project', '1', '--recipient', 'opencode', '--worker', 'opencode-test'],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        )
        self.assertNotIn('invalid choice', result.stderr)
        self.assertIn('the following arguments are required: action', result.stderr)


if __name__ == '__main__':
    unittest.main()
