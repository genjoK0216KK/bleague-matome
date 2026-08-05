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


# --------------------------------------------------- 手書き記事（article-*.html）

def _attr(tag, name):
    m = re.search(name + r'="([^"]*)"', tag)
    return m.group(1) if m else ""


def read_articles():
    """article-*.html を走査し、各記事のメタ情報（タイトル・カテゴリ・日付・
    サムネ）を記事ファイル自身から読み取って一覧化用のデータにする。"""
    items = []
    for fn in sorted(os.listdir(ROOT)):
        if not (fn.startswith("article-") and fn.endswith(".html")):
            continue
        try:
            with open(os.path.join(ROOT, fn), encoding="utf-8") as f:
                t = f.read()
        except OSError:
            continue

        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", t, re.DOTALL)
        title = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else ""
        if not title:
            log(f"   {fn}: <h1> が無いため一覧化をスキップ")
            continue

        pm = re.search(r'<div class="pmeta">(.*?)</div>', t, re.DOTALL)
        pmeta = pm.group(1) if pm else ""
        tagm = re.search(r'<span class="tag (\w+)"[^>]*>(.*?)</span>', pmeta, re.DOTALL)
        cat = tagm.group(1) if tagm else "sokuho"
        label = (re.sub(r"<[^>]+>", "", tagm.group(2)).strip()
                 if tagm else CATEGORY_LABEL.get(cat, "速報"))
        datem = re.search(r"\d{4}\.\d{2}\.\d{2}", pmeta)
        date = datem.group(0) if datem else ""
        extra = ""
        for s in re.findall(r"<span[^>]*>(.*?)</span>", pmeta, re.DOTALL):
            txt = re.sub(r"<[^>]+>", "", s).strip()
            if txt and txt != label and not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", txt):
                extra = txt

        imgm = re.search(r'<img[^>]*class="eyecatch"[^>]*>', t)
        thumb = _attr(imgm.group(0), "src") if imgm else ""
        alt = _attr(imgm.group(0), "alt") if imgm else ""

        items.append({
            "href": fn, "title": title, "cat": cat, "label": label,
            "date": date, "extra": extra, "thumb": thumb, "alt": alt or title,
        })

    items.sort(key=lambda a: a["date"] or "0000.00.00", reverse=True)
    return items


def render_articles(articles, category=None):
    """記事カードを既存デザイン（.item）と同じマークアップで生成する。"""
    rows = [a for a in articles if category is None or a["cat"] == category]
    if not rows:
        return '<p class="note">この分類の記事はまだありません。</p>'

    out = []
    for a in rows:
        meta = esc(a["date"])
        if a["extra"]:
            meta = f'{meta} ・ {esc(a["extra"])}'
        out.append(
            '<a class="item" href="{href}">'
            '<div class="thumb"><img src="{thumb}" alt="{alt}" loading="lazy"></div>'
            '<div class="c">'
            '<span class="tag {cat}">{label}</span>'
            '<h3>{title}</h3>'
            '<div class="meta">{meta}</div>'
            '</div></a>'.format(
                href=esc(a["href"]), thumb=esc(a["thumb"]), alt=esc(a["alt"]),
                cat=esc(a["cat"]), label=esc(a["label"]), title=esc(a["title"]),
                meta=meta,
            )
        )
    return "\n".join(out)


def render_hero(articles):
    """トップ最上部のヒーロー枠。最新の記事1本を大きく出す。"""
    if not articles:
        return ('<article class="hero"><div class="body">'
                '<h3>記事はまだありません。</h3></div></article>')
    a = articles[0]
    meta = esc(a["date"])
    if a["extra"]:
        meta = f'{meta} ・ {esc(a["extra"])}'
    return (
        '<article class="hero">'
        '<div class="ph"><img src="{thumb}" alt="{alt}"></div>'
        '<div class="body">'
        '<span class="cat">{label}</span>'
        '<h3><a href="{href}">{title}</a></h3>'
        '<div class="meta">{meta}</div>'
        '</div></article>'.format(
            thumb=esc(a["thumb"]), alt=esc(a["alt"]), label=esc(a["label"]),
            href=esc(a["href"]), title=esc(a["title"]), meta=meta,
        )
    )


def render_picks(articles, n=3):
    """トップの「ピックアップ」枠。新しい記事 n 本を pick カードで出す。"""
    rows = articles[:n]
    if not rows:
        return '<p class="note">記事はまだありません。</p>'
    out = []
    for a in rows:
        title = a["title"]
        if len(title) > 34:
            title = title[:33] + "…"
        out.append(
            '<a class="pick" href="{href}">'
            '<div class="pimg"><img src="{thumb}" alt="{alt}" loading="lazy"></div>'
            '<div class="pbody"><span class="tag {cat}">{label}</span><h3>{title}</h3></div>'
            '</a>'.format(
                href=esc(a["href"]), thumb=esc(a["thumb"]), alt=esc(a["alt"]),
                cat=esc(a["cat"]), label=esc(a["label"]), title=esc(title),
            )
        )
    return "\n".join(out)


