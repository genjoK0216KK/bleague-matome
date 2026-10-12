#!/usr/bin/env python3
"""
スコアボード風サムネイルの見本ジェネレーター（480x300 / 16:10）。
- 数字・欧文は Barlow Condensed（OFL）を必要な字だけに絞って SVG に埋め込む。
- 和文は閲覧端末のゴシック（ヒラギノ / Noto Sans JP / 游ゴシック）。
- 写真やロゴは使わない。チームは名前とイメージカラーだけで表現する。
"""
import base64, io, sys, os
from fontTools import subset
from fontTools.ttLib import TTFont

FONT_SRC = sys.argv[1]
OUT = sys.argv[2]

CHARS = "0123456789-–:.,/+%()ABCDEFGHIJKLMNOPQRSTUVWXYZ "


def embed_font():
    f = TTFont(FONT_SRC)
    opts = subset.Options()
    opts.flavor = "woff2"
    sub = subset.Subsetter(opts)
    sub.populate(text=CHARS)
    sub.subset(f)
    buf = io.BytesIO()
    f.flavor = "woff2"
    f.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return ("<style>@font-face{font-family:'BC';font-weight:800;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}</style>")


JP = "'Hiragino Kaku Gothic ProN','Hiragino Sans','Noto Sans JP','Yu Gothic',Meiryo,sans-serif"
NUM = "BC,'Arial Narrow',sans-serif"
FONT = None


def head(label):
    return f'''<svg viewBox="0 0 480 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}">
{FONT}'''


def brand(x=462, y=286, fill="#ffffff", op=0.55):
    return (f'<text x="{x}" y="{y}" text-anchor="end" font-family="{JP}" font-weight="800" '
            f'font-size="12" fill="{fill}" opacity="{op}">バスケまとめ</text>')


def chip(text, x, y, bg, fg="#ffffff"):
    w = 14 + len(text) * 13
    return (f'<rect x="{x}" y="{y}" width="{w}" height="24" rx="3" fill="{bg}"/>'
            f'<text x="{x + w / 2}" y="{y + 17}" text-anchor="middle" font-family="{JP}" '
            f'font-weight="800" font-size="13" fill="{fg}">{text}</text>')


def game(home, away, hs, as_, hc, ac, meta, star, star_stat):
    """試合結果: 左右にチームカラー、中央に大きなスコア。勝者側を明るく。"""
    home_win = hs > as_
    hop, aop = (1, 0.55) if home_win else (0.55, 1)
    return head(f"{home} {hs}-{as_} {away}") + f'''
<rect width="480" height="300" fill="#151b22"/>
<polygon points="0,0 262,0 218,300 0,300" fill="{hc}" opacity="{0.95 if home_win else 0.55}"/>
<polygon points="262,0 480,0 480,300 218,300" fill="{ac}" opacity="{0.55 if home_win else 0.95}"/>
<polygon points="252,0 272,0 228,300 208,300" fill="#151b22"/>
<rect x="0" y="0" width="480" height="40" fill="#000" opacity="0.38"/>
<text x="20" y="27" font-family="{NUM}" font-weight="800" font-size="19" fill="#fff" letter-spacing="1">FINAL</text>
<text x="80" y="26" font-family="{JP}" font-weight="700" font-size="13" fill="#fff" opacity="0.85">{meta}</text>
<text x="118" y="104" text-anchor="middle" font-family="{JP}" font-weight="900" font-size="26" fill="#fff" opacity="{hop}">{home}</text>
<text x="362" y="104" text-anchor="middle" font-family="{JP}" font-weight="900" font-size="26" fill="#fff" opacity="{aop}">{away}</text>
<text x="118" y="212" text-anchor="middle" font-family="{NUM}" font-weight="800" font-size="110" fill="#fff" opacity="{hop}">{hs}</text>
<text x="362" y="212" text-anchor="middle" font-family="{NUM}" font-weight="800" font-size="110" fill="#fff" opacity="{aop}">{as_}</text>
<text x="{118 if home_win else 362}" y="132" text-anchor="middle" font-family="{NUM}" font-weight="800" font-size="15" fill="#fff" letter-spacing="3">WIN</text>
<rect x="0" y="246" width="480" height="54" fill="#000" opacity="0.5"/>
<text x="20" y="279" font-family="{JP}" font-weight="800" font-size="16" fill="#fff">{star}</text>
<text x="{26 + len(star) * 16}" y="280" font-family="{NUM}" font-weight="800" font-size="20" fill="#ffd166" letter-spacing="1">{star_stat}</text>
{brand(y=280)}
</svg>'''


