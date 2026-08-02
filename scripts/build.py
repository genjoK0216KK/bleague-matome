#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bリーグまとめ - HTML生成スクリプト

data/*.json を読み、既存ページの
    <!-- AUTO:名前:START --> ～ <!-- AUTO:名前:END -->
で囲まれた区間だけを差し替える。
手書きの記事ページ（article-*.html）には一切触れない。
"""

import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

SITE_URL = "https://genjok0216kk.github.io/bleague-matome/"

CATEGORY_LABEL = {
    "kekka": "試合結果",
    "sokuho": "速報",
    "iseki": "移籍情報",
    "data": "順位・日程",
}
CATEGORY_PAGE = {
    "kekka": "cat-kekka.html",
    "sokuho": "cat-sokuho.html",
    "iseki": "cat-iseki.html",
    "data": "cat-data.html",
}


def log(msg):
    print(f"[build] {msg}", flush=True)


def esc(text):
    return html.escape(str(text or ""), quote=True)


def load(name, default):
    try:
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        log(f"!! {name} を読めませんでした（既定値を使用）")
        return default


def fmt_date(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%Y.%m.%d")
    except (ValueError, TypeError):
        return iso or ""


# ------------------------------------------------------------ marker replace

def replace_region(text, name, body):
    start = f"<!-- AUTO:{name}:START -->"
    end = f"<!-- AUTO:{name}:END -->"
    pattern = re.compile(
        re.escape(start) + r".*?" + re.escape(end),
        re.DOTALL,
    )
    if not pattern.search(text):
        log(f"   区間 {name} が見つかりません（スキップ）")
        return text, False
    return pattern.sub(lambda _: f"{start}\n{body}\n{end}", text, count=1), True


AUTO_BLOCK = """
  <!-- ここから自動更新エリア（scripts/build.py が生成。手で編集しても次回上書きされます） -->
{standings}  <div class="sec-h"><span class="bar"></span><h2>公式・メディアの新着</h2><a class="more" href="news.html">もっと見る ›</a></div>
  <p class="note auto-note">配信元の見出しとリンクのみを自動収集しています。タップすると元記事が開きます。</p>
  <div class="feed">
<!-- AUTO:FEED:START -->
    <p class="note">まもなく自動更新が始まります。</p>
<!-- AUTO:FEED:END -->
  </div>
  <div class="upd">最終更新: <!-- AUTO:UPDATED:START -->—<!-- AUTO:UPDATED:END --></div>
  <!-- ここまで自動更新エリア -->
"""

STANDINGS_BLOCK = """  <div class="sec-h"><span class="bar"></span><h2>B.PREMIER 順位表</h2></div>
<!-- AUTO:STANDINGS_FULL:START -->
  <p class="note">順位表は取得待ちです。</p>
<!-- AUTO:STANDINGS_FULL:END -->
"""


CSS_LINK = '<link rel="stylesheet" href="auto.css?v=1">'


def ensure_css(text):
    """自動更新エリア用のCSSが読み込まれていなければ <head> に追加する。"""
    if "auto.css" in text or "</head>" not in text:
        return text
    return text.replace("</head>", CSS_LINK + "\n</head>", 1)


def ensure_markers(text, with_standings=False):
    """マーカーが無いページには、<main> 直後に自動更新エリアを一度だけ差し込む。"""
    if "<!-- AUTO:FEED:START -->" in text:
        return text
    anchor = '<main class="wrap">'
    if anchor not in text:
        return text
    block = AUTO_BLOCK.format(
        standings=STANDINGS_BLOCK if with_standings else ""
    )
    return text.replace(anchor, anchor + block, 1)


def update_file(filename, regions, with_standings=False):
    path = os.path.join(ROOT, filename)
    try:
        with open(path, encoding="utf-8") as f:
            original = f.read()
    except OSError:
        log(f"!! {filename} が存在しません（スキップ）")
        return False

    text = ensure_css(ensure_markers(original, with_standings))
    hit = False
    for name, body in regions.items():
        text, ok = replace_region(text, name, body)
        hit = hit or ok

    if text != original:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        log(f"更新: {filename}")
        return True
    if hit:
        log(f"変更なし: {filename}")
    return False


# ---------------------------------------------------------------- rendering

def render_feed(items, limit=None):
    """外部ニュースの一覧。見出しとリンクのみを掲載する。"""
    items = items[:limit] if limit else items
    if not items:
        return '<p class="note">現在取得できた新着はありません。</p>'

    out = []
    for it in items:
        cat = it.get("category", "sokuho")
        out.append(
            '<a class="item ext" href="{url}" target="_blank" rel="noopener nofollow">'
            '<div class="c">'
            '<span class="tag {cat}">{label}</span>'
            '<h3>{title}</h3>'
            '<div class="meta">{date} ・ <span class="src">{source}</span></div>'
            '</div></a>'.format(
                url=esc(it.get("url")),
                cat=esc(cat),
                label=esc(CATEGORY_LABEL.get(cat, "速報")),
                title=esc(it.get("title")),
                date=esc(fmt_date(it.get("date"))),
                source=esc(it.get("source")),
            )
        )
    return "\n".join(out)


def render_ticker(items, limit=6):
    links = [
        '<a href="{url}" target="_blank" rel="noopener nofollow">{title}</a>'.format(
            url=esc(it.get("url")), title=esc(it.get("title"))
        )
        for it in items[:limit]
    ]
    if not links:
        return ""
    return "\n".join(links * 2)  # 途切れないよう2周分


def render_standings_card(standings):
    """サイドバー用のコンパクトな順位表。"""
    if not standings or not standings.get("groups"):
        return '<p class="note">順位表は取得待ちです。</p>'

    if not standings.get("started"):
        return (
            '<p class="note">2026-27シーズンは9月22日開幕。'
            '開幕後、順位表がここに自動で表示されます。</p>'
            f'<div class="upd">確認: {esc(standings.get("updated"))}</div>'
        )

    out = []
    for group in standings["groups"][:2]:
        out.append(f'<div class="gname">{esc(group["name"])}</div>')
        out.append('<div class="stand">')
        for row in group["rows"][:5]:
            out.append(
                '<div class="row"><span class="r">{rank}</span>'
                '<span class="nm">{team}</span>'
                '<span class="mv">{w}勝{l}敗</span></div>'.format(
                    rank=esc(row.get("rank", "-")),
                    team=esc(row.get("team")),
                    w=esc(row.get("w", "-")),
                    l=esc(row.get("l", "-")),
                )
            )
        out.append("</div>")
    out.append(
        '<div style="margin-top:10px">'
        '<a class="more" href="cat-data.html" style="font-size:13px">順位表を全部見る ›</a></div>'
    )
    return "\n".join(out)


def render_standings_table(standings):
    """cat-data.html 用のフル順位表。"""
    if not standings or not standings.get("groups"):
        return '<p class="note">順位表は取得待ちです。</p>'

    if not standings.get("started"):
        return (
            '<p class="note">りそなグループ B.LEAGUE 2026-27（B.PREMIER）は'
            '<strong>9月22日開幕</strong>です。開幕後、'
            '<a href="https://www.bleague.jp/standings/" target="_blank" rel="noopener nofollow">公式順位表</a>'
            'をもとに勝敗・勝率・得失点差を1日3回自動で更新します。</p>'
            f'<div class="upd">最終確認: {esc(standings.get("updated"))}</div>'
        )

    heads = ["順位", "クラブ", "勝", "負", "勝率", "差", "得点", "失点", "得失差"]
    keys = ["rank", "team", "w", "l", "pct", "gb", "pf", "pa", "diff"]

    out = []
    for group in standings["groups"]:
        out.append(f'<div class="sec-h"><span class="bar"></span><h2>{esc(group["name"])}</h2></div>')
        out.append('<div class="tblwrap"><table class="stdtbl"><thead><tr>')
        out += [f"<th>{esc(h)}</th>" for h in heads]
        out.append("</tr></thead><tbody>")
        for row in group["rows"]:
            out.append("<tr>")
            out += [f'<td>{esc(row.get(k, "-"))}</td>' for k in keys]
            out.append("</tr>")
        out.append("</tbody></table></div>")

    out.append(f'<div class="upd">最終更新: {esc(standings.get("updated"))} ・ '
               '出典: <a href="https://www.bleague.jp/standings/" target="_blank" '
               'rel="noopener nofollow">B.LEAGUE公式</a></div>')
    return "\n".join(out)


# ----------------------------------------------------------------- news page

NEWS_PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>新着ニュース一覧｜Bリーグ まとめ</title>
<meta name="description" content="B.LEAGUE公式・バスケ専門メディアの最新ニュースを自動でまとめた一覧。1日3回更新。">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{site}news.html">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%230d1b2a'/><circle cx='16' cy='16' r='9' fill='%23ff5a1f'/><path d='M16 7v18M7 16h18M10 8.4a13 13 0 000 15.2M22 8.4a13 13 0 010 15.2' stroke='%230d1b2a' stroke-width='1.4' fill='none'/></svg>">
<link rel="stylesheet" href="style.css?v=5">
<link rel="stylesheet" href="auto.css?v=1">
</head>
<body>
<header class="hdr"><div class="hdr-in"><a class="logo" href="index.html"><span class="mk"><svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" fill="#fff"/><path d="M12 3v18M3 12h18M6.2 5.2a13 13 0 000 13.6M17.8 5.2a13 13 0 010 13.6" stroke="#e2360b" stroke-width="1.3"/></svg></span><span class="wm"><span class="t">Bリーグ<em>まとめ</em></span><span class="sub">非公式ファンサイト</span></span></a><nav class="gnav"><a href="index.html">最新</a><a href="cat-kekka.html">試合結果</a><a href="cat-sokuho.html">速報</a><a href="cat-iseki.html">移籍情報</a><a href="cat-data.html">順位・日程</a></nav></div></header>
<main class="wrap">
  <div class="sec-h"><span class="bar"></span><h2>新着ニュース一覧</h2></div>
  <p class="note">B.LEAGUE公式サイトとバスケ専門メディアの新着を自動で収集しています。見出しをタップすると配信元の記事が開きます。</p>
  <div class="feed">
<!-- AUTO:FEED:START -->
{feed}
<!-- AUTO:FEED:END -->
  </div>
  <div class="upd">最終更新: <!-- AUTO:UPDATED:START -->{updated}<!-- AUTO:UPDATED:END --></div>
</main>
<footer class="ft"><div class="ft-in"><a href="about.html">このサイトについて</a><a href="privacy.html">プライバシーポリシー</a><a href="contact.html">お問い合わせ</a><span class="cp">© 2026 Bリーグ まとめ（非公式）. 見出しと出典リンクのみを掲載しています。</span></div></footer>
</body>
</html>
"""


def write_news_page(news, updated):
    path = os.path.join(ROOT, "news.html")
    content = NEWS_PAGE.format(
        site=SITE_URL,
        feed=render_feed(news, limit=120),
        updated=esc(updated),
    )
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if old != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        log("更新: news.html")
        return True
    return False


# --------------------------------------------------------------- sitemap etc

def write_sitemap():
    pages = sorted(
        f for f in os.listdir(ROOT)
        if f.endswith(".html")
    )
    today = datetime.now(JST).strftime("%Y-%m-%d")
    urls = "\n".join(
        f"  <url><loc>{SITE_URL}{p}</loc><lastmod>{today}</lastmod></url>"
        for p in pages
    )
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n</urlset>\n"
    )
    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(content)
    log(f"更新: sitemap.xml（{len(pages)}ページ）")


# --------------------------------------------------------------------- main

def main():
    news = load("news.json", [])
    standings = load("standings.json", {})
    updated = datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")

    if not news:
        log("!! ニュースデータが空です。生成を中止します")
        return 1

    log(f"ニュース {len(news)}件 / 更新日時 {updated}")

    changed = False

    # トップページ
    changed |= update_file("index.html", {
        "TICKER": render_ticker(news),
        "FEED": render_feed(news, limit=12),
        "STANDINGS": render_standings_card(standings),
        "UPDATED": esc(updated),
    })

    # カテゴリページ
    for cat, page in CATEGORY_PAGE.items():
        subset = [n for n in news if n.get("category") == cat]
        regions = {
            "FEED": render_feed(subset, limit=40),
            "UPDATED": esc(updated),
        }
        if cat == "data":
            regions["STANDINGS_FULL"] = render_standings_table(standings)
        changed |= update_file(page, regions, with_standings=(cat == "data"))

    # 新着一覧ページ
    changed |= write_news_page(news, updated)

    write_sitemap()

    log("完了" if changed else "完了（内容に変化なし）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
