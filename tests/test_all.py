"""オフライン試験（人工データ）。実行: python -m unittest discover -s tests -v"""
import datetime as dt
import io
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analysis
import config
import datasrc
import dictseed
import docx_report
import news
import outlook
import pipeline
import prompt
import report as rpt
import store as st


def bdays(start, end):
    return pd.bdate_range(start, end)


def synth_market(end="2026-11-20", years=9, seed=1, last_high=False):
    idx = bdays(pd.Timestamp(end) - pd.DateOffset(years=years), end)
    rng = np.random.default_rng(seed)
    o = pd.Series(10000 * np.cumprod(1 + rng.normal(0.0004, 0.01, len(idx))), index=idx)
    g = pd.Series(10000 * np.cumprod(1 + rng.normal(0.0003, 0.012, len(idx))), index=idx)
    if last_high:
        o.iloc[-3:] = o.max() * np.array([1.01, 1.02, 1.03])
    m = {"orukan": o, "gold": g,
         "usdjpy": pd.Series(150 + rng.normal(0, 1, len(idx)).cumsum() * 0.1, index=idx),
         "us10y": pd.Series(4 + rng.normal(0, 0.02, len(idx)).cumsum(), index=idx),
         "dxy": pd.Series(100 + rng.normal(0, 0.1, len(idx)).cumsum(), index=idx),
         "vix": pd.Series(18 + rng.normal(0, 0.5, len(idx)).cumsum() * 0.2, index=idx).abs() + 10}
    return m


class TestDatasrc(unittest.TestCase):
    def test_toushin_csv(self):
        csv = "年月日,基準価額(円),純資産総額（百万円）,分配金,決算期\r\n2018年07月03日,10038,1,,\r\n2018年07月07日,10000,1,,\r\n2018年07月04日,9936,1,,\r\n"
        s = datasrc.parse_toushin_csv(csv.encode("cp932"))
        self.assertEqual(len(s), 2)                      # 土曜は除く
        self.assertEqual(float(s.iloc[0]), 10038.0)

    def test_yahoo_parse_drops_weekend_and_nan(self):
        base = int(pd.Timestamp("2026-11-20 00:00").timestamp())
        j = {"chart": {"result": [{"meta": {"gmtoffset": 0},
                                   "timestamp": [base, base + 86400, base + 2 * 86400, base + 3 * 86400],
                                   "indicators": {"quote": [{"close": [1.0, 2.0, None, 4.0]}]}}]}}
        s = datasrc.parse_yahoo_chart(j, "x")
        self.assertTrue((s.index.dayofweek < 5).all())
        self.assertFalse(s.isna().any())


class TestAnalysis(unittest.TestCase):
    def test_new_high_streak(self):
        m = synth_market(last_high=True)
        s = m["orukan"]
        rep = pd.Timestamp("2026-11-21")
        h = analysis.high_update(s, rep)
        self.assertTrue(h["ath_update"])
        self.assertGreater(h["ath_margin"], 0)
        self.assertGreaterEqual(h["ath_streak"], 1)

    def test_no_update_remaining(self):
        s = synth_market()["orukan"]
        s.iloc[-10:] = s.max() * 0.9
        h = analysis.high_update(s, pd.Timestamp("2026-11-21"))
        self.assertFalse(h["ath_update"])
        self.assertAlmostEqual(h["ath_remaining_pct"], 1 / 0.9 - 1, places=3)

    def test_week_with_holiday(self):
        s = synth_market()["orukan"]
        s = s.drop(pd.Timestamp("2026-11-18"))
        prev, end = analysis.week_bounds(s, pd.Timestamp("2026-11-21"))
        self.assertEqual(end, pd.Timestamp("2026-11-20"))
        self.assertEqual(prev, pd.Timestamp("2026-11-13"))

    def test_summary_keys(self):
        s = synth_market()["orukan"]
        r = analysis.weekly_summary(s, pd.Timestamp("2026-11-21"))
        for k in ("close", "week_return", "week_high", "week_low", "ret_1m", "ret_3m", "ret_1y", "ret_ytd", "from_high", "highs"):
            self.assertIn(k, r)
        self.assertLessEqual(r["from_high"], 0)


class TestOutlook(unittest.TestCase):
    def test_probs_sum_100(self):
        for asset in ("orukan", "gold"):
            for h in config.HORIZONS:
                for sc in (-4, -1, 0, 2, 4):
                    self.assertEqual(sum(outlook.rule_probs(asset, h["key"], sc)), 100)

    def test_sign(self):
        up = outlook.rule_probs("orukan", "1m", 3)
        dn = outlook.rule_probs("orukan", "1m", -3)
        self.assertGreater(up[0], dn[0])
        self.assertGreater(dn[2], up[2])

    def test_analog_and_backtest(self):
        m = synth_market()
        o = outlook.build_outlook("orukan", m["orukan"], m, 0.0)
        self.assertEqual([r["key"] for r in o["rows"]], ["1w", "1m", "6m", "3y"])
        self.assertTrue(all(r["analog"] for r in o["rows"]))
        bt = outlook.backtest("gold", m["gold"], m)
        self.assertIn("1m", bt)
        self.assertTrue(0 <= bt["1m"]["hit"] <= 1)

    def test_gold_has_5y(self):
        m = synth_market(years=9)
        o = outlook.build_outlook("gold", m["gold"], m, 0.0)
        self.assertIn("5y", [r["key"] for r in o["rows"]])

    def test_actual_label(self):
        self.assertEqual(outlook.actual_label(0.02, 0.01), "上昇優勢")
        self.assertEqual(outlook.actual_label(-0.02, 0.01), "下落優勢")
        self.assertEqual(outlook.actual_label(0.005, 0.01), "横ばい")


