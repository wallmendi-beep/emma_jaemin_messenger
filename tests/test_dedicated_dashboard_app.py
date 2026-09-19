import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dashboard_app import doorbell_dashboard


class DedicatedDashboardAppTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_selected_project_root_is_persisted_for_desktop_app(self):
        with patch.object(doorbell_dashboard, 'app_data_directory', return_value=Path(self._tmp.name)):
            doorbell_dashboard.save_project_root(Path('C:/work/messenger'))
            self.assertEqual(Path('C:/work/messenger'), doorbell_dashboard.saved_project_root())

    def test_frozen_app_uses_python_to_start_the_local_server(self):
        fake_process = Mock()
        fake_process.poll.return_value = None
        with patch.object(doorbell_dashboard, 'dashboard_running', side_effect=[False, True]), patch.object(doorbell_dashboard.subprocess, 'Popen', return_value=fake_process) as popen, patch.object(sys, 'frozen', True, create=True):
            result = doorbell_dashboard.start_server(Path.cwd())
        self.assertIs(fake_process, result)
        self.assertEqual('python', popen.call_args.args[0][0])
        self.assertIn('messenger.server', popen.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
