"""設定・定数（ルールの目盛りはここだけで変える）。"""

ASSETS = {
    "orukan": {"label": "オルカン", "full": "eMAXIS Slim 全世界株式", "unit": "円", "digits": 0},
    "gold": {"label": "ゴールド（円建て）", "full": "金の国際先物価格の円換算", "unit": "円/g", "digits": 0},
}

# 見通しの区分：キー、表示名、営業日数、目標日までのカレンダー日数、横ばいの幅（±）、対象
HORIZONS = [
    {"key": "1w", "label": "来週", "days": 5, "cal": 7, "band": 0.01, "assets": ["orukan", "gold"]},
    {"key": "1m", "label": "1か月後", "days": 21, "cal": 30, "band": 0.025, "assets": ["orukan", "gold"]},
    {"key": "6m", "label": "半年後", "days": 126, "cal": 182, "band": 0.05, "assets": ["orukan", "gold"]},
    {"key": "3y", "label": "3年後", "days": 756, "cal": 1095, "band": 0.15, "assets": ["orukan", "gold"]},
    {"key": "5y", "label": "5年（参考）", "days": 1260, "cal": 1826, "band": 0.25, "assets": ["gold"]},
]

# ルール判定の目盛り
RULE_SCALE = {"1w": 1.0, "1m": 0.8, "6m": 0.5, "3y": 0.25, "5y": 0.2}      # 材料の点数の効き方
RULE_FLAT = {"1w": 0.5, "1m": 0.3, "6m": 0.0, "3y": -0.3, "5y": -0.4}      # 「横ばい」の出やすさ
RULE_DRIFT = {                                                              # 長期の上向きの偏り（上昇側に足す）
    "orukan": {"1w": 0.05, "1m": 0.10, "6m": 0.30, "3y": 0.60, "5y": 0.60},
    "gold": {"1w": 0.00, "1m": 0.05, "6m": 0.20, "3y": 0.40, "5y": 0.50},
}
RULE_K = 0.3          # 点数を確率に変える強さ
NEWS_WEIGHT = 0.5     # ニュース点数（−2〜+2）の重み

LABELS = ["上昇優勢", "横ばい", "下落優勢"]

# データ取得
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2={p2}&interval=1d"
YAHOO_SYMBOLS = {"gold_usd": "GC=F", "usdjpy": "JPY=X", "us10y": "^TNX", "dxy": "DX-Y.NYB", "vix": "^VIX"}
TOUSHIN_CSV = ("https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000/csv-file-download"
               "?isinCd=JP90C000H1T1&associFundCd=0331418A")
TROY_OZ_G = 31.1035
USER_AGENT = "Mozilla/5.0 (compatible; personal-research)"

# ニュース
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}+when:7d&hl=ja&gl=JP&ceid=JP:ja"
NEWS_QUERIES = ["日経平均 株価", "米国株 ダウ ナスダック", "円相場 ドル円", "金価格 ゴールド",
                "FRB 利下げ 利上げ", "日銀 金融政策", "原油 中東", "関税 貿易", "半導体 AI 決算"]
YAHOO_NEWS_RSS = "https://news.yahoo.co.jp/rss/categories/business.xml"
NEWS_SIMILARITY = 0.45
TRUST = [(3, "信ぴょう性が高い", 1.0), (2, "信用できる", 0.8), (1, "要確認", 0.4)]

# シート名
SH_REPORT = "週次レポート"
SH_FORECAST = "見通し記録"
SH_NEWS = "ニュース"
SH_DICT = "辞書"
SH_PRICE = "価格履歴"
SH_SETTINGS = "設定"
SH_DAILY = "日次記録"
SH_PROV = "暫定版"
SH_WEEKS = "週一覧"
SH_MEMO = "週メモ"
SH_NOTIFY = "通知記録"

# 週の区切り：土曜の9:23に最終版を作る。これより前の土曜は、まだ「暫定」の扱い
FINAL_TIME = (9, 23)
# 補足の期限：最終版の翌日（日曜）の24:00（過ぎても取り込めるが「期限後」と表示）
NOTE_DUE_DAYS = 1

# 設定シートの初期値（項目, 値, 説明）。プログラムを直さずに、シートの値を書き換えて変える
DEFAULT_SETTINGS = [
    ("通知を送る", "はい", "「いいえ」にすると、メール通知を止める"),
    ("通知先メール", "", "大きな動き・最高値の更新を送る先（空欄なら、通知しない）"),
    ("大きな動きの目安（前日比 ±%）", "3", "オルカン・ゴールドのどちらかが、この値を超えたら通知"),
    ("最高値の更新を通知", "はい", "過去最高値・年初来高値を更新したときに通知"),
    ("ニュースの保持（月）", "12", "これより古い見出しは削除の対象（今は自動削除しません）"),
]

DISCLAIMER = ("本レポートは、過去の統計と、ルール・見出しの単語判定にもとづく参考情報であり、投資の助言ではありません。"
              "予想は外れることがあります。ゴールドは国際先物価格の円換算で、国内の小売価格とは異なります。"
              "ニュースは見出しのみを収集し、本文は保存していません。")
