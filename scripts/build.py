#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
バスケまとめ - HTML生成スクリプト

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

SITE_URL = "https://basuke-matome.jp/"

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

        t = re.sub(r"<!-- AUTO:PV:START -->.*?<!-- AUTO:PV:END -->", "", t, flags=re.DOTALL)
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

    items.sort(key=article_order, reverse=True)
    return items


def article_order(a):
    """新しい順に並べるためのキー。同じ日付なら 貢献度ランキング → article-daily-YYYYMMDD-3
    → -2 → 無印 の順（1日に複数本書いた日は後から書いた記事を上に）。"""
    m = re.search(r"-(\d+)\.html$", a["href"])
    seq = int(m.group(1)) if m and not re.search(r"\d{8}\.html$", a["href"]) else 1
    if a["href"].startswith("article-stats-"):
        seq = 99  # 貢献度ランキングは全試合終了後（夜）に出るので、その日の記事の中で最新
    return (a["date"] or "0000.00.00", seq, a["href"])


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


def render_video():
    """トップの「注目の公式動画」。data/featured_video.json の id があれば
    その動画を埋め込み、無ければ公式チャンネルへのリンクを出す（古い動画が
    残らないようにする）。JSON は毎日のタスクが最新に更新する。"""
    v = load("featured_video.json", {})
    vid = (v or {}).get("id")
    if not vid:
        return ('<p class="note" style="margin:4px 0 22px">'
                '<a href="https://www.youtube.com/@B.LEAGUE" target="_blank" '
                'rel="noopener nofollow">B.LEAGUE公式YouTubeチャンネルで最新動画を見る ›</a></p>')
    cap = v.get("caption") or v.get("title") or "B.LEAGUE公式動画"
    return (
        '<div style="position:relative;padding-bottom:56.25%;height:0;margin:4px 0 6px;'
        'border-radius:12px;overflow:hidden;background:#000">'
        '<iframe src="https://www.youtube-nocookie.com/embed/{id}" title="{title}" '
        'style="position:absolute;top:0;left:0;width:100%;height:100%;border:0" '
        'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; '
        'picture-in-picture; web-share" allowfullscreen loading="lazy"></iframe></div>'
        '<p style="font-size:12.5px;color:#5c6672;margin:0 0 22px">▲ {cap}</p>'.format(
            id=esc(vid), title=esc(v.get("title", "B.LEAGUE公式動画")), cap=esc(cap))
    )


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
    """トップの「ピックアップ」枠。ヒーローに出した最新1本を除く新しい記事 n 本。"""
    rows = articles[1:n + 1]
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


def load_affiliates():
    return load("affiliates.json", {}) or {}


def _aff_enabled(cfg, key):
    return [x for x in (cfg.get(key) or []) if x.get("enabled") and x.get("url")]


def _aff_buttons(items):
    out = []
    for i in items:
        out.append(
            '<a class="aff-btn" href="{url}" target="_blank" rel="nofollow sponsored noopener">'
            '<span class="aff-cta">{cta}</span>'
            '<span class="aff-sub">{desc}</span></a>'.format(
                url=esc(i["url"]),
                cta=esc(i.get("cta") or i.get("name")),
                desc=esc(i.get("desc") or ""),
            ))
    return "\n".join(out)


