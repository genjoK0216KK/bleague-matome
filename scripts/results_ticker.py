#!/usr/bin/env python3
"""試合終了の見張り役：試合が終わる頃から5分ごとに当日結果の更新（results.yml）を起動する。

GitHub Actions の定期実行（cron）は混雑時に数時間遅れたり飛ばされたりする
（実測：15分ごとの予定が1日2回ほど・22時半以降しか動かない日が続いた）。そこで結果更新
そのものは手動起動（workflow_dispatch。定期実行のような遅延がない）で呼ぶ。

- 公式サイトへはこのスクリプトから一切アクセスしない。GitHub上の保存データ
  （data/match_articles/article-games-YYYYMMDD.json）を読んで判断するだけ。
- 結果更新は従来どおり site-update の順番待ちに並ぶ。順番待ちは2件目が来ると古い待ちを
  取り消すため、同じ列（通常更新・閲覧数・結果更新）が動いている／待っている間は起動しない。
- 当日（と前日）の全試合が確定し、EFF TOP3まで揃ったら終了する。
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_results  # noqa: E402
from preview_data import is_verified_final  # noqa: E402

JST = timezone(timedelta(hours=9))
FINISH_AFTER = timedelta(minutes=100)   # 開始からこれだけ経てば終了している可能性がある
TICK = 300                              # 5分ごとに確認
STALE_AFTER = timedelta(hours=3)        # 終了見込みから3時間過ぎた未確定は30分ごとに間引く
STALE_INTERVAL = timedelta(minutes=30)
RUN_LIMIT = timedelta(minutes=345)      # ジョブ上限（355分）の手前で終える
SITE_UPDATE = ("results.yml", "update.yml", "pv.yml")   # site-update の列に並ぶ処理
BUSY = ("queued", "in_progress", "waiting", "pending", "requested")


def log(msg):
    print(f"[ticker {datetime.now(JST):%H:%M:%S}] {msg}", flush=True)


def starts_at(game):
    try:
        return datetime.fromisoformat(game.get("starts_at") or "")
    except ValueError:
        return None


def open_games(saved):
    """中止・延期を除き、公式記録の確定がまだの試合。"""
    return [g for g in saved.get("games", [])
            if g.get("status") not in ("cancelled", "postponed") and not is_verified_final(g)]


def need(saved, now):
    """(更新が必要になった時刻, 理由)。不要なら (None, None)。理由ごとに間引き方が違う。
      games    : 未確定の試合が終了見込みを過ぎた（due＝最も新しい過去の終了見込み）
      rankings : 全試合確定でTOP3だけ未作成（due＝その日の最後の試合の終了見込み。古ければ間引く）
      missing  : 保存データが無い日（試合なしの日も公式取得の結果を保存しないため、毎回確認すると繰り返す）
      unknown  : 開始時刻が読めない未確定試合がある
    """
    if saved is None:
        return now, "missing"
    if update_results.done(saved):
        return None, None
    games = open_games(saved)
    if not games:
        ends = [s + FINISH_AFTER for s in map(starts_at, saved.get("games", [])) if s is not None]
        past = [e for e in ends if e <= now]
        return (max(past) if past else now), "rankings"
    ends = [s + FINISH_AFTER for s in map(starts_at, games) if s is not None]
    past = [e for e in ends if e <= now]
    if past:
        return max(past), "games"
    if len(ends) < len(games):
        return now, "unknown"
    return None, None             # まだどの試合も終わっていない


def due_since(saved, now):
    """need() の時刻だけ（互換用）。"""
    return need(saved, now)[0]


def should_dispatch(due, now, last_dispatch, kind="games"):
    """last_dispatch はその日付に対して最後に起動した時刻（日付ごとに持つ）。"""
    if due is None:
        return False
    recent = last_dispatch is not None and now - last_dispatch < STALE_INTERVAL
    if kind in ("missing", "unknown"):
        return not recent     # 初回は起動、以後は30分ごと（試合なしの日に5分ごと繰り返さない）
    if now - due > STALE_AFTER and recent:
        return False          # 終了見込みから時間が経っても未確定・TOP3待ち。公式への負荷を抑える
    return True


def should_stop(now, started):
    """見張りを終える時刻か。外部起動の前に判定する（終了時刻の直前・遅延起動で1回余計に起動しない）。"""
    return 2 <= now.hour < 12 or now - started >= RUN_LIMIT


def load(date):
    path = "data/match_articles/" + update_results.day_articles.filename(date.isoformat()).replace(".html", ".json")
    out = subprocess.run(["git", "show", f"FETCH_HEAD:{path}"], text=True, capture_output=True)
    if out.returncode:
        return None
    try:
        return json.loads(out.stdout)
    except ValueError:
        return None


def site_update_busy():
    for wf in SITE_UPDATE:
        out = subprocess.run(["gh", "run", "list", "--workflow", wf, "--limit", "5", "--json", "status"],
                             text=True, capture_output=True)
        if out.returncode:
            log(f"{wf} の状態を取得できないため今回は起動しない: {out.stderr.strip()[:200]}")
            return True
        if any(r.get("status") in BUSY for r in json.loads(out.stdout or "[]")):
            return True
    return False


def dispatch():
    out = subprocess.run(["gh", "workflow", "run", "results.yml", "--ref", "main"], text=True, capture_output=True)
    if out.returncode:
        log(f"結果更新の起動に失敗: {out.stderr.strip()[:200]}")
        return False
    log("結果更新（results.yml）を起動")
    return True


def main():
    started = datetime.now(JST)
    last_by_date = {}             # 日付 → 最後に結果更新を起動した時刻
    while True:
        now = datetime.now(JST)
        if should_stop(now, started):
            log("見張りの時間帯を終了")
            return 0
        subprocess.run(["git", "fetch", "-q", "--depth=1", "origin", "main"], check=False)
        today, yesterday = now.date(), now.date() - timedelta(days=1)
        saved_today, saved_yday = load(today), load(yesterday)
        if (saved_today is not None and update_results.done(saved_today)
                and (saved_yday is None or update_results.done(saved_yday))):
            log("当日・前日とも全試合確定・TOP3作成済み。終了")
            return 0
        wanted = []
        for date, saved in ((today, saved_today), (yesterday, saved_yday)):
            if saved is None and date == yesterday:
                continue          # 前日の保存データが無い＝試合なし（前日分は取りに行かない）
            due, kind = need(saved, now)
            if should_dispatch(due, now, last_by_date.get(date), kind):
                wanted.append((date, kind))
        if wanted:
            if site_update_busy():
                log("同じ順番待ちの処理が動作中・待機中のため今回は起動しない")
            elif dispatch():
                for date, kind in wanted:
                    last_by_date[date] = now
                log("対象: " + ", ".join(f"{d}({k})" for d, k in wanted))
        else:
            log("まだ更新の必要なし（試合中・試合前、または間引き中）")
        if should_stop(now + timedelta(seconds=TICK), started):
            log("見張りの時間帯を終了")
            return 0
        time.sleep(TICK)


if __name__ == "__main__":
    raise SystemExit(main())
