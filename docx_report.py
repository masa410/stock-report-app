"""週次レポートのWord（レポートdict → docx）。PCとクラウドのどちらでも動く。"""
import io
import logging
import os

import matplotlib
matplotlib.use("Agg")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

import config
import fmt

FONT = "Yu Gothic"
plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _chart_png(report):
    c = report["chart"]
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=200)
    xs = list(range(-len(c["dates"]) + 1, 1))
    ax.plot(xs, c["orukan"], label="オルカン", color="#1f5fa8", lw=1.6)
    ax.plot(xs, c["gold"], label="ゴールド（円建て）", color="#b8860b", lw=1.6)
    ax.axhline(100, color="#999999", lw=0.6, ls=":")
    ax.set_xlabel("週（0 = 今週）")
    ax.set_ylabel("1年前を100とした指数")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.14), ncol=2, frameon=False)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color="#e5e5e5", lw=0.5)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


class _Doc:
    def __init__(self):
        self.doc = Document()
        sec = self.doc.sections[0]
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.left_margin = sec.right_margin = Cm(1.8)
        sec.top_margin = sec.bottom_margin = Cm(1.6)
        st = self.doc.styles["Normal"]
        st.font.name = FONT
        st.font.size = Pt(10)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

    @staticmethod
    def _font(run, size=None, bold=None, color=None):
        run.font.name = FONT
        run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        if size:
            run.font.size = Pt(size)
        if bold is not None:
            run.bold = bold
        if color:
            run.font.color.rgb = RGBColor.from_string(color)

    def para(self, text="", size=10, bold=False, color=None, align=None, after=3, before=0, keep=False):
        p = self.doc.add_paragraph()
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.keep_with_next = keep
        if align:
            p.alignment = align
        self._font(p.add_run(text), size, bold, color)
        return p

    def heading(self, text):
        p = self.para(text, size=13, bold=True, color="1F3864", before=10, after=4, keep=True)
        b = OxmlElement("w:pBdr")
        bt = OxmlElement("w:bottom")
        for k, v in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", "1F3864")):
            bt.set(qn("w:" + k), v)
        b.append(bt)
        p._p.get_or_add_pPr().append(b)

    @staticmethod
    def _shade(cell, fill):
        sh = OxmlElement("w:shd")
        sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), fill)
        cell._tc.get_or_add_tcPr().append(sh)

    @staticmethod
    def _borders(table, color="A6A6A6", sz="4"):
        b = OxmlElement("w:tblBorders")
        for e in ("top", "left", "bottom", "right", "insideH", "insideV"):
            x = OxmlElement("w:" + e)
            for k, v in (("val", "single"), ("sz", sz), ("space", "0"), ("color", color)):
                x.set(qn("w:" + k), v)
            b.append(x)
        table._tbl.tblPr.append(b)

    def table(self, rows, widths, size=9, right_from=1):
        t = self.doc.add_table(rows=len(rows), cols=len(rows[0]))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        self._borders(t)
        for i, row in enumerate(rows):
            t.rows[i]._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
            for j, val in enumerate(row):
                c = t.cell(i, j)
                c.width = Cm(widths[j])
                p = c.paragraphs[0]
                p.paragraph_format.space_after = Pt(1)
                p.paragraph_format.space_before = Pt(1)
                p.paragraph_format.keep_with_next = i < len(rows) - 1
                self._font(p.add_run(str(val)), size, bold=(i == 0))
                if i == 0:
                    self._shade(c, "D9E2F3")
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif j >= right_from:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)


