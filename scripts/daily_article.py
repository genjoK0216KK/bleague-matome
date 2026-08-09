#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bリーグまとめ - 毎日のまとめ記事をクラウド(GitHub Actions)で生成する。

data/news.json（fetch.pyが収集した見出し＋リンク）を材料に、Claude APIで
「その日の主役トピック」のまとめ記事を書き、article-daily-YYYYMMDD.html と
thumb-daily-YYYYMMDD.svg を生成する。build.py が一覧化・カード化する。

必要: 環境変数 ANTHROPIC_API_KEY。モデルは ANTHROPIC_MODEL（既定 claude-sonnet-5）。
"""

import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import anthropic

JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SITE = "https://genjok0216kk.github.io/bleague-matome/"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

CAT_LABEL = {"kekka": "試合結果", "sokuho": "速報", "iseki": "移籍情報", "data": "順位・日程"}
CAT_PAGE = {"kekka": "cat-kekka.html", "sokuho": "cat-sokuho.html",
            "iseki": "cat-iseki.html", "data": "cat-data.html"}


def log(m):
    print(f"[daily] {m}", flush=True)


def esc(t):
    return html.escape(str(t or ""), quote=True)


# ---------------------------------------------------------------- 生成

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": {"type": "string", "enum": ["kekka", "sokuho", "iseki", "data"]},
        "extra_label": {"type": "string"},
        "title": {"type": "string"},
        "meta_description": {"type": "string"},
        "thumb_line1": {"type": "string"},
        "thumb_line2": {"type": "string"},
        "lead": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"h2": {"type": "string"}, "body": {"type": "string"}},
                "required": ["h2", "body"],
            },
        },
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"name": {"type": "string"}, "url": {"type": "string"}},
                "required": ["name", "url"],
            },
        },
    },
    "required": ["category", "extra_label", "title", "meta_description",
                 "thumb_line1", "thumb_line2", "lead", "sections", "sources"],
}


def load_news():
    try:
        with open(os.path.join(DATA_DIR, "news.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def generate(news, date_dot):
    items = sorted(news, key=lambda x: x.get("date", ""), reverse=True)[:30]
    valid_urls = {i.get("url") for i in items}
    lines = [f"- [{i.get('date')}][{CAT_LABEL.get(i.get('category'),'速報')}] "
             f"{i.get('title')}  (出典:{i.get('source')} / {i.get('url')})"
             for i in items]
    news_block = "\n".join(lines)

    system = (
        "あなたは日本のバスケットボール「Bリーグ」まとめサイトの編集者です。"
        "初心者にも分かりやすく、簡潔で、煽らない日本語で書きます。"
        "与えられた見出しリストの範囲で裏が取れた事実だけを使い、スコアや人名などを創作しません。"
        "原文は転載せず、必ず自分の言葉で要約します。"
    )
    user = f"""本日は {date_dot} です。以下は自動収集した最新ニュースの見出しとリンクです。

{news_block}

この中から「本日の最も重要なトピック」を1つ選び、まとめ記事をJSONで出力してください。
- category: kekka(試合結果)/sokuho(速報)/iseki(移籍情報)/data(順位・日程) から主役トピックに合うものを1つ。
- extra_label: pmetaの補足ラベル（例「日本代表 / 速報」）。短く。
- title: 記事タイトル（末尾に「｜Bリーグ まとめ」は付けない）。
- meta_description: 120字程度の説明。
- thumb_line1 / thumb_line2: サムネ用の短い2行見出し（各16字程度まで）。
- lead: リード文（1段落）。
- sections: 3〜4個。各 h2 見出しと body（1〜2段落、段落は空行で区切る）。
- sources: 実際に参考にした見出しの name(媒体名) と url。**url は必ず上のリストにあるものだけ**。3件程度まで。
本文は見出しから読み取れる事実の範囲で。不確かなこと・憶測は書かない。"""

    resp = anthropic.Anthropic().messages.create(
        model=MODEL,
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA},
                       "effort": "low"},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("モデルが生成を拒否しました")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    data = json.loads(text)
    # 出典URLを収集済みリストに限定（創作URL防止）
    data["sources"] = [s for s in data.get("sources", []) if s.get("url") in valid_urls][:4]
    return data


# ---------------------------------------------------------------- 組み立て

HEAD = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}｜Bリーグ まとめ</title>
<meta name="description" content="{desc}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%230d1b2a'/><circle cx='16' cy='16' r='9' fill='%23ff5a1f'/><path d='M16 7v18M7 16h18M10 8.4a13 13 0 000 15.2M22 8.4a13 13 0 010 15.2' stroke='%230d1b2a' stroke-width='1.4' fill='none'/></svg>">
<meta property="og:type" content="article">
<meta property="og:url" content="{site}{fname}">
<link rel="stylesheet" href="style.css?v=4">
</head>
<body>
<header class="hdr"><div class="hdr-in"><a class="logo" href="index.html"><span class="mk"><svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" fill="#fff"/><path d="M12 3v18M3 12h18M6.2 5.2a13 13 0 000 13.6M17.8 5.2a13 13 0 010 13.6" stroke="#e2360b" stroke-width="1.3"/></svg></span><span class="wm"><span class="t">Bリーグ<em>まとめ</em></span><span class="sub">非公式ファンサイト</span></span></a><nav class="gnav"><a href="index.html">最新</a><a href="cat-kekka.html">試合結果</a><a href="cat-sokuho.html">速報</a><a href="cat-iseki.html">移籍情報</a><a href="cat-data.html">順位・日程</a></nav></div></header>
<main class="wrap">
  <article class="article">
"""

