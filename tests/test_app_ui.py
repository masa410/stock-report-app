"""画面（app.py）の自動試験：4つの状態で、エラーなく表示され、見出しが出ること（ダミーのデータ）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def run(stage, now):
    os.environ["STOCK_APP_MEMORY"] = "demo"
    os.environ["STOCK_APP_STAGE"] = stage
    os.environ["STOCK_APP_NOW"] = now
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["authed"] = True                 # 合い言葉の画面は、試験では通過済みにする
    at.run()
    return at


def texts(at):
    out = [m.value for m in at.markdown] + [c.value for c in at.caption] + [w.value for w in at.warning] \
        + [e.value for e in at.error] + [i.value for i in at.info] + [s.value for s in at.success]
    return "\n".join(str(x) for x in out)


class TestAppStates(unittest.TestCase):
    def tearDown(self):
        for k in ("STOCK_APP_MEMORY", "STOCK_APP_STAGE", "STOCK_APP_NOW"):
            os.environ.pop(k, None)

    def test_weekday_provisional(self):
        at = run("prov", "2026-11-25 18:20:00")
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        t = texts(at)
        self.assertIn("暫定", t)
        self.assertIn("今日のひとこと", t)
        self.assertIn("今週の日々の動き", t)
        self.assertEqual(len(at.tabs), 7)
        self.assertIn("先週（2026-11-21 の週）の最終版の見通しです", t)       # 見通しは先週の最終版のまま

    def test_saturday_wait_for_note(self):
        at = run("wait", "2026-11-28 09:40:00")
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        t = texts(at)
        self.assertIn("最終・補足待ち", t)
        self.assertIn("補足の期限：11月29日", t)

    def test_after_deadline(self):
        at = run("wait", "2026-11-30 08:00:00")
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        t = texts(at)
        self.assertIn("補足待ち（期限後）", t)
        self.assertIn("期限を過ぎています", t)

    def test_week_list_has_rows(self):
        at = run("prov", "2026-11-25 18:20:00")
        self.assertEqual(len(at.exception), 0)
        self.assertIn("週の一覧", texts(at))


if __name__ == "__main__":
    unittest.main()
