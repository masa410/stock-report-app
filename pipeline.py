"""週次・毎日の一連の処理（取得済みのデータを受け取り、分析・保存まで行う）。ネットワークには触れない。"""
import datetime as dt

import config
import dictseed
import news as newsmod
import notify
import outlook
import report as rpt
import store as st


def load_dictionary(store):
    rows = store.read(config.SH_DICT)
    if not rows:
        store.append(config.SH_DICT, newsmod.dict_rows_from_seed(dictseed.SEED))
        rows = store.read(config.SH_DICT)
    out = []
    for r in rows:
        try:
            out.append({"keyword": r["keyword"], "category": r["category"], "score": int(float(r["score"] or 0)),
                        "scope": r["scope"] or "all"})
        except ValueError:
            continue
    return out


def add_dictionary_word(store, keyword, category, direction, today=None):
    """辞書に語を足す（アプリの選択式の入口から呼ぶ）。direction: 上昇/下落/影響なし。"""
    score = {"上昇": 1, "下落": -1}.get(direction, 0)
    store.append(config.SH_DICT, [{"keyword": keyword, "category": category, "score": score, "scope": "all",
                                   "added": str(today or rpt.now_jst().date())}])


def _as_datetime(when):
    if when is None:
        return rpt.now_jst()
    if isinstance(when, dt.datetime):
        return when
    return dt.datetime.combine(when, dt.time(12, 0))


def collect_headlines(store, items, today=None):
    """新しい見出しだけをシートへ足す（取得日・取得時刻・週・取得回つき）。戻り値: 足した件数。"""
    when = _as_datetime(today)
    week = str(rpt.coming_saturday(when))
    have = {(r["title"], r["source"]) for r in store.read(config.SH_NEWS)}
    new = []
    for it in items:
        k = (it["title"], it["source"])
        if k in have:
            continue
        have.add(k)
        new.append({"fetched": str(when.date()), "published": it["published"], "title": it["title"],
                    "source": it["source"], "link": it["link"], "fetched_time": when.strftime("%H:%M"),
                    "week": week, "run": rpt.run_label(when)})
    if new:
        store.append(config.SH_NEWS, new)
    return len(new)


def recent_headlines(store, today, days=7, week=None):
    """その週（土曜から土曜）の見出し。週の列がない古い行は、日付で近いものだけ拾う。"""
    base = week if week is not None else today
    cut = str(base - dt.timedelta(days=days))
    out = []
    for r in store.read(config.SH_NEWS):
        if week is not None and r.get("week"):
            if r["week"] != str(week):
                continue
        elif (r["published"] or r["fetched"]) < cut:
            continue
        out.append({"title": r["title"], "source": r["source"], "link": r["link"], "published": r["published"],
                    "fetched": r["fetched"]})
    return out


def make_news_pack(store, fresh_items, today, week=None):
    items = newsmod.dedupe_exact(recent_headlines(store, today, week=week) + list(fresh_items))
    dictionary = load_dictionary(store)
    clusters = newsmod.cluster(items)
    return newsmod.judge(clusters, dictionary)


# ---------------- 週一覧（見返し用の軽い表） ----------------
def _high_label(report):
    flags = [report["assets"][a]["summary"]["highs"]["ath_update"] for a in ("orukan", "gold")]
    return "両方" if all(flags) else "オルカン" if flags[0] else "ゴールド" if flags[1] else "なし"


def sync_week_row(store, report, now=None):
    """最終版（と補足の状態）から、週一覧の1行を作る・更新する。見通しの結果は、あとから自動で入る。"""
    o, g = report["assets"]["orukan"], report["assets"]["gold"]
    one_w = [r["judgment"] for r in o.get("outlook", {}).get("rows", []) if r["key"] == "1w"]
    old = next((r for r in store.read(config.SH_WEEKS) if r["week"] == report["report_date"]), {})
    note = report.get("claude_note") or {}
    row = {"week": report["report_date"], "orukan": round(o["summary"]["close"]), "gold": round(g["summary"]["close"]),
           "orukan_ret": round(o["summary"]["week_return"] * 100, 2), "gold_ret": round(g["summary"]["week_return"] * 100, 2),
           "high": _high_label(report), "outlook": one_w[0] if one_w else "", "result": old.get("result", ""),
           "note_state": st.note_state(report, now), "note_at": note.get("saved_at", "")}
    return st.upsert(store, config.SH_WEEKS, "week", row)


def update_week_results(store):
    """答え合わせが済んだ「来週の見通し」の結果（当たり／外れ）を、週一覧に書く。"""
    done = {r["report_week"]: r["hit"] for r in store.read(config.SH_FORECAST)
            if r["asset"] == "orukan" and r["horizon"] == "1w" and r["status"] == "確認済み"}
    for i, r in enumerate(store.read(config.SH_WEEKS)):
        if r["week"] in done and r["result"] != done[r["week"]]:
            store.update(config.SH_WEEKS, i, dict(r, result=done[r["week"]]))


