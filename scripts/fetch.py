#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
バスケまとめ - データ取得スクリプト

取得元:
  1. B.LEAGUE公式サイト ニュース一覧 (HTML)
  2. B.LEAGUE公式サイト 順位表 (HTML)
  3. バスケット・カウント RSS
  4. まとめブログの RSS（MATOME_FEEDS。国内の話題＋日本人選手・超有名選手の海外の話題のみ）

出力:
  data/news.json      … 見出し・URL・日付・出典（本文は保存しない）
  data/standings.json … 順位表
  data/matome.json    … まとめブログの見出し・URL・日付・出典（本文は保存しない）

方針:
  - 記事本文は一切保存・転載しない。見出しとリンクのみを扱う「まとめ」形式。
  - robots.txt を尊重し、リクエスト間に待機を入れる。
  - 取得に失敗しても既存データを壊さない（前回分を維持する）。
"""

import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

UA = (
    "Mozilla/5.0 (compatible; BleagueMatomeBot/1.0; "
    "+https://basuke-matome.jp/about.html)"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
TIMEOUT = 25
SLEEP = 2.0

# 保持する記事数の上限（これを超えた古い記事は捨てる）
MAX_NEWS = 240


# ---------------------------------------------------------------- utilities

def log(msg):
    print(f"[fetch] {msg}", flush=True)


def get(url):
    log(f"GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    time.sleep(SLEEP)
    return r


def clean(text):
    """全角スペースや連続空白、HTMLの名残を整理する。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("　", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
    log(f"wrote {os.path.relpath(path, ROOT)}")


# ------------------------------------------------------------- categorising

CATEGORY_RULES = [
    # (カテゴリ, 正規表現)
    ("iseki", r"移籍|契約|加入|退団|獲得|残留|自由交渉|新加入|入団|選手登録|解除|オファー"),
    ("kekka", r"試合結果|ハイライト|勝利|敗戦|白星|黒星|決勝|準決勝|優勝|\d+[-−―]\d+"),
    ("data",  r"順位|日程|スケジュール|開幕|ランキング|スタッツ|成績|レギュレーション"),
]


def categorise(title):
    for cat, pattern in CATEGORY_RULES:
        if re.search(pattern, title):
            return cat
    return "sokuho"


CATEGORY_LABEL = {
    "kekka": "試合結果",
    "sokuho": "速報",
    "iseki": "移籍情報",
    "data": "順位・日程",
}


# --------------------------------------------------------- source: official

BLEAGUE_NEWS_URL = "https://www.bleague.jp/news/"
DATE_RE = re.compile(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})")


def parse_date(text):
    m = DATE_RE.search(text or "")
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, tzinfo=JST).strftime("%Y-%m-%d")
    except ValueError:
        return None


# 公式一覧のリンクには「見出し＋カテゴリラベル＋見出し（再掲）」がまとめて
# 入っているため、ラベルを外したうえで重複を畳む。
CATEGORY_TOKEN_RE = re.compile(
    r"[*・]?\s*(?:RELEASE|ANNOUNCEMENT|CLUB\s*/\s*GAME|TICKET|BROADCAST"
    r"|GOODS|NATIONAL\s+TEAM|COLUMN)\s*"
)


def tidy_title(title):
    text = CATEGORY_TOKEN_RE.sub(" ", title)
    text = re.sub(r"\s+", " ", text).strip(" *・")
    n = len(text)
    for k in range(n // 2, 7, -1):
        if k * 2 < n - 3:
            break
        if text[:k].strip() == text[n - k:].strip():
            return text[:k].strip()
    return text


def fetch_bleague_news():
    """
    公式ニュース一覧から見出し・URL・日付を抜き出す。

    クラス名の変更に強くするため、CSSセレクタではなく
    「ニュース詳細へのリンクであること」を手がかりに探索する。
    """
    items = []
    try:
        soup = BeautifulSoup(get(BLEAGUE_NEWS_URL).text, "html.parser")
    except Exception as e:  # noqa: BLE001
        log(f"!! B.LEAGUE公式の取得に失敗: {e}")
        return items

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"news_detail|/news/[a-z]+\.html", href):
            continue
        url = requests.compat.urljoin(BLEAGUE_NEWS_URL, href)
        if url in seen:
            continue

        raw = a.get_text(" ", strip=True)
        date = parse_date(raw)
        title = tidy_title(clean(DATE_RE.sub("", raw, count=1)))
        if len(title) < 6:
            continue

        seen.add(url)
        items.append({
            "title": title,
            "url": url,
            "source": "B.LEAGUE公式",
            "date": date or datetime.now(JST).strftime("%Y-%m-%d"),
        })

    log(f"B.LEAGUE公式: {len(items)}件")
    return items


