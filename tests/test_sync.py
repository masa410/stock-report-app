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
            p = os.path.join(root, "2026年", "11月", "週報_2026-11-21.docx")
            self.assertTrue(os.path.exists(p))
            self.assertEqual(sync_pc.sync(s, root), (0, 0, 0))      # 2回目は何もしない
            # 作り直したレポートが新しければ更新する
            time.sleep(1.1)
            pipeline.run_report(s, m, dt.date(2026, 11, 21), [])
            self.assertEqual(sync_pc.sync(s, root), (0, 1, 0))
            # 補足を取り込んだら、Wordを更新する
            self.assertEqual(sync_pc.sync(s, root), (0, 0, 0))
            time.sleep(1.1)
            rows = s.read(st.config.SH_REPORT)
            rep = [r for r in st.load_reports(s) if r[1] == "最終"][-1]
            body = dict(rep[3], claude_note={"sections": {"今週の動きの要因": "テスト"}, "candidates": [],
                                              "saved_at": dt.datetime.now().isoformat(timespec="seconds")})
            st.save_report(s, rep[0], rep[1], rep[2], body)
            self.assertEqual(sync_pc.sync(s, root), (0, 1, 0))

    def test_catch_up_many_weeks_and_year_change(self):
        """何週も押さなかったとき、年・月をまたいでも、置いていない週を全部作る。"""
        s = st.MemoryStore()
        m = synth_market()
        for d in (dt.date(2026, 12, 12), dt.date(2026, 12, 19), dt.date(2026, 12, 26)):
            pipeline.run_report(s, m, d, [])
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(sync_pc.sync(s, root), (3, 0, 0))
            for w in ("2026年/12月/週報_2026-12-12.docx", "2026年/12月/週報_2026-12-19.docx", "2026年/12月/週報_2026-12-26.docx"):
                self.assertTrue(os.path.exists(os.path.join(root, *w.split("/"))), w)
            pipeline.run_report(s, m, dt.date(2027, 1, 2), [])
            self.assertEqual(sync_pc.sync(s, root), (1, 0, 0))
            self.assertTrue(os.path.exists(os.path.join(root, "2027年", "1月", "週報_2027-01-02.docx")))


if __name__ == "__main__":
    unittest.main()
