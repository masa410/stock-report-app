"""画面確認用：人工データで保存先を満たす（本番では使わない）。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import news
import pipeline
from test_all import RSS, synth_market


def fill(store):
    m = synth_market(last_high=True)
    pipeline.run_report(store, m, dt.date(2026, 11, 14) if False else dt.date(2026, 11, 21), news.parse_rss(RSS))
    pipeline.run_report(store, m, dt.date(2026, 11, 18), [])
