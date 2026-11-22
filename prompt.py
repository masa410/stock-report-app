"""Claudeに渡す文章（毎回同じ型）と、返ってきた補足の取り込み。"""
import re

import config
import fmt

FORMAT = """【出力形式】次の見出しをそのまま使い、各項目は3行以内で書いてください。数字の断定や売買の推奨はしないでください。
## 今週の総括
## 来週の注目点
## 1か月〜半年の見方
## 数年の見方
## 辞書への追加候補
（この見出しの下に、1行1件で「語|分類|上昇／下落／影響なし」の形で、最大5件。分類は 金融政策・為替・景気・株式市場・地政学・関税/政策・AI/半導体・企業業績・原油/エネルギー・インフレ・ゴールド固有 から選ぶ）"""


def build_prompt(report):
    o, g = report["assets"]["orukan"], report["assets"]["gold"]
    lines = ["あなたは、個人投資家向けの週次レポートの補足を書く助手です。次のデータだけを根拠に、日本語で補足してください。", ""]
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
