"""Shared head assets for full builds and standalone stats saves."""
import html
import re
from collections import namedtuple
from html.parser import HTMLParser


def ga_snippet(ga_id):
    ga_id = html.escape(ga_id, quote=True)
    return (
        '<!-- AUTO:GA:START -->\n'
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={ga_id}"></script>\n'
        '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}'
        f"gtag('js',new Date());gtag('config','{ga_id}');</script>\n"
        '<!-- AUTO:GA:END -->\n'
    )


def ensure_ga(text, ga_id):
    text = re.sub(r"<!-- AUTO:GA:START -->.*?<!-- AUTO:GA:END -->\n?", "", text, flags=re.DOTALL)
    if ga_id and "</head>" in text:
        text = text.replace("</head>", ga_snippet(ga_id) + "</head>", 1)
    return text


# ヒートマップ（Microsoft Clarity・プロジェクト「バスケまとめ」）。2026-11-07 本人「今後すべてのサイトにヒートマップを入れる」
CLARITY_ID = "z9kto3yxr3"


def clarity_snippet(cid=CLARITY_ID):
    return (
        '<!-- AUTO:CLARITY:START -->\n'
        '<script type="text/javascript">(function(c,l,a,r,i,t,y){c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};'
        't=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);})'
        f'(window, document, "clarity", "script", "{cid}");</script>\n'
        '<!-- AUTO:CLARITY:END -->\n'
    )


def ensure_clarity(text, cid=CLARITY_ID):
    text = re.sub(r"<!-- AUTO:CLARITY:START -->.*?<!-- AUTO:CLARITY:END -->\n?", "", text, flags=re.DOTALL)
    if cid and "</head>" in text:
        text = text.replace("</head>", clarity_snippet(cid) + "</head>", 1)
    return text


DEFAULT_OG_IMAGE = "https://basuke-matome.jp/og-default.png"
# ---- head の meta の読み取り（11/12 MINI8-OG-TAGS-QA）。
# 正規表現では、属性の値の中の「>」・属性名の取り違え（data-property を property と見る等）・「=」前後の空白で
# 読み違えるため、標準の HTMLParser で読む。属性名は小文字・値は文字参照を戻して前後の空白を除く。
# script・style の中身と、head の外（body 以降）は見ない。thumb_auto も同じ関数を使う。
HeadMeta = namedtuple("HeadMeta", "start end raw attrs")


class _HeadMetaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.state = "before"          # before → head → after
        self.found = []

    def handle_starttag(self, tag, attrs):
        if self.state == "before" and tag == "head":
            self.state = "head"
        elif self.state == "head" and tag == "body":
            self.state = "after"
        elif self.state == "head" and tag == "meta":
            self.found.append((self.getpos(), self.get_starttag_text(), attrs))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.state == "head" and tag == "head":
            self.state = "after"


def head_metas(text):
    """head の中の meta を、元の文字列での位置・元のタグ文字列・属性 {小文字の名前: 値} の順で返す。"""
    parser = _HeadMetaParser()
    parser.feed(text)
    parser.close()
    lines = [0] + [m.end() for m in re.finditer("\n", text)]
    out = []
    for (line, col), raw, attrs in parser.found:
        start = lines[line - 1] + col
        if text[start:start + len(raw)] != raw:          # 念のため：位置がずれたら同じ行から探し直す
            start = text.find(raw, lines[line - 1])
            if start < 0:
                raise ValueError("meta の位置を特定できません: " + raw[:80])
        values = {}
        for name, value in attrs:
            values.setdefault(name, (value or "").strip())
        out.append(HeadMeta(start, start + len(raw), raw, values))
    return out


def meta_keys(attrs):
    """property 属性と name 属性の値（小文字）。data-property などの別の属性は含めない。"""
    return {attrs.get("property", "").lower(), attrs.get("name", "").lower()} - {""}


def remove_head_metas(text, drop):
    """head の中の meta のうち drop(属性) が真のものを、行の前の空白・後ろの改行ごと外す。ほかは1文字も変えない。"""
    for m in reversed(head_metas(text)):
        if drop(m.attrs):
            start, end = m.start, m.end
            while start > 0 and text[start - 1] in " \t":
                start -= 1
            if text[end:end + 1] == "\n":
                end += 1
            text = text[:start] + text[end:]
    return text


def has_meta(text, attr, value):
    """head の中に attr 属性（完全一致）の値が value（大文字小文字は問わない）の meta があるか。"""
    value = value.lower()
    return any(m.attrs.get(attr, "").lower() == value for m in head_metas(text))


_has_meta = has_meta


def ensure_default_og(text):
    """自分の画像を持たないページに、サイト共通のカード画像を付ける（X などで共有した時に出る画像）。
    自動サムネの og:image があるページには付けない。何度呼んでも同じ結果になる。"""
    text = remove_head_metas(text, lambda attrs: "data-default-og" in attrs)
    if "</head>" not in text or _has_meta(text, "property", "og:image"):
        return text
    tags = [("property", "og:image", DEFAULT_OG_IMAGE), ("property", "og:image:width", "1200"),
            ("property", "og:image:height", "630"), ("name", "twitter:card", "summary_large_image"),
            ("name", "twitter:image", DEFAULT_OG_IMAGE)]
    metas = "".join(f'<meta {k}="{v}" content="{c}" data-default-og>\n' for k, v, c in tags if not _has_meta(text, k, v))
    return text.replace("</head>", metas + "</head>", 1)


def ensure(text, ga_id):
    if 'href="design-system.css?v=1"' not in text:
        text = text.replace('</head>', '<link rel="stylesheet" href="design-system.css?v=1">\n</head>', 1)
    return ensure_clarity(ensure_default_og(ensure_ga(text, ga_id)))
