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
LOOKBACK_DAYS = 3          # これより古い未確定日は諦める
TOTAL_PERIOD = 18          # ボックススコアの「試合合計」行
TOP_N = 10

# 日本人選手かどうかは名前から推測しない。B.LEAGUE公式の選手ページ（roster_detail）の
# 「リーグ登録国籍」を data/players.json に記録して使い、確認できない選手は「未確認」として扱う。
PLAYERS_PATH = os.path.join(ROOT, "data", "players.json")
ROSTER_URL = "https://www.bleague.jp/roster_detail/?PlayerID={pid}"
JAPAN = {"日本", "JPN", "Japan", "JAPAN"}
PLAYERS_NOTE = ("選手の国籍（B.LEAGUE公式の選手ページ roster_detail の「リーグ登録国籍」欄）。key は PlayerID。stats.py が未登録の選手だけ取得して追記する。ここにない選手は「未確認」扱い。公式ページには「リーグ登録国籍は選手が有する国籍と異なる場合がございます」と注記がある。")


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
            "pid": str(r.get("PlayerID") or ""),
            "jp": None,                     # 国籍は apply_nationality() で公式登録から付ける
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


def parse_nationality(page):
    """roster_detail の HTML から「リーグ登録国籍」欄の値を取り出す。見つからなければ None。"""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    # 「リーグ登録国籍 アメリカ合衆国」の形。注記文「リーグ登録国籍は〜」は値として拾わない
    for m in re.finditer(r"リーグ登録国籍\s*[:：]?\s*([^\s/｜|]{1,20})", text):
        if not m.group(1).startswith("は"):
            return m.group(1)
    return None


def is_japanese(nationality):
    """True=日本国籍、False=日本以外、None=未確認。"""
    if not nationality:
        return None
    return nationality in JAPAN


def apply_nationality(players, registry, fetch=None, today=None):
    """registry（data/players.json の players）で各選手の jp を決める。
    未登録の選手は fetch(pid) で公式ページから国籍を取り、registry に追記する。"""
    today = today or datetime.now(JST).strftime("%Y-%m-%d")
    for p in players:
        pid = p.get("pid")
        rec = registry.get(pid) if pid else None
        if pid and rec is None and fetch:
            nat = None
            try:
                nat = parse_nationality(fetch(pid))
            except Exception as e:  # noqa: BLE001
                log(f"!! 国籍の取得に失敗 {pid} {p['name']}: {e}")
            if nat:
                rec = registry[pid] = {"name": p["name"], "team": p["team"],
                                       "nationality": nat,
                                       "source": ROSTER_URL.format(pid=pid),
                                       "checked": today}
        p["nationality"] = rec.get("nationality") if rec else None
        p["jp"] = is_japanese(p["nationality"])
    return players


def summarise(date, games):
    players = [p for g in games for p in g["players"]]
    unknown = [p for p in players if p.get("jp") is None]
    return {
        "date": date,
        "generated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "games": [{k: g[k] for k in ("key", "home", "away", "home_full", "away_full",
                                     "home_score", "away_score", "ot", "stadium")}
                  for g in games],
        "eff_top": rank(players, "eff"),
        "eff_top_jp": rank([p for p in players if p.get("jp") is True], "eff"),
        # 出場選手全員の国籍が公式登録で確認できたときだけ「日本人トップ」と書く
        "jp_complete": not unknown,
        "jp_unknown": [{k: p.get(k) for k in ("name", "team", "pid", "eff")}
                       for p in rank(unknown, "eff", len(unknown))],
        "leaders": {k: rank(players, k, 3) for k in ("pts", "reb", "ast", "stl", "blk")},
        "player_count": len(players),
        # 出場した全選手（集計漏れ・同点・国籍の確認用）
        "players": [{k: p.get(k) for k in ("pid", "name", "team", "key", "min", "pts", "eff",
                                           "nationality", "jp")}
                    for p in rank(players, "eff", len(players))],
    }


# --------------------------------------------------------------- rendering

