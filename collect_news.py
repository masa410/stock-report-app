"""毎日1回、ニュースの見出しを集めてシートへ貯める（GitHub Actions）。"""
import sys

import news as newsmod
import pipeline
import store_factory


def main(store=None):
    store = store or store_factory.get_store()
    items, problems = newsmod.fetch_all_headlines()
    n = pipeline.collect_headlines(store, items)
    print("見出し %d 件を取得、新しく %d 件を保存。失敗 %d 件" % (len(items), n, len(problems)))
    for p in problems:
        print("  注意:", p)
    return n


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("失敗:", type(e).__name__, e)
        sys.exit(1)
