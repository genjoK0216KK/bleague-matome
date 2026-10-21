"""ニュース取得が全滅しても、公開済みの記事を一覧に載せる（10/22・未公開）。

実例：main 5b71ef8 で article-daily-20261022.html が公開済みなのに、01:22 のニュース取得 503 で
update.yml が止まり、index / articles に載っていなかった。出力範囲を固定し、それ以外は1バイトも変えない。
"""
import hashlib
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from bs4 import BeautifulSoup

from scripts import refresh_listings

ROOT = Path(__file__).resolve().parents[1]
NEW = 'article-daily-20261022.html'
ALLOWED = re.compile(r'(articles(-\d+)?\.html|cat-data(-\d+)?\.html|index\.html|sitemap\.xml)\Z')


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts}


class RefreshListings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'site'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        # 試験の前提：公開済みなのに一覧に未掲載（main 5b71ef8 と同じ状態）
        self.assertTrue((self.root / NEW).exists())
        self.assertNotIn(NEW, (self.root / 'articles.html').read_text())
        offline = patch.object(requests, 'get', side_effect=AssertionError('no network'))
        offline.start(); self.addCleanup(offline.stop)

    def test_new_article_is_listed_and_nothing_else_changes(self):
        before = snapshot(self.root)
        index_before = BeautifulSoup((self.root / 'index.html').read_text(), 'html.parser')
        written = refresh_listings.refresh(str(self.root))
        after = snapshot(self.root)
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        self.assertEqual(changed, written)
        self.assertTrue(changed)
        self.assertEqual([c for c in changed if not ALLOWED.fullmatch(c)], [])   # fixed output range
        # listed everywhere it belongs
        self.assertIn(NEW, (self.root / 'articles.html').read_text())
        self.assertIn(NEW, (self.root / 'cat-data.html').read_text())
        self.assertIn('<loc>https://basuke-matome.jp/' + NEW + '</loc>', (self.root / 'sitemap.xml').read_text())
        index_after = BeautifulSoup((self.root / 'index.html').read_text(), 'html.parser')
        self.assertEqual(index_after.select('#own-articles a.own-card')[0]['href'], NEW)
        # everything else on the top page is byte-for-byte the same section
        for sel in ('#ranking', '#updates', '#games', 'aside.side', 'header', 'footer', 'head'):
            self.assertEqual(str(index_before.select_one(sel)), str(index_after.select_one(sel)), sel)

    def test_data_and_article_bodies_are_untouched(self):
        before = snapshot(self.root)
        refresh_listings.refresh(str(self.root))
        after = snapshot(self.root)
        for name in ('data/news.json', 'data/matome.json', 'data/standings.json',
                     'data/match_articles/result-status.json', NEW, 'article-games-20261021.html',
                     'article-games-20261022.html', 'news.html', 'matome.html', 'cat-kekka.html'):
            self.assertEqual(before[name], after[name], name)
        old_sitemap = [l for l in (ROOT / 'sitemap.xml').read_text().splitlines() if '<url>' in l]
        new_sitemap = [l for l in (self.root / 'sitemap.xml').read_text().splitlines() if '<url>' in l]
        self.assertEqual(new_sitemap[:len(old_sitemap)], old_sitemap)   # existing lastmod kept
        self.assertEqual(len(new_sitemap), len(old_sitemap) + 1)

    def test_category_page_keeps_its_data_timestamp(self):
        stamp = re.compile(r'<!-- AUTO:UPDATED:START -->(.*?)<!-- AUTO:UPDATED:END -->')
        old = stamp.search((self.root / 'cat-data.html').read_text()).group(1)
        refresh_listings.refresh(str(self.root))
        self.assertEqual(stamp.search((self.root / 'cat-data.html').read_text()).group(1), old)

    def test_identical_input_is_a_no_op(self):
        refresh_listings.refresh(str(self.root))
        before = snapshot(self.root)
        self.assertEqual(refresh_listings.refresh(str(self.root)), [])
        self.assertEqual(snapshot(self.root), before)

    def test_same_day_article_update_is_reflected(self):
        """独立QA再現：掲載後に同じ記事の h1 を書き換える（12時・19時の同日更新）→ 一覧も追従。"""
        refresh_listings.refresh(str(self.root))
        path = self.root / NEW
        path.write_text(path.read_text().replace('<h1>', '<h1>【12時更新】', 1))
        before = snapshot(self.root)
        written = refresh_listings.refresh(str(self.root))
        self.assertEqual(written, ['articles.html', 'cat-data.html', 'index.html'])
        for fn in written:
            self.assertIn('【12時更新】', (self.root / fn).read_text(), fn)
        after = snapshot(self.root)
        self.assertEqual(sorted(k for k in after if before[k] != after[k]), written)

    def test_partial_failure_is_repaired(self):
        """独立QA再現：articles には載っているのに index だけ欠落 → 直る。"""
        refresh_listings.refresh(str(self.root))
        index = self.root / 'index.html'
        soup = BeautifulSoup(index.read_text(), 'html.parser')
        card = soup.select_one('#own-articles a.own-card[href="%s"]' % NEW)
        text = index.read_text().replace(str(card), '', 1)
        self.assertNotIn(NEW, BeautifulSoup(text, 'html.parser').select_one('#own-articles').decode())
        index.write_text(text)
        self.assertEqual(refresh_listings.refresh(str(self.root)), ['index.html'])
        self.assertEqual(BeautifulSoup(index.read_text(), 'html.parser')
                         .select_one('#own-articles a.own-card')['href'], NEW)

    def test_news_data_empty_or_broken_does_not_block_listing(self):
        for content in ('[]', '{broken', ''):
            with self.subTest(news=content or 'empty file'):
                shutil.copy(ROOT / 'articles.html', self.root / 'articles.html')
                (self.root / 'data/news.json').write_text(content)
                refresh_listings.refresh(str(self.root))
                self.assertIn(NEW, (self.root / 'articles.html').read_text())
                self.assertEqual((self.root / 'data/news.json').read_text(), content)   # not repaired/overwritten

    def test_workflow_step_runs_only_after_fetch_failure_and_stages_fixed_files(self):
        text = (ROOT / '.github/workflows/update.yml').read_text()
        self.assertIn('id: fetch', text)
        step = text.split('ニュース取得失敗時：公開済み記事を一覧に載せる')[1].split('- name:')[0]
        self.assertIn("if: failure() && steps.fetch.outcome == 'failure'", step)
        self.assertIn("git add -- 'articles*.html' 'cat-*.html' index.html sitemap.xml", step)
        self.assertNotIn('git add -A', step)
        self.assertNotIn('continue-on-error', text)


if __name__ == '__main__':
    unittest.main()
