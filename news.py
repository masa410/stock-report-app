"""ニュース見出しの収集（無料RSS・見出しのみ）、同じ話題のまとめ、辞書による判定。"""
import re
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

import config

HEADERS = {"User-Agent": config.USER_AGENT}


# ---------------- 取得 ----------------
def parse_rss(xml_bytes, default_source=None):
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None and src_el.text else default_source
        pub = it.findtext("pubDate")
        try:
            published = parsedate_to_datetime(pub).astimezone().replace(tzinfo=None).isoformat(timespec="minutes") if pub else ""
        except (TypeError, ValueError):
            published = ""
        if source and title.endswith(" - " + source):       # Googleニュースは末尾に配信元が付く
            title = title[: -len(source) - 3].strip()
        if title:
            items.append({"title": title, "source": source or "不明", "link": link, "published": published})
    return items


def fetch_feed(url, default_source=None):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return parse_rss(r.content, default_source)


def fetch_all_headlines():
    """Googleニュース（検索語ごと）＋Yahoo!ニュース経済。戻り値: (見出しのリスト, 失敗の説明)"""
    out, problems = [], []
    for q in config.NEWS_QUERIES:
        try:
            out += fetch_feed(config.GOOGLE_NEWS.format(q=urllib.parse.quote(q)))
        except Exception as e:  # noqa: BLE001
            problems.append("Googleニュース(%s): %s" % (q, type(e).__name__))
    try:
        out += fetch_feed(config.YAHOO_NEWS_RSS, default_source="Yahoo!ニュース")
    except Exception as e:  # noqa: BLE001
        problems.append("Yahoo!ニュース: %s" % type(e).__name__)
    return dedupe_exact(out), problems


def dedupe_exact(items):
    seen, out = set(), []
    for it in items:
        k = (it["title"], it["source"])
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


# ---------------- 同じ話題のまとめ ----------------
_STRIP = re.compile(r"[\s　、。，．・「」『』（）()\[\]【】〈〉!！?？:：;；\-–—―~〜…\"'“”]+")


def normalize(title):
    t = title.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return _STRIP.sub("", t)


def bigrams(t):
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def similarity(a, b):
    A, B = bigrams(normalize(a)), bigrams(normalize(b))
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def cluster(items, threshold=None):
    """似た見出しを1つの話題にまとめる。配信元の数で信頼度を付ける。"""
    th = config.NEWS_SIMILARITY if threshold is None else threshold
    clusters = []
    for it in items:
        for c in clusters:
            if similarity(it["title"], c["title"]) >= th:
                c["items"].append(it)
                break
        else:
            clusters.append({"title": it["title"], "items": [it]})
    out = []
    for c in clusters:
        sources = sorted({x["source"] for x in c["items"]})
        n = len(sources)
        label, weight = "要確認", 0.4
        for need, lab, w in config.TRUST:
            if n >= need:
                label, weight = lab, w
                break
        out.append({"title": c["title"], "sources": sources, "n_sources": n, "trust": label, "weight": weight,
                    "links": [x["link"] for x in c["items"][:3]],
                    "titles": [x["title"] for x in c["items"][:5]]})
    return sorted(out, key=lambda x: -x["n_sources"])


# ---------------- 辞書による判定 ----------------
def match_dictionary(title, dictionary):
    """辞書の行（語・分類・点・対象）のうち、見出しに含まれるものを返す。長い語が短い語を含む場合は長い方だけ。"""
    hit = [d for d in dictionary if d["keyword"] and d["keyword"] in title]
    keep = []
    for d in hit:
        if any(d["keyword"] != e["keyword"] and d["keyword"] in e["keyword"] for e in hit):
            continue
        keep.append(d)
    return keep


def _scope_ok(scope, asset):
    return scope == "all" or (scope == "gold" and asset == "gold") or (scope == "stock" and asset == "orukan")


def score_title(title, dictionary):
    hits = match_dictionary(title, dictionary)
    scores = {}
    for asset in ("orukan", "gold"):
        v = sum(int(d["score"]) for d in hits if _scope_ok(d["scope"], asset))
        scores[asset] = max(-2, min(2, v))
    cats = []
    for d in sorted(hits, key=lambda d: -abs(int(d["score"]))):
        if d["category"] not in cats:
            cats.append(d["category"])
    return {"matched": [d["keyword"] for d in hits], "categories": cats, "scores": scores}


def judge(clusters, dictionary):
    """話題ごとに判定し、資産ごとの合計を出す。戻り値: (話題のリスト, 合計, 未分類の話題)"""
    total = {"orukan": {"up": 0.0, "down": 0.0}, "gold": {"up": 0.0, "down": 0.0}}
    judged, unclassified = [], []
    for c in clusters:
        titles = c["titles"] or [c["title"]]
        # 同じ話題のどの見出しにも辞書を当て、最も強く当たったものを採用
        best = max((score_title(t, dictionary) for t in titles), key=lambda r: (len(r["matched"]), abs(r["scores"]["orukan"]) + abs(r["scores"]["gold"])))
        c = dict(c, **{"categories": best["categories"], "matched": best["matched"], "scores": best["scores"]})
        if not best["matched"]:
            unclassified.append(c)
        else:
            for a in ("orukan", "gold"):
                s = best["scores"][a] * c["weight"]
                total[a]["up" if s > 0 else "down"] += abs(s) if s != 0 else 0.0
        judged.append(c)
    return judged, total, unclassified


def news_layer_score(total_asset):
    """資産ひとつの合計（上昇側・下落側）を −2〜+2 の点にする。"""
    up, down = total_asset["up"], total_asset["down"]
    return round(2.0 * (up - down) / (up + down + 20.0), 2)      # 偏りの割合。材料が少ないと0に近づく


def candidate_keywords(title):
    """辞書追加の候補：見出しから取り出した語（漢字・カタカナ・英数字のまとまり）。"""
    words = re.findall(r"[一-龥々]{2,8}|[ァ-ヴー]{3,10}|[A-Za-z]{2,10}[0-9A-Za-z]*", title)
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:12]


def dict_rows_from_seed(seed):
    return [{"keyword": k, "category": c, "score": s, "scope": sc, "added": "初版"} for k, c, s, sc in seed]
