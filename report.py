"""レポート（辞書型）の組み立てと、見通しの記録・答え合わせ。"""
import datetime as dt

import pandas as pd

import analysis
import config
import news as newsmod
import outlook

JST = dt.timezone(dt.timedelta(hours=9))


def now_jst():
    return dt.datetime.now(JST).replace(tzinfo=None, microsecond=0)


def week_key_and_mode(today):
    """実行した日から、レポートの週（土曜の日付）と種別を決める。土・日は本番、それ以外は暫定版。"""
    wd = today.weekday()      # 月0 … 土5 日6
    if wd == 5:
        return today, "最終"
    if wd == 6:
        return today - dt.timedelta(days=1), "最終"
    return today + dt.timedelta(days=5 - wd), "暫定"


def _weekday_ja(d):
    return "月火水木金土日"[d.weekday()]


def build_news_section(judged, total, unclassified):
    items = sorted(judged, key=lambda c: (-c["n_sources"], -(abs(c["scores"]["orukan"]) + abs(c["scores"]["gold"]))))
    shown = []
    for c in items[:15]:
        shown.append({"title": c["title"], "n_sources": c["n_sources"], "trust": c["trust"], "sources": c["sources"][:6],
                      "categories": c["categories"], "scores": c["scores"], "link": (c["links"] or [""])[0]})
    un = []
    for c in unclassified[:12]:
        un.append({"title": c["title"], "n_sources": c["n_sources"], "trust": c["trust"],
                   "candidates": newsmod.candidate_keywords(c["title"])})
    return {"clusters": shown, "total": {a: {"up": round(v["up"], 1), "down": round(v["down"], 1)} for a, v in total.items()},
            "scores": {a: newsmod.news_layer_score(total[a]) for a in total},
            "n_topics": len(judged), "unclassified": un, "n_unclassified": len(unclassified)}


def forecast_rows_from(report_week, as_of, assets_out, prices):
    rows = []
    for asset, block in assets_out.items():
        base = prices[asset]
        for r in block["outlook"]["rows"]:
            target = as_of + dt.timedelta(days=r["cal"])
            rows.append({"report_week": str(report_week), "asset": asset, "horizon": r["key"], "issued": str(as_of)[:10],
                         "target": str(target)[:10], "judgment": r["judgment"], "p_up": r["probs"][0], "p_flat": r["probs"][1],
                         "p_down": r["probs"][2], "base_price": base, "band": r["band"], "status": "未確認",
                         "actual_return": "", "actual_label": "", "hit": ""})
    return rows


def resolve_forecasts(store, market):
    """目標日が過ぎた予想に、実際の結果を書き込む。戻り値: 更新した件数。"""
    rows = store.read(config.SH_FORECAST)
    n = 0
    for i, r in enumerate(rows):
        if r.get("status") != "未確認":
            continue
        s = market.get(r["asset"])
        if s is None or s.empty:
            continue
        target = pd.Timestamp(r["target"])
        if s.index[-1] < target:
            continue
        _, v = analysis.asof(s, target)
        base = float(r["base_price"])
        ret = v / base - 1.0
        band = float(r["band"])
        lab = outlook.actual_label(ret, band)
        r2 = dict(r, status="確認済み", actual_return=round(ret, 6), actual_label=lab,
                  hit="当たり" if lab == r["judgment"] else "外れ")
        store.update(config.SH_FORECAST, i, r2)
        n += 1
    return n


def answers_section(store, backtests):
    rows = store.read(config.SH_FORECAST)
    done = [r for r in rows if r.get("status") == "確認済み"]
    pend = [r for r in rows if r.get("status") == "未確認"]
    hlabel = {h["key"]: h["label"] for h in config.HORIZONS}
    recent = sorted(done, key=lambda r: r["target"], reverse=True)[:8]
    live = {}
    for r in done:
        k = (r["asset"], r["horizon"])
        d = live.setdefault(k, [0, 0])
        d[0] += 1
        d[1] += 1 if r["hit"] == "当たり" else 0
    return {
        "recent": [{"issued": r["issued"], "asset": r["asset"], "horizon": hlabel.get(r["horizon"], r["horizon"]),
                    "judgment": r["judgment"], "actual": float(r["actual_return"]), "hit": r["hit"]} for r in recent],
        "n_pending": len(pend),
        "live": {"%s|%s" % k: {"n": v[0], "hit": v[1] / v[0]} for k, v in live.items() if v[0] >= 5},
        "backtest": backtests,
    }


def build_report(market, news_pack, report_date, mode, backtests=None, answers=None, problems=None):
    """report_date: 土曜（または暫定版では実行日）の pandas.Timestamp。"""
    rep_ts = pd.Timestamp(report_date)
    assets = {}
    prices = {}
    for asset, meta in config.ASSETS.items():
        s = market[asset].dropna()
        summ = analysis.weekly_summary(s, rep_ts)
        block = {"label": meta["label"], "unit": meta["unit"], "summary": summ}
        prices[asset] = summ["close"]
        assets[asset] = block
    as_of = pd.Timestamp(assets["orukan"]["summary"]["date"])
    news_sec = build_news_section(*news_pack) if news_pack else None
    if mode == "最終":
        for asset in assets:
            ns = news_sec["scores"][asset] if news_sec else 0.0
            assets[asset]["outlook"] = outlook.build_outlook(asset, market[asset].dropna(), market, ns)
    report = {
        "version": 1,
        "mode": mode,
        "report_date": str(rep_ts.date()),
        "weekday": _weekday_ja(rep_ts.date()),
        "as_of": str(as_of.date()),
        "generated_at": str(now_jst()),
        "assets": assets,
        "usdjpy": analysis.usdjpy_summary(market["usdjpy"], rep_ts),
        "chart": analysis.weekly_chart(market["orukan"], market["gold"], rep_ts),
        "news": news_sec,
        "answers": answers if mode == "最終" else None,
        "problems": problems or [],
        "history": {"orukan": str(market["orukan"].index[0].date()), "gold": str(market["gold"].index[0].date())},
        "disclaimer": config.DISCLAIMER,
    }
    return report, prices, as_of


def price_row(market, as_of):
    row = {"date": str(as_of.date())}
    for k, key in (("orukan", "orukan"), ("gold", "gold"), ("usdjpy", "usdjpy"), ("us10y", "us10y"), ("dxy", "dxy"), ("vix", "vix")):
        s = market.get(k)
        if s is not None:
            _, v = analysis.asof(s, as_of)
            row[key] = round(v, 4) if v is not None else ""
    return row