# ------------------------------------------------------------- source: rss

RSS_FEEDS = [
    ("バスケット・カウント", "https://basket-count.com/feed"),
]

# Bリーグ／日本代表に関係ない記事（NBA・大学等）を落とすためのゆるいフィルタ
RELEVANT_RE = re.compile(
    r"B\.?リーグ|B\.?LEAGUE|Bプレミア|B\.PREMIER|日本代表|"
    r"レバンガ|仙台|秋田|茨城|宇都宮|群馬|千葉|アルバルク|A東京|サンロッカーズ|川崎|横浜|"
    r"富山|信州|三遠|三河|名古屋|滋賀|京都|大阪|神戸|島根|広島|佐賀|長崎|琉球|"
    r"ブレックス|ジェッツ|ドラゴンフライズ|ヴェルカ|キングス|スサノオ|グラウジーズ|"
    r"ハンナリーズ|エヴェッサ|ストークス|レイクス|ネオフェニックス|シーホース|"
    r"ブレイブサンダース|ビー・コルセアーズ|クレインサンダーズ|ノーザンハピネッツ|ロボッツ|"
    r"バルーナーズ|アルティーリ|89ERS|ダイヤモンドドルフィンズ|ブレイブウォリアーズ",
    re.I,
)


def fetch_rss(name, url):
    items = []
    try:
        root = ElementTree.fromstring(get(url).content)
    except Exception as e:  # noqa: BLE001
        log(f"!! {name} の取得に失敗: {e}")
        return items

    for entry in root.iter("item"):
        title = clean((entry.findtext("title") or ""))
        link = (entry.findtext("link") or "").strip()
        if not title or not link:
            continue
        if not RELEVANT_RE.search(title):
            continue
        items.append({
            "title": title,
            "url": link,
            "source": name,
            "date": parse_date(entry.findtext("pubDate") or "")
                    or _parse_rfc822(entry.findtext("pubDate"))
                    or datetime.now(JST).strftime("%Y-%m-%d"),
        })

    log(f"{name}: {len(items)}件")
    return items


def _parse_rfc822(value):
    if not value:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(value.strip(), fmt).astimezone(JST).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ------------------------------------------------------ source: まとめブログ

# まとめブログの新着見出し（本文は保存しない）。robots.txt で取得が許可されているものだけ。
MATOME_FEEDS = [
    ("バスケまとめ・COM", "https://basketballbbs.com/?feed=rss2"),
    ("NBAまとめ！", "http://nbama.blog.fc2.com/?xml"),
]
MAX_MATOME = 240

# 海外の話題でも載せてよい日本人選手（表記ゆれも並べる）
JP_PLAYERS = [
    "八村塁", "八村", "河村勇輝", "河村", "富永啓生", "富永", "渡邊雄太", "渡邊", "渡辺雄太",
    "馬場雄大", "馬場", "山崎一渉", "ジェイコブス晶", "ジェイコブス",
]
# 海外の話題でも載せてよい超有名選手
STAR_PLAYERS = [
    "カリー", "ヨキッチ", "レブロン", "ドンチッチ", "ウェンバンヤマ", "ウェンビー", "ヤニス",
    "アデトクンボ", "デュラント", "SGA", "ギルジャス", "ギルジャス=アレクサンダー",
    "ギルジャス・アレクサンダー", "エドワーズ", "テイタム",
]

