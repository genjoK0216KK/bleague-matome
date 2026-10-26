"""記事を作った時に1回だけサムネの依頼を積む（MINI-8、本人 10/26「サムネは記事を作成する時のみ。巡回は必要ない」）。"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts import thumb_auto as ta, thumb_requests as tr

T0 = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)


def page(body, pv=None):
    pvb = f'<!-- AUTO:PV:START -->{pv} views<!-- AUTO:PV:END -->' if pv is not None else ''
    return f'<html><body><article><h1>見出し</h1><div class="pmeta">{pvb}</div><p>{body}</p></article></body></html>'


class Record(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data/thumbs').mkdir(parents=True)
        self.enable(True)
        (self.root / 'article-daily-20261025.html').write_text(page('既存A'))
        (self.root / 'article-games-20261026.html').write_text(page('既存B'))
        (self.root / 'article-daily-20261020.html').write_text(page('対象外の古い記事'))

    def enable(self, on):
        (self.root / ta.CONFIG).write_text(json.dumps({'enabled': on}))

    def ledger(self):
        return json.loads((self.root / tr.REQUESTS).read_text())['events']

    def test_disabled_writes_nothing(self):
        self.enable(False)
        r = tr.record(self.root, T0)
        self.assertEqual((r['enabled'], r['requested']), (False, []))
        self.assertFalse((self.root / tr.REQUESTS).exists())

    def test_record_before_init_adds_nothing(self):
        r = tr.record(self.root, T0)
        self.assertEqual((r['initialized'], r['requested']), (False, []))
        self.assertFalse((self.root / tr.REQUESTS).exists())

    def test_init_registers_existing_articles_as_baseline_once(self):
        r = tr.init(self.root, T0)
        self.assertEqual(r['baseline'], ['article-daily-20261025.html', 'article-games-20261026.html'])
        self.assertNotIn('article-daily-20261020.html', self.ledger())   # START より前は対象外
        self.assertTrue(all(e['status'] == 'baseline' for e in self.ledger().values()))
        self.assertEqual(tr.init(self.root, T0), {'created': False, 'baseline': []})   # 2回目は何もしない

    def test_first_update_after_init_requests_new_articles(self):
        """P2-3：有効化直後の最初の更新で作られた記事を基準に取り込んで取りこぼさない。"""
        tr.init(self.root, T0)
        (self.root / 'article-daily-20261027.html').write_text(page('有効化直後に作られた記事'))
        r = tr.record(self.root, T0)
        self.assertEqual(r['requested'], ['article-daily-20261027.html'])
        self.assertEqual(self.ledger()['article-daily-20261027.html']['status'], 'requested')

    def test_new_article_is_requested_once_with_pinned_source(self):
        tr.init(self.root, T0)
        new = self.root / 'article-daily-20261027.html'
        new.write_text(page('新しい記事'))
        r = tr.record(self.root, T0)
        self.assertEqual(r['requested'], ['article-daily-20261027.html'])
        e = self.ledger()['article-daily-20261027.html']
        raw = new.read_bytes()
        self.assertEqual(e['event_id'], tr.event_id('article-daily-20261027.html'))
        self.assertEqual(e['source_blob_sha'], ta.blob_sha(raw))                    # GitHub から固定版を取り出せる
        self.assertEqual(e['editorial_fingerprint'], ta.editorial_fingerprint(raw))  # 生成側と同じ定義
        self.assertEqual(e['article_url'], 'https://basuke-matome.jp/article-daily-20261027.html')

    def test_updates_reruns_and_view_counts_never_add_requests(self):
        tr.init(self.root, T0)
        new = self.root / 'article-daily-20261027.html'
        new.write_text(page('新しい記事'))
        tr.record(self.root, T0)
        before = (self.root / tr.REQUESTS).read_text()
        new.write_text(page('本文を更新した', pv=40))                        # 本文更新・閲覧数
        (self.root / 'article-daily-20261025.html').write_text(page('既存Aも更新'))
        for _ in range(3):                                                  # 再実行
            self.assertEqual(tr.record(self.root, T0)['requested'], [])
        self.assertEqual((self.root / tr.REQUESTS).read_text(), before)      # 台帳は1文字も変わらない

    def test_event_id_depends_only_on_article_path(self):
        self.assertEqual(tr.event_id('article-daily-20261027.html'), tr.event_id('article-daily-20261027.html'))
        self.assertNotEqual(tr.event_id('article-daily-20261027.html'), tr.event_id('article-games-20261027.html'))

    def test_build_records_after_all_pages_are_written(self):
        text = (Path(__file__).resolve().parents[1] / 'scripts/build.py').read_text()
        main = text[text.index('def main():'):]
        self.assertLess(main.index('write_sitemap()'), main.index('thumb_requests.record(ROOT)'))


if __name__ == '__main__':
    unittest.main()
