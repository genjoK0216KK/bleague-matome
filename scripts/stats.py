#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
バスケまとめ - 当日のスタッツリーダー（貢献度ランキング）生成

B.LEAGUE公式の試合詳細ページに埋め込まれたボックススコア（JSON）を集計し、
その日のB.PREMIER全試合の記録が確定した時点で次を生成する。

  data/stats/YYYY-MM-DD.json      … 集計結果
  article-stats-YYYYMMDD.html     … まとめ記事（貢献度TOP10・日本人TOP10・部門別リーダー）
  thumb-stats-YYYYMMDD.svg        … サムネイル
  stats.html                      … 最新日のスタッツリーダー

数値は公式記録をそのまま使い、推測で補わない。1試合でも記録が確定していなければ
その日は生成せず、次回の実行で再判定する。
"""

import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

try:
    from . import site_header
except ImportError:
    import site_header

JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATS_DIR = os.path.join(ROOT, "data", "stats")
STATE_PATH = os.path.join(STATS_DIR, "state.json")

SCHEDULE_URL = "https://www.bleague.jp/schedule/"
GAME_URL = "https://www.bleague.jp/game_detail/?ScheduleKey={key}"
UA = ("Mozilla/5.0 (compatible; BleagueMatomeBot/1.0; "
      "+https://basuke-matome.jp/about.html)")
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
SLEEP = 2.0
LOOKBACK_DAYS = 7          # 保存済みの結果を見直す日数（公式への追加取得はしないので取得量は増えない）
TOTAL_PERIOD = 18          # ボックススコアの「試合合計」行
TOP_N = 10

# The boxscore adapter has no verified nationality field. Names are never evidence.
def verified_japanese(player):
    return (player.get('nationality') == 'JPN'
            and player.get('nationality_verified') is True
            and str(player.get('nationality_source','')).startswith('https://www.bleague.jp/'))


def verified_japanese_rows(summary):
    return [p for p in summary.get('eff_top_jp',[]) if verified_japanese(p)]


def log(msg):
    print(f"[stats] {msg}", flush=True)


def esc(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def flag(v):
    return v is True or str(v).strip().lower() in ("true", "1")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def get(url):
    log(f"GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    time.sleep(SLEEP)
    return r.text


# ------------------------------------------------------------------ parsing

def extract_context(page):
    """試合ページのscriptから HomeBoxscores を含むJSONオブジェクトを取り出す。"""
    for s in BeautifulSoup(page, "html.parser").find_all("script"):
        txt = s.string or s.get_text() or ""
        if "HomeBoxscores" not in txt:
            continue
        for m in re.finditer(r"=\s*\{", txt):
            try:
                obj, _ = json.JSONDecoder().raw_decode(txt[m.end() - 1:])
            except ValueError:
                continue
            if isinstance(obj, dict) and "HomeBoxscores" in obj:
                return obj
    return None


def mmss_to_min(t):
    m = re.match(r"(\d+):(\d+)", str(t or ""))
    return round(int(m.group(1)) + int(m.group(2)) / 60, 1) if m else 0.0


def player_rows(rows, team_short, opp_short, won, key):
    out = []
    for r in rows or []:
        if num(r.get("Category")) != 1 or num(r.get("PeriodCategory")) != TOTAL_PERIOD:
            continue
        # PlayingFlg は「試合終了時にコート上にいたか」なので使わない。出場時間で判定する
        if mmss_to_min(r.get("PlayTime")) <= 0:
            continue
        name = (r.get("PlayerNameJ") or "").strip()
        if not name:
            continue
        fgm = num(r.get("PT2M")) + num(r.get("PT3M"))
        fga = num(r.get("PT2A")) + num(r.get("PT3A"))
        out.append({
            "name": name,
            "name_en": r.get("PlayerNameE") or "",
            "no": str(r.get("PlayerNo") or ""),
            "team": team_short,
            "team_full": r.get("TeamNameJ") or team_short,
            "opp": opp_short,
            "won": won,
            "key": key,
            "jp": None, "nationality": None, "nationality_verified": False,
            "min": mmss_to_min(r.get("PlayTime")),
            "pts": num(r.get("Point")),
            "reb": num(r.get("RB_TOT")),
            "ast": num(r.get("AS")),
            "stl": num(r.get("ST")),
            "blk": num(r.get("BS")),
            "tov": num(r.get("TO")),
            "fgm": fgm, "fga": fga,
            "tpm": num(r.get("PT3M")), "tpa": num(r.get("PT3A")),
            "ftm": num(r.get("FTM")), "fta": num(r.get("FTA")),
            "eff": num(r.get("EFF")),
            "pm": num(r.get("PLUSMINUS")),
        })
    return out


def parse_game(key, page):
    ctx = extract_context(page)
    if not ctx:
        return None
    g = ctx.get("Game") or {}
    ts = num(g.get("GameDateTime"))
    if ts:
        date = datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d")
    else:
        m = re.search(r"(\d+)", str(ctx.get("GameDateTime") or ""))
        date = (datetime.fromtimestamp(int(m.group(1)) / 1000, JST).strftime("%Y-%m-%d")
                if m else "")
    home, away = g.get("HomeTeamShortNameJ") or "", g.get("AwayTeamShortNameJ") or ""
    hs, as_ = num(g.get("HomeTeamScore")), num(g.get("AwayTeamScore"))
    same_day = sorted({k for k in re.findall(r"ScheduleKey=(\d+)", page)})
    game = {
        "key": str(key),
        "date": date,
        "convention": g.get("ConventionNameJ") or "",
        "ended": flag(g.get("GameEndedFlg")),
        "fixed": flag(g.get("RecordFixedFlg")),
        "home": home, "away": away,
        "home_full": g.get("HomeTeamNameJ") or home,
        "away_full": g.get("AwayTeamNameJ") or away,
        "home_score": hs, "away_score": as_,
        "ot": any(num(g.get(f"HomeTeamScore0{p}")) or num(g.get(f"AwayTeamScore0{p}"))
                  for p in range(5, 10)),
        "stadium": g.get("StadiumNameJ") or "",
        "same_day": same_day,
        "players": [],
    }
    if game["fixed"]:
        game["players"] = (
            player_rows(ctx.get("HomeBoxscores"), home, away, hs > as_, key)
            + player_rows(ctx.get("AwayBoxscores"), away, home, as_ > hs, key)
        )
    return game


def is_premier(game):
    return "PREMIER" in game.get("convention", "").upper()


# ------------------------------------------------------------------ ranking

def rank(players, key, n=TOP_N):
    return sorted(players, key=lambda p: (-p[key], -p["eff"], -p["pts"], -p["min"]))[:n]


def summarise(date, games):
    players = [p for g in games for p in g["players"]]
    return {
        "date": date,
        "generated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "games": [{k: g[k] for k in ("key", "home", "away", "home_full", "away_full",
                                     "home_score", "away_score", "ot", "stadium")}
                  for g in games],
        "eff_top": rank(players, "eff"),
        "eff_top_jp": rank([p for p in players if verified_japanese(p)], "eff"),
        "leaders": {k: rank(players, k, 3) for k in ("pts", "reb", "ast", "stl", "blk")},
        "player_count": len(players),
    }


# --------------------------------------------------------------- rendering

HEADER = site_header.render()
FOOTER = (
    '<footer class="ft"><div class="ft-in"><a href="about.html">このサイトについて</a>'
    '<a href="privacy.html">プライバシーポリシー</a><a href="contact.html">お問い合わせ</a>'
    '<span class="cp">© 2026 バスケまとめ（非公式）.</span></div></footer>'
)
FAVICON = site_header.BRAND_HEAD
SITE_URL = "https://basuke-matome.jp/"
LEADER_LABEL = {"pts": "得点", "reb": "リバウンド", "ast": "アシスト",
                "stl": "スティール", "blk": "ブロック"}


def jp_date(date):
    d = datetime.strptime(date, "%Y-%m-%d")
    return f"{d.month}月{d.day}日"


def eff_table(rows):
    if not rows:
        return '<p class="note">該当する選手がいません。</p>'
    head = ("<tr><th>順位</th><th>選手（チーム）</th><th>貢献度</th><th>得点</th>"
            "<th>リバウンド</th><th>アシスト</th><th>スティール</th><th>ブロック</th>"
            "<th>出場時間</th></tr>")
    body = []
    for i, p in enumerate(rows, 1):
        body.append(
            f"<tr><td>{i}</td><td>{esc(p['name'])}（{esc(p['team'])}）</td>"
            f"<td><strong>{p['eff']}</strong></td><td>{p['pts']}</td><td>{p['reb']}</td>"
            f"<td>{p['ast']}</td><td>{p['stl']}</td><td>{p['blk']}</td>"
            f"<td>{p['min']:.0f}分</td></tr>"
        )
    return ('<div class="tablewrap">\n<table>\n' + head + "\n" + "\n".join(body)
            + "\n</table>\n</div>")


def leaders_table(leaders):
    rows = []
    for k, label in LEADER_LABEL.items():
        top = leaders.get(k) or []
        if not top or top[0][k] <= 0:
            continue
        names = "、".join(f"{esc(p['name'])}（{esc(p['team'])}）{p[k]}" for p in top if p[k] > 0)
        rows.append(f"<tr><td>{label}</td><td>{names}</td></tr>")
    return ('<div class="tablewrap">\n<table>\n<tr><th>部門</th><th>上位3人</th></tr>\n'
            + "\n".join(rows) + "\n</table>\n</div>")


def games_table(games):
    rows = []
    for g in games:
        ot = "（延長）" if g.get("ot") else ""
        rows.append(f"<tr><td>{esc(g['home'])} vs {esc(g['away'])}{ot}</td>"
                    f"<td>{g['home_score']}－{g['away_score']}</td></tr>")
    return ('<div class="tablewrap">\n<table>\n<tr><th>対戦（ホーム vs アウェー）</th>'
            '<th>スコア</th></tr>\n' + "\n".join(rows) + "\n</table>\n</div>")


def source_links(games):
    return "<br>\n    ".join(
        f'<a href="{GAME_URL.format(key=g["key"])}" target="_blank" rel="noopener nofollow">'
        f'{GAME_URL.format(key=g["key"])}</a>' for g in games)


def body_sections(s):
    top, jp = s["eff_top"], verified_japanese_rows(s)
    first = top[0]
    lead = (f"{jp_date(s['date'])}に行われたりそなB.LEAGUE PREMIER(Bプレミア){len(s['games'])}試合の"
            f"ボックススコアから、貢献度（EFF）の上位選手をまとめました。この日の貢献度1位は"
            f"{esc(first['team'])}の{esc(first['name'])}で、{first['pts']}得点・{first['reb']}リバウンド・"
            f"{first['ast']}アシストを記録し、貢献度{first['eff']}をマークしました。")
    if jp:
        lead += (f"日本人選手のトップは{esc(jp[0]['team'])}の{esc(jp[0]['name'])}（貢献度{jp[0]['eff']}）"
                 f"でした。")
    nationality = (f'<h2>公式国籍確認済み・日本人選手 TOP{TOP_N}</h2>' + eff_table(jp) if jp else '<p class="note">国籍別ランキングは未掲載です。公式国籍情報を確認できない選手を名前から分類しません。</p>')
    return f"""<p class="lead">{lead}</p>

    <h2>貢献度ランキング TOP{TOP_N}</h2>
    {eff_table(top)}

    {nationality}

    <h2>部門別リーダー</h2>
    {leaders_table(s['leaders'])}

    <h2>この日の試合結果</h2>
    {games_table(s['games'])}

    <div class="note"><p style="margin:0"><strong>Q. 貢献度（EFF）とは？</strong><br>A. 得点・リバウンド・アシスト・スティール・ブロック・被ファウルを加算し、外したシュート数（フィールドゴール・フリースロー）、ターンオーバー・被ブロック・ファウルを減算した指標です。B.LEAGUE公式記録の値をそのまま掲載しています。<a href="https://www.bleague.jp/glossary/" rel="noopener nofollow">公式用語集</a>を参照してください。</p></div>"""


def page(title, desc, url, body):
    result = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}｜バスケまとめ</title>
<meta name="description" content="{esc(desc)}">
{FAVICON}
<meta property="og:type" content="article">
<meta property="og:url" content="{SITE_URL}{url}">
<link rel="stylesheet" href="style.css?v=4">
<link rel="stylesheet" href="auto.css?v=2">
</head>
<body>
{HEADER}
<main class="wrap">
  <article class="article">
{body}
  <!-- AUTO:AFFILIATE:START -->

<!-- AUTO:AFFILIATE:END -->
</article>
</main>
{FOOTER}
</body>
</html>
"""

    return site_header.enhance(result, url)


