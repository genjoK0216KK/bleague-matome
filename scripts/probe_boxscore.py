#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bleague.jp の試合ページに埋め込まれたJSONの構造をログに出す調査用スクリプト（何も保存しない）。"""

import json
import re
import time

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (compatible; BleagueMatomeBot/1.0; "
      "+https://genjok0216kk.github.io/bleague-matome/about.html)")
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}


def get(url):
    print(f"\n===== PROBE GET {url}", flush=True)
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.encoding = r.apparent_encoding or r.encoding
    print(f"status={r.status_code} len={len(r.text)}")
    time.sleep(2)
    return r.text


def shape(obj, depth=0, maxdepth=3):
    pad = "  " * depth
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:80]:
            if isinstance(v, (dict, list)) and depth < maxdepth:
                n = len(v)
                print(f"{pad}{k}: {type(v).__name__}({n})")
                shape(v, depth + 1, maxdepth)
            else:
                print(f"{pad}{k}: {str(v)[:60]!r}")
    elif isinstance(obj, list) and obj:
        print(f"{pad}[0] of {len(obj)}:")
        shape(obj[0], depth + 1, maxdepth)


def main():
    print("\n########## PROBE2 START ##########", flush=True)
    sched = get("https://www.bleague.jp/schedule/")
    soup = BeautifulSoup(sched, "html.parser")
    for a in soup.find_all("a", href=re.compile(r"ScheduleKey=\d+&tab=2"))[:6]:
        box = a.find_parent(["li", "div"]) or a
        print("GAMECARD:", a["href"], "|", box.get_text(" ", strip=True)[:220])
    m = re.search(r"schedule_contexts\s*=\s*(\{.*?\});", sched, re.S)
    print("schedule_contexts:", (m.group(1)[:300] if m else None))

    keys = sorted(set(re.findall(r"ScheduleKey=(\d+)&", sched)))
    print("keys:", keys)
    html = get(f"https://www.bleague.jp/game_detail/?ScheduleKey={keys[0]}&tab=4")
    for s in BeautifulSoup(html, "html.parser").find_all("script"):
        txt = s.string or s.get_text() or ""
        if '"EFF"' not in txt:
            continue
        print("SCRIPT with EFF, head:", txt[:200].replace("\n", " "))
        for m in re.finditer(r"([\w.\[\]'\"]+)\s*=\s*(\{|\[)", txt):
            start = m.start(2)
            try:
                obj, end = json.JSONDecoder().raw_decode(txt[start:])
            except ValueError as e:
                print("  var", m.group(1), "not json:", e)
                continue
            print(f"  VAR {m.group(1)} -> {type(obj).__name__}, len={end}")
            shape(obj)
            # 選手行を探して全キーと値を1件出す
            stack = [obj]
            shown = 0
            while stack and shown < 2:
                cur = stack.pop()
                if isinstance(cur, dict):
                    if "EFF" in cur and "PlayerNameJ" in cur:
                        print("  PLAYER ROW:", json.dumps(cur, ensure_ascii=False)[:1500])
                        shown += 1
                    stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
                elif isinstance(cur, list):
                    stack.extend(cur)
        break
    for kw in ["GameStatus", "Status", "Finish", "試合終了", "FINAL", "Nationality", "Country",
               "Foreign", "Naturalized", "帰化", "アジア", "PlayerType", "IsJapanese"]:
        i = html.find(kw)
        print(f"kw {kw!r}:", (repr(html[max(0, i-120):i+160]) if i >= 0 else None))
    print("########## PROBE2 END ##########", flush=True)


if __name__ == "__main__":
    main()
