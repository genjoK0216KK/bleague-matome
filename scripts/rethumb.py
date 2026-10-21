#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
既存記事のサムネイルを、スコアボード風デザイン（scripts/thumbgen.py）で作り直す。

  python3 scripts/rethumb.py            # 全記事のサムネを作り直す
  python3 scripts/rethumb.py --list     # 作り直す内容を一覧表示するだけ

- 試合結果の記事のうち、記事のタイトル・説明文・旧サムネで勝敗とスコアが確かめられる
  ものは GAMES に手で書いた内容で「試合結果」デザインにする（推測でスコアを作らない）。
- それ以外は旧サムネの見出し（ラベル・1行目・2行目・3行目）をそのまま使い、
  「速報など」のデザインにする。チーム色は見出しに出てくるクラブの色。
- 記事本文やファイル名には触れない（eyecatch が指す SVG を上書きするだけ）。
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True

import thumbgen  # noqa: E402

JAPAN = "#bc002d"

# 記事ファイル → 試合結果サムネの内容（タイトル・説明文・旧サムネの数字で確認済み）
GAMES = {
    "article-daily-20260816.html": dict(home="日本", away="韓国", home_score=88, away_score=68, meta="男子日本代表  強化試合", star="八村塁", star_stat="22PTS"),
    "article-daily-20260817.html": dict(home="日本", away="韓国", home_score=95, away_score=66, meta="男子日本代表  強化試合", star="河村勇輝", star_stat="24PTS"),
    "article-daily-20260824.html": dict(home="神戸", away="千葉J", home_score=95, away_score=100, meta="プレシーズン  KOBE RISING", star="千葉ジェッツが接戦制す", star_stat=""),
    "article-daily-20260828.html": dict(home="日本", away="サウジアラビア", home_score=106, away_score=78, meta="W杯予選  WINDOW4", star="八村塁", star_stat="29PTS"),
    "article-daily-20260830.html": dict(home="佐賀", away="長崎", home_score=89, away_score=85, meta="プレシーズンマッチ", star="新加入ナシール・リトルが躍動", star_stat=""),
    "article-daily-20260901.html": dict(home="日本", away="カタール", home_score=123, away_score=70, meta="W杯予選  WINDOW4", star="八村塁", star_stat="30PTS"),
    "article-daily-20260906.html": dict(home="日本", away="ドイツ", home_score=58, away_score=74, meta="女子W杯2026", star="最終戦はスペイン戦へ", star_stat=""),
    "article-daily-20260908.html": dict(home="日本", away="スペイン", home_score=59, away_score=79, meta="女子W杯2026", star="A組3位でハンガリー戦へ", star_stat=""),
    "article-daily-20260909.html": dict(home="日本", away="ハンガリー", home_score=63, away_score=84, meta="女子W杯2026", star="47年ぶりの8強ならず", star_stat=""),
    "article-daily-20260911.html": dict(home="日本", away="インドネシア", home_score=98, away_score=53, meta="アジア競技大会2026", star="津屋一球", star_stat="23PTS"),
    "article-daily-20260912.html": dict(home="日本", away="サウジアラビア", home_score=86, away_score=80, meta="アジア競技大会2026", star="カーク", star_stat="23PTS 10REB"),
    "article-daily-20260914.html": dict(home="日本", away="韓国", home_score=83, away_score=100, meta="アジア競技大会2026", star="黒川虎徹", star_stat="21PTS"),
    "article-daily-20260917.html": dict(home="日本", away="チャイニーズ・タイペイ", home_score=85, away_score=78, meta="アジア競技大会2026  準々決勝", star="黒川虎徹", star_stat="23PTS"),
    "article-daily-20260919.html": dict(home="日本", away="中国", home_score=97, away_score=78, meta="アジア競技大会2026  準決勝", star="64年ぶり決勝進出", star_stat=""),
    "article-daily-20260923.html": dict(home="A東京", away="琉球", home_score=84, away_score=73, meta="B.PREMIER  開幕戦", star="新加入ホグ&ジョンソンが52得点", star_stat=""),
    "article-daily-20260924.html": dict(home="A東京", away="琉球", home_score=74, away_score=85, meta="B.PREMIER  開幕週", star="ヌワバ", star_stat="27PTS 14REB"),
    "article-daily-20260925.html": dict(home="群馬", away="A千葉", home_score=76, away_score=74, meta="B.PREMIER  開幕週", star="ジョンソンが逆転ブザービーター", star_stat=""),
    "article-daily-20260926.html": dict(home="京都", away="滋賀", home_score=95, away_score=94, meta="B.PREMIER  京滋ダービー", star="岸本隆一が残り3.6秒で逆転3P", star_stat=""),
    "article-daily-20260927.html": dict(home="東京SR", away="千葉J", home_score=95, away_score=79, meta="B.PREMIER  開幕週", star="ホーキンソン", star_stat="22PTS 16REB"),
    "article-daily-20260928.html": dict(home="宇都宮", away="横浜BC", home_score=71, away_score=74, meta="B.PREMIER  第2週", star="並里成が土壇場で12得点", star_stat=""),
    "article-daily-20261003.html": dict(home="千葉J", away="A東京", home_score=131, away_score=138, meta="B.PREMIER  4OT", star="史上2度目のクアドラプルOT", star_stat=""),
    "article-daily-20261004.html": dict(home="富山", away="宇都宮", home_score=77, away_score=67, meta="B.PREMIER  YKK APアリーナ", star="新アリーナこけら落としで白星", star_stat=""),
    "article-daily-20261005.html": dict(home="島根", away="名古屋D", home_score=80, away_score=90, meta="B.PREMIER", star="ヘンリー", star_stat="25PTS"),
    "article-daily-20261008.html": dict(home="島根", away="北海道", home_score=95, away_score=83, meta="B.PREMIER", star="デニス", star_stat="30PTS"),
    "article-daily-20261009.html": dict(home="群馬", away="琉球", home_score=76, away_score=65, meta="B.PREMIER", star="群馬が開幕5連勝", star_stat=""),
    "article-daily-20261010.html": dict(home="富山", away="東京SR", home_score=96, away_score=90, meta="B.PREMIER  OT", star="最大29点差の大逆転", star_stat=""),
    "article-daily-20261011.html": dict(home="広島", away="滋賀", home_score=111, away_score=105, meta="B.PREMIER  3OT", star="トリプルOTで開幕6連勝", star_stat=""),
    "article-daily-20261012.html": dict(home="茨城", away="名古屋D", home_score=78, away_score=90, meta="B.PREMIER  アダストリアみとアリーナ", star="齋藤拓実", star_stat="21PTS 10AST"),
    # 2026-10-20 追加：タイトル「…釜山KCCに83-98」と旧サムネ（長崎 83／釜山KCC 98）で確認。並びは旧サムネのまま
    "article-daily-20261016.html": dict(home="長崎", away="釜山KCC", home_score=83, away_score=98, meta="EASL  10.15  アウェイ", star="釜山KCC外国籍デュオ", star_stat="2人で62PTS"),
}

