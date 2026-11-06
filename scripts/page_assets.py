"""Shared head assets for full builds and standalone stats saves."""
import html
import re


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
DEFAULT_OG = re.compile(r'[ \t]*<meta\b[^>]*\bdata-default-og\b[^>]*>\n?')


def _has_meta(text, attr, value):
    return re.search(r'<meta\b[^>]*\b' + attr + r'=["\']' + re.escape(value) + r'["\']', text) is not None


def ensure_default_og(text):
    """自分の画像を持たないページに、サイト共通のカード画像を付ける（X などで共有した時に出る画像）。
    自動サムネの og:image があるページには付けない。何度呼んでも同じ結果になる。"""
    text = DEFAULT_OG.sub("", text)
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
