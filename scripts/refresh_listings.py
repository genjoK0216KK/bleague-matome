#!/usr/bin/env python3
"""記事一覧だけを更新する（外部取得なし）。

ニュース取得（fetch.py）が全滅すると update.yml の後続（build.py）が止まり、記事ルーティンが
公開した記事（記事HTML＋サムネの2ファイル）が一覧に載らない。そのとき用の最小処理。

出力範囲（これ以外のファイルは書かない）：
  - index.html の「当サイトの独自記事」欄（section#own-articles）だけ
  - articles.html / articles-N.html（記事一覧）
  - 新しい記事のカテゴリの cat-*.html（そのカテゴリだけ）
  - sitemap.xml（未掲載のURLを追記するだけ。既存行の lastmod は変えない）

しないこと：外部取得、news.json 等のデータ更新、記事本文・結果ページ・状態ファイルの書き換え、
全記事への広告枠差し込み、全ページの後処理（finalize）、ニュース一覧の再生成。
新しい記事が無ければ何も書かない。ニュース取得の失敗を成功扱いにはしない（呼び出し側が失敗のまま報告する）。
"""
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True

import build  # noqa: E402

home_sections = build.home_sections

from bs4 import BeautifulSoup  # noqa: E402


def log(msg):
    print(f"[refresh_listings] {msg}", flush=True)


def listed_hrefs(root):
    """articles*.html に既に載っている記事ファイル名。"""
    hrefs = set()
    for fn in os.listdir(root):
        if re.fullmatch(r"articles(?:-\d+)?\.html", fn):
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                hrefs |= set(re.findall(r'href="(article-[^"#]+\.html)"', f.read()))
    return hrefs


def refresh_index(root, articles):
    path = os.path.join(root, "index.html")
    with open(path, encoding="utf-8") as f:
        original = f.read()
    soup = BeautifulSoup(original, "html.parser")
    old = soup.select_one("section#own-articles")
    if old is None:
        log("!! index.html に独自記事欄が無いため変更しません")
        return False
    new = BeautifulSoup(home_sections.own_articles(articles), "html.parser").select_one("section#own-articles")
    if str(old) == str(new):
        return False
    # 置き換えるのはこの section の文字列だけ。他の部分のバイトは保つ。
    start = original.find(str(old))
    if start < 0:
        # BeautifulSoup の正規化で元の文字列と一致しない場合は、安全のため変更しない
        log("!! 独自記事欄の位置を特定できないため index.html は変更しません")
        return False
    text = original[:start] + str(new) + original[start + len(str(old)):]
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def refresh_sitemap(root, new_hrefs):
    path = os.path.join(root, "sitemap.xml")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    today = datetime.now(build.JST).strftime("%Y-%m-%d")
    lines = [f"  <url><loc>{build.SITE_URL}{h}</loc><lastmod>{today}</lastmod></url>"
             for h in sorted(new_hrefs) if f"<loc>{build.SITE_URL}{h}</loc>" not in text]
    if not lines:
        return False
    text = text.replace("\n</urlset>", "\n" + "\n".join(lines) + "\n</urlset>", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def refresh(root=None):
    """新しく公開された記事を一覧に載せる。戻り値：書き換えたファイル名の一覧。"""
    root = root or build.ROOT
    old_root, old_data = build.ROOT, build.DATA_DIR
    build.ROOT, build.DATA_DIR = root, os.path.join(root, "data")   # build の関数はモジュールの値を使う
    try:
        articles = build.read_articles()
        new = [a for a in articles if a["href"] not in listed_hrefs(root)]
        if not new:
            log("一覧に未掲載の記事はありません（何も書きません）")
            return []
        log("未掲載の記事：" + "、".join(a["href"] for a in new))
        written = []
        before = {fn: _read(root, fn) for fn in os.listdir(root) if fn.endswith(".html") or fn == "sitemap.xml"}
        updated = datetime.now(build.JST).strftime("%Y年%m月%d日 %H:%M")
        build.write_article_pages(articles, updated)
        standings = build.load("standings.json", {})
        for cat in sorted({a["cat"] for a in new}):
            build.update_category(cat, build.CATEGORY_PAGE[cat], [], articles, standings, updated)
        # カテゴリページは日程・順位・結果など他のデータも載せるので、最終更新の表示は元の時刻のまま残す
        # （記事一覧だけ差し替えたのに、古いデータを新しく見せないため）
        for fn in sorted(os.listdir(root)):
            if re.fullmatch(r"cat-[a-z]+(?:-\d+)?\.html", fn) and before.get(fn) and _read(root, fn) != before[fn]:
                keep_updated_stamp(root, fn, before[fn])
        # 一覧ページは build と同じ後処理（ナビ・GA4・共通CSS）をこのページだけに行う
        cfg = build.site_config()
        for fn in sorted(os.listdir(root)):
            if re.fullmatch(r"(articles|cat-[a-z]+)(?:-\d+)?\.html", fn) and _read(root, fn) != before.get(fn):
                finalize_one(root, fn, cfg)
        refresh_index(root, articles)
        refresh_sitemap(root, {a["href"] for a in new})
        after = {fn: _read(root, fn) for fn in os.listdir(root) if fn.endswith(".html") or fn == "sitemap.xml"}
        written = sorted(fn for fn in set(before) | set(after) if before.get(fn) != after.get(fn))
        log("更新：" + ("、".join(written) if written else "なし"))
        return written
    finally:
        build.ROOT, build.DATA_DIR = old_root, old_data


STAMP = re.compile(r"<!-- AUTO:UPDATED:START -->.*?<!-- AUTO:UPDATED:END -->", re.DOTALL)


def keep_updated_stamp(root, fn, previous):
    old = STAMP.search(previous)
    if not old:
        return
    path = os.path.join(root, fn)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = STAMP.sub(lambda _: old.group(0), text, count=1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def finalize_one(root, fn, cfg):
    """build.finalize_pages の1ページ版（記事ページの閲覧数処理は対象外）。"""
    path = os.path.join(root, fn)
    with open(path, encoding="utf-8") as f:
        original = f.read()
    text = build.ensure_nav(original, bool(cfg["x_list_url"]), fn)
    text = build.ensure_ga(text, cfg["ga4_id"])
    if 'href="design-system.css?v=1"' not in text:
        text = text.replace("</head>", '<link rel="stylesheet" href="design-system.css?v=1">\n</head>', 1)
    if text != original:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def _read(root, fn):
    try:
        with open(os.path.join(root, fn), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


if __name__ == "__main__":
    refresh()