RSS = """<?xml version="1.0"?><rss><channel><title>x</title>
<item><title>米利下げ観測が強まり株価指数が上昇 - 日本経済新聞</title><link>http://a</link><source url="http://n">日本経済新聞</source><pubDate>Fri, 20 Nov 2026 03:00:00 GMT</pubDate></item>
<item><title>米利下げ観測が強まり株価指数上昇 - 株探</title><link>http://b</link><source url="http://k">株探</source><pubDate>Fri, 20 Nov 2026 04:00:00 GMT</pubDate></item>
<item><title>米利下げ観測強まり、株価指数が上昇</title><link>http://c</link><pubDate>Fri, 20 Nov 2026 05:00:00 GMT</pubDate></item>
<item><title>円高が進み輸出関連に売り - Yahoo!ファイナンス</title><link>http://d</link><source url="http://y">Yahoo!ファイナンス</source><pubDate>Fri, 20 Nov 2026 06:00:00 GMT</pubDate></item>
<item><title>ダミー企業が新工場を発表 - Yahoo!ファイナンス</title><link>http://e</link><source url="http://y">Yahoo!ファイナンス</source><pubDate>Fri, 20 Nov 2026 06:30:00 GMT</pubDate></item>
</channel></rss>""".encode("utf-8")


class TestNews(unittest.TestCase):
    def setUp(self):
        self.items = news.parse_rss(RSS, default_source="Yahoo!ニュース")
        self.dict = pipeline.load_dictionary(st.MemoryStore())

    def test_parse_strips_source_suffix(self):
        self.assertEqual(self.items[0]["title"], "米利下げ観測が強まり株価指数が上昇")
        self.assertEqual(self.items[2]["source"], "Yahoo!ニュース")

    def test_cluster_trust(self):
        cl = news.cluster(self.items)
        top = cl[0]
        self.assertEqual(top["n_sources"], 3)
        self.assertEqual(top["trust"], "信ぴょう性が高い")
        singles = [c for c in cl if c["n_sources"] == 1]
        self.assertTrue(all(c["trust"] == "要確認" for c in singles))

    def test_longest_match_not_double_counted(self):
        r = news.score_title("米利下げ観測が強まる", self.dict)
        self.assertEqual(r["scores"]["orukan"], 2)           # 「利下げ観測」(+2)のみ。「利下げ」(+2)を足して4にしない
        self.assertIn("金融政策", r["categories"])

    def test_scope(self):
        r = news.score_title("ドル高が進行", self.dict)
        self.assertEqual(r["scores"]["orukan"], 0)
        self.assertEqual(r["scores"]["gold"], -1)

    def test_unclassified_and_layer_score(self):
        judged, total, un = news.judge(news.cluster(self.items), self.dict)
        self.assertEqual(len(un), 1)
        self.assertIn("ダミー企業が新工場を発表", un[0]["title"])
        s = news.news_layer_score(total["orukan"])
        self.assertTrue(-2 <= s <= 2)
        self.assertEqual(news.news_layer_score({"up": 0, "down": 0}), 0.0)

    def test_candidate_keywords(self):
        self.assertIn("新工場", news.candidate_keywords("ダミー企業が新工場を発表"))


