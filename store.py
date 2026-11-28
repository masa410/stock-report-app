"""保存先。MemoryStore（試験用）と SheetsStore（Googleスプレッドシート）。どちらも同じ使い方。"""
import datetime as dt
import json

import config
from gsheets_client import SheetsClient

CHUNK = 40000   # スプレッドシートの1セルの上限（約5万字）に余裕を持たせる

COLUMNS = {
    config.SH_REPORT: [("week", "週(土曜)"), ("mode", "種別"), ("generated_at", "作成日時"),
                       ("json", "内容1"), ("json2", "内容2"), ("json3", "内容3"),
                       ("state", "状態"), ("note_at", "補足の取り込み日時"), ("note_due", "補足の期限"), ("note_late", "期限後に取り込み")],
    config.SH_FORECAST: [("report_week", "報告週"), ("asset", "対象"), ("horizon", "期間"), ("issued", "予想日"),
                         ("target", "確認日"), ("judgment", "判定"), ("p_up", "上昇優勢%"), ("p_flat", "横ばい%"),
                         ("p_down", "下落優勢%"), ("base_price", "予想時の価格"), ("band", "横ばいの幅"),
                         ("status", "状態"), ("actual_return", "実際の騰落率"), ("actual_label", "実際の区分"),
                         ("hit", "当たり外れ")],
    config.SH_NEWS: [("fetched", "取得日"), ("published", "配信日時"), ("title", "見出し"), ("source", "配信元"),
                     ("link", "URL"), ("fetched_time", "取得時刻"), ("week", "週(土曜)"), ("run", "取得回")],
    config.SH_DICT: [("keyword", "語"), ("category", "分類"), ("score", "点"), ("scope", "対象"), ("added", "追加日")],
    config.SH_PRICE: [("date", "日付(金曜)"), ("orukan", "オルカン"), ("gold", "ゴールド円/g"), ("usdjpy", "ドル円"),
                      ("us10y", "米10年金利"), ("dxy", "ドル指数"), ("vix", "VIX")],
    config.SH_SETTINGS: [("item", "項目"), ("value", "値"), ("desc", "説明")],
    config.SH_DAILY: [("date", "日付"), ("week", "週(土曜)"), ("fetched_at", "最終取得"), ("orukan", "オルカン"),
                      ("gold", "ゴールド円/g"), ("usdjpy", "ドル円"), ("us10y", "米10年金利"), ("dxy", "ドル指数"),
                      ("vix", "VIX"), ("orukan_chg", "オルカン前日比%"), ("gold_chg", "ゴールド前日比%")],
    config.SH_PROV: [("date", "日付"), ("week", "週(土曜)"), ("fetched_at", "最終取得"), ("mode", "状態"),
                     ("json", "内容1"), ("json2", "内容2"), ("json3", "内容3")],
    config.SH_WEEKS: [("week", "週(土曜)"), ("orukan", "オルカン終値"), ("gold", "ゴールド終値"), ("orukan_ret", "オルカン週間%"),
                      ("gold_ret", "ゴールド週間%"), ("high", "最高値更新"), ("outlook", "オルカンの来週の見通し"),
                      ("result", "結果"), ("note_state", "補足の状態"), ("note_at", "補足の取り込み日時")],
    config.SH_MEMO: [("week", "週(土曜)"), ("memo", "メモ"), ("updated_at", "更新日時")],
    config.SH_NOTIFY: [("at", "日時"), ("kind", "種類"), ("target", "対象"), ("content", "内容"), ("to", "宛先"),
                       ("result", "結果"), ("key", "識別キー")],
}


def split_json(text):
    parts = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
    if len(parts) > 3:
        raise ValueError("レポートが大きすぎます")
    return {"json": parts[0], "json2": parts[1] if len(parts) > 1 else "", "json3": parts[2] if len(parts) > 2 else ""}


def join_json(row):
    return (row.get("json") or "") + (row.get("json2") or "") + (row.get("json3") or "")


class MemoryStore:
    def __init__(self):
        self.data = {}

    def ensure(self, sheet):
        self.data.setdefault(sheet, [])

    def read(self, sheet):
        self.ensure(sheet)
        return [dict(r) for r in self.data[sheet]]

    def append(self, sheet, rows):
        self.ensure(sheet)
        keys = [k for k, _ in COLUMNS[sheet]]
        for r in rows:
            self.data[sheet].append({k: ("" if r.get(k) is None else r.get(k)) for k in keys})

    def update(self, sheet, index, row):
        keys = [k for k, _ in COLUMNS[sheet]]
        self.data[sheet][index] = {k: ("" if row.get(k) is None else row.get(k)) for k in keys}


class SheetsStore:
    def __init__(self, service_account_info, spreadsheet_id):
        self.c = SheetsClient(service_account_info, spreadsheet_id)
        self._ready = set()

    def ensure(self, sheet):
        if sheet in self._ready:
            return
        want = [jp for _, jp in COLUMNS[sheet]]
        self.c.ensure_sheet(sheet, want)
        # 列を後ろへ足した版に移行：古い見出し（先頭が一致）なら、見出しの行だけ、新しい見出しに書き換える
        have = self.c.get_header(sheet)
        if have and have != want and want[:len(have)] == have:
            self.c.batch_update_rows(sheet, [(0, want)], raw=True)
        self._ready.add(sheet)

    def read(self, sheet):
        self.ensure(sheet)
        vals = self.c.get_all_values(sheet)
        if not vals:
            return []
        jp2key = {jp: k for k, jp in COLUMNS[sheet]}
        keys = [jp2key.get(h) for h in vals[0]]
        rows = []
        for v in vals[1:]:
            rows.append({k: (v[i] if i < len(v) else "") for i, k in enumerate(keys) if k})
        return rows

    def append(self, sheet, rows):
        self.ensure(sheet)
        keys = [k for k, _ in COLUMNS[sheet]]
        # RAW：日付らしい文字（2026-11-21）をGoogleが日付の数値に変えないよう、文字のまま保存する
        self.c.append_rows(sheet, [[_cell(r.get(k)) for k in keys] for r in rows], raw=True)

    def update(self, sheet, index, row):
        keys = [k for k, _ in COLUMNS[sheet]]
        self.c.batch_update_rows(sheet, [(index + 1, [_cell(row.get(k)) for k in keys])], raw=True)


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(round(v, 6))
    return v