FOOTER = """  </article>
</main>
<footer class="ft"><div class="ft-in"><a href="about.html">このサイトについて</a><a href="privacy.html">プライバシーポリシー</a><a href="contact.html">お問い合わせ</a><span class="cp">© 2026 Bリーグ まとめ（非公式）.</span></div></footer>
</body>
</html>
"""

THUMB = """<svg viewBox="0 0 480 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{alt}">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#16b268"/><stop offset="1" stop-color="#0a6e3f"/></linearGradient></defs>
<rect width="480" height="300" fill="url(#g)"/>
<g stroke="#ffffff" stroke-width="3" fill="none" opacity="0.12">
<circle cx="384" cy="252" r="84"/><line x1="300" y1="120" x2="300" y2="300"/>
<path d="M300 168 a64 64 0 0 1 0 128"/><rect x="-30" y="46" width="118" height="150"/><circle cx="29" cy="121" r="48"/>
</g>
<g transform="translate(398,74)" opacity="0.16"><circle r="74" fill="#ffffff"/><path d="M-74 0H74 M0 -74V74 M-52 -52Q0 0 52 52 M52 -52Q0 0 -52 52" stroke="#0d1b2a" stroke-width="4" fill="none"/></g>
<rect x="28" y="26" rx="16" ry="16" width="120" height="34" fill="#ffffff"/>
<text x="88" y="49" font-family="'Hiragino Kaku Gothic ProN','Noto Sans JP','Yu Gothic',Meiryo,sans-serif" font-weight="800" font-size="17" fill="#0c7c46" text-anchor="middle" letter-spacing="1">{badge}</text>
<text x="30" y="192" font-family="'Hiragino Kaku Gothic ProN','Noto Sans JP','Yu Gothic',Meiryo,sans-serif" font-weight="900" font-size="32" fill="#ffffff">{l1}</text>
<text x="30" y="230" font-family="'Hiragino Kaku Gothic ProN','Noto Sans JP','Yu Gothic',Meiryo,sans-serif" font-weight="700" font-size="18" fill="#ffffff" opacity="0.94">{l2}</text>
<text x="454" y="284" font-family="'Hiragino Kaku Gothic ProN','Noto Sans JP','Yu Gothic',Meiryo,sans-serif" text-anchor="end" font-weight="800" font-size="13" fill="#ffffff" opacity="0.65">Bリーグ まとめ</text>
</svg>
"""


def build_html(d, date_dot, fname, thumb):
    cat = d["category"] if d["category"] in CAT_LABEL else "sokuho"
    label = CAT_LABEL[cat]
    body = [HEAD.format(title=esc(d["title"]), desc=esc(d["meta_description"]),
                        site=SITE, fname=fname)]
    body.append(f'    <div class="breadcrumb"><a href="index.html">ホーム</a> ／ {esc(label)}</div>')
    body.append(f'    <h1>{esc(d["title"])}</h1>')
    body.append(f'    <div class="pmeta"><span class="tag {cat}">{esc(label)}</span>'
                f'<span>{esc(date_dot)}</span><span>{esc(d["extra_label"])}</span></div>')
    body.append(f'    <img class="eyecatch" src="{thumb}" alt="{esc(d["title"])}">')
    body.append('    <div class="adbox">広告スペース（AdSense）</div>')
    body.append(f'    <p class="lead">{esc(d["lead"])}</p>')
    for s in d["sections"]:
        body.append(f'    <h2>{esc(s["h2"])}</h2>')
        for para in re.split(r"\n\s*\n", s["body"].strip()):
            if para.strip():
                body.append(f'    <p>{esc(para.strip())}</p>')
    if d["sources"]:
        names = " / ".join(sorted({esc(s["name"]) for s in d["sources"]}))
        links = "<br>".join(
            f'<a href="{esc(s["url"])}" target="_blank" rel="noopener nofollow">{esc(s["url"])}</a>'
            for s in d["sources"])
        body.append(f'    <p class="source">出典：{names}<br>{links}</p>')
    body.append('    <div class="note">本記事は各公式発表・報道をもとに編集部が独自に要約・再構成したものです。'
                '最新・正確な情報は出典元および各公式サイトでご確認ください。</div>')
    body.append('    <div class="adbox">広告スペース（AdSense）</div>')
    body.append('    <div class="card" style="margin-top:24px"><h4>関連記事</h4>'
                f'<div class="rank"><span class="n">›</span><a href="{CAT_PAGE[cat]}">{esc(label)}の一覧を見る</a></div>'
                '<div class="rank"><span class="n">›</span><a href="index.html">トップに戻る</a></div></div>')
    body.append(FOOTER)
    return "\n".join(body)


def main():
    now = datetime.now(JST)
    date_dot = now.strftime("%Y.%m.%d")
    date_file = now.strftime("%Y%m%d")
    fname = f"article-daily-{date_file}.html"
    thumb = f"thumb-daily-{date_file}.svg"

    if os.path.exists(os.path.join(ROOT, fname)):
        log(f"{fname} は既に存在。生成をスキップ。")
        return 0

    news = load_news()
    if not news:
        log("!! news.json が空。中止。")
        return 1
    log(f"ニュース {len(news)}件 / モデル {MODEL}")

    d = generate(news, date_dot)
    log(f"生成トピック: [{d['category']}] {d['title'][:40]}")

    with open(os.path.join(ROOT, thumb), "w", encoding="utf-8") as f:
        f.write(THUMB.format(alt=esc(d["title"]), badge=esc(CAT_LABEL.get(d["category"], "速報")),
                             l1=esc(d["thumb_line1"]), l2=esc(d["thumb_line2"])))
    with open(os.path.join(ROOT, fname), "w", encoding="utf-8") as f:
        f.write(build_html(d, date_dot, fname, thumb))
    log(f"作成: {fname} / {thumb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