NATIONAL_RE = re.compile(r"女子日本代表|男子日本代表|日本代表|3x3女子日本代表")


def read_article(fn):
    with open(os.path.join(ROOT, fn), encoding="utf-8") as f:
        t = f.read()
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", t, re.DOTALL)
    img = re.search(r'<img[^>]*class="eyecatch"[^>]*>', t)
    src = re.search(r'src="([^"]+)"', img.group(0)).group(1) if img else ""
    pm = re.search(r'<div class="pmeta">(.*?)</div>', t, re.DOTALL)
    date = re.search(r"\d{4}\.\d{2}\.\d{2}", pm.group(1)).group(0) if pm else ""
    return re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else "", src, date


def old_lines(svg_path):
    """旧サムネの文字（ラベル・見出し行）。ブランド表記は除く。"""
    try:
        with open(svg_path, encoding="utf-8") as f:
            svg = f.read()
    except OSError:
        return []
    texts = [thumbgen.html.unescape(t).strip()
             for t in re.findall(r"<text[^>]*>([^<]*)</text>", svg)]
    return [t for t in texts if t and t != "バスケまとめ"]


def club_in(title):
    """見出しのクラブ（正式名称）。見出しの先頭が主語のクラブならそれ、1クラブだけならそれ、
    複数のクラブが並ぶまとめ記事なら "B.PREMIER"。"""
    found = {}
    for c in thumbgen.json.load(open(thumbgen.COLORS_PATH, encoding="utf-8"))["clubs"]:
        pos = [title.find(k) for k in (c["name"], c["short"]) if k in title]
        if pos:
            found[c["name"]] = min(pos)
    if not found:
        return None
    first = min(found, key=found.get)
    if len(found) == 1 or found[first] <= 1:
        return first
    return "B.PREMIER"


def plan(fn):
    title, src, date = read_article(fn)
    if not src:
        return None, None
    if fn in GAMES:
        d = dict(type="game", **GAMES[fn])
        for side in ("home", "away"):
            if d[side] == "日本":
                d[f"{side}_color"] = JAPAN
        return src, d
    with open(os.path.join(ROOT, src), encoding="utf-8") as f:
        current = f.read()
    if "font-family:'BC'" in current or 'fill="#e8552b"' in current:
        return None, None   # すでに新デザイン（旧サムネの見出しを読み直せないので触らない）
    lines = old_lines(os.path.join(ROOT, src))
    label = lines[0] if lines and len(lines[0]) <= 6 else "速報"
    body = lines[1:] if lines and len(lines[0]) <= 6 else lines
    headline = body[0] if body else title[:12]
    sub = body[1] if len(body) > 1 else ""
    m = NATIONAL_RE.search(title)
    club = club_in(title)
    team = club or (m.group(0) if m else "B.LEAGUE")
    d = dict(type="news", label=label, team=team, headline=headline, sub=sub,
             facts=[["ポイント", body[2]]] if len(body) > 2 else [["日付", date]])
    if not club and m:
        d["team_color"] = JAPAN
    return src, d


def main(argv):
    thumbgen.FONT = "" if "--list" in argv else thumbgen.embed_font()
    files = sorted(f for f in os.listdir(ROOT)
                   if f.startswith("article-") and f.endswith(".html")
                   and not f.startswith("article-stats-"))   # 貢献度ランキングは stats.py が作る
    for fn in files:
        src, d = plan(fn)
        if not src:
            print(f"skip {fn}（eyecatch なし／作り直し済み）")
            continue
        if "--list" in argv:
            print(fn, "→", src, d)
            continue
        with open(os.path.join(ROOT, src), "w", encoding="utf-8") as f:
            f.write(thumbgen.render(d))
    if "--list" not in argv:
        print(f"{len(files)} 本のサムネを作り直しました")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
