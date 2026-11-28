"""レポート（辞書型）の組み立てと、見通しの記録・答え合わせ。"""
import datetime as dt
import os

import pandas as pd

import analysis
import config
import fmt
import news as newsmod
import outlook

JST = dt.timezone(dt.timedelta(hours=9))


def now_jst():
    fake = os.environ.get("STOCK_APP_NOW")          # 試験・画面確認用：時刻を固定する（本番では設定しない）
    if fake:
        return dt.datetime.fromisoformat(fake)
    return dt.datetime.now(JST).replace(tzinfo=None, microsecond=0)


def week_key_and_mode(today):
    """実行した日から、レポートの週（土曜の日付）と種別を決める。土・日は本番、それ以外は暫定版。"""
    wd = today.weekday()      # 月0 … 土5 日6
    if wd == 5:
        return today, "最終"
    if wd == 6:
        return today - dt.timedelta(days=1), "最終"
    return today + dt.timedelta(days=5 - wd), "暫定"


def coming_saturday(now):
    """その時刻の「週」を表す土曜の日付。土曜は、最終版の時刻（9:23）より前ならその日、後なら翌週の土曜。"""
    d = now.date()
    wd = d.weekday()
    if wd == 5:
        return d if (now.hour, now.minute) < config.FINAL_TIME else d + dt.timedelta(days=7)
    if wd == 6:
        return d + dt.timedelta(days=6)
    return d + dt.timedelta(days=5 - wd)


def run_kind(now):
    """毎日の更新で何を作るか。月〜金と、土曜9:23より前＝暫定版。それ以外（土曜9:23以降・日曜）＝見出しを集めるだけ。"""
    wd = now.weekday()
    if wd <= 4 or (wd == 5 and (now.hour, now.minute) < config.FINAL_TIME):
        return "暫定"
    return "取得のみ"


def run_label(now):
    return "朝" if now.hour < 12 else "夕"


def note_due_for(week):
    """補足の期限（最終版の翌日の24:00）。例：土曜 11/28 の週 → 11/29 23:59:59。"""
    d = dt.date.fromisoformat(str(week)[:10]) + dt.timedelta(days=config.NOTE_DUE_DAYS)
    return "%s 23:59:59" % d


def _streak_text(series):
    v = [0.0] + list(series)
    ch = [v[i] - v[i - 1] for i in range(1, len(v))]
    if not ch or ch[-1] == 0:
        return ""
    up = ch[-1] > 0
    n = 0
    for c in reversed(ch):
        if c != 0 and (c > 0) == up:
            n += 1
        else:
            break
    return ("%d日続伸" if up else "%d日続落") % n if n >= 2 else ""


def one_liner(assets, daily, usd):
    """今日のひとこと（暫定版の一番上）。"""
    o, g = assets["orukan"]["summary"], assets["gold"]["summary"]
    t = "オルカンは今週ここまで %s" % fmt.pct(o["week_return"])
    s = _streak_text(daily["orukan"]) if daily else ""
    t += ("、" + s if s else "") + "。"
    h = o["highs"]
    t += "最高値を更新しました。" if h["ath_update"] else "最高値まで、あと %s。" % fmt.pct(h["ath_remaining_pct"], signed=False)
    t += "\n"
    u = "ゴールドは今週ここまで %s" % fmt.pct(g["week_return"])
    s2 = _streak_text(daily["gold"]) if daily else ""
    t += u + ("、" + s2 if s2 else "") + "。"
    if usd and usd.get("change") is not None:
        t += "ドル円は %.1f円（先週末比 %s円）。" % (usd["last"], ("%+.1f" % usd["change"]).replace("-", "−"))
    return t


def _weekday_ja(d):
    return "月火水木金土日"[d.weekday()]


def build_news_section(judged, total, unclassified):
    items = sorted(judged, key=lambda c: (-c["n_sources"], -(abs(c["scores"]["orukan"]) + abs(c["scores"]["gold"]))))
    shown = []
    for c in items[:15]:
        shown.append({"title": c["title"], "n_sources": c["n_sources"], "trust": c["trust"], "sources": c["sources"][:6],
                      "categories": c["categories"], "scores": c["scores"], "link": (c["links"] or [""])[0],
                      "first_seen": c.get("first_seen", ""), "last_seen": c.get("last_seen", "")})
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
    daily = analysis.daily_moves(market["orukan"].dropna(), market["gold"].dropna(), rep_ts)
    usd = analysis.usdjpy_summary(market["usdjpy"], rep_ts)
    position = one = None
    if mode != "最終":
        position = {}
        for asset in assets:
            ns = news_sec["scores"][asset] if news_sec else 0.0
            position[asset] = outlook.build_outlook(asset, market[asset].dropna(), market, ns)["position"]
        one = one_liner(assets, daily, usd)
    report = {
        "version": 2,
        "week": str(rep_ts.date()),
        "daily": daily,
        "position": position,
        "one_liner": one,
        "note_due": note_due_for(rep_ts.date()) if mode == "最終" else None,
        "mode": mode,
        "report_date": str(rep_ts.date()),
        "weekday": _weekday_ja(rep_ts.date()),
        "as_of": str(as_of.date()),
        "generated_at": str(now_jst()),
        "assets": assets,
        "usdjpy": usd,
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