# 国内の話題（Bリーグ関連の既存 RELEVANT_RE に加えて）
DOMESTIC_RE = re.compile(
    r"日本代表|アカツキ|Wリーグ|WリーグW|女子日本代表|高校|大学|インカレ|ウインターカップ|"
    r"ウィンターカップ|インターハイ|U18|U-18|U19|U-19|3x3|3×3|3X3|天皇杯|皇后杯|"
    r"B1|B2|B3|Bワン|B\.ONE|Bネクスト|B\.NEXT|EASL|ホーバス|トム・ホーバス",
    re.I,
)
# 海外（NBAなど）の話題の目印
OVERSEAS_RE = re.compile(
    r"NBA|WNBA|NCAA|Gリーグ|ユーロリーグ|"
    r"レイカーズ|ウォリアーズ|セルティックス|ネッツ|ニックス|シクサーズ|76ers|ラプターズ|"
    r"ブルズ|キャバリアーズ|キャブス|ピストンズ|ペイサーズ|バックス|ホークス|ホーネッツ|"
    r"ヒート|マジック|ウィザーズ|ナゲッツ|ティンバーウルブズ|(?<!クレイン)(?<!ブレイブ)サンダー(?![ズス])|"
    r"ブレイザーズ|ジャズ|クリッパーズ|サンズ|マーベリックス|マブス|ロケッツ|"
    r"グリズリーズ|ペリカンズ|スパーズ",
    re.I,
)
# バスケの試合・選手と関係ないもの（アニメ・漫画、雑談、バッシュ紹介など）
OFFTOPIC_RE = re.compile(
    r"アニメ|漫画|マンガ|スラムダンク|SLAM ?DUNK|黒子のバスケ|あひるの空|ダンク作画|声優|映画|"
    r"雑談|なんJ|バッシュ|シューズ|スニーカー|ゲーム実況|NBA ?2K|2K\d\d|ガチャ|グッズ紹介|"
    r"総合スレ|実況スレ|PR:|広告",
    re.I,
)
_JP_RE = re.compile("|".join(map(re.escape, JP_PLAYERS)))
_STAR_RE = re.compile("|".join(map(re.escape, STAR_PLAYERS)), re.I)


def matome_relevant(title):
    """まとめブログの見出しを載せるかどうか。
    国内の話題は採用。海外（NBAなど）の話題は、日本人選手か超有名選手の名前が
    入っているとき（または国内の話題と結びついているとき）だけ採用する。"""
    if OFFTOPIC_RE.search(title):
        return False
    if _JP_RE.search(title):
        return True
    if OVERSEAS_RE.search(title):
        return bool(_STAR_RE.search(title) or RELEVANT_RE.search(title)
                    or re.search(r"日本代表|アカツキ", title))
    return bool(RELEVANT_RE.search(title) or DOMESTIC_RE.search(title))


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child_text(entry, *names):
    for child in entry:
        if _local(child.tag) in names:
            if _local(child.tag) == "link" and child.get("href"):
                return child.get("href")
            if child.text and child.text.strip():
                return child.text.strip()
    return ""


_robots_cache = {}


def robots_allows(url):
    """robots.txt で取得が禁止されていないか確かめる（読めないときは許可とみなす）。"""
    from urllib import robotparser
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots_cache:
        rp = robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers=HEADERS, timeout=TIMEOUT)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:  # noqa: BLE001
            rp.parse([])
        _robots_cache[base] = rp
    return _robots_cache[base].can_fetch(UA, url)


def fetch_feed_items(name, url, keep):
    """RSS 1.0（RDF）/ RSS 2.0 / Atom のどれでも見出し・リンク・日付を取り出す。"""
    items = []
    if not robots_allows(url):
        log(f"!! {name}: robots.txt で禁止されているため取得しません")
        return items
    try:
        root = ElementTree.fromstring(get(url).content)
    except Exception as e:  # noqa: BLE001
        log(f"!! {name} の取得に失敗: {e}")
        return items

    total = 0
    for entry in root.iter():
        if _local(entry.tag) not in ("item", "entry"):
            continue
        total += 1
        title = clean(_child_text(entry, "title"))
        link = _child_text(entry, "link")
        if not title or not link or not keep(title):
            continue
        raw_date = _child_text(entry, "pubDate", "date", "published", "updated")
        items.append({
            "title": title,
            "url": link,
            "source": name,
            "date": _parse_rfc822(raw_date) or parse_date(raw_date)
                    or datetime.now(JST).strftime("%Y-%m-%d"),
        })

    log(f"{name}: {total}件中 {len(items)}件を採用")
    return items


def fetch_matome():
    items = []
    for name, url in MATOME_FEEDS:
        items += fetch_feed_items(name, url, matome_relevant)
    return items


# -------------------------------------------------------- source: standings

