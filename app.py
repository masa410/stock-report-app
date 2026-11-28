"""週次株価レポート（スマホ用アプリ）。保存済みのレポートを見る・手動実行・Claude補足の取り込み・辞書の追加。"""
import datetime as dt
import io
import json
import os

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
.card {border: 1px solid rgba(250,250,250,0.18); border-radius: 10px; padding: 0.6rem 0.8rem; margin-bottom: 0.5rem;}
.chip {display:inline-block; padding: 0.05rem 0.5rem; border-radius: 999px; font-size: 0.8rem; margin-right: 0.3rem;}
.c3 {background:#1f6f43; color:#fff;} .c2 {background:#8a6d1a; color:#fff;} .c1 {background:#6b3b3b; color:#fff;}
.ln {border:1px solid #888}
div[data-testid="stButton"] button, div[data-testid="stDownloadButton"] button {font-size: 1.05rem; padding: 0.6rem 1rem;
  background: #2a2f3a; color: #ff8a8e; border: 1px solid #3b4252;}
div[data-testid="stDialog"] > div { align-items:center !important; }
</style>
""", unsafe_allow_html=True)


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
def load_reports_cached(_store, stamp):
    return stmod.load_reports(_store)


# ---------------- ポップアップ ----------------
@st.dialog("お知らせ", width="large", dismissible=False)
def popup(kind, text):
    st.markdown("### " + ("✅ " if kind == "ok" else "⚠️ ") + text)
    if st.button("OK", key="popup_ok"):
        st.session_state["reports_stamp"] = st.session_state.get("reports_stamp", 0) + 1
        st.rerun()


# ---------------- 表示部品 ----------------
def highs_box(report):
    body = "<br>".join(fmt.highs_lines(report))
    st.markdown('<div class="hi-box"><b class="t">最高値の更新</b><br>%s</div>' % body, unsafe_allow_html=True)
    st.caption(fmt.disclaimer_range_note(report))


def tab_week(report):
    o, g = report["assets"]["orukan"]["summary"], report["assets"]["gold"]["summary"]
    c1, c2 = st.columns(2)
    c1.metric("オルカン", fmt.price(o["close"], ""), "%+.1f%%" % (o["week_return"] * 100))
    c2.metric("ゴールド（円/g）", fmt.price(g["close"], ""), "%+.1f%%" % (g["week_return"] * 100))
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


def tab_outlook(report):
    if report["mode"] != "最終":
        st.info("暫定版には、先の見通しはありません。土曜の最終版で出ます。")
        return
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


def tab_news(report, store):
    n = report.get("news")
    if not n:
        st.info("ニュースはありません。")
        return
    st.caption("無料RSSの見出しを、配信元の数でまとめています。配信元が2つ以上、または辞書に当たった話題を表示します。")
    for c in n["clusters"]:
        if c["n_sources"] < 2 and not c["categories"]:
            continue
        cls = "c3" if c["n_sources"] >= 3 else "c2" if c["n_sources"] == 2 else "c1"
        cats = "・".join(c["categories"][:2]) or "未分類"
        st.markdown('<div class="card"><b>%s</b><br><span class="chip %s">%s</span><span class="chip ln">%d配信元</span>'
                    '<span class="chip ln">%s</span> オルカン %s／ゴールド %s</div>' % (
                        c["title"], cls, c["trust"], c["n_sources"], cats, docx_report._sc(c["scores"]["orukan"]),
                        docx_report._sc(c["scores"]["gold"])), unsafe_allow_html=True)
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


def tab_answers(report):
    if report["mode"] != "最終":
        st.info("暫定版には、答え合わせはありません。")
        return
    a = report["answers"]
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


def tab_run(report, store, reports):
    st.markdown("**今週のレポート**")
    st.caption("毎週土曜9時に自動で作られます。押すのは、自動が失敗したときの予備です。")
    today = rpt.now_jst().date()
    week, mode = rpt.week_key_and_mode(today)
    if st.button("今週のレポートを作る", key="run", type="primary", disabled=st.session_state.get("running", False)):
        st.session_state["running"] = True
        try:
            import run_weekly
            with st.spinner("取得・分析・保存しています（1分ほどかかります）"):
                rep = run_weekly.main(store, today)
            st.session_state["pending"] = ("ok", "%s を作りました（%s）" % (fmt.jp_date(rep["report_date"]), rep["mode"]))
        except Exception as e:  # noqa: BLE001
            st.session_state["pending"] = ("ng", "作れませんでした：%s" % e)
        st.session_state["running"] = False
        st.rerun()
    st.info("今日は%s曜日です。%s" % ("月火水木金土日"[today.weekday()],
                                  "土・日に押すと、最終版（土曜付け）になります。" if mode == "最終" else
                                  "土・日以外は「暫定版」になります（過去との突合せと見通しは出ません）。"))

    st.markdown("**Claudeに補足を頼む（クリックだけ）**")
    text = prompt.build_prompt(report)
    components.html(_clip_buttons(text), height=200)
    pasted = st.text_area("貼り付け欄（Claudeの回答）", key="paste_area", height=120, label_visibility="collapsed",
                          placeholder="ここにClaudeの回答が入ります")
    if st.button("③ 取り込む", key="import") and pasted.strip():
        sections, cands = prompt.parse_note(pasted)
        if not sections:
            st.session_state["pending"] = ("ng", "見出し（## で始まる行）が見つかりません。型どおりの回答か確認してください")
        else:
            report = dict(report, claude_note={"sections": sections, "candidates": cands, "saved_at": str(rpt.now_jst())})
            stmod.save_report(store, report["report_date"], report["mode"], report["generated_at"], report)
            st.session_state["pending"] = ("ok", "Claudeの補足を取り込みました")
        st.rerun()

    st.markdown("**Word**")
    buf = io.BytesIO()
    try:
        docx_report.build_docx(report, buf)
        st.download_button("Wordをダウンロード", buf.getvalue(), file_name="週報_%s.docx" % report["report_date"], key="dl")
    except Exception as e:  # noqa: BLE001
        st.error("Wordを作れませんでした：%s" % e)
    st.caption("PCでアプリを開くと、C:\\株価分析\\2026年\\11月\\ のように、年・月のフォルダが自動で作られ、まだ置いていない週のWordが全部置かれます。")


def tab_note(report, store):
    note = report.get("claude_note")
    if not note:
        st.info("Claudeの補足はまだありません。「実行」タブから取り込めます。")
        return
    for k, v in note["sections"].items():
        st.markdown("**%s**" % k)
        st.write(v)
    if note["candidates"]:
        st.markdown("**辞書への追加候補（タップで追加）**")
        for i, (w, c, d) in enumerate(note["candidates"]):
            if st.button("「%s」を %s・%s で追加" % (w, c, d), key="nc%d" % i):
                pipeline.add_dictionary_word(store, w, c, d)
                st.toast("追加しました")
    st.caption("取り込み：" + note["saved_at"])


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


# ---------------- 本体 ----------------
def main():
    if not gate():
        return
    store = get_store()
    stamp = st.session_state.get("reports_stamp", 0)
    reports = load_reports_cached(store, stamp)
    st.markdown("### 週次レポート")
    if not reports:
        st.info("まだレポートがありません。「実行」タブから作れます。")
        report = None
    else:
        labels = ["%s（%s）" % (w, m) for w, m, _, _ in reversed(reports)]
        idx = st.selectbox("週", range(len(labels)), format_func=lambda i: labels[i], label_visibility="collapsed")
        w, m, g, report = list(reversed(reports))[idx]
        st.caption("作成：%s　／　データ基準：%s" % (report["generated_at"][:16], report["as_of"]))
        if report["mode"] != "最終":
            st.warning("暫定版（%s曜日時点）：その時点の分析だけです。土曜の最終版で置き換わります。" % report["weekday"])
        if report.get("problems"):
            st.caption("取得できなかった項目：" + " / ".join(report["problems"])[:200])
        highs_box(report)
    tabs = st.tabs(["今週", "見通し", "ニュース", "答え合わせ", "補足", "実行"])
    for i, fn in enumerate((tab_week, tab_outlook, None, tab_answers)):
        with tabs[i]:
            if not report:
                st.write("―")
            elif i == 2:
                tab_news(report, store)
            else:
                fn(report)
    with tabs[4]:
        if not report:
            st.write("―")
        else:
            tab_note(report, store)
    with tabs[5]:
        if report:
            tab_run(report, store, reports)
        elif st.button("今週のレポートを作る", key="run0", type="primary"):
            import run_weekly
            with st.spinner("取得・分析・保存しています（1分ほどかかります）"):
                run_weekly.main(store, rpt.now_jst().date())
            st.session_state["reports_stamp"] = stamp + 1
            st.rerun()
    pend = st.session_state.pop("pending", None)
    if pend:
        popup(*pend)


main()
