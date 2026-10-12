#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
バスケまとめ - 新しい記事を「バスケまとめ」の X アカウントに自動投稿する

  - main に追加された article-*.html のうち、まだ投稿していないものをポストする。
  - 本文: タイトル＋要点1行（meta description の最初の一文）＋記事URL＋ハッシュタグ2〜3個。
  - 二重投稿しないよう、投稿済みの記事を data/posted.json に記録する。
  - 1日の投稿上限は DAILY_LIMIT 件。投稿するのは直近 MAX_AGE_DAYS 日以内の記事だけ。
  - data/posted.json が無い初回は、既存記事をすべて「投稿済み」として記録するだけで投稿しない。

必要な環境変数（GitHub Secrets）:
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
どれかが無ければ何もせず正常終了する。
"""

import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True

import build  # noqa: E402  記事の読み取りを共通化

JST = timezone(timedelta(hours=9))
POSTED_PATH = os.path.join(ROOT, "data", "posted.json")
SITE_URL = build.SITE_URL
DAILY_LIMIT = 6          # 1日5本＋貢献度ランキング
MAX_AGE_DAYS = 3
URL_WEIGHT = 23          # X は URL を一律 23 文字として数える
MAX_WEIGHT = 280
TWEET_URL = "https://api.x.com/2/tweets"
ENV_KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")


def log(msg):
    print(f"[post_x] {msg}", flush=True)


# ------------------------------------------------------------ text length

def char_weight(ch):
    """X の文字数カウント（CJK などは2、ラテン文字などは1）。"""
    cp = ord(ch)
    if (cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F
            or 0x2032 <= cp <= 0x2037):
        return 1
    return 2


def weight(text):
    return sum(char_weight(c) for c in text)


def clip(text, limit):
    """重み付き文字数が limit 以下になるよう末尾を「…」で切る。"""
    if weight(text) <= limit:
        return text
    out = ""
    for c in text:
        if weight(out + c) + 2 > limit:
            break
        out += c
    return out.rstrip() + "…"


# ---------------------------------------------------------------- content

def load_teams():
    try:
        with open(os.path.join(HERE, "team_colors.json"), encoding="utf-8") as f:
            return json.load(f).get("clubs", [])
    except (OSError, ValueError):
        return []


def hashtags(title, n=3):
    """#Bリーグ ＋ 見出しに出てくる順のチーム名（最大 n 個）。"""
    found = []
    for c in load_teams():
        pos = [title.find(k) for k in (c["name"], c["short"]) if len(k) >= 2 and k in title]
        if pos:
            found.append((min(pos), "#" + re.sub(r"[・\s\-]", "", c["name"])))
    tags = ["#Bリーグ"] + [t for _, t in sorted(found)]
    if re.search(r"日本代表|アカツキ", title):
        tags.insert(1, "#バスケ日本代表")
    return list(dict.fromkeys(tags))[:n]


def tweet_weight(text):
    """URL を23文字として数えた、X 上での文字数。"""
    urls = re.findall(r"https?://\S+", text)
    return weight(text) - sum(weight(u) for u in urls) + URL_WEIGHT * len(urls)


def summary(fn):
    """meta description の最初の一文を要点として使う。"""
    try:
        with open(os.path.join(ROOT, fn), encoding="utf-8") as f:
            t = f.read()
    except OSError:
        return ""
    m = re.search(r'<meta name="description" content="([^"]*)"', t)
    if not m:
        return ""
    desc = unicodedata.normalize("NFKC", build.html.unescape(m.group(1))).strip()
    return desc.split("。")[0] + ("。" if "。" in desc else "")


def compose(article):
    title = article["title"]
    url = SITE_URL + article["href"]
    tags = " ".join(hashtags(title))
    body_budget = MAX_WEIGHT - URL_WEIGHT - weight(tags) - 4   # 改行ぶん
    title = clip(title, min(body_budget, 120))
    point = clip(summary(article["href"]), body_budget - weight(title) - 1)
    lines = [title] + ([point] if point and weight(point) > 4 else []) + [url, tags]
    return "\n".join(lines)


