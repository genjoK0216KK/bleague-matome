#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
バスケまとめ - 記事ごとの閲覧数（PV）を GA4 Data API から取得する

出力:
  data/pv.json … {"updated": "...", "week_start": "YYYY-MM-DD", "week_end": "YYYY-MM-DD",
                  "total": {"/article-xxx.html": 123, ...}, "week": {"/article-xxx.html": 45, ...}}
  total は計測開始から昨日までの累計、week は week_start〜week_end（昨日までの7日間）。build.py が記事の pmeta に
  「◯◯ views」を、トップのサイドバーに週間人気ランキングを表示する。

必要な環境変数（GitHub Secrets から渡す）:
  GA4_PROPERTY_ID   … GA4 のプロパティID（数字のみ。測定ID G-XXXX とは別）
  GA4_SA_KEY        … サービスアカウントの鍵（JSON の中身そのもの）
終了コード:
  0 … 取得して pv.json を更新した
  2 … キーが未設定のため何もしなかった（スキップ。成功とは区別する）
  1 … API 呼び出しなどに失敗した（既存の pv.json は消さずに残す）
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "pv.json")


def log(msg):
    print(f"[pv] {msg}", flush=True)


def normalize(path):
    """/article-x.html?utm=... → /article-x.html。トップは "/"。"""
    path = (path or "").split("?")[0].split("#")[0]
    return path if path.startswith("/") else "/" + path


def report(client, prop, start, end):
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest)
    req = RunReportRequest(
        property=f"properties/{prop}",
        dimensions=[Dimension(name="pagePath")],
        metrics=[Metric(name="screenPageViews")],
        date_ranges=[DateRange(start_date=start, end_date=end)],
        limit=100000,
    )
    out = {}
    for row in client.run_report(req).rows:
        path = normalize(row.dimension_values[0].value)
        if not re.fullmatch(r"/[\w\-]*\.html|/", path):
            continue
        out[path] = out.get(path, 0) + int(row.metric_values[0].value or 0)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main():
    prop = (os.environ.get("GA4_PROPERTY_ID") or "").strip()
    key = (os.environ.get("GA4_SA_KEY") or "").strip()
    if not prop or not key:
        log("スキップ: GA4_PROPERTY_ID / GA4_SA_KEY が未設定です")
        return 2
    today = datetime.now(JST).date()
    week_end = today - timedelta(days=1)          # 昨日まで（集計が確定している日）
    week_start = week_end - timedelta(days=6)     # 7日間
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(
            json.loads(key),
            scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        client = BetaAnalyticsDataClient(credentials=creds)
        total = report(client, prop, "2015-08-14", week_end.isoformat())
        week = report(client, prop, week_start.isoformat(), week_end.isoformat())
    except Exception as e:  # noqa: BLE001
        log(f"!! 失敗: GA4 からの取得に失敗しました（既存の pv.json は維持）: {e}")
        return 1
    data = {
        "updated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total": total,
        "week": week,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    log(f"成功: data/pv.json を更新（累計 {len(total)}ページ / 週間 {len(week)}ページ、"
        f"{week_start}〜{week_end}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
