"""画面確認用：人工データで保存先を満たす（本番では使わない）。
STOCK_APP_STAGE: prov（平日・暫定版が出ている）／wait（土曜9:23・最終版ができて補足待ち）。時刻は STOCK_APP_NOW で固定する。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import news
import pipeline
import store as st
from test_all import RSS, synth_market

SAT = dt.date(2026, 11, 28)


def _final(store, sat, items, note_at=None):
    end = (sat - dt.timedelta(days=1)).isoformat()
    m = synth_market(end=end)
    rep = pipeline.run_report(store, m, sat, items, now=dt.datetime.combine(sat, dt.time(9, 31)))
    if note_at:
        rep = dict(rep, claude_note={"sections": {"今週の動きの要因（調べた結果）": "【ダミー】調べた結果の文章が入ります。",
                                                  "来週の予定と注目点": "【ダミー】来週の予定が入ります。"},
                                     "candidates": [], "saved_at": note_at})
        st.save_report(store, sat.isoformat(), "最終", rep["generated_at"], rep)
        pipeline.sync_week_row(store, rep, dt.datetime.fromisoformat(note_at))
    return rep


def fill(store, stage=None):
    stage = stage or os.environ.get("STOCK_APP_STAGE", "prov")
    items = news.parse_rss(RSS)
    weeks = [dt.date(2026, 10, 31), dt.date(2026, 11, 7), dt.date(2026, 11, 14), dt.date(2026, 11, 21)]
    notes = {dt.date(2026, 11, 7): "2026-11-08 20:41:00", dt.date(2026, 11, 14): "2026-11-15 21:05:00",
             dt.date(2026, 11, 21): "2026-11-23 08:00:00"}           # 11/21の週は、期限後に取り込み
    for w in weeks:
        _final(store, w, items, notes.get(w))
    if stage == "wait":
        _final(store, SAT, items)
    else:
        m = synth_market(end="2026-11-25")
        pipeline.run_daily(store, m, dt.datetime(2026, 11, 25, 7, 13), items)
        pipeline.run_daily(store, m, dt.datetime(2026, 11, 25, 18, 13), items)
    stmod = st
    stmod.set_memo(store, "2026-11-14", "【ダミー】メモの例です。", "2026-11-16 10:00:00")
