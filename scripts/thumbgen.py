#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
バスケまとめ - スコアボード風サムネイル生成（480x300 / 16:10 の SVG）

使い方:
  python3 scripts/thumbgen.py data.json thumb-daily-20261013.svg
  python3 scripts/thumbgen.py --samples samples/      # 見本3種を作り直す

data.json の形（type ごと。チームは略称でも正式名称でもよい）:
  試合結果 {"type": "game", "home": "茨城", "away": "名古屋D", "home_score": 78, "away_score": 90,
            "meta": "B.PREMIER  10.11  アダストリアみとアリーナ",
            "star": "齋藤拓実", "star_stat": "21PTS 10AST"}
  移籍     {"type": "transfer", "name": "ウィリアムス・ニカ", "pos": "C  /  CENTER",
            "from": "富山", "to": "千葉ジェッツ", "note": "高さを補強し、B.PREMIER優勝を狙う"}
  速報など {"type": "news", "label": "速報", "team": "横浜ビー・コルセアーズ", "headline": "負傷離脱",
            "sub": "マクガスティがIL入り", "facts": [["診断", "右大腿四頭筋損傷"], ["全治", "2〜3カ月"]]}
  色を直接指定したいときは home_color / away_color / to_color / from_color / team_color を足す。

デザイン:
  - 数字・欧文は Barlow Condensed（SIL OFL、fonts/ に同梱）を使う字だけに絞って SVG に埋め込む。
  - 和文は閲覧端末のゴシック（ヒラギノ / Noto Sans JP / 游ゴシック）。
  - 写真やロゴは使わない。チームは名前とイメージカラー（scripts/team_colors.json）だけで表現する。
  - fontTools が無い環境でも動く（その場合は数字フォントを埋め込まず端末の字体で表示）。
