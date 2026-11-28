"""メール通知：大きな動き（前日比）と、最高値の更新。同じ内容を二重には送らない。

送信には、メール送信用の合鍵（Gmailの「アプリパスワード」）が要る。GitHub Actionsの Secrets に
NOTIFY_SMTP_USER（Gmailのアドレス）と NOTIFY_SMTP_PASSWORD（アプリパスワード）を入れる。未設定なら、送らずに、何もしない。
通知先は、設定シートの「通知先メール」（空欄なら、環境変数 NOTIFY_TO）。
"""
import os
import smtplib
from email.mime.text import MIMEText

import config
import store as st


def _labels():
    return {"orukan": "オルカン", "gold": "ゴールド"}


def detect(market, now, threshold, notify_high=True):
    """通知する出来事の一覧。直近の営業日（取得日から5日以内）だけを見る。"""
    out = []
    for asset, label in _labels().items():
        s = market[asset].dropna()
        if len(s) < 3 or (now.date() - s.index[-1].date()).days > 5:
            continue
        d = str(s.index[-1].date())
        chg = (float(s.iloc[-1]) / float(s.iloc[-2]) - 1.0) * 100
        if abs(chg) >= threshold:
            out.append({"key": "move|%s|%s" % (asset, d), "kind": "大きな動き", "target": label,
                        "content": "%s %s 前日比 %+.1f%%" % (label, d, chg), "subject": "【株価】%s が前日比 %+.1f%%" % (label, chg)})
        if notify_high:
            prior = s.iloc[:-1]
            last = float(s.iloc[-1])
            if last > float(prior.max()):
                out.append({"key": "ath|%s|%s" % (asset, d), "kind": "最高値の更新", "target": label,
                            "content": "%s が過去最高値を更新（%s）" % (label, d), "subject": "【株価】%s が過去最高値を更新" % label})
            else:
                ytd = prior[prior.index.year == s.index[-1].year]
                if len(ytd) and last > float(ytd.max()):
                    out.append({"key": "ytd|%s|%s" % (asset, d), "kind": "年初来高値の更新", "target": label,
                                "content": "%s が年初来高値を更新（%s）" % (label, d), "subject": "【株価】%s が年初来高値を更新" % label})
    return out


def smtp_send(subject, body, to):
    """Gmail（SSL）で送る。合鍵が未設定なら False。"""
    user = os.environ.get("NOTIFY_SMTP_USER")
    pw = os.environ.get("NOTIFY_SMTP_PASSWORD")
    if not user or not pw or not to:
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())
    return True


def check_and_send(store, market, now, sender=None):
    """戻り値: 送った（または送ろうとした）出来事のリスト。sender(subject, body, to) は試験用に差し替えられる。"""
    settings = st.get_settings(store)
    if settings.get("通知を送る", "はい") != "はい":
        return []
    to = (settings.get("通知先メール") or os.environ.get("NOTIFY_TO") or "").strip()
    if not to:
        return []
    try:
        thr = float(settings.get("大きな動きの目安（前日比 ±%）") or 3)
    except ValueError:
        thr = 3.0
    events = detect(market, now, thr, settings.get("最高値の更新を通知", "はい") == "はい")
    done = {r["key"] for r in store.read(config.SH_NOTIFY)}
    sender = sender or smtp_send
    sent = []
    for e in events:
        if e["key"] in done:
            continue
        try:
            ok = sender(e["subject"], e["content"] + "\n\n（週次株価レポートアプリからの自動通知です）", to)
        except Exception as ex:  # noqa: BLE001
            ok, err = False, type(ex).__name__
        else:
            err = ""
        if not ok and not err:
            continue                         # 合鍵が未設定：記録せず、あとで設定すれば、その日のうちは送れる
        store.append(config.SH_NOTIFY, [{"at": str(now), "kind": e["kind"], "target": e["target"], "content": e["content"],
                                         "to": to, "result": "送信済み" if ok else "失敗：" + err, "key": e["key"]}])
        sent.append(e)
    return sent
