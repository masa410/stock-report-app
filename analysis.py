"""直近一週間のまとめ・最高値の更新判定（Pythonだけで計算）。"""
import pandas as pd


def asof(s, d):
    """d 以前で最後の営業日の (日付, 値)。なければ (None, None)。"""
    x = s[s.index <= d]
    if x.empty:
        return None, None
    return x.index[-1], float(x.iloc[-1])


def pct(new, old):
    if old in (None, 0) or new is None:
        return None
    return new / old - 1.0


def week_bounds(s, report_date, k=0):
    """k週前の週の (前週末日, 今週末日)。週末日＝その週で最後に値がある日。"""
    ref = report_date - pd.Timedelta(days=7 * k)
    end, _ = asof(s, ref)
    prev, _ = asof(s, ref - pd.Timedelta(days=7))
    return prev, end


def window_stats(s, prev, end):
    w = s[(s.index > prev) & (s.index <= end)] if prev is not None else s[s.index <= end]
    return w


def _new_high(s, prev, end):
    """その週に、それまでの最高値を超えたか。(更新したか, 週内最高, それまでの最高, 最高日)"""
    w = window_stats(s, prev, end)
    before = s[s.index <= prev] if prev is not None else s.iloc[0:0]
    if w.empty or before.empty:
        return False, None, None, None
    wmax = float(w.max())
    pmax = float(before.max())
    return wmax > pmax, wmax, pmax, before.idxmax()


def high_update(s, report_date):
    """過去最高値・年初来高値の更新の判定。"""
    prev, end = week_bounds(s, report_date)
    close = float(s[s.index == end].iloc[0])
    upd, wmax, pmax, pdate = _new_high(s, prev, end)
    out = {"ath_update": bool(upd), "ath_prev": pmax, "ath_prev_date": str(pdate.date()) if pdate is not None else None,
           "history_start": str(s.index[0].date())}
    w = window_stats(s, prev, end)
    if upd:
        out["ath_new"] = wmax
        out["ath_new_date"] = str(w.idxmax().date())
        out["ath_margin"] = wmax - pmax
        out["ath_margin_pct"] = wmax / pmax - 1.0
        n = 0
        for k in range(0, 200):
            p, e = week_bounds(s, report_date, k)
            if e is None or p is None:
                break
            u, _, _, _ = _new_high(s, p, e)
            if not u:
                break
            n += 1
        out["ath_streak"] = n
    else:
        ath = float(s[s.index <= end].max())
        out["ath_value"] = ath
        out["ath_date"] = str(s[s.index <= end].idxmax().date())
        out["ath_remaining_pct"] = ath / close - 1.0        # あと何%で最高値
    # 年初来
    y0 = pd.Timestamp(year=end.year, month=1, day=1)
    ytd_before = s[(s.index >= y0) & (s.index <= (prev if prev is not None else end))]
    if prev is not None and prev >= y0 and not ytd_before.empty:
        out["ytd_update"] = bool(w.max() > ytd_before.max())
    else:
        out["ytd_update"] = False
    return out


def weekly_summary(s, report_date):
    prev, end = week_bounds(s, report_date)
    w = window_stats(s, prev, end)
    close = float(s[s.index == end].iloc[0])
    prev_close = float(s[s.index == prev].iloc[0]) if prev is not None else None
    ath = float(s[s.index <= end].max())
    res = {
        "date": str(end.date()),
        "close": close,
        "prev_close": prev_close,
        "week_return": pct(close, prev_close),
        "week_high": float(w.max()),
        "week_low": float(w.min()),
        "from_high": close / ath - 1.0,
    }
    for name, off in (("1m", pd.DateOffset(months=1)), ("3m", pd.DateOffset(months=3)), ("1y", pd.DateOffset(years=1))):
        d, v = asof(s, end - off)
        res["ret_" + name] = pct(close, v) if d is not None and d >= s.index[0] else None
    d, v = asof(s, pd.Timestamp(year=end.year - 1, month=12, day=31))
    res["ret_ytd"] = pct(close, v) if d is not None else None
    res["highs"] = high_update(s, report_date)
    return res


def usdjpy_summary(fx, report_date):
    prev, end = week_bounds(fx, report_date)
    last = float(fx[fx.index == end].iloc[0])
    pv = float(fx[fx.index == prev].iloc[0]) if prev is not None else None
    return {"last": last, "prev": pv, "change": (last - pv) if pv is not None else None}


def weekly_chart(orukan, gold, report_date, weeks=52):
    """1年前を100とした週次の指数。"""
    _, end = week_bounds(orukan, report_date)
    dates = [end - pd.Timedelta(days=7 * k) for k in range(weeks, -1, -1)]
    out = {"dates": [], "orukan": [], "gold": []}
    base_o = asof(orukan, dates[0])[1]
    base_g = asof(gold, dates[0])[1]
    for d in dates:
        do, vo = asof(orukan, d)
        dg, vg = asof(gold, d)
        if vo is None or vg is None or base_o is None or base_g is None:
            continue
        out["dates"].append(str(d.date()))
        out["orukan"].append(round(vo / base_o * 100, 2))
        out["gold"].append(round(vg / base_g * 100, 2))
    return out
