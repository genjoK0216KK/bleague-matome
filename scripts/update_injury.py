#!/usr/bin/env python3
"""公式IL（インジュアリーリスト）だけを取得・保存する（ニュース取得とは独立）。

update.yml の既存の実行枠（JST 07/12/21/23時）の中で、ニュース取得より前に1回だけ動く。
新しいスケジュールは作らない。同じ回の後続工程（update_match_features）は --il-capture で
この回の取得結果を使い、IL を再取得しない。

- 成功：data/match_articles/injury.json と injury.html を更新し、原文を一時ファイル（capture）に保存。
- 失敗：前回の一覧は残し、状態を「失敗」、最新の確認日時とエラーの種類を記録。capture は作らない。
- 終了コードは常に 0（後続のニュース等を止めないため）。失敗は GITHUB_OUTPUT の il_status=failed で
  ワークフロー末尾の確認ステップに渡し、ジョブを失敗として報告する（成功扱いにしない）。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.dont_write_bytecode = True

from scripts import build, injury_page, official_data as official  # noqa: E402


def finalize(root, fn="injury.html"):
    """build.py の全ページ後処理のうち、このページ分だけ（ナビ・GA4・共通CSS）。"""
    old_root, old_data = build.ROOT, build.DATA_DIR
    build.ROOT, build.DATA_DIR = str(root), os.path.join(str(root), "data")
    try:
        cfg = build.site_config()
        path = Path(root) / fn
        text = path.read_text(encoding="utf-8")
        new = build.ensure_ga(build.ensure_nav(text, bool(cfg["x_list_url"]), fn), cfg["ga4_id"])
        if 'href="design-system.css?v=1"' not in new:
            new = new.replace("</head>", '<link rel="stylesheet" href="design-system.css?v=1">\n</head>', 1)
        if new != text:
            path.write_text(new, encoding="utf-8")
    finally:
        build.ROOT, build.DATA_DIR = old_root, old_data


def run(root, client, capture=None, now=None):
    root = Path(root)
    if capture and Path(capture).exists():
        Path(capture).unlink()                     # 前の回の原文を使わない
    error = injury_page.generate(client, root, root / "data/match_articles/injury.json",
                                 now or datetime.now(timezone.utc), capture=capture)
    finalize(root)
    state = json.loads((root / "data/match_articles/injury.json").read_text())
    return error, state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.path.dirname(HERE))
    parser.add_argument("--capture", help="成功時に原文を保存する一時ファイル（同じ回の後続工程用）")
    args = parser.parse_args()
    error, state = run(args.root, official.Client(max_requests=5, time_budget=120), args.capture)
    e = state.get("last_error") or {}
    if error:
        print(f"::warning::IL fetch failed category={e.get('category')} type={e.get('type')} "
              f"http={e.get('http_status')} url={e.get('url')} last_success={state.get('last_success_at')}; "
              "previous list retained and shown as unconfirmed", flush=True)
    else:
        print(f"::notice::IL fetched records={len(state.get('records', []))} at={state.get('last_success_at')}", flush=True)
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a") as handle:
            handle.write("il_status=" + ("failed" if error else "ok") + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
