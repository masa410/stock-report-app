"""先の見通し：いまの位置、過去の同じ局面の統計、ルール判定、バックテスト。"""
import math

import numpy as np
import pandas as pd

import config

WARMUP = 250


def feature_frame(s):
    """各日の特徴量：高値からの位置・25週平均との差・変動の大きさ・直近20日の騰落。"""
    r = s.pct_change()
    vol20 = r.rolling(20).std()
    vol_all = r.expanding(WARMUP).std()
    f = pd.DataFrame({
        "close": s,
        "dd": s / s.cummax() - 1.0,
        "ma_dev": s / s.rolling(125).mean() - 1.0,
        "vol_ratio": vol20 / vol_all,
        "r20": s.pct_change(20),
    })
    return f


def external_frame(market, index):
    """外部環境（円建ての材料）。日付をそろえる。無い項目は列ごと欠損。"""
    e = pd.DataFrame(index=index)
    fx = market.get("usdjpy")
    if fx is not None:
        e["fx20"] = fx.reindex(index, method="ffill").pct_change(20)
    y = market.get("us10y")
    if y is not None:
        e["y20"] = y.reindex(index, method="ffill").diff(20)
    d = market.get("dxy")
    if d is not None:
        e["dxy20"] = d.reindex(index, method="ffill").pct_change(20)
    v = market.get("vix")
    if v is not None:
        e["vix"] = v.reindex(index, method="ffill")
    return e


