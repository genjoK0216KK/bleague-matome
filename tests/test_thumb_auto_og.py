"""自動サムネを入れた記事の画像の指定（og:image・twitter:image）が1組だけになること（11/12 MINI8-OG-TAGS-QA）。

日次まとめは記事ジョブが thumb-daily-*.svg を og:image に書く。取込が自動サムネの1組を足した時に、
元の指定が残って2組になっていた。"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
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


class _HeadMetas(HTMLParser):
    """試験側の独立した読み取り（標準の HTMLParser。属性名は小文字、空白・引用符の違いは吸収される）。"""
    def __init__(self):
        super().__init__()
        self.in_head, self.metas = False, []

    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.in_head = True
        elif tag == 'meta' and self.in_head:
            self.metas.append({k: (v or '') for k, v in attrs})

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False


def image_metas(page):
    parser = _HeadMetas()
    parser.feed(page)
    out = {k: [] for k in ('og:image', 'twitter:image', 'twitter:card')}
    for m in parser.metas:
        for key in {m.get('property', '').lower(), m.get('name', '').lower()} & set(out):
            out[key].append(m.get('content', ''))
    return out


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

    # ---- 2回目のQA（11/12 ChatGPT「直してから」）の指摘①〜④

    def write_head(self, extra):
        page = self.html.replace('</head>', extra + '</head>', 1)
        (self.root / self.PATH).write_text(page)
        return page

    def test_intended_other_images_are_kept(self):
        """①：SVG 以外の画像の指定（記事が意図して書いた別の画像）は消さない。"""
        keep = ('<meta name="twitter:image" content="https://basuke-matome.jp/thumbs/special-20261025.jpg">\n'
                '<meta property="og:image" content="https://basuke-matome.jp/og-default.png">\n'
                '<meta property="og:image" content="https://example.com/thumb-daily-20261025.svg">\n'
                '<meta name="twitter:card" content="summary">\n')
        self.write_head(keep)
        ta.apply_all(self.root)
        page = self.page()
        for line in keep.splitlines():
            self.assertIn(line, page)
        self.assertNotIn('content="https://basuke-matome.jp/thumb-daily-20261025.svg"', page)   # SVG だけ消える

    def test_lookalike_attributes_are_not_touched(self):
        """①④：property・name 以外の属性（data-property 等）や、値に og:image を含むだけの meta は消さない。"""
        keep = ('<meta name="description" data-property="og:image" content="https://basuke-matome.jp/thumb-daily-20261025.svg">\n'
                '<meta itemprop="image" content="https://basuke-matome.jp/thumb-daily-20261025.svg">\n'
                '<meta property="og:image:alt" content="thumb-daily-20261025.svg">\n'
                '<meta name="xtwitter:image" content="https://basuke-matome.jp/thumb-daily-20261025.svg">\n')
        self.write_head(keep)
        ta.apply_all(self.root)
        page = self.page()
        for line in keep.splitlines():
            self.assertIn(line, page)

    def test_spacing_case_and_quotes_are_recognized(self):
        """③④：属性の前後の空白・大文字小文字・引用符の違いがあっても、記事ジョブの SVG は1つも残らない。"""
        odd = ('<META Property = "og:image" CONTENT = "https://basuke-matome.jp/thumb-daily-20261025.svg" >\n'
               "<meta name='Twitter:Image' content='/thumb-daily-20261025.svg'/>\n"
               '<meta property=og:image content=thumb-daily-20261025.svg>\n'
               '<meta name="twitter:card"   content="SUMMARY_LARGE_IMAGE">\n')
        self.write_head(odd)
        ta.apply_all(self.root)
        self.assert_one_auto_set(self.page())
        self.assertEqual(ta.apply_all(self.root)['applied'], [])          # 再実行で変化なし

    def test_meta_outside_head_is_not_touched(self):
        body = '<meta property="og:image" content="https://basuke-matome.jp/thumb-daily-20261025.svg">'
        page = self.html.replace('<p class="lead">', body + '<p class="lead">', 1)
        (self.root / self.PATH).write_text(page)
        ta.apply_all(self.root)
        self.assertIn(body + '<p class="lead">', self.page())

    def test_restore_alone_leaves_exactly_the_default_card(self):
        """②④：restore_html だけを通しても、画像の指定が0件の状態を作らない（既定のカード1組）。"""
        ta.apply_all(self.root)
        restored = ta.restore_html(self.page())
        self.assertNotIn('data-auto-thumb', restored)
        self.assertEqual(image_metas(restored), {'og:image': [page_assets.DEFAULT_OG_IMAGE],
                                                 'twitter:image': [page_assets.DEFAULT_OG_IMAGE],
                                                 'twitter:card': ['summary_large_image']})
        self.assertEqual(page_assets.ensure_default_og(restored), restored)          # build の後処理でも変わらない
        self.assertEqual(ta.restore_html(restored), restored)                         # 何度通しても同じ

    def test_restore_keeps_intended_other_image(self):
        keep = '<meta property="og:image" content="https://basuke-matome.jp/thumbs/special-20261025.jpg">\n'
        self.write_head(keep)
        ta.apply_all(self.root)
        restored = ta.restore_html(self.page())
        self.assertIn(keep, restored)
        self.assertNotIn('og-default.png', restored)        # 画像の指定が残っているので既定のカードは足さない
        self.assertNotIn('thumb-daily-20261025.svg"', re.sub(r'<img[^>]*>', '', restored))


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