def transfer(name, pos, frm, to, to_c, frm_c, note):
    """移籍: 選手名が主役。旧所属→新所属を矢印で。新所属のカラーで塗る。"""
    return head(f"{name} {frm}から{to}へ") + f'''
<rect width="480" height="300" fill="{to_c}"/>
<polygon points="300,0 480,0 480,300 230,300" fill="#000" opacity="0.18"/>
<text x="470" y="250" text-anchor="end" font-family="{NUM}" font-weight="800" font-size="190" fill="#fff" opacity="0.10">IN</text>
{chip("移籍・新加入", 20, 20, "#ffffff", to_c)}
<text x="22" y="118" font-family="{JP}" font-weight="900" font-size="38" fill="#fff" stroke="#fff" stroke-width="1.2" paint-order="stroke">{name}</text>
<text x="24" y="146" font-family="{NUM}" font-weight="800" font-size="20" fill="#fff" opacity="0.85" letter-spacing="2">{pos}</text>
<rect x="20" y="172" width="150" height="46" rx="4" fill="{frm_c}" opacity="0.9"/>
<text x="95" y="202" text-anchor="middle" font-family="{JP}" font-weight="800" font-size="17" fill="#fff">{frm}</text>
<path d="M184 195 h46 m-14 -12 l14 12 l-14 12" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
<rect x="244" y="172" width="170" height="46" rx="4" fill="#fff"/>
<text x="329" y="202" text-anchor="middle" font-family="{JP}" font-weight="900" font-size="18" fill="{to_c}">{to}</text>
<text x="22" y="262" font-family="{JP}" font-weight="700" font-size="14" fill="#fff" opacity="0.9">{note}</text>
{brand(y=286)}
</svg>'''


def news(kind, team, team_c, headline, sub, facts):
    """速報: 見出しの種類（負傷離脱など）を大きく、要点を数字で。"""
    xs, x = [], 32
    for k, v in facts:
        xs.append(x)
        x += max(len(k), len(v)) * 19 + 34
    rows = "".join(
        f'<text x="{xs[i]}" y="236" font-family="{JP}" font-weight="700" font-size="12" fill="#fff" opacity="0.75">{k}</text>'
        f'<text x="{xs[i]}" y="266" font-family="{JP}" font-weight="900" font-size="19" fill="#fff">{v}</text>'
        for i, (k, v) in enumerate(facts))
    return head(f"{team} {headline}") + f'''
<rect width="480" height="300" fill="#1c232c"/>
<rect x="0" y="0" width="12" height="300" fill="{team_c}"/>
<rect x="12" y="0" width="468" height="6" fill="#e8552b"/>
{chip("速報", 32, 26, "#e8552b")}
<text x="88" y="44" font-family="{JP}" font-weight="800" font-size="15" fill="#fff" opacity="0.9">{team}</text>
<text x="30" y="122" font-family="{JP}" font-weight="900" font-size="46" fill="#fff">{headline}</text>
<text x="32" y="160" font-family="{JP}" font-weight="800" font-size="19" fill="#ffd166">{sub}</text>
<rect x="20" y="210" width="440" height="1" fill="#fff" opacity="0.2"/>
{rows}
{brand(y=290)}
</svg>'''


if __name__ == "__main__":
    FONT = embed_font()
    os.makedirs(OUT, exist_ok=True)
    samples = {
        "sample-game.svg": game("茨城", "名古屋D", 78, 90, "#1f3a7a", "#0b6fb8",
                                "B.PREMIER  10.11  アダストリアみとアリーナ",
                                "齋藤拓実", "21PTS 10AST"),
        "sample-transfer.svg": transfer("ウィリアムス・ニカ", "C  /  CENTER", "富山", "千葉ジェッツ",
                                        "#c8102e", "#3b2a6b", "高さを補強し、B.PREMIER優勝を狙う"),
        "sample-news.svg": news("負傷", "横浜ビー・コルセアーズ", "#1e5bc6", "負傷離脱",
                                "マクガスティがIL入り",
                                [("診断", "右大腿四頭筋損傷"), ("全治", "2〜3カ月"), ("IL登録", "10月1日")]),
    }
    for fn, svg in samples.items():
        with open(os.path.join(OUT, fn), "w", encoding="utf-8") as f:
            f.write(svg)
        print(fn, len(svg))
