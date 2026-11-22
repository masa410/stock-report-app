"""価格データの取得（無料の公開データ）。取得に失敗したものは、前回の値で代用せず、失敗として報告する。"""
import io
import time
import datetime as dt

import pandas as pd
import requests

import config

HEADERS = {"User-Agent": config.USER_AGENT}


class DataError(Exception):
    pass


def _get(url, tries=3, timeout=30):
    last = None
    for _ in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
            last = "status %s" % r.status_code
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(2)
    raise DataError("取得できませんでした: %s (%s)" % (url[:70], last))


def drop_non_business(s):
    """土日の日付と欠損を除く（途中の行が混ざることがあるため）。"""
    s = s.dropna()
    s = s[s.index.dayofweek < 5]
    s = s[~s.index.duplicated(keep="last")]
    return s.sort_index()


def parse_toushin_csv(raw):
    text = raw.decode("cp932", "ignore")
    df = pd.read_csv(io.StringIO(text))
    df = df.iloc[:, :2]
    df.columns = ["date", "nav"]
    df["date"] = pd.to_datetime(df["date"], format="%Y年%m月%d日", errors="coerce")
    df = df.dropna()
    s = pd.Series(df["nav"].astype(float).values, index=df["date"], name="orukan")
    return drop_non_business(s)


def fetch_orukan():
    return parse_toushin_csv(_get(config.TOUSHIN_CSV).content)


def parse_yahoo_chart(j, name):
    res = j["chart"]["result"][0]
    off = res.get("meta", {}).get("gmtoffset", 0) or 0
    idx = pd.to_datetime([t + off for t in res["timestamp"]], unit="s").normalize()
    close = res["indicators"]["quote"][0]["close"]
    return drop_non_business(pd.Series(close, index=idx, dtype="float64", name=name))


def fetch_yahoo(sym, name, years=30):
    p2 = int(time.time())
    p1 = p2 - years * 366 * 86400
    r = _get(config.YAHOO_CHART.format(sym=sym, p1=p1, p2=p2))
    return parse_yahoo_chart(r.json(), name)


def gold_jpy_per_gram(gold_usd, usdjpy):
    fx = usdjpy.reindex(gold_usd.index, method="ffill")
    s = (gold_usd * fx / config.TROY_OZ_G).dropna()
    s.name = "gold"
    return s


def load_market(optional_ok=True):
    """戻り値: (market, problems)。market = 各系列のdict。problems = 取得できなかった項目の説明。"""
    problems = []
    market = {}
    market["orukan"] = fetch_orukan()           # 必須
    parts = {}
    for key, sym in config.YAHOO_SYMBOLS.items():
        try:
            parts[key] = fetch_yahoo(sym, key)
        except Exception as e:  # noqa: BLE001
            parts[key] = None
            problems.append("%s: %s" % (key, e))
    if parts["gold_usd"] is None or parts["usdjpy"] is None:
        raise DataError("ゴールドの円建てを計算できません: " + " / ".join(problems))
    market["gold"] = gold_jpy_per_gram(parts["gold_usd"], parts["usdjpy"])
    market["usdjpy"] = parts["usdjpy"]
    for k in ("us10y", "dxy", "vix"):
        market[k] = parts[k]
    return market, problems
