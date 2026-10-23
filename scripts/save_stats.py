#!/usr/bin/env python3
"""貢献度ランキング（stats）をニュース取得の成否と無関係に集計し、その成果物だけを保存・公開する。

update.yml の終盤で毎回実行する（ニュース取得・試合記事・HTML生成が失敗した回も）。
1. 失敗した工程の途中の生成物（未コミットの変更）は先に退避し、公開しない。集計にも使わない
   （集計の入力は、コミット済みの保存結果 data/match_articles/article-games-*.json だけ）。
2. stats.run_reported() で集計（公式への追加取得なし）。
3. stats の成果物だけをコミットして公開する。変化が無ければ何もしない。
全工程が成功した回は、通常のコミットに stats も含まれているので、ここでは差分が出ず何もしない。
"""
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from pathlib import Path

try:
    from . import publish_update, stats
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.dont_write_bytecode = True
    import publish_update  # noqa: E402
    import stats  # noqa: E402

PATHS = ["stats.html", "data/stats", "article-stats-*.html", "thumb-stats-*.svg"]


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def save(publish=True, now=None, root="."):
    """戻り値：'saved' / 'nothing'。公開に失敗したら例外。"""
    if git("status", "--porcelain").stdout.strip():
        git("stash", "push", "--include-untracked", "-m", "failed-run outputs (not published, not used for stats)")
    report = stats.run_reported(now, root)
    if "error" in report:
        raise RuntimeError("貢献度ランキングの集計に失敗: " + report["error"])
    paths = [p for p in PATHS if list(Path(root).glob(p))]   # 一致しない指定は git add がエラーにする
    if not paths:
        print("[save_stats] 貢献度ランキングの成果物がありません（何もしません）", flush=True)
        return "nothing"
    git("add", "--", *paths)
    if git("diff", "--cached", "--quiet", "--", *paths, check=False).returncode == 0:
        print("[save_stats] 貢献度ランキングは保存済み・変更なし（何もしません）", flush=True)
        return "nothing"
    stamp = (now or datetime.now(timezone(timedelta(hours=9)))).strftime("%Y-%m-%d %H:%M")
    git("commit", "-m", "貢献度ランキングのみ保存: " + stamp, "--only", "--", *paths)
    if publish:
        publish_update.publish()
    print("[save_stats] 保存：" + ", ".join(sorted(report)), flush=True)
    return "saved"


if __name__ == "__main__":
    try:
        save()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print("::error::貢献度ランキングの保存に失敗しました: " + (str(exc) if isinstance(exc, RuntimeError) else "git 操作の失敗"))
        sys.exit(1)