def article_title(s):
    top, jp = s["eff_top"][0], verified_japanese_rows(s)[:1]
    t = f"{jp_date(s['date'])}の貢献度ランキング 1位は{top['name']}（{top['team']}）の{top['eff']}"
    if jp:
        t += f" 日本人トップは{jp[0]['name']}"
    return t


def write_article(s):
    ymd = s["date"].replace("-", "")
    fn, thumb = f"article-stats-{ymd}.html", f"thumb-stats-{ymd}.svg"
    title = article_title(s)
    dot = s["date"].replace("-", ".")
    desc = (f"{jp_date(s['date'])}のB.LEAGUE PREMIER全{len(s['games'])}試合のボックススコアから、"
            f"貢献度（EFF）TOP{TOP_N}、得点・リバウンド・アシストなどの"
            f"部門別リーダーを公式記録をもとにまとめました。")
    body = f"""    <div class="breadcrumb"><a href="index.html">ホーム</a> ／ <a href="cat-data.html">順位・日程</a></div>
    <h1>{esc(title)}</h1>
    <div class="pmeta"><span class="tag data">順位・日程</span><span>{dot}</span><span>B.PREMIER / 貢献度ランキング</span></div>
    <img class="eyecatch" src="{thumb}" alt="{esc(jp_date(s['date']))}の貢献度ランキング">
    <div class="adbox">広告スペース（AdSense）</div>
    {body_sections(s)}

    <p class="source">出典：B.LEAGUE公式 試合詳細（ボックススコア）<br>
    {source_links(s['games'])}</p>
    <div class="note">本記事はB.LEAGUE公式記録を自動集計して作成しています。記録は公式の訂正により変わる場合があります。最新・正確な情報は出典元でご確認ください。</div>
    <div class="adbox">広告スペース（AdSense）</div>
    <div class="card" style="margin-top:24px"><h4>関連ページ</h4>
      <div class="rank"><span class="n">›</span><a href="stats.html">最新のスタッツリーダー</a></div>
      <div class="rank"><span class="n">›</span><a href="cat-data.html">順位・日程の一覧を見る</a></div>
    </div>"""
    with open(os.path.join(ROOT, fn), "w", encoding="utf-8") as f:
        f.write(page(title, desc, fn, body))
    with open(os.path.join(ROOT, thumb), "w", encoding="utf-8") as f:
        f.write(thumbnail(s))
    log(f"wrote {fn} / {thumb}")
    return fn


