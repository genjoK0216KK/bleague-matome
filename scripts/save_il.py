#!/usr/bin/env python3
"""公式ILの2つの成果（injury.html と data/match_articles/injury.json）だけを保存・公開する。

update.yml の最後で、IL の工程が動いた回は必ず実行する（後の工程＝ニュース・試合記事・HTML生成・
記事一覧の補完が失敗した回も）。IL の取得に成功した一覧も、失敗した時の「未確認」の記録も同じく保存する。
ほかの工程の成果物は含めない（失敗した回の途中の生成物は公開しない＝従来どおり）。
全工程が成功した回は、通常のコミットに IL も含まれているので何もしない。
"""
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

import publish_update  # noqa: E402

FILES = ["injury.html", "data/match_articles/injury.json"]


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def save(publish=True, now=None):
    """戻り値：'saved' / 'nothing'。公開に失敗したら例外。"""
    present = [f for f in FILES if Path(f).exists()]
    if not present:
        print("[save_il] IL の成果物がありません（何もしません）", flush=True)
        return "nothing"
    git("add", "--", *present)
    if git("diff", "--cached", "--quiet", "--", *present, check=False).returncode == 0:
        print("[save_il] IL は保存済み・変更なし（何もしません）", flush=True)
        return "nothing"
    stamp = (now or datetime.now(timezone(timedelta(hours=9)))).strftime("%Y-%m-%d %H:%M")
    # 指定した2ファイルだけをコミットする（ほかにステージ済みの変更があっても含めない）
    git("commit", "-m", "公式ILのみ保存: " + stamp, "--only", "--", *present)
    # 失敗した回の途中の生成物は公開しない。公開前の rebase のため、作業ツリーから退避する
    if git("status", "--porcelain").stdout.strip():
        git("stash", "push", "--include-untracked", "-m", "failed-run outputs (not published)")
    if publish:
        publish_update.publish()
    print("[save_il] 保存：" + "、".join(present), flush=True)
    return "saved"


if __name__ == "__main__":
    try:
        save()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print("::error::公式ILの保存に失敗しました: " + (str(exc) if isinstance(exc, RuntimeError) else "git 操作の失敗"))
        sys.exit(1)