def render_affiliate():
    """アフィリエイト枠。data/affiliates.json に有効なリンクが無ければ何も出さない。
    ステマ規制対応で必ずPR表記と広告利用の注記を付ける。"""
    cfg = load_affiliates()
    stream = _aff_enabled(cfg, "streaming")
    goods = _aff_enabled(cfg, "goods")
    if not stream and not goods:
        return ""
    pr = esc(cfg.get("pr_label", "PR"))
    parts = ['<aside class="affbox" aria-label="広告">',
             '<div class="aff-h"><span class="aff-pr">{}</span>{}</div>'.format(
                 pr, esc(cfg.get("heading", "バスケをもっと楽しむ")))]
    if stream:
        parts.append('<div class="aff-sec">{}</div>'.format(
            esc(cfg.get("streaming_heading", "配信・放送で見る"))))
        parts.append('<div class="aff-row">' + _aff_buttons(stream) + '</div>')
    if goods:
        parts.append('<div class="aff-sec">{}</div>'.format(
            esc(cfg.get("goods_heading", "関連グッズ"))))
        parts.append('<div class="aff-row">' + _aff_buttons(goods) + '</div>')
    parts.append('<p class="aff-note">{}</p>'.format(esc(cfg.get("note", ""))))
    parts.append('</aside>')
    return "\n".join(parts)


def ensure_marker_before(text, anchor, name):
    """anchor の（最後の）直前に AUTO:name マーカー対を一度だけ挿入する。"""
    if "<!-- AUTO:{}:START -->".format(name) in text:
        return text
    idx = text.rfind(anchor)
    if idx == -1:
        return text
    block = "<!-- AUTO:{n}:START -->\n<!-- AUTO:{n}:END -->\n".format(n=name)
    return text[:idx] + block + text[idx:]


def ensure_marker_after(text, anchor, name):
    """anchor の（最初の）直後に AUTO:name マーカー対を一度だけ挿入する。"""
    if "<!-- AUTO:{}:START -->".format(name) in text:
        return text
    idx = text.find(anchor)
    if idx == -1:
        return text
    pos = idx + len(anchor)
    block = "\n<!-- AUTO:{n}:START -->\n<!-- AUTO:{n}:END -->".format(n=name)
    return text[:pos] + block + text[pos:]


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


CSS_VER = 3
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


def update_file(filename, regions, with_standings=False, article_heading=None,
                extra_markers=None, manage_feed=True, canonical=None, index_page=False):
    path = os.path.join(ROOT, filename)
    try:
        with open(path, encoding="utf-8") as f:
            original = f.read()
    except OSError:
        log(f"!! {filename} が存在しません（スキップ）")
        return False

    text = ensure_css(original)
    if index_page:
        text = ensure_matome_section(text)
        text = ensure_popular_marker(text)
        text = text.replace('<h2>編集部まとめ記事</h2><a class="more" href="cat-sokuho.html">',
                            '<h2>編集部まとめ記事</h2><a class="more" href="articles.html">')
    if canonical:
        text = set_canonical(text, canonical)
    if manage_feed:
        text = ensure_markers(text, with_standings)
    if article_heading:
        text = ensure_article_markers(text, article_heading)
    for em in (extra_markers or []):
        if em["mode"] == "after":
            text = ensure_marker_after(text, em["anchor"], em["name"])
        else:
            text = ensure_marker_before(text, em["anchor"], em["name"])
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


# ------------------------------------------------------------- site config

def site_config():
    """data/site_config.json（無ければ既定値）。
      ga4_id      … GA4 の測定ID（G-XXXX）。空なら計測タグを入れない
      x_list_url  … クラブ公式XのリストURL。空なら x.html を作らない"""
    cfg = load("site_config.json", {}) or {}
    return {
        "ga4_id": (cfg.get("ga4_id") or "").strip(),
        "x_list_url": (cfg.get("x_list_url") or "").strip(),
    }


PER_PAGE = 20          # 一覧ページ1ページあたりの件数
TOP_ARTICLES = 20      # トップの「編集部まとめ記事」の件数
TOP_MATOME = 10        # トップの「ファンの反応・まとめブログ」の件数


# ------------------------------------------------------------------ paging

def page_file(base, n):
    return f"{base}.html" if n == 1 else f"{base}-{n}.html"


def chunk(items, per=PER_PAGE):
    return [items[i:i + per] for i in range(0, len(items), per)] or [[]]