HEADER = (
    '<header class="hdr"><div class="hdr-in"><a class="logo" href="index.html"><span class="mk">'
    '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" '
    'cy="12" r="9" fill="#fff"/><path d="M12 3v18M3 12h18M6.2 5.2a13 13 0 000 13.6M17.8 5.2a13 '
    '13 0 010 13.6" stroke="#e2360b" stroke-width="1.3"/></svg></span><span class="wm"><span '
    'class="t">バスケ<em>まとめ</em></span><span class="sub">非公式ファンサイト</span></span>'
    '</a><nav class="gnav"><a href="index.html">最新</a><a href="cat-kekka.html">試合結果</a>'
    '<a href="cat-sokuho.html">速報</a><a href="cat-iseki.html">移籍情報</a>'
    '<a href="cat-data.html">順位・日程</a><a href="matome.html">まとめ</a></nav></div></header>'
)
FOOTER = (
    '<footer class="ft"><div class="ft-in"><a href="about.html">このサイトについて</a>'
    '<a href="privacy.html">プライバシーポリシー</a><a href="contact.html">お問い合わせ</a>'
    '<span class="cp">© 2026 バスケまとめ（非公式）.</span></div></footer>'
)
FAVICON = (
    "<link rel=\"icon\" href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%230d1b2a'/><circle cx='16' "
    "cy='16' r='9' fill='%23ff5a1f'/><path d='M16 7v18M7 16h18M10 8.4a13 13 0 000 15.2M22 8.4a13 "
    "13 0 010 15.2' stroke='%230d1b2a' stroke-width='1.4' fill='none'/></svg>\">"
)
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
    top, jp = s["eff_top"], s["eff_top_jp"]
    first = top[0]
    lead = (f"{jp_date(s['date'])}に行われたりそなB.LEAGUE PREMIER(Bプレミア){len(s['games'])}試合の"
            f"ボックススコアから、貢献度（EFF）の上位選手をまとめました。この日の貢献度1位は"
            f"{esc(first['team'])}の{esc(first['name'])}で、{first['pts']}得点・{first['reb']}リバウンド・"
            f"{first['ast']}アシストを記録し、貢献度{first['eff']}をマークしました。")
    if jp and s.get("jp_complete"):
        lead += (f"日本人選手のトップは{esc(jp[0]['team'])}の{esc(jp[0]['name'])}（貢献度{jp[0]['eff']}）"
                 f"でした。")
    return f"""<p class="lead">{lead}</p>

    <h2>貢献度ランキング TOP{TOP_N}</h2>
    {eff_table(top)}

    <h2>日本人選手 貢献度ランキング TOP{TOP_N}{"" if s.get("jp_complete") else "（国籍確認済みの選手のみ）"}</h2>
    {eff_table(jp)}
    {jp_note(s)}

    <h2>部門別リーダー</h2>
    {leaders_table(s['leaders'])}

    <h2>この日の試合結果</h2>
    {games_table(s['games'])}

    <div class="note"><p style="margin:0"><strong>Q. 貢献度（EFF）とは？</strong><br>A. 得点・リバウンド・アシスト・スティール・ブロックの合計から、外したシュート数（フィールドゴール・フリースロー）とターンオーバーを引いた指標です。B.LEAGUE公式記録の値をそのまま掲載しています。</p></div>"""


def jp_note(s):
    base = ("日本人選手かどうかは、B.LEAGUE公式サイトの選手ページの「リーグ登録国籍」で判定しています"
            "（名前の表記からは推測していません）。")
    if s.get("jp_complete"):
        return f'<div class="note">{base}この日の出場選手全員の国籍を確認済みです。</div>'
    names = "、".join(f"{esc(p['name'])}（{esc(p['team'])}）" for p in s.get("jp_unknown", []))
    return (f'<div class="note">{base}次の選手は国籍を確認できていない（未確認）ため集計から外しており、'
            f'順位が変わる可能性があります。そのため「日本人トップ」とは断定していません。'
            f'未確認：{names}</div>')


def page(title, desc, url, body):
    return f"""<!DOCTYPE html>
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


def article_title(s):
    top, jp = s["eff_top"][0], s["eff_top_jp"][:1]
    t = f"{jp_date(s['date'])}の貢献度ランキング 1位は{top['name']}（{top['team']}）の{top['eff']}"
    if jp and s.get("jp_complete"):
        t += f" 日本人トップは{jp[0]['name']}"
    return t


def write_article(s):
    ymd = s["date"].replace("-", "")
    fn, thumb = f"article-stats-{ymd}.html", f"thumb-stats-{ymd}.svg"
    title = article_title(s)
    dot = s["date"].replace("-", ".")
    desc = (f"{jp_date(s['date'])}のB.LEAGUE PREMIER全{len(s['games'])}試合のボックススコアから、"
            f"貢献度（EFF）TOP{TOP_N}、日本人選手TOP{TOP_N}、得点・リバウンド・アシストなどの"
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
    import thumbgen
    if not thumbgen.FONT:
        thumbgen.FONT = thumbgen.embed_font()
    top = s["eff_top"][0]
    jp = s["eff_top_jp"][:1]
    d = {
        "type": "news",
        "label": "スタッツ",
        "team": f"B.PREMIER {jp_date(s['date'])} 全{len(s['games'])}試合",
        "team_color": thumbgen.team_color(top["team"]),
        "headline": "貢献度ランキング",
        "sub": f"1位 {top['name']}（{top['team']}） EFF {top['eff']}",
        "facts": ([["日本人1位", f"{jp[0]['name']}（{jp[0]['team']}） {jp[0]['eff']}"]]
                  if jp and s.get("jp_complete") else [["集計", f"{s['player_count']}人"]]),
    }
    return thumbgen.render(d)


def write_stats_page(s, published):
    title = f"スタッツリーダー（{jp_date(s['date'])}）貢献度ランキング"
    desc = "B.LEAGUE PREMIERの最新試合日の貢献度（EFF）ランキングと部門別リーダー。全試合の記録確定後に自動更新します。"
    archive = "\n".join(
        f'      <div class="rank"><span class="n">›</span><a href="article-stats-{d.replace("-", "")}.html">'
        f'{esc(jp_date(d))}（{d[:4]}年）の貢献度ランキング</a></div>'
        for d in sorted(published, reverse=True)[:30])
    body = f"""    <div class="breadcrumb"><a href="index.html">ホーム</a> ／ <a href="cat-data.html">順位・日程</a></div>
    <h1>{esc(title)}</h1>
    <div class="pmeta"><span class="tag data">順位・日程</span><span>{s['date'].replace('-', '.')}</span><span>最終更新 {esc(s['generated'])}</span></div>
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

