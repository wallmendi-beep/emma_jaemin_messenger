import hashlib
import tempfile
import unittest
from pathlib import Path
from messenger import courier as store


class CourierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_claim_lease_read_complete_and_reject_stale_owner(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        courier = store.CourierStore(self.root / 'db.sqlite')
        p = courier.create_project('test', str(self.root))['id']
        memo = self.root / 'memo.md'
        memo.write_bytes(b'memo')
        h = hashlib.sha256(memo.read_bytes()).hexdigest()
        n = courier.notify(p, 'emma', 'memo.md', h)
        self.assertTrue(hasattr(courier, 'claim'), 'atomic lease claim missing')
        def claim(i):
            return store.CourierStore(courier.path).claim(p, 'emma', 'worker-' + str(i), 1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = [x for x in pool.map(claim, range(4)) if x]
        self.assertEqual(1, len(claims))
        first = claims[0]
        self.assertIsNone(courier.claim(1, 'emma', 'other', 1))
        self.assertIsNone(courier.claim(p, 'jaemin', 'other', 1))
        with self.assertRaises(ValueError):
            courier.ack(p, n['id'], first['claim_token'], 'complete', result_path='memo.md', result_hash=h)
        read = courier.ack(p, n['id'], first['claim_token'], 'read', version_hash=h)
        self.assertEqual('read', read['status'])
        time.sleep(1.1)
        second = courier.claim(p, 'emma', 'replacement', 10)
        self.assertEqual(2, second['attempts'])
        with self.assertRaises(ValueError):
            courier.ack(p, n['id'], first['claim_token'], 'read', version_hash=h)
        courier.ack(p, n['id'], second['claim_token'], 'read', version_hash=h)
        done = courier.ack(p, n['id'], second['claim_token'], 'complete', result_path='memo.md', result_hash=h)
        self.assertEqual('completed', done['status'])
        self.assertEqual(str(memo.resolve()), done['result_path'])
        self.assertIsNone(courier.claim(p, 'emma', 'other', 1))

    def test_fractional_project_id_cannot_create_orphan_notification(self):
        courier = store.CourierStore(self.root / 'db.sqlite')
        p = courier.create_project('test', str(self.root))['id']
        memo = self.root / 'memo.md'
        memo.write_bytes(b'memo')
        digest = hashlib.sha256(memo.read_bytes()).hexdigest()
        for invalid in [p + 0.5, True, str(p)]:
            with self.subTest(project_id=invalid), self.assertRaises(ValueError):
                courier.notify(invalid, 'emma', 'memo.md', digest)
        with courier._connect() as con:
            self.assertEqual(0, con.execute('SELECT COUNT(*) FROM notifications').fetchone()[0])

    def test_archived_project_cannot_dispatch_pending_work(self):
        courier = store.CourierStore(self.root / 'db.sqlite')
        p = courier.create_project('test', str(self.root))['id']
        (self.root / 'memo.md').write_bytes(b'memo')
        courier.notify(p, 'emma', 'memo.md', hashlib.sha256(b'memo').hexdigest())
        with courier._connect() as con:
            con.execute('UPDATE projects SET archived=1 WHERE id=?', (p,))
        with self.assertRaises(ValueError):
            courier.claim(p, 'emma', 'existing-worker')
        self.assertEqual('pending', courier.notifications(p)[0]['status'])

    def test_courier_rules_correct_external_provider_claim(self):
        legacy = store.MessageStore(self.root / 'rules.db')
        with legacy._connect() as con:
            con.execute('INSERT INTO global_rules(created_at,text,protected) VALUES(0,?,1)',
                        ('메신저는 127.0.0.1에서만 작동하며 협업 내용을 외부로 전송하지 않는다.',))
        courier = store.CourierStore(self.root / 'rules.db')
        texts = [r['text'] for r in courier.list_global_rules()]
        self.assertFalse(any('외부로 전송하지 않는다' in t for t in texts))
        self.assertTrue(any('AI 제공자' in t for t in texts))

    def test_durable_versioned_memo_and_readonly_history(self):
        self.assertTrue(hasattr(store, 'CourierStore'), 'durable courier store is missing')
        db = self.root / 'db.sqlite'
        legacy = store.MessageStore(db)
        old = legacy.post('user', 'emma', 'INFO', 'history')
        courier = store.CourierStore(db)
        project = courier.create_project('test', str(self.root))
        memo = self.root / 'memo.md'
        memo.write_text('actual memo', encoding='utf-8')
        digest = hashlib.sha256(memo.read_bytes()).hexdigest()
        item = courier.notify(project['id'], 'emma', 'memo.md', digest)
        self.assertEqual('pending', item['status'])
        again = store.CourierStore(db)
        self.assertEqual(item['id'], again.notifications(project['id'])[0]['id'])
        self.assertEqual(old, again.list_messages()[0])
        with self.assertRaises(Exception):
            again.post('user', 'emma', 'INFO', 'forbidden')
        self.assertTrue(list(self.root.glob('db.sqlite.pre-courier-*.bak')))


if __name__ == '__main__':
    unittest.main()
