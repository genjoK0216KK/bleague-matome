"""ロゴを押すとトップページ（/）に戻る（10/22 本人要望）。"""
import re
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from scripts import site_header

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'バスケまとめ トップページ'


class LogoHome(unittest.TestCase):
    def test_shared_header_logo_links_to_top(self):
        logo = BeautifulSoup(site_header.render('article-daily-20261021.html'), 'html.parser').select_one('a.logo')
        self.assertEqual(logo['href'], '/')
        self.assertEqual(logo['aria-label'], LABEL)

    def test_enhance_replaces_old_logo_link(self):
        old = ('<html><head></head><body><header class="hdr"><div class="hdr-in">'
               '<a class="logo" href="index.html" aria-label="バスケまとめ ホーム">x</a></div></header></body></html>')
        logo = BeautifulSoup(site_header.enhance(old, 'article-x.html'), 'html.parser').select_one('a.logo')
        self.assertEqual(logo['href'], '/')

    def test_every_published_page_logo_links_to_top(self):
        pages = [p for p in ROOT.glob('*.html') if 'class="hdr"' in p.read_text(encoding='utf-8')]
        self.assertGreater(len(pages), 100)
        for page in pages:
            soup = BeautifulSoup(page.read_text(encoding='utf-8'), 'html.parser')
            logos = soup.select('header.hdr a.logo')
            self.assertEqual(len(logos), 1, page.name)
            self.assertEqual(logos[0]['href'], '/', page.name)
            self.assertEqual(logos[0]['aria-label'], LABEL, page.name)


if __name__ == '__main__':
    unittest.main()