def run():
    state = load_json(STATE_PATH, {"pending": {}, "published": []})
    pending = state.setdefault("pending", {})       # key -> date（未確定）
    published = set(state.setdefault("published", []))
    today = datetime.now(JST).date()
    oldest = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    try:
        queue = sorted(set(re.findall(r"ScheduleKey=(\d+)", get(SCHEDULE_URL))))
    except Exception as e:  # noqa: BLE001
        log(f"!! 日程ページの取得に失敗: {e}")
        queue = []
    queue = list(dict.fromkeys(queue + sorted(pending)))

    games, failed, seen = {}, set(), set()
    while queue:
        key = queue.pop(0)
        if key in seen:
            continue
        seen.add(key)
        try:
            g = parse_game(key, get(GAME_URL.format(key=key)))
        except Exception as e:  # noqa: BLE001
            log(f"!! {key} の取得に失敗: {e}")
            failed.add(key)
            continue
        if not g or not g["date"]:
            log(f"   {key}: ボックススコアなし")
            continue
        if not is_premier(g) or g["date"] < oldest or g["date"] in published:
            continue
        games[key] = g
        queue.extend(k for k in g["same_day"] if k not in seen)

    by_date = {}
    for g in games.values():
        by_date.setdefault(g["date"], []).append(g)

    new_pending = {}
    latest = None
    registry = load_json(PLAYERS_PATH, {}).get("players", {})
    for date, day_games in sorted(by_date.items()):
        expected = {k for g in day_games for k in g["same_day"]} | {g["key"] for g in day_games}
        expected = {k for k in expected
                    if (k in games and games[k]["date"] == date) or k in failed}
        complete = (not (expected & failed)
                    and all(g["ended"] and g["fixed"] and g["players"] for g in day_games))
        if not complete:
            for g in day_games:
                new_pending[g["key"]] = date
            log(f"{date}: 未確定の試合があるため次回に持ち越し")
            continue
        day_games.sort(key=lambda g: g["key"])
        apply_nationality([p for g in day_games for p in g["players"]], registry,
                          fetch=lambda pid: get(ROSTER_URL.format(pid=pid)))
        save_json(PLAYERS_PATH, {"_note": PLAYERS_NOTE, "players": registry})
        summary = summarise(date, day_games)
        if not summary["eff_top"]:
            continue
        save_json(os.path.join(STATS_DIR, f"{date}.json"), summary)
        write_article(summary)
        published.add(date)
        latest = summary
        log(f"{date}: {len(day_games)}試合 / {summary['player_count']}人を集計")

    if latest is None:
        last = max(published) if published else None
        latest = load_json(os.path.join(STATS_DIR, f"{last}.json"), None) if last else None
    if latest:
        write_stats_page(latest, published)

    state["pending"] = new_pending
    state["published"] = sorted(published)
    save_json(STATE_PATH, state)


def regenerate(date, keys):
    """公開済みの日を公式ボックススコアから作り直す（state.json は変えない）。
    例: python scripts/stats.py --regen 2026-10-12 506459,506460,506461,506462,506463"""
    registry = load_json(PLAYERS_PATH, {}).get("players", {})
    games = []
    for key in keys:
        g = parse_game(key, get(GAME_URL.format(key=key)))
        if not g or not (g["ended"] and g["fixed"] and g["players"]) or g["date"] != date:
            raise SystemExit(f"!! {key} は {date} の確定済みの試合ではありません")
        games.append(g)
    games.sort(key=lambda g: g["key"])
    apply_nationality([p for g in games for p in g["players"]], registry,
                      fetch=lambda pid: get(ROSTER_URL.format(pid=pid)))
    save_json(PLAYERS_PATH, {"_note": PLAYERS_NOTE, "players": registry})
    summary = summarise(date, games)
    save_json(os.path.join(STATS_DIR, f"{date}.json"), summary)
    return summary


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 4 and sys.argv[1] == "--regen":
        print(json.dumps(regenerate(sys.argv[2], sys.argv[3].split(",")), ensure_ascii=False))
    else:
        run()