def build_docx(report, path_or_buf):
    d = _Doc()
    num = [0]

    def H(t):
        num[0] += 1
        d.heading("%d. %s" % (num[0], t))

    final = report["mode"] == "最終"
    a_o, a_g = report["assets"]["orukan"], report["assets"]["gold"]
    d.para(fmt.title_of(report), size=18, bold=True, color="1F3864", after=1)
    d.para("オルカン（eMAXIS Slim 全世界株式）とゴールド（円建て）　／　データ基準：%s　／　作成：%s" % (
        fmt.jp_date(report["as_of"]), report["generated_at"][:16].replace("T", " ")), size=9, color="595959", after=6)
    if not final:
        d.para("暫定版です。その時点の分析のみで、過去データとの突合せと先の見通しは出していません。土曜の最終版で置き換わります。",
               size=9, color="C00000", after=4)

    # 最高値の更新
    box = d.doc.add_table(rows=1, cols=1)
    box.alignment = WD_TABLE_ALIGNMENT.CENTER
    d._borders(box, color="C00000", sz="12")
    c = box.cell(0, 0)
    c.width = Cm(17.4)
    d._shade(c, "FFF2F2")
    p = c.paragraphs[0]
    d._font(p.add_run("最高値の更新"), 12, True, "C00000")
    for line in fmt.highs_lines(report):
        q = c.add_paragraph()
        q.paragraph_format.space_after = Pt(1)
        d._font(q.add_run(line), 10)
    d.para(fmt.disclaimer_range_note(report), size=8, color="595959", before=3)

    # 直近一週間
    H("直近一週間のまとめ")
    so, sg = a_o["summary"], a_g["summary"]
    d.table([
        ["項目", "オルカン", "ゴールド（円/g）"],
        ["今週の終値", fmt.price(so["close"], "orukan"), fmt.price(sg["close"], "gold")],
        ["週間騰落率", fmt.pct(so["week_return"]), fmt.pct(sg["week_return"])],
        ["週内の高値／安値（終値ベース）", "%s／%s" % (fmt.price(so["week_high"], "o"), fmt.price(so["week_low"], "o")),
         "%s／%s" % (fmt.price(sg["week_high"], "g"), fmt.price(sg["week_low"], "g"))],
        ["直近1か月", fmt.pct(so["ret_1m"]), fmt.pct(sg["ret_1m"])],
        ["直近3か月", fmt.pct(so["ret_3m"]), fmt.pct(sg["ret_3m"])],
        ["直近1年", fmt.pct(so["ret_1y"]), fmt.pct(sg["ret_1y"])],
        ["年初来", fmt.pct(so["ret_ytd"]), fmt.pct(sg["ret_ytd"])],
        ["高値からの下落率", fmt.pct(so["from_high"], digits=1) if so["from_high"] < 0 else "0.0%（最高値）", fmt.pct(sg["from_high"])],
    ], [5.4, 6.0, 6.0])
    fx = report["usdjpy"]
    if fx["change"] is not None:
        d.para("ドル円：%.1f円（前週比 %s円、%s）。%s" % (
            fx["last"], ("%+.1f" % fx["change"]).replace("-", "−"), "円安方向" if fx["change"] > 0 else "円高方向",
            _compare_line(so, sg)), size=10)
    d.doc.add_picture(_chart_png(report), width=Cm(16.5))
    d.doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    d.para("図：直近1年の推移（1年前を100とした指数）", size=8, color="595959", align=WD_ALIGN_PARAGRAPH.CENTER)

    # ニュース
    n = report.get("news")
    if n:
        H("今週のニュースと判定")
        d.para("無料RSSの見出しを集め、同じ話題を配信元の数でまとめています（3配信元以上＝信ぴょう性が高い／2＝信用できる／1＝要確認）。"
               "配信元が2つ以上の話題と、点数がついた話題を表示しています。", size=9, color="595959", keep=True)
        rows = [["見出し", "配信元数", "信頼度", "分類", "判定（オルカン／ゴールド）"]]
        shown = [c for c in n["clusters"] if c["n_sources"] >= 2 or c["categories"]][:10]
        for c in shown:
            rows.append([c["title"][:46], c["n_sources"], c["trust"], "・".join(c["categories"][:2]) or "未分類",
                         "%s／%s" % (_sc(c["scores"]["orukan"]), _sc(c["scores"]["gold"]))])
        d.table(rows, [6.2, 1.4, 3.5, 2.9, 3.4], right_from=9)
        d.para("ニュース判定の点数（−2〜+2）：オルカン %+.1f／ゴールド %+.1f。話題 %d件のうち、辞書に当たらなかったものは %d件です"
               "（アプリで分類を選ぶと辞書が育ちます）。" % (n["scores"]["orukan"], n["scores"]["gold"], n["n_topics"], n["n_unclassified"]),
               size=9)

    if final:
        H("先の見通し")
        d.para("「過去統計」は過去の同じ局面での結果、「ルール判定」はルールで決めた目安です。別枠で示し、混ぜていません。",
               size=9, color="595959", keep=True)
        for asset in ("orukan", "gold"):
            b = report["assets"][asset]
            o = b["outlook"]
            d.para(b["label"], size=11, bold=True, color="1F3864", before=4, keep=True)
            comp = "、".join("%s %s（%+.1f）" % (x["name"], x["value"], x["score"]) for x in o["components"])
            d.para(("いまの位置：" + "／".join(o["position"]) + "。判断材料：" + comp + "。").replace("-", "−"), size=9, keep=True)
            rows = [["期間", "過去統計（件数／上昇割合／中央値）", "80%が収まる幅", "ルール判定（目安の確率）"]]
            for r in o["rows"]:
                rows.append([r["label"], fmt.analog_text(r["analog"]), fmt.range_text(r["analog"]) if r["analog"] else "―",
                             fmt.probs_text(r["probs"])])
            d.table(rows, [2.2, 5.3, 3.5, 6.4], right_from=9)
        d.para("※3年・5年の過去統計は、日付が重なる件が多く、参考程度です（オルカンは約8年分の記録しかありません）。", size=8, color="595959")

        H("見通しの答え合わせ")
        ans = report["answers"]
        if ans["recent"]:
            rows = [["予想した日", "対象", "期間", "予想（判定）", "実際の結果", "当たり外れ"]]
            for r in ans["recent"]:
                rows.append([fmt.md(r["issued"]), config.ASSETS[r["asset"]]["label"].split("（")[0], r["horizon"], r["judgment"],
                             fmt.pct(r["actual"]), r["hit"]])
            d.table(rows, [2.4, 2.4, 2.4, 3.2, 3.2, 3.8], right_from=9)
        else:
            d.para("まだ結果が確認できた予想はありません（確認待ち：%d件）。" % ans["n_pending"], size=9)
        bt = ans["backtest"]
        lines = []
        for asset in ("orukan", "gold"):
            parts = []
            for h in config.HORIZONS:
                x = bt.get(asset, {}).get(h["key"])
                if x:
                    parts.append("%s %d%%（常に横ばいなら%d%%・常に上昇なら%d%%）" % (
                        h["label"], round(x["hit"] * 100), round(x["always_flat"] * 100), round(x["always_up"] * 100)))
            lines.append("%s：%s" % (config.ASSETS[asset]["label"].split("（")[0], "／".join(parts)))
        d.para("過去データでの試験（バックテスト）による、このルールの判定の当たった割合です。比較のため、毎回同じ答えを出した場合の割合を並べています"
               "（ニュースは過去のものが無いため、価格と外部環境だけの試験です）。", size=9, keep=True)
        for ln in lines:
            d.para(ln, size=9, after=1)

    note = report.get("claude_note")
    if note:
        H("Claudeによる補足")
        d.para("月に1回など、必要なときにClaudeへ依頼した補足です（取り込み：%s）。" % note["saved_at"][:16], size=9, color="595959", keep=True)
        for k, v in note["sections"].items():
            d.para(k, size=10, bold=True, color="1F3864", before=3, keep=True)
            for ln in v.splitlines():
                d.para(ln, size=9, after=1)
    H("ご注意")
    d.para(report["disclaimer"], size=9, color="595959")
    if report.get("problems"):
        d.para("取得できなかった項目：" + " / ".join(report["problems"])[:300], size=8, color="C00000")
    d.doc.save(path_or_buf)


def _sc(v):
    return "%+d" % v if v else "0"


def _compare_line(so, sg):
    a, b = so["week_return"], sg["week_return"]
    if a is None or b is None:
        return ""
    if a > b:
        return "今週はオルカンのほうが強い週でした。"
    if b > a:
        return "今週はゴールドのほうが強い週でした。"
    return "今週は同じ動きでした。"