def backfill_weeks(store, now=None):
    """最終版はあるのに、週一覧に行がない週（この機能を入れる前の週）を、自動で埋める。戻り値: 足した行数。"""
    have = {r["week"] for r in store.read(config.SH_WEEKS)}
    n = 0
    for w, m, _g, rep in st.load_reports(store):
        if m == "最終" and w not in have:
            sync_week_row(store, rep, now)
            n += 1
    if n:
        update_week_results(store)
    return n


# ---------------- 毎日の更新（暫定版） ----------------
def _daily_row(market, now, week):
    def last2(key):
        s = market[key].dropna()
        return float(s.iloc[-1]), (float(s.iloc[-2]) if len(s) > 1 else None)

    def chg(a, b):
        return round((a / b - 1.0) * 100, 2) if b else ""

    o, op = last2("orukan")
    g, gp = last2("gold")
    return {"date": str(now.date()), "week": str(week), "fetched_at": str(now), "orukan": round(o, 2), "gold": round(g, 2),
            "usdjpy": round(float(market["usdjpy"].dropna().iloc[-1]), 3), "us10y": round(float(market["us10y"].dropna().iloc[-1]), 3),
            "dxy": round(float(market["dxy"].dropna().iloc[-1]), 3), "vix": round(float(market["vix"].dropna().iloc[-1]), 2),
            "orukan_chg": chg(o, op), "gold_chg": chg(g, gp)}


def run_provisional(store, market, now, fresh=(), problems=None):
    """暫定版を作って、日ごとに保存する（同じ日は上書き）。見通しの確率・答え合わせは、土曜の最終版だけ。"""
    week = rpt.coming_saturday(now)
    news_pack = make_news_pack(store, fresh, now.date(), week)
    report, _prices, _as_of = rpt.build_report(market, news_pack, week, "暫定", problems=problems)
    report["weekday"] = rpt._weekday_ja(now.date())
    report["fetched_at"] = str(now)
    st.save_prov(store, now.date(), week, str(now), report)
    st.upsert(store, config.SH_DAILY, "date", _daily_row(market, now, week))
    return report


def run_daily(store, market, now, fresh=(), problems=None, sender=None):
    """毎日の更新（朝・夕）。戻り値: {"kind", "added", "report", "alerts"}"""
    backfill_weeks(store, now)
    added = collect_headlines(store, fresh, now)
    kind = rpt.run_kind(now)
    out = {"kind": kind, "added": added, "report": None, "alerts": []}
    if kind == "暫定":
        out["report"] = run_provisional(store, market, now, (), problems)
        out["alerts"] = notify.check_and_send(store, market, now, sender)
    return out


# ---------------- 土曜の最終版 ----------------
def run_report(store, market, today, fresh_headlines=(), problems=None, now=None):
    """戻り値: レポート(dict)。today は実行日（datetime.date）。土・日は最終版、それ以外は暫定版。"""
    week, mode = rpt.week_key_and_mode(today)
    if mode == "暫定":
        return run_provisional(store, market, now or dt.datetime.combine(today, dt.time(18, 10)), fresh_headlines, problems)
    news_pack = make_news_pack(store, fresh_headlines, today, week)
    rpt.resolve_forecasts(store, market)
    backtests = {a: outlook.backtest(a, market[a].dropna(), market) for a in ("orukan", "gold")}
    answers = rpt.answers_section(store, backtests)
    report, prices, as_of = rpt.build_report(market, news_pack, week, "最終", backtests, answers, problems)
    new_rows = rpt.forecast_rows_from(week, as_of, report["assets"], prices)
    old = store.read(config.SH_FORECAST)
    for i, r in enumerate(old):          # 同じ週をやり直したときは、前の予想を「差し替え」にする
        if r["report_week"] == str(week) and r["status"] == "未確認":
            store.update(config.SH_FORECAST, i, dict(r, status="差し替え"))
    store.append(config.SH_FORECAST, new_rows)
    have = {r["date"] for r in store.read(config.SH_PRICE)}
    prow = rpt.price_row(market, as_of)
    if prow["date"] not in have:
        store.append(config.SH_PRICE, [prow])
    if not report.get("claude_note"):
        # 同じ週をやり直しても、取り込み済みのClaudeの補足は消さずに引き継ぐ
        prev = [r for w, m, _g, r in st.load_reports(store) if w == str(week) and m == "最終" and r.get("claude_note")]
        if prev:
            report["claude_note"] = prev[-1]["claude_note"]
    st.save_report(store, str(week), mode, report["generated_at"], report)
    sync_week_row(store, report, now or rpt.now_jst())
    update_week_results(store)
    return report
