"""Regressions from the independent pre-publication review."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from scripts import official_data as official, match_articles as articles, preview_data as data

FIX = Path(__file__).parent / 'fixtures'


class Client:
    sources = []
    offline = True
    def get(self, url):
        if 'ScheduleKey=506464' in url:
            return (FIX / 'game-506464.html').read_text()
        return 'Verified report fixture'


class IndependentReviewRegressions(unittest.TestCase):
    def game(self, **overrides):
        g = official.parse_game((FIX / 'game-507233.html').read_text(), '507233', 2026)
        return dict(g, **overrides)

    def summary(self, game):
        s = data.daily_results([game], date='2026-10-13', season='2026-27', competitions=['B1', 'BN'],
                               schedule_complete={'B1': True, 'BN': True})
        s['schedule_complete'] = {'B1': True, 'BN': True}
        return s

    def test_started_unfinished_game_is_not_next(self):
        for cutoff in ('2026-10-16T19:05:00+09:00', '2026-10-16T20:05:00+09:00'):
            with tempfile.TemporaryDirectory() as folder, patch.object(official, 'fetch_day', return_value=([], True, '', [])):
                r = articles.generate(Client(), year=2026, date='2026-10-16', preview_keys=['506464'],
                                      output=folder, as_of=datetime.fromisoformat(cutoff))
                self.assertTrue(any('started' in e for e in r['errors']))
                self.assertNotIn('article-preview-506464.html', r['artifacts'])

    def test_missing_score_never_claims_final_in_row(self):
        s = self.summary(self.game(home_score=None))
        self.assertEqual(s['status'], 'pending')
        _, html = articles.render_results(s, season='2026-27', updated='TEST', schedule_sources=[])
        self.assertNotIn('None', html)
        self.assertIn('<td>未確定</td>', html)
        self.assertNotIn('<td>確定</td>', html)

    def test_cancelled_and_postponed_not_highlighted(self):
        for status in ('cancelled', 'postponed'):
            g = self.game(status=status, home_score=None, away_score=None, notable_reason='Old milestone',
                          notable_source='https://www.bleague.jp/news/test/')
            self.assertEqual(self.summary(g)['individual_candidates'], [])
            with self.assertRaises(official.DataError):
                articles.render_notable(g, date='2026-10-13', updated='TEST')

    def test_highlight_withdrawal_and_no_games_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            unrelated = output / 'article-daily-20261013.html'
            unrelated.write_text('Existing independently authored article')
            def run(games, notes=None, complete=True):
                def day(client, year, league, date):
                    return (games if league == 'B1' else [], complete, 'https://www.bleague.jp/schedule/', [])
                with patch.object(official, 'fetch_day', side_effect=day):
                    return articles.generate(Client(), year=2026, date='2026-10-13', preview_keys=[], output=folder, editorial=notes)
            notes = {'507233': {'reason': 'Verified milestone fixture', 'source': 'https://www.bleague.jp/news/test/'}}
            run([self.game()], notes)
            highlight = output / 'article-result-highlight-507233.html'
            self.assertTrue(highlight.exists())
            run([self.game()])
            self.assertFalse(highlight.exists())
            self.assertFalse((output / 'thumb-result-highlight-507233.svg').exists())
            run([self.game()], notes)
            run([], complete=False)
            self.assertTrue(highlight.exists(), 'Network failure must not revoke prior work')
            result = run([])
            self.assertEqual(result['results_status'], 'no_games')
            self.assertFalse(highlight.exists())
            self.assertFalse((output / 'article-results-one-next-20261013.html').exists())
            self.assertTrue(unrelated.exists())
            state = json.loads((output / 'article-results-one-next-20261013.json').read_text())
            self.assertEqual(state['status'], 'no_games')

    def test_partial_fetch_preserves_highlight_registry_until_withdrawal(self):
        with tempfile.TemporaryDirectory() as folder:
            def run(notes=None, bn_complete=True):
                def day(client, year, league, date):
                    return ([self.game()] if league == 'B1' else [], league == 'B1' or bn_complete, '', [])
                with patch.object(official, 'fetch_day', side_effect=day):
                    return articles.generate(Client(), year=2026, date='2026-10-13', preview_keys=[], output=folder, editorial=notes)
            run({'507233': {'reason': 'Verified milestone fixture', 'source': 'https://www.bleague.jp/news/test/'}})
            run(bn_complete=False)
            state = json.loads((Path(folder) / 'article-results-one-next-20261013.json').read_text())
            self.assertEqual(state['managed_highlights'], ['507233'])
            self.assertEqual(state['individual_candidates'], [])
            self.assertTrue((Path(folder) / 'article-result-highlight-507233.html').exists())
            result = run()
            self.assertIn('article-result-highlight-507233.html', result['removed'])
            self.assertFalse((Path(folder) / 'article-result-highlight-507233.html').exists())

    def test_article_provenance_does_not_use_unrelated_newer_time(self):
        client = Client()
        urls = [official.BASE + '/game_detail/?ScheduleKey=506464', official.stats_url(2026, 'BP'), official.BASE + '/news/injury.html']
        client.sources = [{'url': url, 'retrieved_at': date + 'T00:00:00+00:00'} for url, date in zip(urls, ['2026-10-13', '2026-10-01', '2026-10-05'])]
        client.sources.append({'url': official.BASE + '/unrelated', 'retrieved_at': '2026-10-14T00:00:00+00:00'})
        raw = articles.page('Fixture', '2026-10-16', 'data', 'test', 'article-preview-506464.html', urls, '2026-10-14')
        result = articles.annotate_provenance(raw, client)
        self.assertIn('2026-10-01', result)
        self.assertIn('2026-10-05', result)
        self.assertNotIn('2026-10-14', result)
        self.assertIn('ローカル検証版', result)
        self.assertIn('noindex,nofollow', result)

    def test_live_provenance_not_labelled_offline(self):
        client = Client(); client.offline = False
        raw = articles.page('Fixture', '2026-10-16', 'data', 'test', 'article-preview-506464.html', [], 'TEST')
        self.assertNotIn('ローカル検証版', articles.annotate_provenance(raw, client))


if __name__ == '__main__': unittest.main()