def render_pager(base, n, total):
    """前へ／次へとページ番号。1ページしかなければ何も出さない。"""
    if total <= 1:
        return ""
    out = ['<nav class="pager" aria-label="ページ送り">']
    if n > 1:
        out.append(f'<a class="pg-prev" href="{page_file(base, n - 1)}" rel="prev">‹ 前へ</a>')
    for k in range(1, total + 1):
        if k == n:
            out.append(f'<span class="pg-cur" aria-current="page">{k}</span>')
        else:
            out.append(f'<a href="{page_file(base, k)}">{k}</a>')
    if n < total:
        out.append(f'<a class="pg-next" href="{page_file(base, n + 1)}" rel="next">次へ ›</a>')
    out.append("</nav>")
    return "".join(out)


def remove_stale_pages(base, total):
    """ページ数が減ったときに残った {base}-N.html を消す（自動生成分のみ）。"""
    pat = re.compile(re.escape(base) + r"-(\d+)\.html$")
    for fn in os.listdir(ROOT):
        m = pat.fullmatch(fn)
        if m and int(m.group(1)) > total:
            os.remove(os.path.join(ROOT, fn))
            log(f"削除: {fn}")


def write_if_changed(filename, content):
    path = os.path.join(ROOT, filename)
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if old != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"更新: {filename}")
        return True
    return False


def set_canonical(text, filename):
    """canonical と og:url を自分自身のURLにする（無ければ canonical を追加）。"""
    url = SITE_URL + ("" if filename == "index.html" else filename)
    if re.search(r'<link rel="canonical"[^>]*>', text):
        text = re.sub(r'<link rel="canonical"[^>]*>', f'<link rel="canonical" href="{url}">', text)
    elif "</head>" in text:
        text = text.replace("</head>", f'<link rel="canonical" href="{url}">\n</head>', 1)
    return re.sub(r'<meta property="og:url"[^>]*>', f'<meta property="og:url" content="{url}">', text)


def page_title(text, n):
    if n == 1:
        return text
    return re.sub(r"<title>(.*?)｜", lambda m: f"<title>{m.group(1)}（{n}ページ目）｜", text, count=1)


# ------------------------------------------------------------ list pages

HEADER_HTML = (
    '<header class="hdr"><div class="hdr-in"><a class="logo" href="index.html"><span class="mk">'
    '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" '
    'r="9" fill="#fff"/><path d="M12 3v18M3 12h18M6.2 5.2a13 13 0 000 13.6M17.8 5.2a13 13 0 010 13.6" '
    'stroke="#e2360b" stroke-width="1.3"/></svg></span><span class="wm"><span class="t">バスケ<em>まとめ'
    '</em></span><span class="sub">非公式ファンサイト</span></span></a><nav class="gnav">'
    '<a href="index.html">最新</a><a href="cat-kekka.html">試合結果</a><a href="cat-sokuho.html">速報</a>'
    '<a href="cat-iseki.html">移籍情報</a><a href="cat-data.html">順位・日程</a>'
    '<a href="matome.html">まとめ</a></nav></div></header>'
)

LIST_PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}｜バスケまとめ</title>
<meta name="description" content="{desc}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{site}{file}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%230d1b2a'/><circle cx='16' cy='16' r='9' fill='%23ff5a1f'/><path d='M16 7v18M7 16h18M10 8.4a13 13 0 000 15.2M22 8.4a13 13 0 010 15.2' stroke='%230d1b2a' stroke-width='1.4' fill='none'/></svg>">
<link rel="stylesheet" href="style.css?v=5">
<link rel="stylesheet" href="auto.css?v={ver}">
</head>
<body>
{header}
<main class="wrap">
  <div class="sec-h"><span class="bar"></span><h2>{heading}</h2></div>
  <p class="note">{note}</p>
  <div class="feed">
<!-- AUTO:FEED:START -->
{feed}
<!-- AUTO:FEED:END -->
  </div>
{pager}
  <div class="upd">最終更新: <!-- AUTO:UPDATED:START -->{updated}<!-- AUTO:UPDATED:END --></div>
