"""自動サムネを入れた記事の画像の指定（og:image・twitter:image）が1組だけになること（11/12 MINI8-OG-TAGS-QA）。

日次まとめは記事ジョブが thumb-daily-*.svg を og:image に書く。取込が自動サムネの1組を足した時に、
元の指定が残って2組になっていた。"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import page_assets, thumb_auto as ta
from tests.test_thumb_auto import Base, article, bundle

REPO = Path(__file__).resolve().parent.parent
PLAIN = ('<meta property="og:image" content="https://basuke-matome.jp/thumb-daily-20261025.svg">\n'
         '<meta name="twitter:card" content="summary_large_image">\n'
         '<meta name="twitter:image" content="https://basuke-matome.jp/thumb-daily-20261025.svg">\n')


def with_plain(html):
    return html.replace('<meta property="og:type" content="article">\n',
                        '<meta property="og:type" content="article">\n' + PLAIN, 1)


def image_metas(page):
    return {k: re.findall(r'<meta\b[^>]*\b(?:property|name)="' + re.escape(k) + r'"[^>]*\bcontent="([^"]*)"', page)
            for k in ('og:image', 'twitter:image', 'twitter:card')}


class ArticleWrittenImage(Base):
    def setUp(self):
        super().setUp()
        self.html = with_plain(article())
        (self.root / self.PATH).write_text(self.html)
        self.m = bundle(self.inbox, self.PATH, self.html)
        self.run_import()
        entry = json.loads((self.root / ta.REGISTRY).read_text())['entries'][self.PATH]
        self.og = ta.SITE + entry['files']['og']['path']

    def assert_one_auto_set(self, page):
        self.assertEqual(image_metas(page), {'og:image': [self.og], 'twitter:image': [self.og],
                                             'twitter:card': ['summary_large_image']})
        self.assertNotIn('thumb-daily-20261025.svg"', re.sub(r'<img[^>]*>', '', page))   # head に旧SVGが残らない

    def test_auto_image_replaces_article_written_svg(self):
        ta.apply_all(self.root)
        page = self.page()
        self.assert_one_auto_set(page)
        self.assertEqual(ta.editorial_fingerprint(page.encode()), self.m['editorial_fingerprint'])
        self.assertEqual(ta.stable_fingerprint(page), ta.stable_fingerprint(self.html))
        self.assertIn('data-default-src="thumb-daily-20261025.svg"', page)    # 本文の画像の戻り先はそのまま

    def test_build_after_apply_keeps_one_set_and_twice_is_a_no_op(self):
        ta.apply_all(self.root)
        once = page_assets.ensure_default_og(self.page())
        (self.root / self.PATH).write_text(once)
        self.assertEqual(ta.apply_all(self.root)['applied'], [])
        self.assertEqual(page_assets.ensure_default_og(self.page()), once)
        self.assert_one_auto_set(once)

    def test_page_already_duplicated_is_cleaned(self):
        """いまの本番と同じ形（自動の1組＋記事の旧SVG）も、次の build で1組になる。"""
        ta.apply_all(self.root)
        dup = self.page().replace('</head>', PLAIN + '</head>', 1)
        self.assertEqual(len(image_metas(dup)['og:image']), 2)
        (self.root / self.PATH).write_text(dup)
        self.assertEqual(ta.apply_all(self.root)['applied'], [self.PATH])
        self.assert_one_auto_set(self.page())

    def test_regenerated_article_with_svg_has_no_duplicate(self):
        ta.apply_all(self.root)
        (self.root / self.PATH).write_text(with_plain(article(body='19:05版の本文')))   # 記事ジョブが書き直した
        r = ta.apply_all(self.root)
        self.assertEqual(r['outdated'], [self.PATH])
        self.assert_one_auto_set(self.page())
        self.assertIn('19:05版の本文', self.page())

    def test_headline_change_goes_back_to_default_card(self):
        ta.apply_all(self.root)
        (self.root / self.PATH).write_text(self.page().replace('<h1>10/25 見出し</h1>', '<h1>10/25 試合結果</h1>'))
        before = self.page()
        r = ta.apply_all(self.root)
        self.assertEqual(r['stale'], [{'article': self.PATH, 'reason': 'title_changed'}])
        built = page_assets.ensure_default_og(self.page())
        self.assertNotIn('data-auto-thumb', built)
        self.assertEqual(image_metas(built), {'og:image': [page_assets.DEFAULT_OG_IMAGE],
                                              'twitter:image': [page_assets.DEFAULT_OG_IMAGE],
                                              'twitter:card': ['summary_large_image']})
        self.assertIn('<img class="eyecatch" src="thumb-daily-20261025.svg"', built)
        self.assertEqual(ta.stable_fingerprint(built), ta.stable_fingerprint(before))

    def test_default_card_from_page_assets_is_left_to_page_assets(self):
        """既定のカード画像（data-default-og）は page_assets の持ち物。外した記事で毎回の付け外し（差分）を起こさない。"""
        ta.apply_all(self.root)
        (self.root / self.PATH).write_text(self.page().replace('<h1>10/25 見出し</h1>', '<h1>10/25 試合結果</h1>'))
        ta.apply_all(self.root)
        built = page_assets.ensure_default_og(self.page())
        (self.root / self.PATH).write_text(built)
        r = ta.apply_all(self.root)
        self.assertEqual((r['applied'], self.page()), ([], built))

    def test_unrelated_meta_is_kept(self):
        ta.apply_all(self.root)
        page = self.page()
        for keep in ('property="og:type" content="article"', '<meta charset="UTF-8">'):
            self.assertIn(keep, page)


class RealDailyArticles(unittest.TestCase):
    """本番の日次まとめ3本（いま og:image が2本ずつ）を、手元の写しで build と同じ順に通す。"""
    PATHS = ('article-daily-20261110.html', 'article-daily-20261111.html', 'article-daily-20261112.html')

    def test_real_pages_end_with_one_set_and_unchanged_text(self):
        reg = json.loads((REPO / ta.REGISTRY).read_text())['entries']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data/thumbs').mkdir(parents=True)
            (root / ta.CONFIG).write_text(json.dumps({'enabled': True}))
            sub = {p: reg[p] for p in self.PATHS if p in reg}
            if len(sub) != len(self.PATHS):
                self.skipTest('registry に3本の記録が無い')
            (root / ta.REGISTRY).write_text(json.dumps({**json.loads((REPO / ta.REGISTRY).read_text()), 'entries': sub}))
            originals = {}
            for p, e in sub.items():
                originals[p] = (REPO / p).read_text(encoding='utf-8')
                (root / p).write_text(originals[p], encoding='utf-8')
                for f in e['files'].values():
                    (root / f['path']).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(REPO / f['path'], root / f['path'])
            ta.apply_all(root)
            for p, e in sub.items():
                page = page_assets.ensure_default_og((root / p).read_text(encoding='utf-8'))
                og = ta.SITE + e['files']['og']['path']
                metas = image_metas(page)
                self.assertEqual(metas['og:image'], [og], p)
                self.assertEqual(metas['twitter:image'], [og], p)
                self.assertEqual(len(metas['twitter:card']), 1, p)
                self.assertEqual(ta.editorial_fingerprint(page.encode()), ta.editorial_fingerprint(originals[p].encode()), p)
                self.assertEqual(ta.stable_fingerprint(page), ta.stable_fingerprint(originals[p]), p)
                body = lambda h: re.sub(r'<head>[\s\S]*?</head>', '', h)
                self.assertEqual(body(page), body(originals[p]), p)            # head 以外は1文字も変えない


if __name__ == '__main__':
    unittest.main()