# ---- 使いやすい入口 ----
def save_report(store, week, mode, generated_at, report):
    """同じ週・同じ種別は上書き（古い版は消さず、種別を「履歴」に変えて残す）。"""
    rows = store.read(config.SH_REPORT)
    for i, r in enumerate(rows):
        if r["week"] == week and r["mode"] == mode:
            old = dict(r, mode="履歴")
            store.update(config.SH_REPORT, i, old)
    row = {"week": week, "mode": mode, "generated_at": generated_at}
    row.update(split_json(json.dumps(report, ensure_ascii=False)))
    if mode == "最終":
        row.update(report_extras(report))
    store.append(config.SH_REPORT, [row])


def _due(report):
    """補足の期限。古い最終版（期限の記録がない）は、土曜の翌日の24:00として計算する。"""
    if report.get("note_due"):
        return str(report["note_due"])
    try:
        d = dt.date.fromisoformat(str(report.get("report_date"))[:10]) + dt.timedelta(days=config.NOTE_DUE_DAYS)
    except ValueError:
        return ""
    return "%s 23:59:59" % d


def note_late(report):
    """補足を期限後に取り込んだか（None＝まだ取り込んでいない／期限なし）。"""
    note = report.get("claude_note")
    due = _due(report)
    if not note or not due:
        return None
    return str(note.get("saved_at", ""))[:19] > due[:19]


def note_state(report, now=None):
    """補足の状態（一覧用）：済み／期限後／待ち／なし。"""
    if report.get("claude_note"):
        return "期限後" if note_late(report) else "済み"
    due = _due(report)
    if due and now is not None and str(now)[:19] > due[:19]:
        return "なし"
    return "待ち"


def report_status(report, now=None):
    """ページの状態の呼び名：暫定／最終・補足待ち／補足待ち（期限後）／完成。"""
    if report.get("mode") != "最終":
        return "暫定"
    if report.get("claude_note"):
        return "完成"
    due = _due(report)
    if due and now is not None and str(now)[:19] > due[:19]:
        return "補足待ち（期限後）"
    return "最終・補足待ち"


def report_extras(report):
    note = report.get("claude_note")
    late = note_late(report)
    return {"state": "完成" if note else "最終・補足待ち", "note_at": (note or {}).get("saved_at", ""),
            "note_due": _due(report), "note_late": "" if late is None else ("はい" if late else "いいえ")}


def upsert(store, sheet, key, row):
    """key の値が同じ行があれば上書き、なければ追加。"""
    for i, r in enumerate(store.read(sheet)):
        if str(r.get(key)) == str(row.get(key)):
            store.update(sheet, i, row)
            return "更新"
    store.append(sheet, [row])
    return "追加"


def save_prov(store, date, week, fetched_at, report):
    """暫定版：日ごとに1行（同じ日は上書き）。"""
    row = {"date": str(date), "week": str(week), "fetched_at": fetched_at, "mode": "暫定"}
    row.update(split_json(json.dumps(report, ensure_ascii=False)))
    return upsert(store, config.SH_PROV, "date", row)


def load_provs(store):
    """戻り値: [(日付, 週, 最終取得, レポートdict)]（日付順）"""
    out = []
    for r in store.read(config.SH_PROV):
        if not r.get("date"):
            continue
        try:
            out.append((r["date"], r["week"], r["fetched_at"], json.loads(join_json(r))))
        except ValueError:
            continue
    return sorted(out, key=lambda x: x[0])


def get_settings(store):
    """設定シートを辞書で返す。シートが空なら初期値を入れる。"""
    rows = store.read(config.SH_SETTINGS)
    if not rows:
        store.append(config.SH_SETTINGS, [{"item": a, "value": b, "desc": c} for a, b, c in config.DEFAULT_SETTINGS])
        rows = store.read(config.SH_SETTINGS)
    return {r["item"]: r["value"] for r in rows}


def get_memo(store, week):
    for r in store.read(config.SH_MEMO):
        if r["week"] == str(week):
            return r["memo"]
    return ""


def set_memo(store, week, memo, now):
    return upsert(store, config.SH_MEMO, "week", {"week": str(week), "memo": memo, "updated_at": str(now)})


def load_reports(store):
    """戻り値: [(週, 種別, 作成日時, レポートdict)]。種別が「履歴」のものは含めない。"""
    out = []
    for r in store.read(config.SH_REPORT):
        if r["mode"] == "履歴" or not r["week"]:
            continue
        try:
            out.append((r["week"], r["mode"], r["generated_at"], json.loads(join_json(r))))
        except ValueError:
            continue
    return sorted(out, key=lambda x: (x[0], x[1] == "最終", x[2]))      # 同じ週では、最終版を後ろ（新しい側）に