</main>
<footer class="ft"><div class="ft-in"><a href="about.html">このサイトについて</a><a href="privacy.html">プライバシーポリシー</a><a href="contact.html">お問い合わせ</a><span class="cp">© 2026 バスケまとめ（非公式）. 見出しと出典リンクのみを掲載しています。</span></div></footer>
</body>
</html>
"""


def write_list_pages(base, rows, render, title, desc, heading, note, updated):
    """rows を PER_PAGE 件ずつ {base}.html, {base}-2.html … に書き出す。"""
    pages = chunk(rows)
    changed = False
    for n, part in enumerate(pages, 1):
        fn = page_file(base, n)
        t = title if n == 1 else f"{title}（{n}ページ目）"
        content = LIST_PAGE.format(
            title=esc(t), desc=esc(desc), site=SITE_URL, file=fn, ver=CSS_VER,
            header=HEADER_HTML, heading=esc(heading), note=note, feed=render(part),
            pager=render_pager(base, n, len(pages)), updated=esc(updated),
        )
        changed |= write_if_changed(fn, content)
    remove_stale_pages(base, len(pages))
    return changed


def write_news_pages(news, updated):
    return write_list_pages(
        "news", news, lambda part: render_feed(part, grouped=True),
        "新着ニュース一覧",
        "B.LEAGUE公式・バスケ専門メディアの最新ニュースを自動でまとめた一覧。1日4回更新。",
        "新着ニュース一覧",
        "B.LEAGUE公式サイトとバスケ専門メディアの新着を自動で収集しています。"
        "見出しをタップすると配信元の記事が開きます。",
        updated)


def write_matome_pages(matome, updated):
    return write_list_pages(
        "matome", matome, lambda part: render_matome(part, grouped=True),
        "ファンの反応・まとめブログ新着",
        "バスケ系まとめブログの新着見出しへのリンク集。国内バスケ中心、海外は日本人選手と"
        "スター選手の話題のみ。本文は転載していません。",
        "ファンの反応・まとめブログ",
        "バスケ系まとめブログの新着見出しへのリンクです（本文は転載していません）。"
        "国内バスケの話題と、海外は日本人選手・スター選手の話題だけを載せています。"
        "見出しをタップすると配信元のブログが開きます。",
        updated)


def write_article_pages(articles, updated):
    return write_list_pages(
        "articles", articles, render_articles,
        "編集部まとめ記事 一覧",
        "バスケまとめ編集部が書いたまとめ記事の一覧（新しい順）。",
        "編集部まとめ記事 一覧",
        "試合結果・速報・移籍情報・データのまとめ記事を新しい順に並べています。",
        updated)


def render_matome(items, limit=None, grouped=False):
    """まとめブログの見出し一覧（.item.ext と同じ見た目。出典ブログ名を表示）。"""
    if not items:
        return '<p class="note">現在取得できた新着はありません。</p>'
    html_ = render_feed(items, limit=limit, grouped=grouped)
    return html_.replace('rel="noopener nofollow"', 'rel="nofollow noopener"')


MATOME_SECTION = """      <!-- ファンの反応・まとめブログ（scripts/build.py が生成） -->
      <div class="sec-h"><span class="bar"></span><h2>ファンの反応・まとめブログ</h2><a class="more" href="matome.html">もっと見る ›</a></div>
      <p class="note auto-note">バスケ系まとめブログの新着見出しへのリンクです（本文は転載していません）。タップすると配信元が開きます。</p>
      <div class="feed">
<!-- AUTO:MATOME:START -->
<!-- AUTO:MATOME:END -->
      </div>

