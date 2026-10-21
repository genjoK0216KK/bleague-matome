"""Shared site header, current section, and progressive navigation assets."""
import re
from html import escape

LINKS = [('index.html', 'ホーム'), ('next-games.html', '次の試合'),
         ('cat-kekka.html', '試合結果'), ('injury.html', 'IL一覧'),
         ('cat-sokuho.html', '速報'), ('cat-iseki.html', '移籍情報'),
         ('cat-data.html', '順位・日程'), ('matome.html', 'まとめ')]
LOGO = ('<a class="logo" href="/" aria-label="バスケまとめ トップページ">'
        '<img class="brand-logo" src="basuke-matome-logo-dark.svg" width="240" height="45" alt="バスケまとめ">'
        '<span class="brand-sub">非公式ファンサイト</span></a>')
BRAND_HEAD = ('<link rel="icon" href="favicon.ico" sizes="any">\n'
              '<link rel="icon" type="image/svg+xml" href="favicon.svg">\n'
              '<link rel="icon" type="image/png" sizes="32x32" href="favicon-32.png">\n'
              '<link rel="icon" type="image/png" sizes="16x16" href="favicon-16.png">\n'
              '<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">\n'
              '<link rel="manifest" href="site.webmanifest">\n'
              '<meta name="theme-color" content="#151A18">\n')


def brand_head(text):
    # Match complete quoted attributes, including the old inline SVG data URI.
    pattern = r"<(?:link|meta)\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>[ \t]*\n?"
    def keep_or_remove(match):
        tag = match.group(0)
        if re.search(r"(?:rel=[\"'](?:icon|shortcut icon|apple-touch-icon|manifest)[\"']|name=[\"']theme-color[\"'])", tag, re.I):
            return ''
        return tag
    text = re.sub(pattern, keep_or_remove, text, flags=re.I)
    return text.replace('</head>', BRAND_HEAD + '</head>', 1)


def current_section(filename, content=''):
    if filename in {path for path, _ in LINKS} or filename == 'x.html':
        return filename
    if filename.startswith('article-preview-'):
        return 'next-games.html'
    if filename.startswith(('article-games-', 'article-results-', 'article-result-highlight-')):
        return 'cat-kekka.html'
    for category in ('kekka', 'sokuho', 'iseki', 'data'):
        if filename.startswith('cat-' + category + '-'):
            return 'cat-' + category + '.html'
        if filename.startswith('article-') and re.search(r'class=["\'][^"\']*\btag\b[^"\']*\b' + category + r'\b', content):
            return 'cat-' + category + '.html'
    if filename == 'stats.html':
        return 'cat-data.html'
    return None


def render(filename='', content='', x_enabled=False):
    current = current_section(filename, content)
    links = LINKS + ([('x.html', 'クラブX')] if x_enabled else [])
    nav = []
    for href, label in links:
        attribute = (' aria-current="' + ('page' if filename == href else 'location') + '"') if href == current else ''
        nav.append(f'<a href="{escape(href)}"{attribute}>{escape(label)}</a>')
    return ('<header class="hdr"><div class="hdr-in">' + LOGO
            + '<button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-navigation" aria-label="メニューを開く" hidden>'
            + '<span class="nav-toggle-lines" aria-hidden="true"><span></span><span></span><span></span></span>'
            + '<span class="nav-toggle-label">メニュー</span></button>'
            + '<nav class="gnav" id="site-navigation" aria-label="メインメニュー">'
            + ''.join(nav) + '</nav></div></header>')


def enhance(text, filename='', x_enabled=False):
    pattern = r'<header\b[^>]*class=["\'][^"\']*\bhdr\b[^"\']*["\'][^>]*>.*?</header>'
    if not re.search(pattern, text, flags=re.DOTALL):
        return text
    text = re.sub(pattern, lambda _: render(filename, text, x_enabled), text, count=1, flags=re.DOTALL)
    text = re.sub(r'style\.css(?:\?v=\d+)?', 'style.css?v=7', text)
    text = re.sub(r'<script\b[^>]*src=["\']site-nav\.js(?:\?v=\d+)?["\'][^>]*>\s*</script>\s*', '', text)
    text = brand_head(text)
    return text.replace('</head>', '<script src="site-nav.js?v=1" defer></script>\n</head>', 1)
