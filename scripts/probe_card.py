#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""card.bleaguepark.jp の公開ページ・APIの構造をログに出す調査用スクリプト（何も保存しない）。"""

import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (compatible; BleagueMatomeBot/1.0; "
      "+https://genjok0216kk.github.io/bleague-matome/about.html)")
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
BASE = "https://card.bleaguepark.jp/"


def get(url):
    print(f"\n===== CARD GET {url}", flush=True)
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        print(f"status={r.status_code} final={r.url} type={r.headers.get('content-type')} len={len(r.content)}")
        time.sleep(2)
        r.encoding = r.apparent_encoding or r.encoding
        return r.text
    except Exception as e:  # noqa: BLE001
        print(f"!! {e}")
        return ""


def main():
    print("\n########## CARD PROBE START ##########", flush=True)
    top = get(BASE)
    print("HEAD:", top[:1500].replace("\n", " "))
    soup = BeautifulSoup(top, "html.parser")
    print("title:", soup.title.get_text(strip=True) if soup.title else None)
    links = sorted({urljoin(BASE, a["href"]) for a in soup.find_all("a", href=True)})
    print(f"links ({len(links)}):")
    for h in links[:60]:
        print("   ", h)
    srcs = [urljoin(BASE, s["src"]) for s in soup.find_all("script", src=True)]
    print("scripts:", srcs[:20])
    for kw in ["api", "fantasy", "FANTASY", "point", "score", "ranking", "__NEXT_DATA__", "__NUXT__"]:
        i = top.find(kw)
        print(f"kw {kw!r}:", repr(top[max(0, i-100):i+200]) if i >= 0 else None)

    # JSバンドル内のAPIパスを洗い出す
    apis = set()
    for src in srcs[:8]:
        if "bleaguepark" not in src and not src.startswith(BASE):
            continue
        js = get(src)
        for m in re.findall(r"[\"'`](/?(?:api|v\d)/[A-Za-z0-9_\-/{}.$]+)[\"'`]", js):
            apis.add(m)
        for m in re.findall(r"https://[a-z0-9.\-]*bleaguepark\.jp[A-Za-z0-9_\-/.]*", js):
            apis.add(m)
    print("API candidates:", sorted(apis)[:120])

    for path in ["robots.txt", "fantasy", "ranking", "player", "news", "faq", "help"]:
        body = get(urljoin(BASE, path))
        print("   head:", body[:300].replace("\n", " "))
    print("########## CARD PROBE END ##########", flush=True)


if __name__ == "__main__":
    main()