def _matching_div_close(text, open_pos):
    """open_pos の <div ...> に対応する </div> の開始位置を返す。"""
    depth = 0
    for m in re.finditer(r"<div\b[^>]*>|</div>", text[open_pos:]):
        if m.group().startswith("</div"):
            depth -= 1
            if depth == 0:
                return open_pos + m.start()
        else:
            depth += 1
    return -1


def ensure_article_markers(text, heading):
    """<h2>{heading}...</h2> という見出しの直後にある記事用 <div class="feed">
    の中身を AUTO:ARTICLES マーカーに置き換える（未挿入なら）。見出しは前方一致
    で探すので「順位・日程」→「順位・日程・データ」のような表記揺れも拾う。
    既存の手書きカードはここで一度だけ除去され、以降は build が自動生成する。"""
    if "<!-- AUTO:ARTICLES:START -->" in text:
        return text
    m = re.search(r"<h2>\s*" + re.escape(heading), text)
    if not m:
        log(f"   記事見出し「{heading}」が見つかりません（ARTICLESマーカー挿入をスキップ）")
        return text
    feed_open = text.find('<div class="feed">', m.start())
    if feed_open == -1:
        return text
    close = _matching_div_close(text, feed_open)
    if close == -1:
        return text
    inner = feed_open + len('<div class="feed">')
    return (
        text[:inner]
        + "\n<!-- AUTO:ARTICLES:START -->\n<!-- AUTO:ARTICLES:END -->\n"
        + text[close:]
    )


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


CSS_VER = 2
CSS_LINK = f'<link rel="stylesheet" href="auto.css?v={CSS_VER}">'


def ensure_css(text):
    """自動更新エリア用のCSSを読み込ませる。未挿入なら <head> に追加し、
    既に入っていればバージョン番号を最新へ更新してキャッシュを確実に切り替える。"""
    if "</head>" not in text:
        return text
    if "auto.css" in text:
        return re.sub(r"auto\.css\?v=\d+", f"auto.css?v={CSS_VER}", text)
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


def update_file(filename, regions, with_standings=False, article_heading=None):
    path = os.path.join(ROOT, filename)
    try:
        with open(path, encoding="utf-8") as f:
            original = f.read()
    except OSError:
        log(f"!! {filename} が存在しません（スキップ）")
        return False

    text = ensure_css(ensure_markers(original, with_standings))
    if article_heading:
        text = ensure_article_markers(text, article_heading)
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

def _feed_item(it):
    cat = it.get("category", "sokuho")
    return (
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


def render_feed(items, limit=None, grouped=False):
    """外部ニュースの一覧。見出しとリンクのみを掲載する。
    grouped=True のときは日付ごとに見出しを付けてダイジェスト風に整理する。"""
    items = items[:limit] if limit else items
    if not items:
        return '<p class="note">現在取得できた新着はありません。</p>'

    if not grouped:
        return "\n".join(_feed_item(it) for it in items)

    rows = sorted(items, key=lambda it: it.get("date") or "", reverse=True)
    out = []
    current = None
    for it in rows:
        d = fmt_date(it.get("date"))
        if d != current:
            current = d
            out.append(f'<div class="feed-date">{esc(d)}</div>')
        out.append(_feed_item(it))
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
<link rel="stylesheet" href="auto.css?v={ver}">
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
        feed=render_feed(news, limit=120, grouped=True),
        updated=esc(updated),
        ver=CSS_VER,
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

    articles = read_articles()
    log(f"手書き記事 {len(articles)}件を一覧化")

    changed = False

    # トップページ
    changed |= update_file("index.html", {
        "TICKER": render_ticker(news),
        "FEED": render_feed(news, limit=12),
        "HERO": render_hero(articles),
        "ARTICLES": render_articles(articles),
        "PICKS": render_picks(articles),
        "STANDINGS": render_standings_card(standings),
        "UPDATED": esc(updated),
    }, article_heading="編集部まとめ記事")

    # カテゴリページ
    for cat, page in CATEGORY_PAGE.items():
        subset = [n for n in news if n.get("category") == cat]
        regions = {
            "FEED": render_feed(subset, limit=40, grouped=True),
            "ARTICLES": render_articles(articles, category=cat),
            "UPDATED": esc(updated),
        }
        if cat == "data":
            regions["STANDINGS_FULL"] = render_standings_table(standings)
        changed |= update_file(page, regions, with_standings=(cat == "data"),
                               article_heading=CATEGORY_LABEL[cat])

    # 新着一覧ページ
    changed |= write_news_page(news, updated)

    write_sitemap()

    log("完了" if changed else "完了（内容に変化なし）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