STANDINGS_URL = "https://www.bleague.jp/standings/"
COLUMNS = ["rank", "team", "w", "l", "pct", "gb", "pf", "pa", "diff"]


def team_name(link):
    """
    クラブ名セルは「順位バッジ・正式名称・略称」が連結されている
    （例: "7 千葉ジェッツ千葉J"）。区切って最長の要素を正式名称とみなす。
    """
    parts = [clean(p) for p in link.get_text("|", strip=True).split("|")]
    parts = [p for p in parts if p and not p.isdigit()]
    if not parts:
        return clean(link.get_text(" ", strip=True))
    return max(parts, key=len)


def fetch_standings():
    """順位表ページから地区ごとのテーブルを抜き出す。"""
    result = {
        "updated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "source": STANDINGS_URL,
        "groups": [],
        "started": False,
    }
    try:
        soup = BeautifulSoup(get(STANDINGS_URL).text, "html.parser")
    except Exception as e:  # noqa: BLE001
        log(f"!! 順位表の取得に失敗: {e}")
        return None

    for table in soup.find_all("table"):
        # 直前の見出し（東地区 / 西地区 など）を探す
        heading = ""
        for prev in table.find_all_previous(["h2", "h3", "h4"], limit=3):
            text = clean(prev.get_text())
            if "地区" in text or "カンファレンス" in text or "リーグ" in text:
                heading = text
                break

        rows = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 4:
                continue
            link = tr.find("a", href=re.compile(r"club_detail"))
            if not link:
                continue  # ヘッダー行など

            values = [clean(c.get_text(" ", strip=True)) for c in cells]
            row = dict(zip(COLUMNS, values[:len(COLUMNS)]))
            row["team"] = team_name(link)
            rows.append(row)

        if rows:
            result["groups"].append({"name": heading or "順位表", "rows": rows})

    result["started"] = any(
        row.get("w") not in ("-", "", None)
        for g in result["groups"] for row in g["rows"]
    )
    log(f"順位表: {len(result['groups'])}グループ / 開幕済={result['started']}")
    return result if result["groups"] else None


# --------------------------------------------------------------------- main

def merge_news(existing, incoming, limit=MAX_NEWS):
    """URLをキーに統合し、初出時刻を保持したまま新しい順に並べる。"""
    now = datetime.now(JST).isoformat(timespec="seconds")
    by_url = {item["url"]: item for item in existing}
    added = 0

    for item in incoming:
        if item["url"] in by_url:
            by_url[item["url"]].update({
                "title": item["title"],
                "date": item["date"],
                "source": item["source"],
            })
            continue
        item["first_seen"] = now
        item["category"] = categorise(item["title"])
        item["category_label"] = CATEGORY_LABEL[item["category"]]
        by_url[item["url"]] = item
        added += 1

    merged = sorted(
        by_url.values(),
        key=lambda x: (x.get("date", ""), x.get("first_seen", "")),
        reverse=True,
    )
    log(f"新規 {added}件 / 合計 {len(merged)}件")
    return merged[:limit], added


def main():
    incoming = fetch_bleague_news()
    for name, url in RSS_FEEDS:
        incoming += fetch_rss(name, url)

    if not incoming:
        log("!! すべての取得元が失敗したため、既存データを維持して終了します")
        return 1

    news_path = os.path.join(DATA_DIR, "news.json")
    existing = load_json(news_path, [])
    merged, added = merge_news(existing, incoming)
    save_json(news_path, merged)

    # まとめブログの新着見出し（失敗しても既存データを維持）
    matome_in = fetch_matome()
    if matome_in:
        matome_path = os.path.join(DATA_DIR, "matome.json")
        merged_m, _ = merge_news(load_json(matome_path, []), matome_in, limit=MAX_MATOME)
        save_json(matome_path, merged_m)
    else:
        log("まとめブログは取得できなかったため、既存データを維持します")

    standings = fetch_standings()
    if standings:
        save_json(os.path.join(DATA_DIR, "standings.json"), standings)
    else:
        log("順位表は取得できなかったため、既存データを維持します")

    # 当日の全試合の記録が確定していれば、貢献度ランキングを生成する
    try:
        sys.dont_write_bytecode = True
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import stats
        stats.run()
    except Exception as e:  # noqa: BLE001
        log(f"!! スタッツ集計に失敗: {e}")

    log(f"完了（新規 {added}件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