class TestStoreAndPipeline(unittest.TestCase):
    def test_split_join_json(self):
        text = "あ" * 90000
        parts = st.split_json(text)
        self.assertEqual(st.join_json(parts), text)

    def test_collect_dedupe(self):
        s = st.MemoryStore()
        items = news.parse_rss(RSS)
        self.assertEqual(pipeline.collect_headlines(s, items, dt.date(2026, 11, 22)), 5)
        self.assertEqual(pipeline.collect_headlines(s, items, dt.date(2026, 11, 22)), 0)

    def test_final_report_and_forecasts(self):
        s = st.MemoryStore()
        m = synth_market()
        rep = pipeline.run_report(s, m, dt.date(2026, 11, 22), news.parse_rss(RSS))     # 日曜 → 11/21付の最終版
        self.assertEqual(rep["mode"], "最終")
        self.assertEqual(rep["report_date"], "2026-11-21")
        fr = s.read(config.SH_FORECAST)
        self.assertEqual(len(fr), 4 + 5)
        self.assertEqual(fr[0]["status"], "未確認")
        # 同じ週をやり直すと、前の予想は「差し替え」になる
        pipeline.run_report(s, m, dt.date(2026, 11, 22), [])
        fr = s.read(config.SH_FORECAST)
        self.assertEqual(sum(1 for r in fr if r["status"] == "差し替え"), 9)
        self.assertEqual(sum(1 for r in fr if r["status"] == "未確認"), 9)
        self.assertEqual(len(s.read(config.SH_PRICE)), 1)

    def test_provisional_has_no_outlook(self):
        s = st.MemoryStore()
        rep = pipeline.run_report(s, synth_market(), dt.date(2026, 11, 18), [])         # 水曜
        self.assertEqual(rep["mode"], "暫定")
        self.assertEqual(rep["report_date"], "2026-11-18")
        self.assertNotIn("outlook", rep["assets"]["orukan"])
        self.assertIsNone(rep["answers"])
        self.assertEqual(len(s.read(config.SH_FORECAST)), 0)

    def test_resolve_forecasts(self):
        s = st.MemoryStore()
        m = synth_market(end="2026-11-20")
        pipeline.run_report(s, m, dt.date(2026, 11, 21), [])
        # 1週間後のデータが届いた状態にする
        m2 = synth_market(end="2026-11-27")
        for k in m2:
            m2[k] = pd.concat([m[k], m2[k][m2[k].index > m[k].index[-1]]])
        n = rpt.resolve_forecasts(s, m2)
        self.assertEqual(n, 2)                                   # オルカン・ゴールドの「来週」だけ
        done = [r for r in s.read(config.SH_FORECAST) if r["status"] == "確認済み"]
        self.assertTrue(all(r["hit"] in ("当たり", "外れ") for r in done))
        self.assertEqual(rpt.resolve_forecasts(s, m2), 0)        # 二重に処理しない

    def test_save_report_keeps_history(self):
        s = st.MemoryStore()
        st.save_report(s, "2026-11-21", "最終", "a", {"x": 1})
        st.save_report(s, "2026-11-21", "最終", "b", {"x": 2})
        reps = st.load_reports(s)
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0][3]["x"], 2)
        self.assertEqual(sum(1 for r in s.read(config.SH_REPORT) if r["mode"] == "履歴"), 1)

    def test_final_sorted_after_provisional_of_same_week(self):
        s = st.MemoryStore()
        m = synth_market()
        pipeline.run_report(s, m, dt.date(2026, 11, 21), [])        # 最終（先に作る）
        pipeline.run_report(s, m, dt.date(2026, 11, 18), [])        # 暫定（あとで作る）
        reps = st.load_reports(s)
        self.assertEqual([r[1] for r in reps], ["暫定", "最終"])

    def test_week_key_and_mode(self):
        self.assertEqual(rpt.week_key_and_mode(dt.date(2026, 11, 21)), (dt.date(2026, 11, 21), "最終"))   # 土
        self.assertEqual(rpt.week_key_and_mode(dt.date(2026, 11, 22)), (dt.date(2026, 11, 21), "最終"))   # 日
        self.assertEqual(rpt.week_key_and_mode(dt.date(2026, 11, 18)), (dt.date(2026, 11, 21), "暫定"))   # 水

    def test_add_dictionary_word(self):
        s = st.MemoryStore()
        n0 = len(pipeline.load_dictionary(s))
        pipeline.add_dictionary_word(s, "新工場", "企業業績", "上昇")
        d = pipeline.load_dictionary(s)
        self.assertEqual(len(d), n0 + 1)
        self.assertEqual(d[-1]["score"], 1)


class TestPromptAndDocx(unittest.TestCase):
    def test_parse_note(self):
        text = "## 今週の総括\n円高と利下げ観測が交錯しました。\n## 辞書への追加候補\n新工場|企業業績|上昇\nおかしな行\n"
        sec, cands = prompt.parse_note(text)
        self.assertIn("今週の総括", sec)
        self.assertEqual(cands, [("新工場", "企業業績", "上昇")])

    def test_docx_smoke(self):
        s = st.MemoryStore()
        m = synth_market(last_high=True)
        rep = pipeline.run_report(s, m, dt.date(2026, 11, 21), news.parse_rss(RSS))
        rep["claude_note"] = {"sections": {"今週の総括": "テスト"}, "candidates": [], "saved_at": "2026-11-21T10:00:00"}
        buf = io.BytesIO()
        docx_report.build_docx(rep, buf)
        self.assertGreater(len(buf.getvalue()), 20000)
        self.assertIn("最高値を更新", "".join(__import__("fmt").highs_lines(rep)))
        self.assertIn("おすすめ", "おすすめ")                      # 文字コード確認用
        self.assertTrue(prompt.build_prompt(rep).startswith("あなたは"))
        # 暫定版
        rep2 = pipeline.run_report(s, m, dt.date(2026, 11, 18), [])
        buf2 = io.BytesIO()
        docx_report.build_docx(rep2, buf2)
        self.assertGreater(len(buf2.getvalue()), 20000)


if __name__ == "__main__":
    unittest.main()
