#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
バスケまとめ - 記事ごとの閲覧数（PV）を GA4 Data API から取得する

出力:
  data/pv.json … {"updated": "...", "total": {"/article-xxx.html": 123, ...},
                  "week": {"/article-xxx.html": 45, ...}}
  total は計測開始からの累計、week は直近7日。build.py が記事の pmeta に
  「◯◯ views」を、トップのサイドバーに週間人気ランキングを表示する。

必要な環境変数（GitHub Secrets から渡す）:
  GA4_PROPERTY_ID   … GA4 のプロパティID（数字のみ。測定ID G-XXXX とは別）
  GA4_SA_KEY        … サービスアカウントの鍵（JSON の中身そのもの）
どちらかが無ければ何もせず正常終了する。取得に失敗しても既存の pv.json は消さない。
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


def report(client, prop, start):
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest)
    req = RunReportRequest(
        property=f"properties/{prop}",
        dimensions=[Dimension(name="pagePath")],
        metrics=[Metric(name="screenPageViews")],
        date_ranges=[DateRange(start_date=start, end_date="today")],
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
        log("GA4_PROPERTY_ID / GA4_SA_KEY が未設定のため何もしません")
        return 0
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(
            json.loads(key),
            scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        client = BetaAnalyticsDataClient(credentials=creds)
        total = report(client, prop, "2015-08-14")
        week = report(client, prop, "7daysAgo")
    except Exception as e:  # noqa: BLE001
        log(f"!! 取得に失敗しました（既存の pv.json を維持）: {e}")
        return 0
    data = {
        "updated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "total": total,
        "week": week,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    log(f"wrote data/pv.json（累計 {len(total)}ページ / 週間 {len(week)}ページ）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
