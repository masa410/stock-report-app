"""毎週土曜9時（GitHub Actions）と、アプリのボタンから呼ばれる入口。"""
import sys

import datasrc
import news as newsmod
import pipeline
import report as rpt
import store_factory


def main(store=None, today=None):
    store = store or store_factory.get_store()
    now = rpt.now_jst()
    today = today or now.date()
    market, problems = datasrc.load_market()
    items, nprob = newsmod.fetch_all_headlines()
    problems = list(problems) + list(nprob)
    pipeline.collect_headlines(store, items, now)
    report = pipeline.run_report(store, market, today, items, problems, now=now)
    print("作成しました: %s（%s）／取得できなかった項目 %d 件" % (report["report_date"], report["mode"], len(problems)))
    for p in problems:
        print("  注意:", p)
    return report


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("失敗:", type(e).__name__, e)
        sys.exit(1)
