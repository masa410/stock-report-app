"""週次株価レポート（スマホ用アプリ）。毎日の暫定版・土曜の最終版・週の一覧（見返し）・Claude補足の取り込み・辞書・通知設定。"""
import datetime as dt
import io
import json
import os

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import config
import docx_report
import fmt
import pipeline
import prompt
import report as rpt
import store as stmod

st.set_page_config(page_title="週次株価レポート", page_icon="📈", layout="centered")

st.markdown("""
<style>
.block-container {padding-top: 4rem; padding-bottom: 3rem;}
.hi-box {border: 2px solid #e5484d; background: rgba(229,72,77,0.10); border-radius: 10px; padding: 0.8rem 1rem; margin: 0.4rem 0 0.8rem 0;}
.hi-box b.t {color: #ff6b70; font-size: 1.1rem;}
.one {border: 1px solid rgba(250,250,250,0.18); background: rgba(250,250,250,0.04); border-radius: 12px; padding: 0.7rem 0.9rem; margin: 0.3rem 0 0.8rem 0; font-size: 1.02rem; line-height: 1.6;}
.card {border: 1px solid rgba(250,250,250,0.18); border-radius: 10px; padding: 0.6rem 0.8rem; margin-bottom: 0.5rem;}
.chip {display:inline-block; padding: 0.05rem 0.5rem; border-radius: 999px; font-size: 0.8rem; margin-right: 0.3rem;}
.c3 {background:#1f6f43; color:#fff;} .c2 {background:#8a6d1a; color:#fff;} .c1 {background:#6b3b3b; color:#fff;}
.s-prov {background:#3b4a6b; color:#fff;} .s-wait {background:#b45309; color:#fff;} .s-done {background:#1f6f43; color:#fff;} .s-late {background:#7f1d1d; color:#fff;}
.new {background:#e5484d; color:#fff;}
.sub {color:#9aa3b2; font-size:0.85rem;}
.ln {border:1px solid #888}
div[data-testid="stButton"] button, div[data-testid="stDownloadButton"] button {font-size: 1.05rem; padding: 0.6rem 1rem;
  background: #2a2f3a; color: #ff8a8e; border: 1px solid #3b4252;}
div[data-testid="stDialog"] > div { align-items:center !important; }
</style>
""", unsafe_allow_html=True)

STATE_CLASS = {"暫定": "s-prov", "最終・補足待ち": "s-wait", "補足待ち（期限後）": "s-late", "完成": "s-done"}
WD = "月火水木金土日"


# ---------------- 接続 ----------------
@st.cache_resource
def get_store():
    if os.environ.get("STOCK_APP_MEMORY"):          # 試験用（保存先を持たない）
        s = stmod.MemoryStore()
        if os.environ.get("STOCK_APP_MEMORY") == "demo":
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))
            import demo_seed
            demo_seed.fill(s)
        return s
    import store_factory
    return store_factory.from_streamlit_secrets(st.secrets)


def gate():
    if os.environ.get("STOCK_APP_MEMORY"):          # 試験・画面確認用（ダミーのデータ）では、合い言葉を求めない
        return True
    pw = ""
    try:
        pw = st.secrets.get("app_password", "")
    except Exception:  # noqa: BLE001
        pw = ""
    if not pw or st.session_state.get("authed"):
        return True
    st.markdown("### 週次株価レポート")
    x = st.text_input("合い言葉", type="password")
    if st.button("入る", key="login"):
        if x == pw:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("合い言葉が違います")
    return False


@st.cache_data(ttl=60, show_spinner=False)
def load_cached(_store, stamp):
    return stmod.load_reports(_store), stmod.load_provs(_store)


# ---------------- ポップアップ ----------------
@st.dialog("お知らせ", width="large", dismissible=False)
def popup(kind, text):
    st.markdown("### " + ("✅ " if kind == "ok" else "⚠️ ") + text)
    if st.button("OK", key="popup_ok"):
        st.session_state["stamp"] = st.session_state.get("stamp", 0) + 1
        st.rerun()


def refresh():
    st.session_state["stamp"] = st.session_state.get("stamp", 0) + 1