# ------------------------------------------------------------------- main

def load_posted():
    try:
        with open(POSTED_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_posted(data):
    with open(POSTED_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def summary(lines):
    """GitHub Actions の Summary に結果を書く（ローカルでは何もしない）。"""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    """終了コード: 0 … 投稿した／対象なし、2 … キー未設定でスキップ、1 … 投稿に失敗。"""
    articles = build.read_articles()
    posted = load_posted()
    now = datetime.now(JST)

    if posted is None:
        save_posted({"posted": {a["href"]: "initial" for a in articles}})
        log(f"初回: 既存の {len(articles)} 本を投稿済みとして記録しました（投稿はしません）")
        summary(["### Xへの投稿: 初回記録のみ",
                 f"既存の {len(articles)} 本を投稿済みとして記録しました（投稿 0 件）。"])
        return 0

    keys = {k: os.environ.get(k, "").strip() for k in ENV_KEYS}
    if not all(keys.values()):
        log("スキップ: X の API キーが未設定のため何もしません")
        summary(["### Xへの投稿: スキップ", "X の API キーが未設定のため投稿していません。"])
        return 2

    done = posted.setdefault("posted", {})
    today = now.strftime("%Y-%m-%d")
    used = sum(1 for v in done.values() if str(v).startswith(today))
    oldest = (now - timedelta(days=MAX_AGE_DAYS)).strftime("%Y.%m.%d")
    todo = [a for a in reversed(articles)            # 古い順に投稿
            if a["href"] not in done and (a["date"] or "") >= oldest]
    if not todo:
        log("新しい記事はありません")
        summary(["### Xへの投稿: 対象なし", "新しい記事がないため投稿 0 件です。"])
        return 0

    from requests_oauthlib import OAuth1Session
    session = OAuth1Session(keys["X_API_KEY"], keys["X_API_SECRET"],
                            keys["X_ACCESS_TOKEN"], keys["X_ACCESS_TOKEN_SECRET"])
    ok, too_long, deferred, failed = [], [], [], []
    for i, a in enumerate(todo):
        if used >= DAILY_LIMIT:
            deferred = [x["href"] for x in todo[i:]]
            log(f"1日の上限 {DAILY_LIMIT} 件に達したので、残り {len(deferred)} 本は翌日に回します")
            break
        text = compose(a)
        if tweet_weight(text) > MAX_WEIGHT:
            log(f"!! 文字数超過のためスキップ: {a['href']}")
            done[a["href"]] = "skipped-too-long"
            too_long.append(a["href"])
            continue
        r = session.post(TWEET_URL, json={"text": text}, timeout=30)
        if r.status_code not in (200, 201):
            log(f"!! 投稿に失敗: {a['href']} {r.status_code} {r.text[:300]}")
            failed.append(f"{a['href']}（HTTP {r.status_code}）")
            break
        done[a["href"]] = now.isoformat(timespec="seconds")
        used += 1
        ok.append(a["href"])
        log(f"投稿: {a['href']}")
        save_posted(posted)
    save_posted(posted)

    head = "失敗あり" if failed else ("投稿" if ok else "見送りのみ")
    lines = [f"### Xへの投稿: {head}",
             f"- 投稿: {len(ok)} 件",
             f"- 見送り（文字数超過）: {len(too_long)} 件",
             f"- 見送り（1日の上限 {DAILY_LIMIT} 件・翌日に回す）: {len(deferred)} 件",
             f"- 失敗: {len(failed)} 件"]
    for label, items in (("投稿", ok), ("文字数超過", too_long),
                         ("翌日に回す", deferred), ("失敗", failed)):
        lines += [f"  - {label}: {h}" for h in items]
    summary(lines)
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--dry-run":
        for art in build.read_articles()[:5]:
            t = compose(art)
            print(f"--- {art['href']} （{tweet_weight(t)}/{MAX_WEIGHT}）\n{t}")
        sys.exit(0)
    sys.exit(main())
