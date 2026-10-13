"""Shared site header, current section, and progressive navigation assets."""
import re
from html import escape

LINKS = [('index.html', 'ホーム'), ('next-games.html', '次の試合'),
         ('cat-kekka.html', '試合結果'), ('injury.html', 'IL一覧'),
         ('cat-sokuho.html', '速報'), ('cat-iseki.html', '移籍情報'),
         ('cat-data.html', '順位・日程'), ('matome.html', 'まとめ')]
LOGO = ('<a class="logo" href="index.html"><span class="mk">'
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<circle cx="12" cy="12" r="9" fill="#fff"/>'
        '<path d="M12 3v18M3 12h18M6.2 5.2a13 13 0 000 13.6M17.8 5.2a13 13 0 010 13.6" stroke="#e2360b" stroke-width="1.3"/>'
        '</svg></span><span class="wm"><span class="t">バスケ<em>まとめ</em></span>'
        '<span class="sub">非公式ファンサイト</span></span></a>')


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
    text = re.sub(r'style\.css(?:\?v=\d+)?', 'style.css?v=6', text)
    text = re.sub(r'<script\b[^>]*src=["\']site-nav\.js(?:\?v=\d+)?["\'][^>]*>\s*</script>\s*', '', text)
    return text.replace('</head>', '<script src="site-nav.js?v=1" defer></script>\n</head>', 1)
