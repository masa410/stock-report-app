import datetime as dt
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline
import store as st
import sync_pc
from test_all import synth_market


class TestSync(unittest.TestCase):
    def test_sync_creates_once(self):
        s = st.MemoryStore()
        m = synth_market()
        pipeline.run_report(s, m, dt.date(2026, 11, 21), [])
        pipeline.run_report(s, m, dt.date(2026, 11, 18), [])        # 暫定版は置かない
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(sync_pc.sync(s, root), (1, 0, 0))
            p = os.path.join(root, "2026", "11月", "週報_2026-11-21.docx")
            self.assertTrue(os.path.exists(p))
            self.assertEqual(sync_pc.sync(s, root), (0, 0, 0))      # 2回目は何もしない
            # 作り直したレポートが新しければ更新する
            time.sleep(1.1)
            pipeline.run_report(s, m, dt.date(2026, 11, 21), [])
            self.assertEqual(sync_pc.sync(s, root), (0, 1, 0))


if __name__ == "__main__":
    unittest.main()