def thumbnail(s):
    """スコアボード風サムネ（scripts/thumbgen.py の「速報など」デザイン）。"""
    try:
        from . import thumbgen
    except ImportError:
        import thumbgen
    if not thumbgen.FONT:
        thumbgen.FONT = thumbgen.embed_font()
    top = s["eff_top"][0]
    jp = verified_japanese_rows(s)[:1]   # 記事タイトルと同じく、確認済みの日本人だけ
    d = {
        "type": "news",
        "label": "スタッツ",
        "team": f"B.PREMIER {jp_date(s['date'])} 全{len(s['games'])}試合",
        "team_color": thumbgen.team_color(top["team"]),
        "headline": "貢献度ランキング",
        "sub": f"1位 {top['name']}（{top['team']}） EFF {top['eff']}",
        "facts": ([["日本人1位", f"{jp[0]['name']}（{jp[0]['team']}） {jp[0]['eff']}"]]
                  if jp else [["集計", f"{s['player_count']}人"]]),
    }
    return thumbgen.render(d)


def status_block(s, notes):
    """表示中の集計の対象日と、より新しい日の保留・未取得の状況。旧結果は消さずに併記する。"""
    items = "".join(f"<li>{esc(n)}</li>" for n in notes)
    newer = (f'<p style="margin:6px 0 0">新しい日の状況：</p><ul style="margin:4px 0 0">{items}</ul>' if notes else "")
    return (f'<div class="note" id="stats-status"><p style="margin:0">表示中：{esc(jp_date(s["date"]))}の'
            f'B.PREMIER {len(s["games"])}試合（記録確定分）</p>{newer}</div>')


