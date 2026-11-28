"""毎日（朝7:13・夕18:13ごろ）、GitHub Actionsから呼ばれる入口。価格・ニュースを取り、暫定版を更新する。"""
import sys

import datasrc
import news as newsmod
import pipeline
import report as rpt
import store_factory


def main(store=None, now=None):
    store = store or store_factory.get_store()
    now = now or rpt.now_jst()
    market, problems = datasrc.load_market()
    items, nprob = newsmod.fetch_all_headlines()
    problems = list(problems) + list(nprob)
    out = pipeline.run_daily(store, market, now, items, problems)
    print("見出し %d 件を取得、新しく %d 件を保存。%s。通知 %d 件。取得できなかった項目 %d 件" % (
        len(items), out["added"], "暫定版を更新しました" if out["report"] else "見出しだけ集めました（土曜9:23以降・日曜）",
        len(out["alerts"]), len(problems)))
    for p in problems:
        print("  注意:", p)
    return out


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("失敗:", type(e).__name__, e)
        sys.exit(1)
