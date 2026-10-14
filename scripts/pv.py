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
未設定・取得失敗は非ゼロ終了する。取得に失敗しても既存の pv.json は消さない。
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "pv.json")


def log(msg):
    print(f"[pv] {msg}", flush=True)


def normalize(path):
    """/article-x.html?utm=... → /article-x.html。トップは "/"。"""
    path = (path or "").split("?")[0].split("#")[0]
    return path if path.startswith("/") else "/" + path


def report(client, prop, start, end="yesterday"):
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
    response = client.run_report(req)
    if response.row_count > len(response.rows):
        raise ValueError("Incomplete report")
    for row in response.rows:
        path = normalize(row.dimension_values[0].value)
        if not re.fullmatch(r"/[\w\-]*\.html|/", path):
            continue
        out[path] = out.get(path, 0) + int(row.metric_values[0].value or 0)
    return dict(sorted(out.items(), key=lambda kv: -kv[1])), response.metadata.time_zone


def collect(client, prop, now=None):
    now = now or datetime.now(JST)
    total, zone = report(client, prop, "2015-08-14")
    day = now.astimezone(ZoneInfo(zone)).date()
    start, end = (day-timedelta(days=7)).isoformat(), (day-timedelta(days=1)).isoformat()
    week, week_zone = report(client, prop, start, end)
    if zone != week_zone:
        raise ValueError("Property timezone changed")
    return {"status":"success", "updated":now.isoformat(), "timezone":zone,
            "period":{"start":start,"end":end}, "total_through":end,
            "total":total,"week":week}


def save(client, prop, now=None):
    # Only replace the previous complete snapshot after both reports succeed.
    data = collect(client, prop, now)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    temporary = OUT + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(temporary, OUT)
    log(f"wrote data/pv.json（累計 {len(data['total'])}ページ / 週間 {len(data['week'])}ページ）")


def main():
    prop = (os.environ.get("GA4_PROPERTY_ID") or "").strip()
    key = (os.environ.get("GA4_SA_KEY") or "").strip()
    if not prop or not key:
        log("GA4設定が不足しています。取得未実行")
        return 1
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(
            json.loads(key), scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        save(BetaAnalyticsDataClient(credentials=creds), prop)
    except Exception:
        # Provider exception strings can include credential/request details.
        log("取得失敗。既存PVを保持しました。設定・権限・API状態を確認してください")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