def write_stats_page(s, published, notes=()):
    title = f"スタッツリーダー（{jp_date(s['date'])}）貢献度ランキング"
    desc = "B.LEAGUE PREMIERの最新試合日の貢献度（EFF）ランキングと部門別リーダー。全試合の記録確定後に自動更新します。"
    archive = "\n".join(
        f'      <div class="rank"><span class="n">›</span><a href="article-stats-{d.replace("-", "")}.html">'
        f'{esc(jp_date(d))}（{d[:4]}年）の貢献度ランキング</a></div>'
        for d in sorted(published, reverse=True)[:30])
    body = f"""    <div class="breadcrumb"><a href="index.html">ホーム</a> ／ <a href="cat-data.html">順位・日程</a></div>
    <h1>{esc(title)}</h1>
    <div class="pmeta"><span class="tag data">順位・日程</span><span>{s['date'].replace('-', '.')}</span><span>最終更新 {esc(s['generated'])}</span></div>
    {status_block(s, notes)}
    {body_sections(s)}

    <p class="source">出典：B.LEAGUE公式 試合詳細（ボックススコア）<br>
    {source_links(s['games'])}</p>
    <div class="note">このページはB.LEAGUE公式記録を自動集計しています。その日の全試合の記録が確定してから更新されます。</div>
    <div class="card" style="margin-top:24px"><h4>過去の貢献度ランキング</h4>
{archive}
    </div>"""
    with open(os.path.join(ROOT, "stats.html"), "w", encoding="utf-8") as f:
        f.write(page(title, desc, "stats.html", body))
    log("wrote stats.html")