"""
import base64
import html
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONT_SRC = os.path.join(ROOT, "fonts", "BarlowCondensed-ExtraBold-latin.woff2")
COLORS_PATH = os.path.join(HERE, "team_colors.json")

CHARS = "0123456789-–:.,/+%()ABCDEFGHIJKLMNOPQRSTUVWXYZ "
JP = "'Hiragino Kaku Gothic ProN','Hiragino Sans','Noto Sans JP','Yu Gothic',Meiryo,sans-serif"
NUM = "BC,'Arial Narrow',sans-serif"
FONT = ""


def embed_font():
    """数字用フォントを使う字だけに絞り、woff2 で SVG に埋め込む <style> を返す。"""
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
        f = TTFont(FONT_SRC)
        opts = subset.Options()
        opts.flavor = "woff2"
        sub = subset.Subsetter(opts)
        sub.populate(text=CHARS)
        sub.subset(f)
        buf = io.BytesIO()
        f.flavor = "woff2"
        f.save(buf)
    except Exception as e:  # noqa: BLE001
        print(f"[thumbgen] 数字フォントを埋め込めませんでした（端末の字体で表示）: {e}",
              file=sys.stderr)
        return ""
    b64 = base64.b64encode(buf.getvalue()).decode()
    return ("<style>@font-face{font-family:'BC';font-weight:800;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}</style>")


def x(text):
    return html.escape(str(text if text is not None else ""), quote=True)


# ------------------------------------------------------------ team colors

def _load_colors():
    try:
        with open(COLORS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}, "#2b3a4a"
    table = {}
    for c in data.get("clubs", []):
        table[c["short"]] = c["color"]
        table[c["name"]] = c["color"]
    return table, data.get("default", "#2b3a4a")


COLORS, DEFAULT_COLOR = _load_colors()


def team_color(name):
    """略称・正式名称・部分一致（「千葉ジェッツふなばし」など）で色を引く。"""
    if not name:
        return DEFAULT_COLOR
    if name in COLORS:
        return COLORS[name]
    for key, color in sorted(COLORS.items(), key=lambda kv: -len(kv[0])):
        if len(key) >= 3 and (key in name or name in key):
            return color
    return DEFAULT_COLOR


# -------------------------------------------------------------- templates

def ink(bg, light="#ffffff", dark="#14202e"):
    """背景色に対して読みやすい文字色。明るい色（黄・金・黄緑など）には濃い文字を使う。"""
    h = str(bg).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return light
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return dark if lum > 0.55 else light


def fit(text, width, base):
    """長い文字列が枠からはみ出さないよう、文字サイズを base から縮める
    （全角=1、英大文字・数字=0.7、その他の半角=0.55 で幅を概算）。"""
    def w(c):
        if ord(c) >= 0x2E80:
            return 1.0
        return 0.7 if (c.isupper() or c.isdigit()) else 0.55
    units = sum(w(c) for c in str(text or "")) or 1
    return round(min(base, width / units), 1)


def head(label):
    return f'''<svg viewBox="0 0 480 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{x(label)}">
{FONT}'''


def brand(xx=462, y=286, fill="#ffffff", op=0.55):
    return (f'<text x="{xx}" y="{y}" text-anchor="end" font-family="{JP}" font-weight="800" '
            f'font-size="12" fill="{fill}" opacity="{op}">バスケまとめ</text>')


def chip(text, xx, y, bg, fg="#ffffff"):
    w = 14 + len(text) * 13
    return (f'<rect x="{xx}" y="{y}" width="{w}" height="24" rx="3" fill="{bg}"/>'
            f'<text x="{xx + w / 2}" y="{y + 17}" text-anchor="middle" font-family="{JP}" '
            f'font-weight="800" font-size="13" fill="{fg}">{x(text)}</text>')


def game(home, away, hs, as_, hc, ac, meta, star, star_stat):
    """試合結果: 左右にチームカラー、中央に大きなスコア。勝者側を明るく。"""
    hs, as_ = int(hs), int(as_)
    home_win = hs > as_
    hop, aop = (1, 0.55) if home_win else (0.55, 1)
    hfg = ink(hc) if home_win else "#fff"   # 勝者側はチーム色がはっきり出るので、明るい色なら濃い文字に
    afg = "#fff" if home_win else ink(ac)
    wfg = hfg if home_win else afg
    return head(f"{home} {hs}-{as_} {away}") + f'''
<rect width="480" height="300" fill="#151b22"/>
<polygon points="0,0 262,0 218,300 0,300" fill="{hc}" opacity="{0.95 if home_win else 0.55}"/>
<polygon points="262,0 480,0 480,300 218,300" fill="{ac}" opacity="{0.55 if home_win else 0.95}"/>
<polygon points="252,0 272,0 228,300 208,300" fill="#151b22"/>
<rect x="0" y="0" width="480" height="40" fill="#000" opacity="0.38"/>
<text x="20" y="27" font-family="{NUM}" font-weight="800" font-size="19" fill="#fff" letter-spacing="1">FINAL</text>
<text x="80" y="26" font-family="{JP}" font-weight="700" font-size="13" fill="#fff" opacity="0.85">{x(meta)}</text>
<text x="118" y="104" text-anchor="middle" font-family="{JP}" font-weight="900" font-size="{fit(home, 190, 26)}" fill="{hfg}" opacity="{hop}">{x(home)}</text>
<text x="362" y="104" text-anchor="middle" font-family="{JP}" font-weight="900" font-size="{fit(away, 190, 26)}" fill="{afg}" opacity="{aop}">{x(away)}</text>
<text x="118" y="212" text-anchor="middle" font-family="{NUM}" font-weight="800" font-size="110" fill="{hfg}" opacity="{hop}">{hs}</text>
<text x="362" y="212" text-anchor="middle" font-family="{NUM}" font-weight="800" font-size="110" fill="{afg}" opacity="{aop}">{as_}</text>
<text x="{118 if home_win else 362}" y="132" text-anchor="middle" font-family="{NUM}" font-weight="800" font-size="15" fill="{wfg}" letter-spacing="3">WIN</text>
<rect x="0" y="246" width="480" height="54" fill="#000" opacity="0.5"/>
<text x="20" y="279" font-family="{JP}" font-weight="800" font-size="{fit(star, 330 - len(star_stat) * 11, 16)}" fill="#fff">{x(star)}</text>
<text x="{26 + len(star) * 16}" y="280" font-family="{NUM}" font-weight="800" font-size="20" fill="#ffd166" letter-spacing="1">{x(star_stat)}</text>
{brand(y=280)}
</svg>'''


def transfer(name, pos, frm, to, to_c, frm_c, note):
    """移籍: 選手名が主役。旧所属→新所属を矢印で。新所属のカラーで塗る。"""
    fg = ink(to_c)                       # 新所属の色が明るければ濃い文字に
    on_white = to_c if fg == "#ffffff" else "#14202e"
    return head(f"{name} {frm}から{to}へ") + f'''
<rect width="480" height="300" fill="{to_c}"/>
<polygon points="300,0 480,0 480,300 230,300" fill="#000" opacity="0.18"/>
<text x="470" y="250" text-anchor="end" font-family="{NUM}" font-weight="800" font-size="190" fill="#fff" opacity="0.10">IN</text>
{chip("移籍・新加入", 20, 20, "#ffffff", on_white)}
<text x="22" y="118" font-family="{JP}" font-weight="900" font-size="38" fill="{fg}" stroke="{fg}" stroke-width="1.2" paint-order="stroke">{x(name)}</text>
<text x="24" y="146" font-family="{NUM}" font-weight="800" font-size="20" fill="{fg}" opacity="0.85" letter-spacing="2">{x(pos)}</text>
<rect x="20" y="172" width="150" height="46" rx="4" fill="{frm_c}" opacity="0.9"/>
<text x="95" y="202" text-anchor="middle" font-family="{JP}" font-weight="800" font-size="17" fill="{ink(frm_c)}">{x(frm)}</text>
<path d="M184 195 h46 m-14 -12 l14 12 l-14 12" stroke="{fg}" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
<rect x="244" y="172" width="170" height="46" rx="4" fill="#fff"/>
<text x="329" y="202" text-anchor="middle" font-family="{JP}" font-weight="900" font-size="18" fill="{on_white}">{x(to)}</text>
<text x="22" y="262" font-family="{JP}" font-weight="700" font-size="14" fill="{fg}" opacity="0.9">{x(note)}</text>
{brand(y=286, fill=fg)}
</svg>'''


def news(label, team, team_c, headline, sub, facts):
    """速報など: 見出しの種類（負傷離脱など）を大きく、要点を数字で。"""
    xs, xx = [], 32
    for k, v in facts:
        xs.append(xx)
        xx += max(len(k), len(v)) * 19 + 34
    rows = "".join(
        f'<text x="{xs[i]}" y="236" font-family="{JP}" font-weight="700" font-size="12" fill="#fff" opacity="0.75">{x(k)}</text>'
        f'<text x="{xs[i]}" y="266" font-family="{JP}" font-weight="900" font-size="19" fill="#fff">{x(v)}</text>'
        for i, (k, v) in enumerate(facts))
    return head(f"{team} {headline}") + f'''
<rect width="480" height="300" fill="#1c232c"/>
<rect x="0" y="0" width="12" height="300" fill="{team_c}"/>
<rect x="12" y="0" width="468" height="6" fill="#e8552b"/>
{chip(label, 32, 26, "#e8552b")}
<text x="{62 + len(label) * 13}" y="44" font-family="{JP}" font-weight="800" font-size="15" fill="#fff" opacity="0.9">{x(team)}</text>
<text x="30" y="122" font-family="{JP}" font-weight="900" font-size="{fit(headline, 430, 46)}" fill="#fff">{x(headline)}</text>
<text x="32" y="160" font-family="{JP}" font-weight="800" font-size="{fit(sub, 430, 19)}" fill="#ffd166">{x(sub)}</text>
<rect x="20" y="210" width="440" height="1" fill="#fff" opacity="0.2"/>
{rows}
{brand(y=290)}
</svg>'''


# --------------------------------------------------------------------- CLI

def render(d):
    kind = d.get("type")
    if kind == "game":
        return game(d["home"], d["away"], d["home_score"], d["away_score"],
                    d.get("home_color") or team_color(d["home"]),
                    d.get("away_color") or team_color(d["away"]),
                    d.get("meta", ""), d.get("star", ""), d.get("star_stat", ""))
    if kind == "transfer":
        return transfer(d["name"], d.get("pos", ""), d["from"], d["to"],
                        d.get("to_color") or team_color(d["to"]),
                        d.get("from_color") or team_color(d["from"]),
                        d.get("note", ""))
    if kind == "news":
        facts = [tuple(f) for f in d.get("facts", [])][:3]
        return news(d.get("label", "速報"), d.get("team", ""),
                    d.get("team_color") or team_color(d.get("team", "")),
                    d["headline"], d.get("sub", ""), facts)
    raise ValueError(f"type は game / transfer / news のどれか: {kind!r}")


SAMPLES = {
    "sample-game.svg": {"type": "game", "home": "茨城", "away": "名古屋D",
                        "home_score": 78, "away_score": 90,
                        "meta": "B.PREMIER  10.11  アダストリアみとアリーナ",
                        "star": "齋藤拓実", "star_stat": "21PTS 10AST"},
    "sample-transfer.svg": {"type": "transfer", "name": "ウィリアムス・ニカ", "pos": "C  /  CENTER",
                            "from": "富山", "to": "千葉ジェッツ", "from_color": "#3b2a6b",
                            "note": "高さを補強し、B.PREMIER優勝を狙う"},
    "sample-news.svg": {"type": "news", "label": "速報", "team": "横浜ビー・コルセアーズ",
                        "headline": "負傷離脱", "sub": "マクガスティがIL入り",
                        "facts": [["診断", "右大腿四頭筋損傷"], ["全治", "2〜3カ月"],
                                  ["IL登録", "10月1日"]]},
}


def main(argv):
    global FONT
    if len(argv) == 3 and argv[1] == "--samples":
        FONT = embed_font()
        os.makedirs(argv[2], exist_ok=True)
        for fn, d in SAMPLES.items():
            with open(os.path.join(argv[2], fn), "w", encoding="utf-8") as f:
                f.write(render(d))
            print(fn)
        return 0
    if len(argv) != 3:
        print(__doc__)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        data = json.load(f)
    FONT = embed_font()
    svg = render(data)
    with open(argv[2], "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[thumbgen] wrote {argv[2]} ({len(svg):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
