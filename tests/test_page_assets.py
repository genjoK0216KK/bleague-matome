import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import page_assets


class DefaultShareCard(unittest.TestCase):
    def test_page_without_image_gets_the_site_card_once(self):
        page = '<html><head><meta content="https://basuke-matome.jp/" property="og:url"/></head><body></body></html>'
        once = page_assets.ensure_default_og(page)
        self.assertIn('property="og:image" content="https://basuke-matome.jp/og-default.png" data-default-og', once)
        self.assertIn('name="twitter:card" content="summary_large_image" data-default-og', once)
        self.assertEqual(page_assets.ensure_default_og(once), once)

    def test_auto_thumbnail_wins_over_the_site_card(self):
        page = ('<html><head><meta property="og:image" content="https://basuke-matome.jp/og-default.png" data-default-og>\n'
                '<meta property="og:image" content="https://basuke-matome.jp/thumbs/auto/a-og.jpg" data-auto-thumb="x">\n'
                '</head></html>')
        out = page_assets.ensure_default_og(page)
        self.assertNotIn('data-default-og', out)
        self.assertIn('thumbs/auto/a-og.jpg', out)

    def test_existing_twitter_card_is_not_repeated(self):
        page = '<html><head><meta name="twitter:card" content="summary"></head></html>'
        out = page_assets.ensure_default_og(page)
        self.assertEqual(out.count('twitter:card'), 1)
        self.assertIn('og:image', out)

    # ---- 11/12 MINI8-OG-TAGS-QA：meta は HTMLParser で読む（空白・属性名の取り違え・値の中の「>」）

    def test_spaced_og_image_counts_as_an_image(self):
        page = '<html><head><meta property = "og:image" content = "https://basuke-matome.jp/x.jpg"></head><body></body></html>'
        self.assertEqual(page_assets.ensure_default_og(page), page)

    def test_uppercase_and_unquoted_og_image_counts(self):
        page = '<html><head><META PROPERTY=og:image CONTENT=https://basuke-matome.jp/x.jpg></head><body></body></html>'
        self.assertEqual(page_assets.ensure_default_og(page), page)

    def test_lookalike_attribute_is_not_an_image(self):
        page = '<html><head><meta name="description" data-property="og:image" content="d"></head><body></body></html>'
        out = page_assets.ensure_default_og(page)
        self.assertIn('property="og:image" content="https://basuke-matome.jp/og-default.png" data-default-og', out)

    def test_og_image_in_body_or_script_is_not_counted(self):
        page = ('<html><head><script>var s = \'<meta property="og:image" content="x">\';</script></head>'
                '<body><meta property="og:image" content="y"></body></html>')
        self.assertIn('data-default-og', page_assets.ensure_default_og(page))

    def test_default_card_with_greater_than_in_attribute_is_replaced_whole(self):
        page = ('<html><head><meta data-note="a > b" property="og:image" content="https://basuke-matome.jp/og-default.png" data-default-og>\n'
                '</head><body></body></html>')
        out = page_assets.ensure_default_og(page)
        self.assertNotIn('data-note', out)
        self.assertEqual(out.count('property="og:image"'), 1)
        self.assertEqual(page_assets.ensure_default_og(out), out)

    def test_remove_head_metas_changes_nothing_else(self):
        page = '<html><head>\n  <meta name="a" content="1">\n<meta name="b" content="2">\n</head><body><p>x</p></body></html>'
        out = page_assets.remove_head_metas(page, lambda a: a.get('name') == 'a')
        self.assertEqual(out, '<html><head>\n<meta name="b" content="2">\n</head><body><p>x</p></body></html>')


if __name__ == '__main__':
    unittest.main()