# --------------------------------------------------------------------- main

# 対象の定義（表示・記録で分けて持つ）
DEFINITION = {"league": "B.PREMIER", "competition": "BP", "metric": "EFF（公式記録の値）",
              "aggregation": "その日のB.PREMIER全試合の試合合計（出場時間0秒の選手は除く）"}
REASON_LABEL = {
    "record_not_fixed": "公式記録が未確定",
    "boxscore_missing": "ボックススコア未取得",
    "boxscore_team_mismatch": "ボックススコアのチームが試合と一致しない",
    "schedule_incomplete": "日程の取得が不完全",
}


def results_dir():
    return os.path.join(ROOT, "data", "match_articles")


def results_path(date):
    return os.path.join(results_dir(), f"article-games-{date.replace('-', '')}.json")


def verified_final(g):
    """結果側（preview_data.is_verified_final）と同じ条件。終了かつ記録確定・出典あり・得点が0以上の整数。"""
    def score(v):
        return isinstance(v, int) and not isinstance(v, bool) and v >= 0
    return (g.get("ended") is True and g.get("fixed") is True and bool(g.get("source"))
            and score(g.get("home_score")) and score(g.get("away_score")))


def game_from_result(date, g):
    """保存済みの確定結果（公式試合ページの記録）を集計用の形にする。再取得はしない。
    返り値：(game, None) または (None, 保留理由)。"""
    key = str(g["game_id"])
    if not verified_final(g):
        return None, "record_not_fixed"
    rows = [r for r in g.get("players") or []
            if num(r.get("Category")) == 1 and num(r.get("PeriodCategory")) == TOTAL_PERIOD]
    if not rows:
        return None, "boxscore_missing"
    home_id, away_id = str(g.get("home_id") or ""), str(g.get("away_id") or "")
    if any(str(r.get("TeamID") or "") not in (home_id, away_id) for r in rows):
        return None, "boxscore_team_mismatch"
    hs, as_ = g["home_score"], g["away_score"]
    home, away = g.get("home") or "", g.get("away") or ""
    players = (player_rows([r for r in rows if str(r.get("TeamID")) == home_id], home, away, hs > as_, key)
               + player_rows([r for r in rows if str(r.get("TeamID")) == away_id], away, home, as_ > hs, key))
    if not players:
        return None, "boxscore_missing"
    return {
        "key": key, "date": date, "convention": g.get("convention") or "",
        "ended": True, "fixed": True, "home": home, "away": away,
        "home_full": g.get("home_full") or home, "away_full": g.get("away_full") or away,
        "home_score": hs, "away_score": as_,
        "ot": None,          # 保存データに延長の有無が無いため不明（推測で付けない）
        "stadium": "", "same_day": [], "players": players,
    }, None


