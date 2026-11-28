"""毎日の更新・週の区切り・補足の期限・通知・シートの移行の試験（人工データ）。"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import news
import notify
import pipeline
import report as rpt
import store as st
from test_all import RSS, synth_market

ITEMS = news.parse_rss(RSS)


class TestWeekRules(unittest.TestCase):
    def test_coming_saturday(self):
        f = rpt.coming_saturday
        self.assertEqual(f(dt.datetime(2026, 11, 23, 7, 13)), dt.date(2026, 11, 28))     # 月
        self.assertEqual(f(dt.datetime(2026, 11, 27, 18, 13)), dt.date(2026, 11, 28))    # 金
        self.assertEqual(f(dt.datetime(2026, 11, 28, 9, 22)), dt.date(2026, 11, 28))     # 土 9:22（まだ今週）
        self.assertEqual(f(dt.datetime(2026, 11, 28, 9, 23)), dt.date(2026, 12, 5))      # 土 9:23（来週）
        self.assertEqual(f(dt.datetime(2026, 11, 29, 20, 0)), dt.date(2026, 12, 5))      # 日
        self.assertEqual(f(dt.datetime(2026, 12, 31, 18, 10)), dt.date(2027, 1, 2))      # 年またぎ

    def test_run_kind(self):
        self.assertEqual(rpt.run_kind(dt.datetime(2026, 11, 25, 7, 13)), "暫定")
        self.assertEqual(rpt.run_kind(dt.datetime(2026, 11, 28, 7, 13)), "暫定")         # 土曜の朝（9:23より前）
        self.assertEqual(rpt.run_kind(dt.datetime(2026, 11, 28, 18, 13)), "取得のみ")    # 土曜の夕
        self.assertEqual(rpt.run_kind(dt.datetime(2026, 11, 29, 7, 13)), "取得のみ")     # 日曜

    def test_note_due_and_late(self):
        self.assertEqual(rpt.note_due_for("2026-11-28"), "2026-11-29 23:59:59")
        rep = {"mode": "最終", "note_due": "2026-11-29 23:59:59"}
        self.assertEqual(st.report_status(rep, "2026-11-28 12:00:00"), "最終・補足待ち")
        self.assertEqual(st.report_status(rep, "2026-11-30 08:00:00"), "補足待ち（期限後）")
        ok = dict(rep, claude_note={"saved_at": "2026-11-29 20:41:00"})
        late = dict(rep, claude_note={"saved_at": "2026-11-30 08:00:00"})
        self.assertEqual((st.note_late(ok), st.note_state(ok), st.report_status(ok)), (False, "済み", "完成"))
        self.assertEqual((st.note_late(late), st.note_state(late)), (True, "期限後"))
        self.assertEqual(st.report_extras(late)["note_late"], "はい")
        self.assertEqual(st.report_status({"mode": "暫定"}), "暫定")


class TestDaily(unittest.TestCase):
    def setUp(self):
        self.m = synth_market(end="2026-11-25")                 # 水曜までのデータ
        self.s = st.MemoryStore()

    def test_weekday_makes_provisional_per_day(self):
        out = pipeline.run_daily(self.s, self.m, dt.datetime(2026, 11, 25, 7, 13), ITEMS)
        self.assertEqual(out["kind"], "暫定")
        rep = out["report"]
        self.assertEqual((rep["mode"], rep["week"], rep["weekday"]), ("暫定", "2026-11-28", "水"))
        self.assertEqual(rep["daily"]["dates"], ["2026-11-23", "2026-11-24", "2026-11-25"])     # 先週金曜の次の日から
        self.assertIn("今週ここまで", rep["one_liner"])
        self.assertIn("ゴールド", rep["one_liner"])
        self.assertTrue(rep["position"]["orukan"])
        self.assertNotIn("outlook", rep["assets"]["orukan"])         # 見通しの確率は、土曜の最終版だけ
        # 同じ日の夕方は、同じ行を上書き（日ごとに1行）
        pipeline.run_daily(self.s, self.m, dt.datetime(2026, 11, 25, 18, 13), ITEMS)
        self.assertEqual(len(self.s.read(config.SH_PROV)), 1)
        self.assertEqual(len(self.s.read(config.SH_DAILY)), 1)
        pipeline.run_daily(self.s, self.m, dt.datetime(2026, 11, 26, 7, 13), ITEMS)
        self.assertEqual(len(self.s.read(config.SH_PROV)), 2)

    def test_news_columns_and_week(self):
        pipeline.run_daily(self.s, self.m, dt.datetime(2026, 11, 25, 7, 13), ITEMS)
        r = self.s.read(config.SH_NEWS)[0]
        self.assertEqual((r["week"], r["run"], r["fetched_time"], r["fetched"]), ("2026-11-28", "朝", "07:13", "2026-11-25"))
        pipeline.run_daily(self.s, self.m, dt.datetime(2026, 11, 29, 18, 13), [dict(ITEMS[0], title="日曜の別の見出し")])
        last = self.s.read(config.SH_NEWS)[-1]
        self.assertEqual((last["week"], last["run"]), ("2026-12-05", "夕"))   # 日曜の記事は、来週の分

    def test_weekend_only_collects_news(self):
        out = pipeline.run_daily(self.s, self.m, dt.datetime(2026, 11, 28, 18, 13), ITEMS)
        self.assertEqual(out["kind"], "取得のみ")
        self.assertIsNone(out["report"])
        self.assertEqual(self.s.read(config.SH_PROV), [])
        self.assertGreater(len(self.s.read(config.SH_NEWS)), 0)

    def test_news_pack_uses_the_week_only(self):
        self.s.append(config.SH_NEWS, [{"fetched": "2026-11-18", "published": "2026-11-18", "title": "先週の見出しＡ", "source": "X",
                                         "link": "", "fetched_time": "07:00", "week": "2026-11-21", "run": "朝"}])
        pipeline.run_daily(self.s, self.m, dt.datetime(2026, 11, 25, 7, 13), ITEMS)
        titles = [c["title"] for c in st.load_provs(self.s)[-1][3]["news"]["clusters"]]
        self.assertNotIn("先週の見出しＡ", titles)


class TestWeeksAndResults(unittest.TestCase):
    def test_week_rows_results_and_note_state(self):
        s = st.MemoryStore()
        m1 = synth_market(end="2026-11-13")
        pipeline.run_report(s, m1, dt.date(2026, 11, 14), ITEMS)
        m2 = synth_market(end="2026-11-20")
        rep2 = pipeline.run_report(s, m2, dt.date(2026, 11, 21), ITEMS, now=dt.datetime(2026, 11, 21, 9, 31))
        rows = {r["week"]: r for r in s.read(config.SH_WEEKS)}
        self.assertEqual(set(rows), {"2026-11-14", "2026-11-21"})
        self.assertIn(rows["2026-11-14"]["result"], ("当たり", "外れ"))      # 1週後に、答え合わせが入る
        self.assertEqual(rows["2026-11-21"]["result"], "")
        self.assertEqual(rows["2026-11-21"]["note_state"], "待ち")
        self.assertEqual(rep2["note_due"], "2026-11-22 23:59:59")
        # 補足を取り込む → 完成。週一覧も更新
        rep2 = dict(rep2, claude_note={"sections": {"a": "b"}, "candidates": [], "saved_at": "2026-11-22 20:00:00"})
        st.save_report(s, "2026-11-21", "最終", rep2["generated_at"], rep2)
        pipeline.sync_week_row(s, rep2)
        rows = {r["week"]: r for r in s.read(config.SH_WEEKS)}
        self.assertEqual((rows["2026-11-21"]["note_state"], rows["2026-11-21"]["note_at"]), ("済み", "2026-11-22 20:00:00"))
        final = [r for r in s.read(config.SH_REPORT) if r["week"] == "2026-11-21" and r["mode"] == "最終"][0]
        self.assertEqual((final["state"], final["note_late"]), ("完成", "いいえ"))

    def test_backfill_weeks(self):
        s = st.MemoryStore()
        pipeline.run_report(s, synth_market(end="2026-11-13"), dt.date(2026, 11, 14), ITEMS)
        pipeline.run_report(s, synth_market(end="2026-11-20"), dt.date(2026, 11, 21), ITEMS)
        s.data[config.SH_WEEKS] = []                          # この機能を入れる前の状態（週一覧が空）
        self.assertEqual(pipeline.backfill_weeks(s), 2)
        rows = {r["week"]: r for r in s.read(config.SH_WEEKS)}
        self.assertIn(rows["2026-11-14"]["result"], ("当たり", "外れ"))
        self.assertEqual(pipeline.backfill_weeks(s), 0)         # 2回目は何もしない

    def test_year_change_weeks(self):
        s = st.MemoryStore()
        pipeline.run_report(s, synth_market(end="2026-12-25"), dt.date(2026, 12, 26), ITEMS)
        pipeline.run_report(s, synth_market(end="2027-01-01"), dt.date(2027, 1, 2), ITEMS)
        self.assertEqual([r["week"] for r in s.read(config.SH_WEEKS)], ["2026-12-26", "2027-01-02"])
        self.assertEqual(rpt.note_due_for("2027-01-02"), "2027-01-03 23:59:59")


class TestNotify(unittest.TestCase):
    def setUp(self):
        self.s = st.MemoryStore()
        self.sent = []

    def sender(self, subject, body, to):
        self.sent.append((subject, to))
        return True

    def market_with_move(self, pct):
        m = synth_market(end="2026-11-25")
        o = m["orukan"].copy()
        o.iloc[-1] = o.iloc[-2] * (1 + pct / 100)
        m["orukan"] = o
        return m

    def test_no_recipient_sends_nothing(self):
        m = self.market_with_move(-5)
        self.assertEqual(notify.check_and_send(self.s, m, dt.datetime(2026, 11, 25, 18, 13), self.sender), [])
        self.assertEqual(self.sent, [])

    def test_big_move_sent_once(self):
        st.get_settings(self.s)
        rows = self.s.read(config.SH_SETTINGS)
        for i, r in enumerate(rows):
            if r["item"] == "通知先メール":
                self.s.update(config.SH_SETTINGS, i, dict(r, value="me@example.com"))
        m = self.market_with_move(-5)
        a = notify.check_and_send(self.s, m, dt.datetime(2026, 11, 25, 18, 13), self.sender)
        self.assertEqual([e["kind"] for e in a if e["kind"] == "大きな動き"], ["大きな動き"])
        n = len(self.sent)
        notify.check_and_send(self.s, m, dt.datetime(2026, 11, 26, 7, 13), self.sender)      # 同じ出来事は、二重に送らない
        self.assertEqual(len(self.sent), n)
        self.assertEqual(self.sent[0][1], "me@example.com")

    def test_threshold_and_high(self):
        st.get_settings(self.s)
        for i, r in enumerate(self.s.read(config.SH_SETTINGS)):
            if r["item"] == "通知先メール":
                self.s.update(config.SH_SETTINGS, i, dict(r, value="me@example.com"))
        m = self.market_with_move(+0.5)
        ev = notify.detect(m, dt.datetime(2026, 11, 25, 18, 13), 3.0)
        self.assertFalse([e for e in ev if e["kind"] == "大きな動き"])         # 小さな動きは通知しない
        m2 = self.market_with_move(+30)
        kinds = {e["kind"] for e in notify.detect(m2, dt.datetime(2026, 11, 25, 18, 13), 3.0)}
        self.assertIn("最高値の更新", kinds)

    def test_old_data_not_notified(self):
        m = self.market_with_move(-9)
        self.assertEqual(notify.detect(m, dt.datetime(2026, 12, 25, 18, 13), 3.0), [])      # 古い営業日は見ない


class FakeClient:
    def __init__(self, header):
        self.header, self.updated = header, None

    def ensure_sheet(self, title, headers):
        pass

    def get_header(self, title):
        return self.header

    def batch_update_rows(self, title, updates, raw=False):
        self.updated = (title, updates, raw)


class TestHeaderMigration(unittest.TestCase):
    def make(self, header):
        s = st.SheetsStore.__new__(st.SheetsStore)
        s.c, s._ready = FakeClient(header), set()
        return s

    def test_old_header_is_extended(self):
        old = [jp for _, jp in st.COLUMNS[config.SH_NEWS]][:5]
        s = self.make(old)
        s.ensure(config.SH_NEWS)
        want = [jp for _, jp in st.COLUMNS[config.SH_NEWS]]
        self.assertEqual(s.c.updated, (config.SH_NEWS, [(0, want)], True))

    def test_current_or_unknown_header_untouched(self):
        want = [jp for _, jp in st.COLUMNS[config.SH_NEWS]]
        s = self.make(want)
        s.ensure(config.SH_NEWS)
        self.assertIsNone(s.c.updated)
        s2 = self.make(["ぜんぜん", "別の見出し"])                   # 見覚えのない見出しは、触らない
        s2.ensure(config.SH_NEWS)
        self.assertIsNone(s2.c.updated)


class TestMemoAndSettings(unittest.TestCase):
    def test_memo_roundtrip(self):
        s = st.MemoryStore()
        self.assertEqual(st.get_memo(s, "2026-11-21"), "")
        st.set_memo(s, "2026-11-21", "メモ1", "2026-11-22 10:00:00")
        st.set_memo(s, "2026-11-21", "メモ2", "2026-11-22 11:00:00")
        self.assertEqual(st.get_memo(s, "2026-11-21"), "メモ2")
        self.assertEqual(len(s.read(config.SH_MEMO)), 1)

    def test_settings_seeded(self):
        s = st.MemoryStore()
        d = st.get_settings(s)
        self.assertEqual(d["通知を送る"], "はい")
        self.assertEqual(d["大きな動きの目安（前日比 ±%）"], "3")


if __name__ == "__main__":
    unittest.main()