"""


def ensure_matome_section(text):
    if "<!-- AUTO:MATOME:START -->" in text:
        return text
    anchor = "      <!-- pickup -->"
    if anchor not in text:
        return text
    return text.replace(anchor, MATOME_SECTION + anchor, 1)


# ------------------------------------------------- category pages (paged)

def update_category(cat, page, news, articles, standings, updated):
    subset = [n for n in news if n.get("category") == cat]
    rows = [a for a in articles if a["cat"] == cat]
    parts = chunk(rows)
    base = page[:-5]
    total = len(parts)

    def regions(n):
        r = {
            "FEED": render_feed(subset, limit=40, grouped=True) if n == 1 else
            ('<p class="note">最新ニュースは<a href="{}">1ページ目</a>に載せています。</p>'.format(page)),
            "ARTICLES": (render_articles(parts[n - 1], category=cat)
                         + "\n" + render_pager(base, n, total)),
            "UPDATED": esc(updated),
        }
        if cat == "data":
            r["STANDINGS_FULL"] = render_standings_table(standings)
        return r

    changed = update_file(page, regions(1), with_standings=(cat == "data"),
                          article_heading=CATEGORY_LABEL[cat], canonical=page)
    with open(os.path.join(ROOT, page), encoding="utf-8") as f:
        first = f.read()
    for n in range(2, total + 1):
        text = first
        for name, body in regions(n).items():
            text, _ = replace_region(text, name, body)
        fn = page_file(base, n)
        changed |= write_if_changed(fn, set_canonical(page_title(text, n), fn))
    remove_stale_pages(base, total)
    return changed


# ------------------------------------------------- nav / GA / PV / popular

NAV_EXTRA = [("matome.html", "まとめ"), ("next-games.html", "次戦"), ("injury.html", "IL・復帰")]


def ensure_nav(text, x_enabled):
    """全ページ共通のグローバルナビに「まとめ」（と設定時は「クラブX」）を入れる。"""
    m = re.search(r'(<nav class="gnav">)(.*?)(\s*)(</nav>)', text, re.DOTALL)
    if not m:
        return text
    inner = m.group(2)
    ws = m.group(3)
    indent = ws if "\n" in ws else ""
    links = list(NAV_EXTRA) + ([("x.html", "クラブX")] if x_enabled else [])
    if not x_enabled:
        inner = re.sub(r'\s*<a href="x\.html"[^>]*>[^<]*</a>', "", inner)
    for href, label in links:
        if f'href="{href}"' not in inner:
            inner += (indent + "  " if indent else "") + f'<a href="{href}">{label}</a>'
    return text[:m.start()] + m.group(1) + inner + ws + m.group(4) + text[m.end():]


def ga_snippet(ga_id):
    return (
        '<!-- AUTO:GA:START -->\n'
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={esc(ga_id)}"></script>\n'
        '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}'
        f"gtag('js',new Date());gtag('config','{esc(ga_id)}');</script>\n"
        '<!-- AUTO:GA:END -->\n'
    )


def ensure_ga(text, ga_id):
    """GA4 の計測タグ。測定IDが設定されていれば head に入れ、無ければ取り除く。"""
    text = re.sub(r"<!-- AUTO:GA:START -->.*?<!-- AUTO:GA:END -->\n?", "", text, flags=re.DOTALL)
    if ga_id and "</head>" in text:
        text = text.replace("</head>", ga_snippet(ga_id) + "</head>", 1)
    return text


def load_pv():
    pv = load("pv.json", {}) if os.path.exists(os.path.join(DATA_DIR, "pv.json")) else {}
    return {"total": (pv or {}).get("total") or {}, "week": (pv or {}).get("week") or {}}


def pv_of(table, fn):
    return int(table.get("/" + fn, 0)) + int(table.get(fn, 0))


def ensure_pv(text, views):
    """記事の pmeta（日付の横）に閲覧数を差し込む。本文には触れない。"""
    body = f'<span class="pv">{views:,} views</span>' if views else ""
    if "<!-- AUTO:PV:START -->" not in text:
        if not body:
            return text
        m = re.search(r'(<div class="pmeta">.*?)(</div>)', text, re.DOTALL)
        if not m:
            return text
        text = (text[:m.end(1)] + "<!-- AUTO:PV:START --><!-- AUTO:PV:END -->"
                + text[m.end(1):])
    return re.sub(r"<!-- AUTO:PV:START -->.*?<!-- AUTO:PV:END -->",
                  lambda _: f"<!-- AUTO:PV:START -->{body}<!-- AUTO:PV:END -->",
                  text, count=1, flags=re.DOTALL)


def render_popular(articles, week, n=5):
    """サイドバー「人気記事ランキング（週間）」。PVデータが無ければ None。"""
    ranked = sorted(((pv_of(week, a["href"]), a) for a in articles),
                    key=lambda x: -x[0])
    ranked = [(v, a) for v, a in ranked if v > 0][:n]
    if not ranked:
        return None
    rows = ['<h4>人気記事ランキング（週間）</h4>']
    for i, (v, a) in enumerate(ranked, 1):
        title = a["title"] if len(a["title"]) <= 30 else a["title"][:29] + "…"
        rows.append('<div class="rank"><span class="n{top}">{i}</span><a href="{href}">{t}</a></div>'
                    .format(top=" top" if i == 1 else "", i=i, href=esc(a["href"]), t=esc(title)))
    return "\n".join(rows)


def ensure_popular_marker(text):
    """index.html の人気記事カードを AUTO:POPULAR で囲む（一度だけ）。"""
    if "<!-- AUTO:POPULAR:START -->" in text:
        return text
    m = re.search(r'(<div class="card">\s*)(<h4>人気記事ランキング.*?)(\s*</div>\s*\n\s*<div class="card">)',
                  text, re.DOTALL)
    if not m:
        return text
    return (text[:m.start(2)] + "<!-- AUTO:POPULAR:START -->\n" + m.group(2)
            + "\n<!-- AUTO:POPULAR:END -->" + text[m.end(2):])


# ---------------------------------------------------------------- X list

X_PAGE_BODY = """  <div class="sec-h"><span class="bar"></span><h2>クラブ公式Xの最新ポスト</h2></div>
  <p class="note">B.PREMIER全クラブの公式アカウントと注目選手のポストを、X公式の埋め込みで表示しています。表示されない場合は<a href="{url}" target="_blank" rel="nofollow noopener">Xでリストを開く</a>からご覧ください。</p>
  <a class="twitter-timeline" data-lang="ja" data-height="1600" data-dnt="true" href="{url}">クラブ公式Xのリストを見る</a>
  <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