def assess_day(date, saved):
    """1日分の判定。saved が None なら「結果データ未取得」（0試合とは別）。"""
    if saved is None:
        return {"state": "not_retrieved", "games_total": None, "games_ready": None,
                "players": None, "holds": [], "excluded": [], "games": []}
    bp = [g for g in saved.get("games", []) if g.get("competition") == DEFINITION["competition"]]
    games, holds, excluded = [], [], []
    for g in sorted(bp, key=lambda x: str(x["game_id"])):
        if g.get("status") in ("cancelled", "postponed"):
            excluded.append({"key": str(g["game_id"]), "status": g["status"]})
            continue
        game, reason = game_from_result(date, g)
        if game:
            games.append(game)
        else:
            holds.append({"key": str(g["game_id"]), "home": g.get("home"), "away": g.get("away"),
                          "status": g.get("status"), "record_note": g.get("record_note"), "reason": reason})
    schedule_ok = (saved.get("schedule_complete") or {}).get(DEFINITION["competition"]) is True
    if not schedule_ok:
        state = "held"
        holds.insert(0, {"key": None, "reason": "schedule_incomplete"})
    elif holds:
        state = "held"
    elif not games:
        state = "no_games"
    else:
        state = "ready"
    return {"state": state, "games_total": len(bp) - len(excluded), "games_ready": len(games),
            "players": sum(len(g["players"]) for g in games) if state == "ready" else None,
            "holds": holds, "excluded": excluded, "games": games}


def content_as_of(date):
    """結果データ（ボックススコアを含む）を公式から取得した時点。result-status の記録だけを使う。"""
    status = load_json(os.path.join(results_dir(), "result-status.json"), {})
    return (status.get("dates", {}).get(date) or {}).get("content_as_of")


def comparable(summary):
    return {k: v for k, v in (summary or {}).items() if k not in ("generated",)}


def pending_note(days, newest):
    """表示中より新しい日が保留・未取得なら、その状況を書く（旧結果は残したまま）。"""
    notes = []
    for date in sorted(days, reverse=True):
        d = days[date]
        if newest and date <= newest:
            break
        if d["state"] == "held":
            waiting = [h for h in d["holds"] if h.get("key")]
            reasons = sorted({REASON_LABEL.get(h["reason"], h["reason"]) for h in d["holds"]})
            notes.append(f"{jp_date(date)}：集計待ち（B.PREMIER {d['games_total']}試合中 "
                         f"{len(waiting)}試合が{'・'.join(reasons)}）")
        elif d["state"] == "not_retrieved":
            notes.append(f"{jp_date(date)}：試合結果データが未取得のため未集計（0人・0試合という意味ではありません）")
    return notes


