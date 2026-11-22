"""PCへの保存：クラウドの最終版レポートから、まだ置いていない週のWordを C:\\株価分析\\年\\月月\\ に作る。
使い方: python sync_pc.py [保存先のフォルダ]   （run_app.bat から呼ばれる）"""
import datetime as dt
import os
import sys

import config
import docx_report
import store as st

DEFAULT_ROOT = r"C:\株価分析"


def target_path(root, week):
    d = dt.date.fromisoformat(week)
    return os.path.join(root, str(d.year), "%d月" % d.month, "週報_%s.docx" % week)


def sync(store, root=DEFAULT_ROOT):
    """戻り値: (作った数, 更新した数, 開いていて飛ばした数)"""
    made = updated = skipped = 0
    for week, mode, generated_at, report in st.load_reports(store):
        if mode != "最終":
            continue
        path = target_path(root, week)
        exists = os.path.exists(path)
        if exists:
            gen = dt.datetime.fromisoformat(generated_at)
            if dt.datetime.fromtimestamp(os.path.getmtime(path)) >= gen:
                continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        try:
            docx_report.build_docx(report, tmp)
            os.replace(tmp, path)
        except PermissionError:
            skipped += 1                                   # Wordで開いているファイルは、触らずに飛ばす
            if os.path.exists(tmp):
                os.remove(tmp)
            continue
        if exists:
            updated += 1
        else:
            made += 1
    return made, updated, skipped


def main():
    import store_factory
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT
    made, updated, skipped = sync(store_factory.get_store(), root)
    print("Wordを作成 %d 件、更新 %d 件、開いていて飛ばした %d 件（保存先 %s）" % (made, updated, skipped, root))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("同期できませんでした:", type(e).__name__, e)
        sys.exit(1)
