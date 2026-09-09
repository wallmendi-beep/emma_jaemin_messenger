"""Opt-in real CLI integration; never connects to an existing conversation."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import uuid


@unittest.skipUnless(os.environ.get('RUN_AGY_STREAM_TEST') == '1', 'opt-in live disposable CLI test')
class StreamIntegration(unittest.TestCase):
    def test_two_turn_marker_in_new_conversation(self):
        self.assertIsNotNone(importlib.util.find_spec('messenger.agy_stream'),
                             'RED: bounded stream driver missing')
        from messenger.agy_stream import probe
        marker = 'COURIER_' + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix='agy-stream-') as cwd:
            report = probe(Path.home() / 'AppData/Local/agy/bin/agy.exe', cwd, marker, timeout=60)
        self.assertEqual(report['returncode'], 0)
        self.assertEqual(len(report['results']), 2)
        self.assertEqual(len({r['conversation_id'] for r in report['results']}), 1)
        self.assertTrue(all(r['status'] == 'SUCCESS' for r in report['results']))
        self.assertIn(marker, report['results'][1]['response'])
        self.assertTrue(report['exited'])
        evidence = Path('data/stream-handoff-probe/live-test.json')
        evidence.parent.mkdir(parents=True, exist_ok=True)
        import json
        evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('LIVE_DISPOSABLE_TWO_TURN_PASS', report['results'][0]['conversation_id'])
