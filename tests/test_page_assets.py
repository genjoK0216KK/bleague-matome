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


if __name__ == '__main__':
    unittest.main()
