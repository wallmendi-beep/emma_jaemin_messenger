"""The consultation bridge is intentionally retired, not compatibility-run."""
import unittest
from messenger import bridge


class RetiredBridgeTest(unittest.TestCase):
    def test_bridge_cannot_spawn_consultation_agents(self):
        self.assertFalse(hasattr(bridge, 'AgentCommandRunner'))
        self.assertFalse(hasattr(bridge, 'CollaborationBridge'))
        with self.assertRaises(SystemExit) as caught:
            bridge.main()
        self.assertIn('retired', str(caught.exception))