# ---------------- 表示部品 ----------------
def line(df, height=170):
    """縦軸を0から始めず、値の幅に合わせて表示する折れ線（銘柄ごとに色分け）。"""
    long = df.reset_index().melt(id_vars="index", var_name="銘柄", value_name="値")
    order = list(df.index)
    ch = alt.Chart(long).mark_line(point=True, strokeWidth=2.5).encode(
        x=alt.X("index:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("値:Q", scale=alt.Scale(zero=False), title=None),
        color=alt.Color("銘柄:N", scale=alt.Scale(domain=["オルカン", "ゴールド"], range=["#e5484d", "#f5c542"]),
                        legend=alt.Legend(orient="bottom", title=None)),
    ).properties(height=height)
    st.altair_chart(ch, use_container_width=True)


def _wd(iso):
    x = dt.date.fromisoformat(str(iso)[:10])
    return "%d/%d（%s）" % (x.month, x.day, WD[x.weekday()])


def daily_chart(report, height=170):
    dm = report.get("daily")
    if not dm or not dm.get("dates"):
        return False
    idx = ["先週金"] + [WD[dt.date.fromisoformat(d).weekday()] for d in dm["dates"]]
    line(pd.DataFrame({"オルカン": [100.0] + [100 + v for v in dm["orukan"]],
                       "ゴールド": [100.0] + [100 + v for v in dm["gold"]]}, index=idx), height)
    return True


def daily_table(report):
    dm = report.get("daily")
    if dm and dm.get("dates"):
        st.dataframe(pd.DataFrame({"": [_wd(d) for d in dm["dates"]],
                                   "オルカン": [("%+.2f%%" % v).replace("-", "−") for v in dm["orukan"]],
                                   "ゴールド": [("%+.2f%%" % v).replace("-", "−") for v in dm["gold"]]}),
                     hide_index=True, use_container_width=True)


def highs_box(report):
    body = "<br>".join(fmt.highs_lines(report))
    st.markdown('<div class="hi-box"><b class="t">最高値の更新</b><br>%s</div>' % body, unsafe_allow_html=True)
    st.caption(fmt.disclaimer_range_note(report))


def news_card(c):
    cls = "c3" if c["n_sources"] >= 3 else "c2" if c["n_sources"] == 2 else "c1"
    cats = "・".join(c["categories"][:2]) or "未分類"
    st.markdown('<div class="card"><b>%s</b><br><span class="chip %s">%s</span><span class="chip ln">%d配信元</span>'
                '<span class="chip ln">%s</span> <span class="sub">オルカン %s／ゴールド %s</span></div>' % (
                    c["title"], cls, c["trust"], c["n_sources"], cats, docx_report._sc(c["scores"]["orukan"]),
                    docx_report._sc(c["scores"]["gold"])), unsafe_allow_html=True)


def shown_clusters(report):
    n = report.get("news") or {"clusters": []}
    return [c for c in n["clusters"] if c["n_sources"] >= 2 or c["categories"]]


# ---------------- 今週 ----------------
def tab_week(report):
    o, g = report["assets"]["orukan"]["summary"], report["assets"]["gold"]["summary"]
    prov = report["mode"] != "最終"
    if prov:
        st.markdown('<div class="one"><b>今日のひとこと</b><br>%s</div>' % report["one_liner"].replace("\n", "<br>"), unsafe_allow_html=True)
        h = o["highs"]
        if h["ath_update"]:
            highs_box(report)
        else:
            st.markdown('<div class="card">最高値まで　<b>あと %s</b>（%s・%s）　<span class="sub">更新したら、ここが赤い枠で目立ちます</span></div>' % (
                fmt.pct(h["ath_remaining_pct"], signed=False), fmt.price(h["ath_value"], ""), fmt.md(h["ath_date"])), unsafe_allow_html=True)
            gh = g["highs"]
            if gh["ath_update"]:
                highs_box(report)
        c1, c2 = st.columns(2)
        c1.metric("オルカン（今週ここまで）", fmt.price(o["close"], ""), "%+.1f%%" % (o["week_return"] * 100))
        c2.metric("ゴールド（円/g）", fmt.price(g["close"], ""), "%+.1f%%" % (g["week_return"] * 100))
        st.markdown("**今週の日々の動き**（先週金曜の終値を100）")
        daily_chart(report)
        daily_table(report)
        st.markdown("**今の位置**")
        for asset, label in (("orukan", "オルカン"), ("gold", "ゴールド")):
            st.caption(("%s：%s" % (label, "／".join((report.get("position") or {}).get(asset, [])))).replace("-", "−"))
        st.info("見通し（上昇優勢・下落優勢などの目安確率）は、土曜 9:23 の最終版で更新されます。「見通し」タブには、先週の最終版が出ています。")
        return
    highs_box(report)
    c1, c2 = st.columns(2)
    c1.metric("オルカン", fmt.price(o["close"], ""), "%+.1f%%" % (o["week_return"] * 100))
    c2.metric("ゴールド（円/g）", fmt.price(g["close"], ""), "%+.1f%%" % (g["week_return"] * 100))
    if report.get("daily", {}).get("dates"):
        st.markdown("**今週の日々の動き**（先週金曜の終値を100）")
        daily_chart(report)
        daily_table(report)
    fx = report["usdjpy"]
    if fx["change"] is not None:
        st.caption("ドル円 %.1f円（前週比 %+.1f円、%s）。%s" % (
            fx["last"], fx["change"], "円安方向" if fx["change"] > 0 else "円高方向", docx_report._compare_line(o, g)))
    df = pd.DataFrame({
        "": ["週内の高値（終値）", "週内の安値（終値）", "直近1か月", "直近3か月", "直近1年", "年初来", "高値から"],
        "オルカン": [fmt.price(o["week_high"], ""), fmt.price(o["week_low"], ""), fmt.pct(o["ret_1m"]), fmt.pct(o["ret_3m"]),
                  fmt.pct(o["ret_1y"]), fmt.pct(o["ret_ytd"]), fmt.pct(o["from_high"]) if o["from_high"] < 0 else "最高値"],
        "ゴールド": [fmt.price(g["week_high"], ""), fmt.price(g["week_low"], ""), fmt.pct(g["ret_1m"]), fmt.pct(g["ret_3m"]),
                  fmt.pct(g["ret_1y"]), fmt.pct(g["ret_ytd"]), fmt.pct(g["from_high"]) if g["from_high"] < 0 else "最高値"],
    })
    st.dataframe(df, hide_index=True, use_container_width=True)
    ch = report["chart"]
    if ch["dates"]:
        st.line_chart(pd.DataFrame({"オルカン": ch["orukan"], "ゴールド": ch["gold"]}, index=pd.to_datetime(ch["dates"])), height=220)
        st.caption("直近1年の推移（1年前を100とした指数）")


# ---------------- 見通し ----------------
def tab_outlook(cur, final):
    if cur["mode"] != "最終":
        if not final:
            st.info("最初の最終版（土曜 9:23）ができると、見通しが出ます。")
            return
        st.info("先週（%s の週）の最終版の見通しです。次の更新は、土曜 9:23 です。" % final["report_date"])
    report = final if cur["mode"] != "最終" else cur
    names = {k: v["label"] for k, v in report["assets"].items()}
    asset = st.radio("銘柄", list(names), format_func=lambda k: names[k], horizontal=True, label_visibility="collapsed")
    o = report["assets"][asset]["outlook"]
    st.caption(("いまの位置：" + "／".join(o["position"])).replace("-", "−"))
    with st.expander("ルール判定の根拠（どの材料が何点か）"):
        for c in o["components"]:
            st.write("・%s　%s　→　%+.1f点" % (c["name"], c["value"], c["score"]))
        st.write("合計：%+.1f点" % o["total_score"])
    for r in o["rows"]:
        top = max(r["probs"])
        with st.expander("%s　→　%s %d%%" % (r["label"], r["judgment"], top), expanded=(r["key"] == "1w")):
            st.markdown("**ルール判定（目安の確率）**")
            for lab, v in zip(config.LABELS, r["probs"]):
                st.progress(v / 100, text="%s %d%%" % (lab, v))
            st.markdown("**過去統計（別枠）**")
            st.write("過去の同じ局面：" + fmt.analog_text(r["analog"]))
            if r["analog"]:
                st.write("80%が収まる幅：" + fmt.range_text(r["analog"]))
                if r["key"] in ("3y", "5y"):
                    st.caption("日付が重なる件が多く、参考程度です。")


# ---------------- ニュース ----------------
def tab_news(report, store):
    n = report.get("news")
    if not n:
        st.info("ニュースはありません。")
        return
    fetched = report.get("fetched_at") or report["generated_at"]
    st.caption("最終取得：%s　／　朝と夕に更新されます。見出しは無料RSS、配信元の数で信ぴょう性を示します。" % fetched[:16])
    today = fetched[:10]
    fresh = [c for c in shown_clusters(report) if c.get("last_seen") == today and c.get("first_seen") == today][:5]
    if fresh:
        st.markdown('**今日の新着**　<span class="chip new">新着 %d</span>' % len(fresh), unsafe_allow_html=True)
        for c in fresh:
            news_card(c)
    st.markdown("**今週の主なニュース（分類別）**")
    groups = {}
    for c in shown_clusters(report):
        groups.setdefault((c["categories"] or ["未分類"])[0], []).append(c)
    for cat, cs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        with st.expander("%s（%d件）" % (cat, len(cs))):
            for c in cs:
                news_card(c)
    st.markdown("ニュース判定（−2〜+2）：オルカン **%+.1f**／ゴールド **%+.1f**" % (n["scores"]["orukan"], n["scores"]["gold"]))
    with st.expander("分類されなかった話題：%d件（タップで辞書に追加）" % n["n_unclassified"]):
        for i, u in enumerate(n["unclassified"][:8]):
            st.write(u["title"])
            c1, c2, c3 = st.columns(3)
            w = c1.selectbox("語", u["candidates"] or ["―"], key="w%d" % i)
            cat = c2.selectbox("分類", sorted({x[1] for x in __import__("dictseed").SEED}), key="c%d" % i)
            d = c3.selectbox("方向", ["上昇", "下落", "影響なし"], key="d%d" % i)
            if st.button("辞書に追加", key="add%d" % i) and w != "―":
                pipeline.add_dictionary_word(store, w, cat, d)
                st.toast("「%s」を辞書に追加しました" % w)


# ---------------- 週の一覧（見返し） ----------------
def week_note_label(row, now):
    due = rpt.note_due_for(row["week"])
    if row.get("note_at"):
        return "期限後" if row["note_at"][:19] > due[:19] else "済み"
    return "なし" if str(now)[:19] > due[:19] else "待ち"


def tab_weeks(store, finals, now):
    rows = [r for r in store.read(config.SH_WEEKS) if r.get("week")]
    if len(rows) < len(finals):                       # 過去の最終版の分を、自動で一覧に足す
        pipeline.backfill_weeks(store, now)
        rows = [r for r in store.read(config.SH_WEEKS) if r.get("week")]
    if not rows:
        st.info("まだ、最終版が１つもありません。土曜 9:23 に、最初の最終版ができます。")
        return
    rows = sorted(rows, key=lambda r: r["week"], reverse=True)
    st.markdown("**週の一覧**（行をタップすると、その週の最終版が開きます）")
    st.caption("週の★＝最高値を更新した週　／　予想：来週の見通しが当たったか　／　補足：Claudeの補足の状態（済み・期限後・待ち・なし）")

    def f(x):
        try:
            return ("%+.1f%%" % float(x)).replace("-", "−")
        except (TypeError, ValueError):
            return "―"

    df = pd.DataFrame({"週": [fmt.md(r["week"]) + ("★" if r["high"] not in ("", "なし") else "") for r in rows],
                       "オルカン": [f(r["orukan_ret"]) for r in rows], "ゴールド": [f(r["gold_ret"]) for r in rows],
                       "予想": [r["result"] or "確認待ち" for r in rows], "補足": [week_note_label(r, now) for r in rows]})
    sel = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row", key="weeklist")
    picked = sel.selection.rows if hasattr(sel, "selection") else []

    st.markdown("**週をまたいだ値動きの比較**")
    span = st.radio("期間", ["直近8週", "半年（26週）", "1年（52週）"], horizontal=True, index=1, label_visibility="collapsed")
    n = {"直近8週": 8, "半年（26週）": 26, "1年（52週）": 52}[span]
    ch = finals[-1][3]["chart"] if finals else None
    if ch and ch["dates"]:
        k = min(n + 1, len(ch["dates"]))
        o, g = ch["orukan"][-k:], ch["gold"][-k:]
        line(pd.DataFrame({"オルカン": [v / o[0] * 100 for v in o], "ゴールド": [v / g[0] * 100 for v in g]},
                          index=[fmt.md(d) for d in ch["dates"][-k:]]), 220)
        st.caption("%sの推移（最初の週を100とした指数）。毎週の金曜の終値から作っています。" % span)
    if picked:
        week = rows[picked[0]]["week"]
        rep = next((r for w, m, g, r in finals if w == week), None)
        st.markdown("---")
        if rep is None:
            st.info("この週のレポートが見つかりません。")
        else:
            week_detail(store, rep, rows[picked[0]], now)
    else:
        st.caption("↑ 一覧の行をタップすると、その週の中身（①まとめ〜⑦Word）が、ここに開きます。")


def week_detail(store, rep, row, now):
    week = rep["report_date"]
    st.markdown("#### %s の週（%s）" % (fmt.md(week), stmod.report_status(rep, now)))
    o, g = rep["assets"]["orukan"]["summary"], rep["assets"]["gold"]["summary"]
    st.markdown("**① まとめ**")
    c1, c2 = st.columns(2)
    c1.metric("オルカン（週間）", fmt.price(o["close"], ""), "%+.1f%%" % (o["week_return"] * 100))
    c2.metric("ゴールド（円/g・週間）", fmt.price(g["close"], ""), "%+.1f%%" % (g["week_return"] * 100))
    st.caption("最高値の更新：" + row.get("high", "なし"))
    st.markdown("**② その週の日々の動き**")
    if not daily_chart(rep, 150):
        st.caption("この週は、日々の記録がありません（毎日の更新を始める前の週です）。")
    st.markdown("**③ その週の主なニュース（確定）**")
    cs = shown_clusters(rep)[:5]
    for c in cs:
        news_card(c)
    if not cs:
        st.caption("主なニュースはありません。")
    st.markdown("**④ 見通しと答え合わせ**")
    for r in rep["assets"]["orukan"].get("outlook", {}).get("rows", []):
        st.caption("オルカン %s：%s %d%%" % (r["label"], r["judgment"], max(r["probs"])))
    st.caption("来週の見通しの結果：" + (row.get("result") or "確認待ち"))
    st.markdown("**⑤ Claudeの補足**")
    note = rep.get("claude_note")
    if note:
        if stmod.note_late(rep):
            st.caption("※期限後に取り込み")
        for k, v in note["sections"].items():
            with st.expander(k):
                st.write(v)
    else:
        st.caption("補足はありません。")
    st.markdown("**⑥ 自分のメモ**")
    key = "memo_" + week
    if key not in st.session_state:
        st.session_state[key] = stmod.get_memo(store, week)
    st.text_area("メモ", key=key, placeholder="この週について、気づいたことを自由に書けます（保存すると、週に残ります）",
                 label_visibility="collapsed")
    if st.button("メモを保存", key="memosave_" + week):
        stmod.set_memo(store, week, st.session_state[key], now)
        st.toast("メモを保存しました")
    st.markdown("**⑦ Word**")
    buf = io.BytesIO()
    try:
        docx_report.build_docx(rep, buf)
        st.download_button("Wordをダウンロード", buf.getvalue(), file_name="週報_%s.docx" % week, key="dl_" + week)
    except Exception as e:  # noqa: BLE001
        st.error("Wordを作れませんでした：%s" % e)


# ---------------- 答え合わせ ----------------
def tab_answers(final):
    if not final:
        st.info("最初の最終版（土曜 9:23）ができると、答え合わせが出ます。")
        return
    a = final["answers"]
    bt = a["backtest"]
    with st.expander("この画面の読み方", expanded=False):
        st.markdown(
            "**この画面は、「このアプリの予想は信用できるのか」を確かめるためのものです。**\n\n"
            "- **上の表**は、アプリのルール判定を、過去の実際の値動きに当てはめたときに、何％当たったかの試験です。\n"
            "- **当たり**：ルール判定が、実際の結果と合っていた割合です。\n"
            "- **横ばい固定／上昇固定**：何も考えず、毎回「横ばい」または「上昇優勢」と答えた場合の、当たった割合です（比べるための基準）。\n"
            "- **見方**：「当たり」が、この2つより高ければ、ルール判定に意味があります。同じか低い間は、参考程度に見てください。\n"
            "- **下の表（実際の予想の結果）**は、毎週出した本物の予想が、期日を過ぎたあとの結果です。件数が増えるほど、参考になります。\n"
            "- 3年後の100％などは、過去に上昇しか無かったための数字です。参考程度に見てください。")
    st.markdown("**過去データでの試験（バックテスト）の当たった割合**")
    rows = []
    for asset in ("orukan", "gold"):
        for h in config.HORIZONS:
            x = bt.get(asset, {}).get(h["key"])
            if x:
                rows.append({"対象": config.ASSETS[asset]["label"].split("（")[0], "期間": h["label"],
                             "当たり": "%d%%" % round(x["hit"] * 100), "横ばい固定": "%d%%" % round(x["always_flat"] * 100),
                             "上昇固定": "%d%%" % round(x["always_up"] * 100)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption("ニュースは過去が無いため、価格と外部環境だけの試験です。「横ばい固定」「上昇固定」は、毎回同じ答えを出した場合の割合（比較用）です。")
    st.markdown("**実際の予想の結果**（確認待ち %d件）" % a["n_pending"])
    if a["recent"]:
        st.dataframe(pd.DataFrame([{"予想日": r["issued"], "対象": config.ASSETS[r["asset"]]["label"].split("（")[0],
                                    "期間": r["horizon"], "予想": r["judgment"], "結果": fmt.pct(r["actual"]), "判定": r["hit"]}
                                   for r in a["recent"]]), hide_index=True, use_container_width=True)
    else:
        st.caption("まだ結果が確認できた予想はありません。")


# ---------------- 補足 ----------------
def tab_note(final, store, now):
    if not final:
        st.info("補足は、土曜 9:23 に最初の最終版ができてから取り込めます。")
        return
    week = final["report_date"]
    note = final.get("claude_note")
    due = final.get("note_due") or rpt.note_due_for(week)
    st.caption("対象：%s の週の最終版" % fmt.md(week))
    if note:
        if stmod.note_late(final):
            st.warning("期限後に取り込みました（期限：%s）。" % due[:10].replace("-", "/") + " 24:00")
        else:
            st.success("補足は、%s に取り込み済みです。" % note["saved_at"][5:16].replace("-", "/"))
        for k, v in note["sections"].items():
            st.markdown("**%s**" % k)
            st.write(v)
        if note["candidates"]:
            st.markdown("**辞書への追加候補（タップで追加）**")
            for i, (w, c, d) in enumerate(note["candidates"]):
                if st.button("「%s」を %s・%s で追加" % (w, c, d), key="nc%d" % i):
                    pipeline.add_dictionary_word(store, w, c, d)
                    st.toast("追加しました")
        st.markdown("---")
        st.markdown("**補足を入れ直す**")
    else:
        if str(now)[:19] <= due[:19]:
            st.warning("補足の期限：%s（日）24:00　（過ぎても取り込めます。その場合は「期限後に取り込み」と表示します）" % fmt.md(due[:10]))
        else:
            st.error("補足の期限（%s 24:00）を過ぎています。取り込むと「期限後に取り込み」と表示されます。" % fmt.md(due[:10]))
    st.markdown("**Claudeに補足を頼む（クリックだけ）**")
    text = prompt.build_prompt(final)
    components.html(_clip_buttons(text), height=200)
    pasted = st.text_area("貼り付け欄（Claudeの回答）", key="paste_area", height=120, label_visibility="collapsed",
                          placeholder="ここにClaudeの回答が入ります")
    st.caption("依頼文には、その週の日々の動きと、日ごとのニュースの流れが入ります。")
    if st.button("③ 取り込む", key="import", type="primary") and pasted.strip():
        sections, cands = prompt.parse_note(pasted)
        if not sections:
            st.session_state["pending"] = ("ng", "見出し（## で始まる行）が見つかりません。型どおりの回答か確認してください")
        else:
            rep = dict(final, claude_note={"sections": sections, "candidates": cands, "saved_at": str(rpt.now_jst())})
            stmod.save_report(store, week, "最終", final["generated_at"], rep)
            pipeline.sync_week_row(store, rep, now)
            st.session_state["pending"] = ("ok", "Claudeの補足を取り込みました" + ("（期限後）" if stmod.note_late(rep) else ""))
        st.rerun()


def _clip_buttons(text):
    return """
<style>button{font-size:16px;padding:10px 14px;margin:4px 6px 4px 0;background:#2a2f3a;color:#ff8a8e;border:1px solid #3b4252;border-radius:8px}
#m{color:#aaa;font-size:13px;margin-top:6px;font-family:sans-serif}</style>
<button id="c">① Claudeに渡す文章をコピー</button><button id="s">② 共有（Claudeアプリへ）</button><button id="p">貼り付け欄へ貼り付け</button>
<div id="m"></div>
<script>
const T = %s;
const m = document.getElementById('m');
function say(x){m.textContent = x;}
function legacyCopy(t){const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();
  let ok=false;try{ok=document.execCommand('copy');}catch(e){} document.body.removeChild(a);return ok;}
document.getElementById('c').onclick = async () => {
  try { await navigator.clipboard.writeText(T); say('コピーしました。Claudeに貼り付けてください'); }
  catch(e){ say(legacyCopy(T) ? 'コピーしました。Claudeに貼り付けてください' : 'コピーできませんでした。共有ボタンを使ってください'); }
};
document.getElementById('s').onclick = async () => {
  if (navigator.share) { try { await navigator.share({text: T}); say('共有しました'); } catch(e){ say('共有を取りやめました'); } }
  else { say('この端末では共有が使えません。コピーを使ってください'); }
};
document.getElementById('p').onclick = async () => {
  try {
    const t = await navigator.clipboard.readText();
    const ta = window.parent.document.querySelector('textarea[aria-label="貼り付け欄（Claudeの回答）"]');
    if (!ta) { say('貼り付け欄が見つかりません'); return; }
    const set = Object.getOwnPropertyDescriptor(window.parent.HTMLTextAreaElement.prototype, 'value').set;
    set.call(ta, t); ta.dispatchEvent(new Event('input', {bubbles: true}));
    say('貼り付けました。下の「取り込む」を押してください');
  } catch(e){ say('自動の貼り付けが許可されませんでした。貼り付け欄を長押しして貼り付けてください'); }
};
</script>""" % json.dumps(text, ensure_ascii=False)


# ---------------- 実行 ----------------
def tab_run(cur, final, store, now):
    today = now.date()
    st.markdown("**今日の分を更新する（暫定版）**")
    st.caption("平日は、朝7:13と夕18:13ごろに自動で更新されます。押すのは、自動が遅れたときの予備です。")
    kind = rpt.run_kind(now)
    if kind == "取得のみ":
        st.info("今は土曜 9:23 より後（または日曜）なので、見出しだけを集めます。月曜から、新しい週の暫定版が育ちます。")
    if st.button("今日の分を更新する", key="run_daily", type="primary", disabled=st.session_state.get("running", False)):
        st.session_state["running"] = True
        try:
            import run_daily
            with st.spinner("取得・分析・保存しています（1分ほどかかります）"):
                out = run_daily.main(store, now)
            st.session_state["pending"] = ("ok", "暫定版を更新しました" if out["report"] else "見出しを集めました（%d件）" % out["added"])
        except Exception as e:  # noqa: BLE001
            st.session_state["pending"] = ("ng", "更新できませんでした：%s" % e)
        st.session_state["running"] = False
        st.rerun()
    st.markdown("**今週の最終版を作る**")
    st.caption("土曜 9:23 に自動で作られます。自動が失敗したときだけ押します（土曜・日曜のみ）。取り込み済みの補足は、消えません。")
    if st.button("今週の最終版を作る", key="run_final", disabled=today.weekday() < 5 or st.session_state.get("running", False)):
        st.session_state["running"] = True
        try:
            import run_weekly
            with st.spinner("取得・分析・保存しています（1分ほどかかります）"):
                rep = run_weekly.main(store, today)
            st.session_state["pending"] = ("ok", "%s を作りました（最終）" % fmt.jp_date(rep["report_date"]))
        except Exception as e:  # noqa: BLE001
            st.session_state["pending"] = ("ng", "作れませんでした：%s" % e)
        st.session_state["running"] = False
        st.rerun()
    if today.weekday() < 5:
        st.caption("（平日は、押せません。土曜になってから、押してください）")

    st.markdown("**通知（メール）**")
    s = stmod.get_settings(store)
    on = st.toggle("大きな動きと最高値の更新を、メールで知らせる", value=(s.get("通知を送る", "はい") == "はい"), key="set_on")
    try:
        thr0 = float(s.get("大きな動きの目安（前日比 ±%）") or 3)
    except ValueError:
        thr0 = 3.0
    thr = st.number_input("大きな動きの目安（前日比 ±％）", value=thr0, step=0.5, key="set_thr")
    mail = st.text_input("通知先のメールアドレス", value=s.get("通知先メール", ""), key="set_mail")
    if st.button("設定を保存", key="set_save"):
        for item, val in (("通知を送る", "はい" if on else "いいえ"), ("大きな動きの目安（前日比 ±%）", str(thr)), ("通知先メール", mail.strip())):
            stmod.upsert(store, config.SH_SETTINGS, "item", {"item": item, "value": val,
                                                          "desc": next((d for a, b, d in config.DEFAULT_SETTINGS if a == item), "")})
        st.toast("設定を保存しました")
    st.caption("送信には、メール送信用の合鍵（GitHub Actionsの Secrets）が要ります。同じ内容は、二重には送りません。")

    st.markdown("**Word**")
    if final:
        buf = io.BytesIO()
        try:
            docx_report.build_docx(final, buf)
            st.download_button("最新の週のWordをダウンロード", buf.getvalue(), file_name="週報_%s.docx" % final["report_date"], key="dl")
        except Exception as e:  # noqa: BLE001
            st.error("Wordを作れませんでした：%s" % e)
    st.caption("PCでアプリを開くと、C:\\株価分析\\2026年\\11月\\ のように、年・月のフォルダが自動で作られ、まだ置いていない週のWordが全部置かれます。")


# ---------------- 本体 ----------------
def main():
    if not gate():
        return
    store = get_store()
    now = rpt.now_jst()
    finals, provs = load_cached(store, st.session_state.get("stamp", 0))
    final = finals[-1][3] if finals else None
    prov = provs[-1][3] if provs else None
    cur = prov if prov and (final is None or prov["week"] > final["report_date"]) else final

    st.markdown("### 週次レポート")
    if cur is None:
        st.info("まだレポートがありません。「実行」タブで「今日の分を更新する」を押してください。")
    else:
        status = stmod.report_status(cur, now)
        fetched = cur.get("fetched_at") or cur["generated_at"]
        when = ("%s曜日 %s 時点" % (cur["weekday"], fetched[11:16])) if cur["mode"] != "最終" else "%s 作成" % fetched[5:16].replace("-", "/")
        st.markdown('<span class="chip %s">%s</span> <span class="sub">%s の週　%s　／　最終取得：%s</span>' % (
            STATE_CLASS[status], status, fmt.md(cur.get("week") or cur["report_date"]), when, fetched[5:16].replace("-", "/")),
            unsafe_allow_html=True)
        if cur["mode"] == "最終" and not cur.get("claude_note"):
            due = cur.get("note_due") or rpt.note_due_for(cur["report_date"])
            if str(now)[:19] <= due[:19]:
                st.warning("補足の期限：%s（日）24:00　（過ぎても取り込めます）" % fmt.md(due[:10]))
            else:
                st.error("補足の期限を過ぎています（取り込むと「期限後に取り込み」と表示されます）")
        if cur.get("problems"):
            st.caption("取得できなかった項目：" + " / ".join(cur["problems"])[:200])
    tabs = st.tabs(["今週", "見通し", "ニュース", "週の一覧", "答え合わせ", "補足", "実行"])
    with tabs[0]:
        if cur:
            tab_week(cur)
        else:
            st.write("―")
    with tabs[1]:
        if cur:
            tab_outlook(cur, final)
        else:
            st.write("―")
    with tabs[2]:
        if cur:
            tab_news(cur, store)
        else:
            st.write("―")
    with tabs[3]:
        tab_weeks(store, finals, now)
    with tabs[4]:
        tab_answers(final)
    with tabs[5]:
        tab_note(final, store, now)
    with tabs[6]:
        tab_run(cur, final, store, now)
    pend = st.session_state.pop("pending", None)
    if pend:
        popup(*pend)


main()
