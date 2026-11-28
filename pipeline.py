"""週次の一連の処理（取得済みのデータを受け取り、分析・保存まで行う）。ネットワークには触れない。"""
import datetime as dt

import config
import dictseed
import news as newsmod
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


def collect_headlines(store, items, today=None):
    """新しい見出しだけをシートへ足す。戻り値: 足した件数。"""
    today = today or rpt.now_jst().date()
    have = {(r["title"], r["source"]) for r in store.read(config.SH_NEWS)}
    new = []
    for it in items:
        k = (it["title"], it["source"])
        if k in have:
            continue
        have.add(k)
        new.append({"fetched": str(today), "published": it["published"], "title": it["title"],
                    "source": it["source"], "link": it["link"]})
    if new:
        store.append(config.SH_NEWS, new)
    return len(new)


def recent_headlines(store, today, days=7):
    cut = str(today - dt.timedelta(days=days))
    out = []
    for r in store.read(config.SH_NEWS):
        if (r["published"] or r["fetched"]) >= cut:
            out.append({"title": r["title"], "source": r["source"], "link": r["link"], "published": r["published"]})
    return out


def make_news_pack(store, fresh_items, today):
    items = newsmod.dedupe_exact(recent_headlines(store, today) + list(fresh_items))
    dictionary = load_dictionary(store)
    clusters = newsmod.cluster(items)
    return newsmod.judge(clusters, dictionary)


def run_report(store, market, today, fresh_headlines=(), problems=None):
    """戻り値: レポート(dict)。today は実行日（datetime.date）。"""
    week, mode = rpt.week_key_and_mode(today)
    news_pack = make_news_pack(store, fresh_headlines, today)
    backtests = answers = None
    if mode == "最終":
        rpt.resolve_forecasts(store, market)
        backtests = {a: outlook.backtest(a, market[a].dropna(), market) for a in ("orukan", "gold")}
        answers = rpt.answers_section(store, backtests)
    report_date = week if mode == "最終" else today
    report, prices, as_of = rpt.build_report(market, news_pack, report_date, mode, backtests, answers, problems)
    if mode == "最終":
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
    if mode == "最終" and not report.get("claude_note"):
        # 同じ週をやり直しても、取り込み済みのClaudeの補足は消さずに引き継ぐ
        prev = [r for w, m, _g, r in st.load_reports(store) if w == str(week) and m == "最終" and r.get("claude_note")]
        if prev:
            report["claude_note"] = prev[-1]["claude_note"]
    st.save_report(store, str(week), mode, report["generated_at"], report)
    return report
