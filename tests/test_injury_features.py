import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
from scripts import official_data as official, injury_page, match_articles as articles, update_match_features as update


def fixture():
    rows = [('9月25日/', '9月25日', '10月25日', 'B.PREMIER', 'Team', 'Player', 'PRIVATE DIAGNOSIS'),
            ('7月1日/9月4日', '7月1日', '7月31日', 'B1', 'Team', 'Player', 'PRIVATE DIAGNOSIS'),
            ('7月1日/10月1日', '7月1日', '7月31日', 'B.PREMIER', 'Other', 'Returned', 'PRIVATE DIAGNOSIS'),
            ('9月10日/', '9月9日', '10月9日', 'B1', 'Team', 'Expired', 'PRIVATE DIAGNOSIS')]
    return '<p>公示日：2026年10月5日</p><table class="flat-tbl02"><thead><th>再登録不可期日</th></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+v+'</td>' for v in r)+'</tr>' for r in rows) + '</tbody></table>'


class ILTests(unittest.TestCase):
    def test_dates_current_and_history_minimal(self):
        records = official.injury_records(fixture())
        self.assertEqual(len([r for r in records if r['active']]), 2)
        self.assertEqual(records[-1]['registered_date'], '9月9日')
        self.assertEqual(records[-1]['announced_date'], '9月10日')
        self.assertNotIn('PRIVATE', json.dumps(records))
        self.assertTrue(records[-1]['active'], 'Expired restriction does not mean removed')

    def test_active_overrides_old_removal_and_return_not_confirmed(self):
        records = official.injury_records(fixture())
        players = [dict(player_id='1', name='Player', team_id='1', availability='unknown'), dict(player_id='2', name='Returned', team_id='2', availability='unknown')]
        game = dict(home_id='1', away_id='2', home_full='Team', away_full='Other')
        class C:
            def get(self, url): return ''
        official.apply_injuries(C(), players, [r for r in records if r['active']], game, [r for r in records if not r['active']])
        self.assertEqual(players[0]['availability'], 'out')
        self.assertNotIn('il_removed_date', players[0])
        self.assertEqual(players[1]['availability'], 'unknown')
        self.assertEqual(players[1]['il_removed_date'], '10月1日')

    def test_stale_failed_state_keeps_original_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            payload = dict(records=official.injury_records(fixture()), retrieved_at='2026-10-12T00:00:00+00:00', source=injury_page.URL)
            state.write_text(json.dumps(payload))
            class C:
                offline = False
                def get(self, url): raise official.DataError('network fixture')
            error = injury_page.generate(C(), folder, state, datetime(2026, 10, 13, tzinfo=timezone.utc))
            self.assertTrue(error)
            self.assertEqual(json.loads(state.read_text())['retrieved_at'], payload['retrieved_at'])
            html = (Path(folder)/'injury.html').read_text()
            self.assertIn('最新取得に失敗', html)
            self.assertIn('12時間超', html)
            self.assertIn('現在は再びIL登録中', html)
            self.assertNotIn('PRIVATE DIAGNOSIS', html)

    def test_no_prior_data_not_zero_confirmed(self):
        html = injury_page.render({}, datetime.now(timezone.utc), failed=True)
        self.assertIn('登録者がいないという意味ではありません', html)

    def test_top_three_including_boundary_ties(self):
        game = official.parse_game((Path(__file__).parent/'fixtures/game-506464.html').read_text(), '506464', 2026)
        players = [dict(player_id=str(i), name='Player'+str(i), team='Team', season=game['season'], competition=game['competition'], positions=['PG'], position_source='https://www.bleague.jp/club_detail/', availability='unknown', metric='EFF', aggregation='average', average=score, games=4, stats_source='https://www.bleague.jp/stats/', coverage_complete=True) for i,score in enumerate([10,9,8,8,7])]
        _, html = articles.render_preview(game, players, updated='TEST')
        soup = BeautifulSoup(html,'html.parser')
        self.assertEqual(len(soup.select('table tr'))-1, 4)
        self.assertNotIn('Player4', soup.get_text())
        self.assertIn('上位3人', soup.get_text())

    def test_budget_blocks_before_request(self):
        client = official.Client(max_requests=0)
        with patch.object(official.requests, 'get') as get:
            with self.assertRaises(official.DataError): client.get(injury_page.URL)
            get.assert_not_called()

    def test_wrapper_with_preview_and_il_history(self):
        fixture_dir = Path(__file__).parent / 'fixtures'
        future_body = (fixture_dir / 'game-506464.html').read_text()
        future = official.parse_game(future_body, '506464', 2026)
        now = datetime(2026, 10, 13, 13, tzinfo=timezone.utc)
        class C:
            offline = True
            request_count = 0
            sources = [{'url': injury_page.URL, 'retrieved_at': '2026-10-13T13:00:00+00:00'}]
            def get(self, url):
                return fixture() if url == injury_page.URL else future_body
        calls = []
        def day(client, year, league, date):
            calls.append(date)
            return [], True, '', []
        with tempfile.TemporaryDirectory() as folder, patch.object(official, 'fetch_day', side_effect=day), patch.object(official, 'fetch_next_games', side_effect=lambda c,y,l,n: [future] if l == 'BP' else []), patch.object(official, 'fetch_averages', return_value={}), patch.object(official, 'fetch_roster', return_value=[]):
            report = update.run(folder, C(), 2026, now.astimezone(articles.data.JST))
            self.assertTrue(any('選手資料の取得時刻' in e for e in report['errors']))
            self.assertFalse((Path(folder) / 'article-preview-506464.html').exists())  # next fixtures now use the dedicated hub
            self.assertTrue((Path(folder) / 'injury.html').exists())
            self.assertTrue((Path(folder) / 'next-games.html').exists())
            self.assertEqual(calls[:6], ['2026-10-13']*3 + ['2026-10-12']*3)
            self.assertFalse((Path(folder) / 'generation-report.json').exists())

    def test_profile_failure_preserves_already_verified_il(self):
        records = official.injury_records(fixture())
        roster = [dict(player_id='1', name='Player', team_id='1'),dict(player_id='2', name='別名', team_id='1')]
        class C:
            def get(self, url): raise official.DataError('profile unavailable')
        with self.assertRaises(official.DataError):
            official.apply_injuries(C(), roster, [r for r in records if r['active']], dict(home_id='1', away_id='2', home_full='Team', away_full='Other'))
        self.assertEqual(roster[0]['availability'], 'out')

    def test_exact_japanese_il_match_needs_no_profile_requests(self):
        records = official.injury_records(fixture())
        roster = [dict(player_id='1', name='Player', team_id='1'),dict(player_id='2', name='Expired', team_id='1'),dict(player_id='3', name='Unrelated', team_id='1')]
        class C:
            def get(self, url): raise AssertionError('All IL identities already matched')
        official.apply_injuries(C(), roster, [r for r in records if r['active']], dict(home_id='1', away_id='2', home_full='Team', away_full='Other'))
        self.assertEqual(roster[0]['availability'], 'out')
        self.assertIn('選手公示日：9月25日', roster[0]['availability_detail'])

    def test_yearless_removal_not_recent_without_dated_evidence(self):
        players = [dict(player_id='1', team_id='10', il_removed_date='8月21日', il_source=injury_page.URL, availability_detail='old')]
        articles.verified_recent_returns(players, {}, datetime(2026,10,13,tzinfo=timezone.utc))
        self.assertNotIn('il_removed_date', players[0])
        players = [dict(player_id='18845', team_id='712', il_removed_date='10月1日')]
        articles.verified_recent_returns(players, {'18845':dict(team_id='712',removed_date='2026-10-01',source='https://www.ibarakirobots.win/news/20261001_01_team/')}, datetime(2026,10,13,tzinfo=timezone.utc))
        self.assertEqual(players[0]['il_removed_date'], '2026-10-01')

    def test_promote_refuses_unmanaged_files(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(official.DataError):
                update.promote(Path(folder), Path(folder), {'artifacts':[], 'removed':['index.html']})


if __name__ == '__main__': unittest.main()