def use_root(root):
    """出力先を root 配下にする（update_results.py --root などと同じ場所に書く）。"""
    global ROOT, STATS_DIR, STATE_PATH
    ROOT = os.path.abspath(str(root))
    STATS_DIR = os.path.join(ROOT, "data", "stats")
    STATE_PATH = os.path.join(STATS_DIR, "state.json")


def run(now=None, root=None):
    """保存済みの確定結果（data/match_articles/article-games-*.json）から日別の貢献度ランキングを作る。
    公式サイトへの追加取得はしない（結果の取得・確定判定は update_results / update_match_features 側）。
    ニュース取得の成否には依存しない。戻り値は日別の判定（記録用）。"""
    if root is not None:
        use_root(root)
    now = (now or datetime.now(JST)).astimezone(JST)
    state = load_json(STATE_PATH, {"pending": {}, "published": []})
    published = set(state.get("published", []))
    today = now.date()
    dates = [(today - timedelta(days=n)).isoformat() for n in range(LOOKBACK_DAYS, -1, -1)]

    days, pending = {}, {}
    for date in dates:
        path = results_path(date)
        saved = load_json(path, None) if os.path.exists(path) else None
        day = assess_day(date, saved)
        record = {k: v for k, v in day.items() if k != "games"}
        record.update(content_as_of=content_as_of(date) if saved is not None else None,
                      source=os.path.relpath(path, ROOT).replace(os.sep, "/"))
        days[date] = record
        if day["state"] == "held":
            for h in day["holds"]:
                if h.get("key"):
                    pending[h["key"]] = date
            kept = "公開済みの確定分は維持" if date in published else "次回に持ち越し"
            log(f"{date}: 保留（{len(day['holds'])}件）{kept} " + json.dumps(day["holds"], ensure_ascii=False))
            continue
        if day["state"] != "ready":
            log(f"{date}: {day['state']}")
            continue
        summary = summarise(date, day["games"])
        summary.update(retrieved_at=record["content_as_of"], definition=DEFINITION, source="saved_results")
        if not summary["eff_top"]:
            continue
        out = os.path.join(STATS_DIR, f"{date}.json")
        stored = load_json(out, None)
        if comparable(stored) == comparable(summary):
            continue
        # 公開済みの日は、試合が増える時だけ作り直す（旧結果をそのまま残す・churn防止）。
        if date in published and stored and {g["key"] for g in day["games"]} <= {g["key"] for g in stored["games"]}:
            log(f"{date}: 公開済み（{len(stored['games'])}試合）を維持")
            continue
        save_json(out, summary)
        write_article(summary)
        published.add(date)
        log(f"{date}: 集計 {len(day['games'])}試合 / {summary['player_count']}人（公式記録の取得時点 {summary['retrieved_at']}）")

    newest = max(published) if published else None
    newest_summary = load_json(os.path.join(STATS_DIR, f"{newest}.json"), None) if newest else None
    if newest_summary:
        write_stats_page(newest_summary, published, pending_note(days, newest))

    state["pending"] = pending
    state["published"] = sorted(published)
    state["days"] = days
    state["definition"] = DEFINITION
    save_json(STATE_PATH, state)
    return days


def run_reported(now=None, root=None):
    """run() を呼び、日別の判定を Actions の注記に残す（ジョブログを読めなくても注記は読める）。
    集計の失敗は結果の保存を止めない（警告にとどめる）。"""
    try:
        days = run(now, root)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("::warning::Stats ranking failed type=" + type(exc).__name__ + " reason=" + str(exc)[:200])
        return {"error": type(exc).__name__}
    for date, d in sorted(days.items()):
        holds = ",".join(f"{h.get('key')}:{h['reason']}" for h in d["holds"])
        print(f"::notice::stats date={date} state={d['state']} games={d['games_ready']}/{d['games_total']} "
              f"players={d['players']} content_as_of={d['content_as_of']} holds={holds}")
    return {date: d["state"] for date, d in days.items()}


if __name__ == "__main__":
    run_reported()
