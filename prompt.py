"""Claudeに渡す文章（毎回同じ型）と、返ってきた補足の取り込み。"""
import re

import config
import fmt

FORMAT = """【調べること（これが依頼の中心です）】
上のデータは出発点です。要約や言い換えは求めていません。あなた自身で、次のことを調べて答えてください。
1. この1週間（データ基準日までの週）に、オルカン（全世界株式）とゴールド（円建て）が動いた本当の理由。株価・為替・金利・原油・金の値動きと、主要な報道・発表を、自分で調べて裏づける。
2. 上の「ニュース見出し」が、本当にその日に報じられたことか、他の信頼できる媒体でも確認できるか。見出しごとに「確認できた／一部確認／確認できず」で判定する。
3. 来週の予定（米国・日本の経済指標、中央銀行の会合や要人発言、主要企業の決算、地政学上の節目）。日付つきで調べる。
4. 1か月後・半年後・3年後（ゴールドは5年後も）の見方。材料と根拠を挙げ、上の「ルール判定」に同意できるか、異論があるかを述べる。

【守ること】
- 検索やWebの閲覧ができる場合は、必ず使って調べる。使えない場合は、その旨を最初の1行に書き、知っている範囲に限って答える。
- 調べた事実には、出典（媒体名と日付）をつける。事実と、あなたの推測は、書き分ける。
- 調べても確認できなかったことは、確認できなかったと書く。推測で埋めない。
- 上のデータの数字を並べ直すだけの文章は、書かない。
- 売買の推奨と、結果の断定はしない。確率は「目安」として扱う。

【出力形式】次の見出しをそのまま使ってください。各項目は5行以内にしてください（「ニュースの信ぴょう性」だけは、見出し1件につき1行で、全件を書いてください）。
## 今週の動きの要因（調べた結果）
## ニュースの信ぴょう性（確認結果）
## 来週の予定と注目点
## 1か月〜半年の見方
## 数年の見方
## ルール判定への所見
## 辞書への追加候補
（この最後の見出しの下に、1行1件で「語|分類|上昇／下落／影響なし」の形で、最大5件。分類は 金融政策・為替・景気・株式市場・地政学・関税/政策・AI/半導体・企業業績・原油/エネルギー・インフレ・ゴールド固有 から選ぶ）"""


def build_prompt(report):
    o, g = report["assets"]["orukan"], report["assets"]["gold"]
    lines = ["あなたは、個人投資家向けの週次レポートを検証する調査担当のアナリストです。次のデータを出発点に、あなた自身で調べ直し、日本語で答えてください。", ""]
    lines.append("■ 週: %s（データ基準 %s）" % (fmt.jp_date(report["report_date"]), report["as_of"]))
    for b in (o, g):
        s = b["summary"]
        lines.append("■ %s: 終値 %s、週間 %s、1か月 %s、3か月 %s、1年 %s、高値から %s" % (
            b["label"], fmt.price(s["close"], ""), fmt.pct(s["week_return"]), fmt.pct(s["ret_1m"]), fmt.pct(s["ret_3m"]),
            fmt.pct(s["ret_1y"]), fmt.pct(s["from_high"])))
    lines += ["■ 最高値の更新:"] + ["  - " + x for x in fmt.highs_lines(report)]
    fx = report["usdjpy"]
    lines.append("■ ドル円: %.1f円（前週比 %s円）" % (fx["last"], "%+.1f" % fx["change"] if fx["change"] is not None else "―"))
    if report.get("assets", {}).get("orukan", {}).get("outlook"):
        lines.append("■ ルール判定（目安の確率）:")
        for asset in ("orukan", "gold"):
            b = report["assets"][asset]
            for r in b["outlook"]["rows"]:
                lines.append("  - %s %s: %s" % (b["label"], r["label"], fmt.probs_text(r["probs"])))
    n = report.get("news")
    if n:
        lines.append("■ 今週のニュース見出し（配信元数・分類つき）:")
        for c in n["clusters"][:12]:
            lines.append("  - [%d配信元・%s] %s" % (c["n_sources"], "・".join(c["categories"][:2]) or "未分類", c["title"]))
    lines += ["", FORMAT]
    return "\n".join(lines)


def parse_note(text):
    """Claudeの回答を、見出しごとに分ける。戻り値: (見出し→本文の辞書, 辞書候補[(語, 分類, 方向)])"""
    sections, cur = {}, None
    cands = []
    for ln in text.splitlines():
        m = re.match(r"^\s*#{1,3}\s*(.+?)\s*$", ln)
        if m:
            cur = m.group(1)
            sections[cur] = []
            continue
        if cur is None or not ln.strip():
            continue
        if "辞書" in cur:
            parts = [p.strip(" 　-・*") for p in re.split(r"[|｜]", ln)]
            if len(parts) >= 3 and parts[0] and parts[2] in ("上昇", "下落", "影響なし"):
                cands.append((parts[0], parts[1], parts[2]))
            continue
        sections[cur].append(ln.strip())
    return {k: "\n".join(v) for k, v in sections.items() if v and "辞書" not in k}, cands