"""


def write_x_page(url, updated):
    """クラブ公式Xのリストを埋め込んだ x.html。リストURL未設定なら作らない（あれば消す）。"""
    path = os.path.join(ROOT, "x.html")
    if not url:
        if os.path.exists(path):
            os.remove(path)
            log("削除: x.html（リストURL未設定）")
        return False
    content = LIST_PAGE.format(
        title="クラブ公式Xの最新ポスト", site=SITE_URL, file="x.html", ver=CSS_VER,
        desc="B.PREMIER全クラブ公式と注目選手のXの最新ポストをまとめて表示。",
        header=HEADER_HTML, heading="クラブ公式Xの最新ポスト", note="", feed="", pager="",
        updated=esc(updated))
    content = re.sub(
        r'  <div class="sec-h">.*?</div>\n  <p class="note"></p>\n  <div class="feed">.*?  </div>\n',
        lambda _: X_PAGE_BODY.format(url=esc(url)), content, count=1, flags=re.DOTALL)
    return write_if_changed("x.html", content)


def render_x_side(url):
    if not url:
        return ""
    return (
        '<div class="card"><h4>クラブ公式Xの最新ポスト</h4>'
        f'<a class="twitter-timeline" data-lang="ja" data-tweet-limit="5" data-chrome="noheader nofooter" '
        f'data-dnt="true" href="{esc(url)}">クラブ公式Xのポストを見る</a>'
        '<script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>'
        f'<div style="margin-top:8px"><a class="more" href="x.html" style="font-size:13px">もっと見る ›</a> ・ '
        f'<a href="{esc(url)}" target="_blank" rel="nofollow noopener" style="font-size:13px">Xでリストを開く</a></div>'
        '</div>'
    )


# --------------------------------------------------------------- sitemap etc

def site_pages():
    """公開ページ（Search Console の確認用ファイルなどは除く）。"""
    return sorted(f for f in os.listdir(ROOT)
                  if f.endswith(".html") and not f.startswith("google"))


def write_sitemap():
    pages = site_pages()
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


def finalize_pages(cfg, pv):
    """全ページ共通の後処理：グローバルナビ・GA4タグ・記事の閲覧数。"""
    changed = False
    for fn in site_pages():
        path = os.path.join(ROOT, fn)
        with open(path, encoding="utf-8") as f:
            original = f.read()
        text = ensure_nav(original, bool(cfg["x_list_url"]))
        text = ensure_ga(text, cfg["ga4_id"])
        if fn.startswith("article-"):
            text = ensure_pv(text, pv_of(pv["total"], fn))
        if text != original:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            changed = True
    return changed


# --------------------------------------------------------------------- main

def main():
    news = load("news.json", [])
    matome = load("matome.json", []) if os.path.exists(
        os.path.join(DATA_DIR, "matome.json")) else []
    standings = load("standings.json", {})
    cfg = site_config()
    pv = load_pv()
    updated = datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")

    if not news:
        log("!! ニュースデータが空です。生成を中止します")
        return 1

    log(f"ニュース {len(news)}件 / まとめブログ {len(matome)}件 / 更新日時 {updated}")

    articles = read_articles()
    log(f"手書き記事 {len(articles)}件を一覧化")

    changed = False

    # トップページ
    index_regions = {
        "TICKER": render_ticker(news),
        "FEED": render_feed(news, limit=12),
        "MATOME": render_matome(matome, limit=TOP_MATOME),
        "HERO": render_hero(articles),
        "VIDEO": render_video(),
        "ARTICLES": render_articles(articles[:TOP_ARTICLES]),
        "PICKS": render_picks(articles),
        "STANDINGS": render_standings_card(standings),
        "AFFILIATE": render_affiliate(),
        "XSIDE": render_x_side(cfg["x_list_url"]),
        "UPDATED": esc(updated),
    }
    popular = render_popular(articles, pv["week"])
    if popular:
        index_regions["POPULAR"] = popular
    changed |= update_file("index.html", index_regions,
                           article_heading="編集部まとめ記事",
                           extra_markers=[{"mode": "after", "anchor": '<aside class="side">',
                                           "name": "AFFILIATE"},
                                          {"mode": "before", "anchor": '      <div class="card">\n        <h4>カテゴリ</h4>',
                                           "name": "XSIDE"}],
                           index_page=True)

    # カテゴリページ（記事は20本ずつページ分け）
    for cat, page in CATEGORY_PAGE.items():
        changed |= update_category(cat, page, news, articles, standings, updated)

    # 記事ページにアフィリエイト枠を差し込む（全 article-*.html。手書き本文は保持）
    aff_html = render_affiliate()
    for fn in sorted(os.listdir(ROOT)):
        if fn.startswith("article-") and fn.endswith(".html"):
            changed |= update_file(
                fn, {"AFFILIATE": aff_html},
                manage_feed=False,
                extra_markers=[{"mode": "before", "anchor": "</article>",
                                "name": "AFFILIATE"}])

    # 一覧ページ（20件ずつ）
    changed |= write_news_pages(news, updated)
    changed |= write_matome_pages(matome, updated)
    changed |= write_article_pages(articles, updated)
    changed |= write_x_page(cfg["x_list_url"], updated)

    changed |= finalize_pages(cfg, pv)
    write_sitemap()

    log("完了" if changed else "完了（内容に変化なし）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
