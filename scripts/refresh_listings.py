#!/usr/bin/env python3
"""記事一覧だけを、いまの記事ファイルに合わせて直す（外部取得なし）。

ニュース取得（fetch.py）が全滅すると update.yml の後続（build.py）が止まり、記事ルーティンが
公開・更新した記事（記事HTML＋サムネの2ファイル）が一覧に反映されない。そのとき用の最小処理。

出力先ごとに「載るべき記事の行（見出し・種類・日付）」と今の中身を比べ、違う所だけ直す：
  - articles.html / articles-N.html の記事の行
  - cat-*.html の記事の行（日程・順位・結果など記事以外の部分はそのまま）
  - index.html の記事欄（独自記事欄。案Cの先頭記事欄があればそれも）
  - sitemap.xml（載っていない記事URLを追記するだけ。既存行の lastmod は変えない）
新しい記事、同じ日の記事の書き換え（見出しの変更）、一部の出力先だけの掲載漏れのどれも直る。
入力が同じなら何も書かない。

しないこと：外部取得、news.json 等のデータの読み書き、記事本文・結果ページ・状態ファイルの書き換え、
全記事への広告枠差し込み、全ページの後処理、ニュース一覧の再生成。
ニュース取得の失敗を成功扱いにはしない（呼び出し側の workflow は失敗のまま報告する）。
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

ROWS = re.compile(r'(?:<a class="item compact-item" href="[^"]*">.*?</div></a>\n?)+'
                  r'|<p class="note">この分類の記事はまだありません。</p>')
STAMP = re.compile(r"(<!-- AUTO:UPDATED:START -->)(.*?)(<!-- AUTO:UPDATED:END -->)", re.DOTALL)


def log(msg):
    print(f"[refresh_listings] {msg}", flush=True)


def _read(root, fn):
    try:
        with open(os.path.join(root, fn), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _write(root, fn, text):
    with open(os.path.join(root, fn), "w", encoding="utf-8") as f:
        f.write(text)


# ------------------------------------------------------------ list pages

def _pages(root, base):
    pat = re.compile(re.escape(base) + r"(?:-(\d+))?\.html\Z")
    return sorted((int(m.group(1) or 1), fn) for fn in os.listdir(root) for m in [pat.match(fn)] if m)


def refresh_list(root, base, rows, keep_stamp, regenerate):
    """base.html, base-2.html … の記事の行だけを差し替える。ページ数が変わる時だけ build の
    生成関数で作り直す（その場合も最終更新の扱いは keep_stamp に従う）。"""
    parts = build.chunk(rows)
    pages = _pages(root, base)
    now_stamp = datetime.now(build.JST).strftime("%Y年%m月%d日 %H:%M")
    if [n for n, _ in pages] != list(range(1, len(parts) + 1)):
        before = {fn: _read(root, fn) for _, fn in pages}
        regenerate()
        cfg = build.site_config()
        first = next(iter(before.values()), None)
        for _, fn in _pages(root, base):
            finalize_one(root, fn, cfg)
            old = STAMP.search(before.get(fn) or first or "")
            if keep_stamp and old:
                _write(root, fn, STAMP.sub(lambda m: m.group(1) + old.group(2) + m.group(3), _read(root, fn), count=1))
        return
    for (n, fn), part in zip(pages, parts):
        text = _read(root, fn)
        found = list(ROWS.finditer(text))
        if len(found) != 1:
            log(f"!! {fn} の記事の行を特定できないため変更しません")
            continue
        block = found[0]
        new_rows = build.render_articles(part) + ("\n" if block.group(0).endswith("\n") else "")
        if block.group(0) == new_rows:
            continue
        text = text[:block.start()] + new_rows + text[block.end():]
        if not keep_stamp:
            text = STAMP.sub(lambda m: m.group(1) + now_stamp + m.group(3), text, count=1)
        _write(root, fn, text)


def finalize_one(root, fn, cfg):
    """build.finalize_pages の1ページ版（作り直したページだけに使う）。"""
    original = _read(root, fn)
    text = build.ensure_nav(original, bool(cfg["x_list_url"]), fn)
    text = build.ensure_ga(text, cfg["ga4_id"])
    if 'href="design-system.css?v=1"' not in text:
        text = text.replace("</head>", '<link rel="stylesheet" href="design-system.css?v=1">\n</head>', 1)
    if text != original:
        _write(root, fn, text)


# ------------------------------------------------------------------ index

def _own_section(articles, current, now):
    """index に今ある独自記事欄と同じ型で作り直す（公開中の型／案Cの型）。"""
    if "home-own-c" in (current.get("class") or []) and hasattr(home_sections, "recent_articles_c"):
        return home_sections.recent_articles_c(articles, now)
    return home_sections.own_articles(articles)


def refresh_index(root, articles, now=None):
    """トップの記事欄だけを作り直す。ランキング・公式更新・試合・サイドバーの文字列は変えない。"""
    now = now or datetime.now(build.JST)
    original = _read(root, "index.html")
    soup = BeautifulSoup(original, "html.parser")
    targets = [("section#own-articles", lambda node: _own_section(articles, node, now))]
    if hasattr(home_sections, "lead_article"):      # 案Cの先頭記事欄（あれば）
        targets.append(("#today .lead-article", lambda node: home_sections.lead_article(articles, now)))
    text = original
    for selector, render in targets:
        node = soup.select_one(selector)
        if node is None:
            continue
        old = str(node)
        fresh = BeautifulSoup(render(node), "html.parser").find(True)
        new = str(fresh) if fresh is not None else ""
        if not new or new == old:
            continue
        if text.count(old) != 1:
            log(f"!! index.html の {selector} の位置を特定できないため変更しません")
            continue
        text = text.replace(old, new, 1)
    if text != original:
        _write(root, "index.html", text)


# ---------------------------------------------------------------- sitemap

def refresh_sitemap(root, hrefs):
    """sitemap に無い記事URLだけを追記する。既存行（lastmod を含む）は変えない。"""
    text = _read(root, "sitemap.xml")
    today = datetime.now(build.JST).strftime("%Y-%m-%d")
    lines = [f"  <url><loc>{build.SITE_URL}{h}</loc><lastmod>{today}</lastmod></url>"
             for h in sorted(hrefs) if f"<loc>{build.SITE_URL}{h}</loc>" not in text]
    if lines:
        _write(root, "sitemap.xml", text.replace("\n</urlset>", "\n" + "\n".join(lines) + "\n</urlset>", 1))


# ------------------------------------------------------------------- main

def refresh(root=None, now=None):
    """戻り値：書き換えたファイル名の一覧（入力が同じなら空）。"""
    root = root or build.ROOT
    old_root, old_data = build.ROOT, build.DATA_DIR
    build.ROOT, build.DATA_DIR = root, os.path.join(root, "data")   # build の関数はモジュールの値を使う
    try:
        articles = build.read_articles()
        before = {fn: _read(root, fn) for fn in os.listdir(root) if fn.endswith(".html") or fn == "sitemap.xml"}
        refresh_list(root, "articles", articles, keep_stamp=False,
                     regenerate=lambda: build.write_article_pages(
                         articles, datetime.now(build.JST).strftime("%Y年%m月%d日 %H:%M")))
        for cat, page in sorted(build.CATEGORY_PAGE.items()):
            rows = [a for a in articles if a["cat"] == cat]
            # カテゴリページは日程・順位・結果も載せるので、最終更新の表示は元の時刻のまま
            refresh_list(root, page[:-5], rows, keep_stamp=True,
                         regenerate=lambda cat=cat, page=page: build.update_category(
                             cat, page, [], articles, build.load("standings.json", {}), "—"))
        refresh_index(root, articles, now)
        refresh_sitemap(root, {a["href"] for a in articles})
        after = {fn: _read(root, fn) for fn in os.listdir(root) if fn.endswith(".html") or fn == "sitemap.xml"}
        written = sorted(fn for fn in set(before) | set(after) if before.get(fn) != after.get(fn))
        log("更新：" + ("、".join(written) if written else "なし（記事一覧は最新）"))
        return written
    finally:
        build.ROOT, build.DATA_DIR = old_root, old_data


if __name__ == "__main__":
    refresh()
