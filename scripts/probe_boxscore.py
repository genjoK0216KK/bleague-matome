#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bleague.jp の日程・ボックススコアのページ構造をログに出す調査用スクリプト（何も保存しない）。"""

import re
import time

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (compatible; BleagueMatomeBot/1.0; "
      "+https://genjok0216kk.github.io/bleague-matome/about.html)")
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}


def get(url):
    print(f"\n===== PROBE GET {url}", flush=True)
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.encoding = r.apparent_encoding or r.encoding
        print(f"status={r.status_code} final={r.url} len={len(r.text)}")
        time.sleep(2)
        return r.text
    except Exception as e:  # noqa: BLE001
        print(f"!! {e}")
        return ""


def describe(html, label):
    soup = BeautifulSoup(html, "html.parser")
    print(f"--- [{label}] title: {soup.title.get_text(strip=True) if soup.title else ''}")
    hrefs = sorted({a["href"] for a in soup.find_all("a", href=True)
                    if re.search(r"game|schedule|ScheduleKey|box", a["href"], re.I)})
    print(f"--- [{label}] game-ish links ({len(hrefs)}):")
    for h in hrefs[:40]:
        print("   ", h)
    tables = soup.find_all("table")
    print(f"--- [{label}] tables: {len(tables)}")
    for i, t in enumerate(tables[:6]):
        rows = t.find_all("tr")
        print(f"   table#{i} rows={len(rows)} class={t.get('class')}")
        for tr in rows[:3]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            print("      ", cells[:26])
    for kw in ["EFF", "貢献度", "ScheduleKey", "boxscore", "BoxScore", "PlayerName",
               "__NEXT_DATA__", "window.__", "api"]:
        idx = html.find(kw)
        if idx >= 0:
            print(f"--- [{label}] '{kw}' at {idx}: {html[max(0, idx-150):idx+300]!r}")
    for s in soup.find_all("script", src=True)[:15]:
        print("    script src:", s["src"])
    return soup


def main():
    print("\n########## PROBE START ##########", flush=True)
    sched = get("https://www.bleague.jp/schedule/")
    soup = describe(sched, "schedule")
    for f in soup.find_all("form")[:3]:
        print("   form action:", f.get("action"),
              [(s.get("name"), [o.get("value") for o in s.find_all("option")][:12])
               for s in f.find_all("select")])

    keys = re.findall(r"ScheduleKey=(\d+)", sched)
    print("ScheduleKeys found:", keys[:20])
    if keys:
        key = keys[0]
        for tab in ("", "&tab=4", "&tab=2"):
            html = get(f"https://www.bleague.jp/game_detail/?ScheduleKey={key}{tab}")
            describe(html, f"game {key}{tab}")
    print("########## PROBE END ##########", flush=True)


if __name__ == "__main__":
    main()
