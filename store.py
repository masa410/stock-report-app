"""保存先。MemoryStore（試験用）と SheetsStore（Googleスプレッドシート）。どちらも同じ使い方。"""
import json

import config
from gsheets_client import SheetsClient

CHUNK = 40000   # スプレッドシートの1セルの上限（約5万字）に余裕を持たせる

COLUMNS = {
    config.SH_REPORT: [("week", "週(土曜)"), ("mode", "種別"), ("generated_at", "作成日時"),
                       ("json", "内容1"), ("json2", "内容2"), ("json3", "内容3")],
    config.SH_FORECAST: [("report_week", "報告週"), ("asset", "対象"), ("horizon", "期間"), ("issued", "予想日"),
                         ("target", "確認日"), ("judgment", "判定"), ("p_up", "上昇優勢%"), ("p_flat", "横ばい%"),
                         ("p_down", "下落優勢%"), ("base_price", "予想時の価格"), ("band", "横ばいの幅"),
                         ("status", "状態"), ("actual_return", "実際の騰落率"), ("actual_label", "実際の区分"),
                         ("hit", "当たり外れ")],
    config.SH_NEWS: [("fetched", "取得日"), ("published", "配信日時"), ("title", "見出し"), ("source", "配信元"),
                     ("link", "URL")],
    config.SH_DICT: [("keyword", "語"), ("category", "分類"), ("score", "点"), ("scope", "対象"), ("added", "追加日")],
    config.SH_PRICE: [("date", "日付(金曜)"), ("orukan", "オルカン"), ("gold", "ゴールド円/g"), ("usdjpy", "ドル円"),
                      ("us10y", "米10年金利"), ("dxy", "ドル指数"), ("vix", "VIX")],
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
        self.c.ensure_sheet(sheet, [jp for _, jp in COLUMNS[sheet]])
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
        self.c.append_rows(sheet, [[_cell(r.get(k)) for k in keys] for r in rows])

    def update(self, sheet, index, row):
        keys = [k for k, _ in COLUMNS[sheet]]
        self.c.batch_update_rows(sheet, [(index + 1, [_cell(row.get(k)) for k in keys])])


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
    store.append(config.SH_REPORT, [row])


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
