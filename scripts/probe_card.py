#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B.LEAGUE CARD（card.bleaguepark.jp）のAPIエンドポイントを洗い出す調査用スクリプト（何も保存しない）。"""

import re
import time
from urllib.parse import urljoin

import requests

UA = ("Mozilla/5.0 (compatible; BleagueMatomeBot/1.0; "
      "+https://genjok0216kk.github.io/bleague-matome/about.html)")
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8",
           "Origin": "https://card.bleaguepark.jp", "Referer": "https://card.bleaguepark.jp/"}
BASE = "https://card.bleaguepark.jp/"
API = "https://api-card.bleaguepark.jp/jpbl"
KW = re.compile(r"fantasy|score|point|stat|player|ranking|game|eff|contribution|match|arena",
                re.I)


def get(url, quiet=False):
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        time.sleep(1.5)
        if not quiet:
            print(f"GET {url} -> {r.status_code} {r.headers.get('content-type')} len={len(r.content)}",
                  flush=True)
        return r
    except Exception as e:  # noqa: BLE001
        print(f"!! {url}: {e}")
        return None


def main():
    print("\n########## CARD PROBE2 START ##########", flush=True)
    top = get(BASE).text
    chunks = sorted(set(re.findall(r'(/_nuxt/[\w.\-]+\.js)', top)))
    print("chunks:", len(chunks))
    paths = {}
    for c in chunks:
        r = get(urljoin(BASE, c), quiet=True)
        if not r or r.status_code != 200:
            continue
        js = r.text
        for m in re.findall(r"[\"'`](/[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-${}.:]+)*)[\"'`]", js):
            if KW.search(m) and not m.startswith("/_nuxt") and len(m) < 90:
                paths.setdefault(m, set()).add(c.split("/")[-1])
    print(f"endpoint-like paths ({len(paths)}):")
    for p in sorted(paths):
        print("  ", p, sorted(paths[p])[:3])

    # 公開APIとして叩けるか試す（GETのみ・パラメータなし）
    tried = 0
    for p in sorted(paths):
        if "$" in p or "{" in p or ":" in p or tried >= 40:
            continue
        r = get(API + p)
        tried += 1
        if r is not None:
            print("    body:", r.text[:300].replace("\n", " "))
    print("########## CARD PROBE2 END ##########", flush=True)


if __name__ == "__main__":
    main()
