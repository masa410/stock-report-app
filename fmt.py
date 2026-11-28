"""表示の整形（アプリとWordで共通）。"""
import datetime as dt

import config


def pct(x, signed=True, digits=1):
    if x is None:
        return "―"
    v = x * 100
    t = ("%+." + str(digits) + "f%%") % v if signed else ("%." + str(digits) + "f%%") % v
    return t.replace("-", "−")


def price(x, asset):
    if x is None:
        return "―"
    return "{:,.0f}{}".format(x, "円")


def md(iso):
    d = dt.date.fromisoformat(str(iso)[:10])        # 「2026-11-20 00:00:00」のように時刻つきで保存された日付も読める
    return "%d月%d日" % (d.month, d.day)


def jp_date(iso):
    d = dt.date.fromisoformat(str(iso)[:10])
    return "%d年%d月%d日（%s）" % (d.year, d.month, d.day, "月火水木金土日"[d.weekday()])


def probs_text(p):
    return "上昇優勢%d%%・横ばい%d%%・下落優勢%d%%" % (p[0], p[1], p[2])


def range_text(a):
    return "%s 〜 %s" % (pct(a["p10"]), pct(a["p90"]))


def analog_text(a):
    if not a:
        return "データ不足"
    return "%d件／上昇%d%%／中央値%s" % (a["count"], round(a["share_up"] * 100), pct(a["median"]))


def title_of(report):
    d = jp_date(report["report_date"])
    return ("週次レポート　" + d) if report["mode"] == "最終" else ("暫定版（%s曜日時点）　%s" % (report["weekday"], d))


def highs_lines(report):
    """最高値の更新の見出し（最上段）。"""
    lines = []
    for asset in ("orukan", "gold"):
        b = report["assets"][asset]
        h = b["summary"]["highs"]
        label = b["label"]
        close = b["summary"]["close"]
        if h["ath_update"]:
            line = "%s：設定来の最高値を更新（%s）。前の最高値 %s（%s）を %s（%s）上回りました。" % (
                label, price(h["ath_new"], asset), price(h["ath_prev"], asset), md(h["ath_prev_date"]),
                price(h["ath_margin"], asset), pct(h["ath_margin_pct"], digits=2))
            if h.get("ath_streak", 1) >= 2:
                line += "更新は%d週連続です。" % h["ath_streak"]
            lines.append(line)
        else:
            lines.append("%s：最高値の更新なし。最高値 %s（%s）まで、あと %s。" % (
                label, price(h["ath_value"], asset), md(h["ath_date"]), pct(h["ath_remaining_pct"], signed=False)))
        if h["ytd_update"]:
            lines.append("%s：年初来高値も更新。" % label)
    return lines


def disclaimer_range_note(report):
    return ("※過去最高値は、取得できる過去データの範囲（オルカン：%s〜、ゴールド：%s〜）での比較です。" % (
        report["history"]["orukan"][:7].replace("-", "年") + "月", report["history"]["gold"][:7].replace("-", "年") + "月"))