def _num(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def score_components(asset, feat, ext, news_score=0.0):
    """判断材料ごとの点（根拠の表示用）。feat/ext は1日分の辞書。戻り値: [(材料, 値の説明, 点)]"""
    comps = []
    ma = _num(feat.get("ma_dev"))
    if ma is not None:
        s = 1.0 if ma > 0.03 else -1.0 if ma < -0.03 else 0.0
        comps.append(("25週平均との差", "%+.1f%%" % (ma * 100), s))
    r20 = _num(feat.get("r20"))
    if r20 is not None:
        s = 1.0 if r20 > 0.02 else -1.0 if r20 < -0.02 else 0.0
        comps.append(("直近20日の騰落", "%+.1f%%" % (r20 * 100), s))
    vr = _num(feat.get("vol_ratio"))
    if vr is not None:
        comps.append(("変動の大きさ", "過去平均の%.1f倍" % vr, -0.5 if vr > 1.5 else 0.0))
    fx = _num(ext.get("fx20"))
    if fx is not None:
        s = 0.5 if fx > 0.02 else -0.5 if fx < -0.02 else 0.0
        comps.append(("ドル円（20日）", "%+.1f%%" % (fx * 100), s))
    if asset == "orukan":
        vix = _num(ext.get("vix"))
        if vix is not None:
            s = -0.5 if vix > 30 else 0.5 if vix < 18 else 0.0
            comps.append(("変動率指数（VIX）", "%.1f" % vix, s))
    else:
        y = _num(ext.get("y20"))
        if y is not None:
            s = -0.5 if y > 0.25 else 0.5 if y < -0.25 else 0.0
            comps.append(("米10年金利（20日）", "%+.2f%%ポイント" % y, s))
        d = _num(ext.get("dxy20"))
        if d is not None:
            s = -0.5 if d > 0.02 else 0.5 if d < -0.02 else 0.0
            comps.append(("ドル指数（20日）", "%+.1f%%" % (d * 100), s))
    if news_score:
        comps.append(("ニュース判定", "%+.1f" % news_score, news_score * config.NEWS_WEIGHT))
    return comps


def _round_pct(ps):
    raw = [p * 100 for p in ps]
    fl = [int(x) for x in raw]
    rem = 100 - sum(fl)
    order = sorted(range(3), key=lambda i: raw[i] - fl[i], reverse=True)
    for i in order[:rem]:
        fl[i] += 1
    return fl


def rule_probs(asset, hkey, total_score):
    """点数 → 上昇優勢・横ばい・下落優勢の目安確率（整数%）。"""
    z = total_score * config.RULE_SCALE[hkey] * config.RULE_K
    logits = [z + config.RULE_DRIFT[asset][hkey], config.RULE_FLAT[hkey], -z]
    m = max(logits)
    ex = [math.exp(x - m) for x in logits]
    t = sum(ex)
    return _round_pct([x / t for x in ex])


def label_of(ps):
    return config.LABELS[int(np.argmax(ps))]


def actual_label(ret, band):
    if ret > band:
        return "上昇優勢"
    if ret < -band:
        return "下落優勢"
    return "横ばい"


def analog_stats(feat_df, hdays):
    """過去の同じ局面：特徴量が近い日を集め、その後 hdays 営業日の結果を数える。"""
    close = feat_df["close"]
    fwd = close.shift(-hdays) / close - 1.0
    cols = ["dd", "ma_dev", "vol_ratio"]
    cand = feat_df[cols].join(fwd.rename("fwd")).dropna()
    if len(cand) < 60 or feat_df[cols].iloc[-1].isna().any():
        return None
    x = cand[cols]
    mu, sd = x.mean(), x.std().replace(0, 1.0)
    cur = (feat_df[cols].iloc[-1] - mu) / sd
    dist = (((x - mu) / sd) - cur).pow(2).sum(axis=1)
    k = int(min(200, max(30, round(0.08 * len(cand)))))
    near = cand.loc[dist.nsmallest(k).index, "fwd"]
    return {
        "count": int(len(near)),
        "share_up": float((near > 0).mean()),
        "median": float(near.median()),
        "p10": float(near.quantile(0.10)),
        "p90": float(near.quantile(0.90)),
        "candidates": int(len(cand)),
    }


def position_lines(asset, feat, ext):
    f = feat
    parts = ["高値から %+.1f%%" % (f["dd"] * 100)]
    if not math.isnan(f["ma_dev"]):
        parts.append("25週平均より %+.1f%%" % (f["ma_dev"] * 100))
    if not math.isnan(f["vol_ratio"]):
        parts.append("変動は過去平均の%.1f倍" % f["vol_ratio"])
    return parts


def build_outlook(asset, s, market, news_score):
    """資産ひとつ分の見通し一式。"""
    feat_df = feature_frame(s)
    ext_df = external_frame(market, s.index)
    feat = feat_df.iloc[-1].to_dict()
    ext = ext_df.iloc[-1].to_dict()
    comps = score_components(asset, feat, ext, news_score)
    total = sum(c[2] for c in comps)
    rows = []
    for h in config.HORIZONS:
        if asset not in h["assets"]:
            continue
        if len(s) < h["days"] + WARMUP:
            continue
        probs = rule_probs(asset, h["key"], total)
        rows.append({
            "key": h["key"], "label": h["label"], "days": h["days"], "cal": h["cal"], "band": h["band"],
            "analog": analog_stats(feat_df, h["days"]),
            "probs": probs, "judgment": label_of(probs),
        })
    return {
        "position": position_lines(asset, feat, ext),
        "components": [{"name": a, "value": b, "score": c} for a, b, c in comps],
        "total_score": total,
        "rows": rows,
    }


def backtest(asset, s, market, step=5):
    """同じルール（価格と外部環境。ニュースは過去が無いので除く）を過去へあてはめ、当たった割合を出す。"""
    feat_df = feature_frame(s)
    ext_df = external_frame(market, s.index)
    out = {}
    pos = list(range(WARMUP, len(s) - 1, step))
    close = s.values
    for h in config.HORIZONS:
        if asset not in h["assets"]:
            continue
        hits = flat = up = n = 0
        for i in pos:
            if i + h["days"] >= len(s):
                break
            comps = score_components(asset, feat_df.iloc[i].to_dict(), ext_df.iloc[i].to_dict(), 0.0)
            probs = rule_probs(asset, h["key"], sum(c[2] for c in comps))
            ret = close[i + h["days"]] / close[i] - 1.0
            act = actual_label(ret, h["band"])
            n += 1
            hits += (label_of(probs) == act)
            flat += (act == "横ばい")
            up += (act == "上昇優勢")
        if n >= 20:
            out[h["key"]] = {"n": n, "hit": hits / n, "always_flat": flat / n, "always_up": up / n}
    return out
