import tempfile
import unittest
from pathlib import Path
from messenger.store import MessageStore
from messenger.courier import CourierStore

class ExecutionModeTest(unittest.TestCase):
    def test_project_mode_persists_and_rejects_unknown_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MessageStore(Path(tmp) / 'messages.db')
            project = store.create_project('mode test', tmp)
            self.assertEqual('card_approval', project['execution_mode'])
            changed = store.set_execution_mode(project['id'], 'project_auto')
            self.assertEqual('project_auto', changed['execution_mode'])
            self.assertEqual('project_auto', store.get_project(project['id'])['execution_mode'])
            with self.assertRaises(ValueError):
                store.set_execution_mode(project['id'], 'anything')

    def test_card_approval_completes_current_card_and_releases_only_successor(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CourierStore(Path(tmp) / 'messages.db')
            project = store.create_project('serial approval', tmp)
            store.create_task(project['id'], 'CARD-1', 'first')
            store.create_task(project['id'], 'CARD-2', 'second')
            store.transition_task(project['id'], 'CARD-2', 'blocked', 1, note='wait')
            store.transition_task(project['id'], 'CARD-1', 'review', 1, note='ready for user approval')
            result = store.approve_serial_card(project['id'], 'CARD-1')
            self.assertEqual('done', result['approved']['state'])
            self.assertEqual('todo', result['released']['state'])

if __name__ == '__main__': unittest.main()
