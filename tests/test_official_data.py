import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import official_data as official, match_articles, preview_data

FIX = Path(__file__).parent / 'fixtures'


class OfficialAdapters(unittest.TestCase):
    def test_real_cumulative_values_and_compound_position_input(self):
        columns = official.stats_columns((FIX/'stats-header.html').read_text())
        payload = json.loads((FIX/'stats-totals.json').read_text())
        rows = official.parse_stats_rows(payload['topics'], columns, 'https://www.bleague.jp/stats/')
        totals = official.choose_totals(rows)
        self.assertEqual(totals['51000312']['total'], 243)
        self.assertEqual(totals['51000312']['games'], 7)
        self.assertEqual(totals['51000655']['total'], 130)
        self.assertNotEqual(totals['51000655']['total'], 26)

    def test_repeated_api_headers(self):
        columns = official.stats_columns((FIX/'stats-header.html').read_text())
        payload = json.loads((FIX/'stats-repeated-header.json').read_text())
        self.assertEqual(len(official.parse_stats_rows(payload['topics'], columns, 'https://www.bleague.jp/stats/')), 1)

    def test_average_response_rejected(self):
        class Fake:
            def get(self, url):
                return (FIX/'stats-header.html').read_text().replace('value="tot"', 'value="avg"')
        with self.assertRaises(official.DataError):
            official.fetch_totals(Fake(), 2026, 'BP')

    def test_unplayed_distinct_from_missing(self):
        from test_preview_data import player, rank
        self.assertEqual(rank([player(games=0,average=0)])['excluded'][0]['exclusion_reason'], 'no_appearance')
        self.assertEqual(rank([player(games=None,average=None)])['excluded'][0]['exclusion_reason'], 'average_unverified')

    def test_next_game_skips_completed_and_uses_actual_time(self):
        from datetime import datetime, timezone
        class Fake:
            def get(self, url):
                return '<select name="year"><option selected value="2026"></option></select><select name="mon"><option selected value="10"></option></select><div id="schedule-b1"></div><a class="js_click_data" data-day="13"></a><a class="js_click_data" data-day="16"></a>'
        future=official.parse_game((FIX/'game-506464.html').read_text(), '506464', 2026)
        old=dict(future,ended=True,starts_at='2026-10-13T00:00:00+09:00')
        with patch.object(official,'fetch_day',side_effect=[([old],True,'',[]),([future],True,'',[])]):
            result=official.fetch_next_games(Fake(),2026,'BP',datetime(2026,10,13,tzinfo=timezone.utc))
        self.assertEqual([g['game_id'] for g in result],['506464'])

    def test_real_game_and_nonplaying_flag(self):
        game = official.parse_game((FIX/'game-507233.html').read_text(), '507233', 2026)
        self.assertEqual((game['home_score'], game['away_score']), (80, 71))
        self.assertEqual(game['competition'], 'B1')
        self.assertEqual(preview_data.jst_date(game['starts_at']), '2026-10-13')
        self.assertTrue(any(p['PlayingFlg'] is False for p in game['players']))
        self.assertTrue(all(p['PeriodCategory'] == 18 for p in game['players']))

    def test_game_identity_rejects_other_scoreboard(self):
        with self.assertRaises(official.DataError):
            official.parse_game((FIX/'game-507233.html').read_text(), '507923', 2026)

    def test_real_future_no_score_invention(self):
        game = official.parse_game((FIX/'game-506464.html').read_text(), '506464', 2026)
        self.assertEqual(game['starts_at'], '2026-10-16T19:05:00+09:00')
        self.assertEqual((game['home_id'], game['away_id']), ('727', '712'))
        self.assertIsNone(game['home_score'])
        self.assertFalse(game['ended'])

    def test_cancelled_time_is_not_invented(self):
        html=(FIX/'game-506464.html').read_text().replace('19:05 TIP OFF','中止')
        game=official.parse_game(html,'506464',2026,schedule_status='cancelled')
        self.assertIsNone(game['starts_at'])
        self.assertEqual(game['official_date'],'2026-10-16')
        self.assertEqual(game['status'],'cancelled')

    def test_real_schedule_fallback(self):
        plan = official.parse_schedule((FIX/'schedule-bnext-fallback.html').read_text(), 'BN', '2026-10-13')
        self.assertTrue(plan['complete'])
        self.assertTrue(plan['no_games'])
        self.assertIn('507923', plan['keys'])

    def test_schedule_unknown_structure_not_no_games(self):
        with self.assertRaises(official.DataError):
            official.parse_schedule('<html>maintenance</html>', 'BN', '2026-10-13')

    def test_transfer_total_not_doubled(self):
        rows = [dict(player_id='a', team=team, total=total, games=games) for team,total,games in [('旧', 20, 2), ('新', 30, 3), ('TOTAL', 50, 5)]]
        self.assertEqual(official.choose_totals(rows)['a']['total'], 50)
        self.assertIsNone(official.choose_totals(rows[:2])['a']['total'])

    def test_stats_pagination_fail_closed(self):
        class Fake:
            def get(self, url):
                if 'data_format' not in url:
                    return (FIX/'stats-header.html').read_text()
                p = json.loads((FIX/'stats-totals.json').read_text());p['index']=50
                return json.dumps(p)
        with self.assertRaises(official.DataError):
            official.fetch_totals(Fake(), 2026, 'BP')

    def test_injury_removed_not_active(self):
        cells = lambda mark: '<tr>' + ''.join('<td>'+v+'</td>' for v in (mark,'9月1日','10月1日','B.PREMIER','TEST CLUB','TEST PLAYER','TEST')) + '</tr>'
        page='<table class="flat-tbl02"><thead><th>再登録不可期日</th></thead><tbody>'+cells('9月1日/')+cells('9月1日/10月2日')+'</tbody></table>'
        self.assertEqual(len(official.injury_rows(page)), 1)


class RenderingAndUpdates(unittest.TestCase):
    def game(self, **changes):
        g=official.parse_game((FIX/'game-507233.html').read_text(), '507233', 2026)
        g.update(changes);return g

    def test_partial_postponed_and_cancelled(self):
        for status in ('postponed','cancelled','unconfirmed'):
            g=self.game(status=status, ended=False, fixed=False)
            summary=preview_data.daily_results([g],date='2026-10-13',season='2026-27',competitions=['B1','BN'],schedule_complete={'B1':True,'BN':True})
            summary['schedule_complete']={'B1':True,'BN':True}
            _, text=match_articles.render_results(summary,season='2026-27',updated='TEST',schedule_sources=[])
            self.assertNotIn('80－71',text)
            self.assertIn({'postponed':'延期','cancelled':'中止','unconfirmed':'途中版'}[status],text)

    def test_correction_updates_same_article_and_preserves_on_failure(self):
        class Fake:
            sources=[];offline=True
        game=self.game()
        with tempfile.TemporaryDirectory() as folder:
            def run(games, complete=True):
                def day(client, year, league, date):
                    return (games if league=='B1' else [],complete,'https://www.bleague.jp/schedule/',[])
                with patch.object(official,'fetch_day',side_effect=day):
                    return match_articles.generate(Fake(),year=2026,date='2026-10-13',preview_keys=[],output=folder)
            run([game]);fn=Path(folder)/'article-results-one-next-20261013.html'
            self.assertIn('80－71',fn.read_text())
            run([dict(game,home_score=81)])
            self.assertIn('81－71',fn.read_text())
            self.assertEqual(len(list(Path(folder).glob('article-*.html'))),1)
            run([],False)
            self.assertIn('81－71',fn.read_text())

    def test_highlight_requires_editorial_evidence(self):
        class Fake:
            sources=[];offline=True
            def get(self,url): return 'official test report'
        with tempfile.TemporaryDirectory() as folder:
            game=self.game()
            def day(client,year,league,date):
                return ([game] if league=='B1' else [],True,'https://www.bleague.jp/schedule/',[])
            with patch.object(official,'fetch_day',side_effect=day):
                result=match_articles.generate(Fake(),year=2026,date='2026-10-13',preview_keys=[],output=folder)
                self.assertFalse(any('highlight' in f for f in result['artifacts']))
                with self.assertRaises(official.DataError):
                    match_articles.generate(Fake(),year=2026,date='2026-10-13',preview_keys=[],output=folder,editorial={'507233':{'reason':'TEST'}})
                result=match_articles.generate(Fake(),year=2026,date='2026-10-13',preview_keys=[],output=folder,editorial={'507233':{'reason':'TEST verified milestone','source':'https://www.bleague.jp/news/test/'}})
                self.assertIn('article-result-highlight-507233.html',result['artifacts'])

    def test_build_indexes_and_sitemap_without_duplicates(self):
        import shutil
        from scripts import build
        source=Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree(source,folder,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','__pycache__','tests'))
            g=self.game()
            summary=preview_data.daily_results([g],date='2026-10-13',season='2026-27',competitions=['B1','BN'],schedule_complete={'B1':True,'BN':True})
            summary['schedule_complete']={'B1':True,'BN':True}
            name,html=match_articles.render_results(summary,season='2026-27',updated='TEST',schedule_sources=[])
            (Path(folder)/name).write_text(html)
            match_articles.write_thumbnail(Path(folder),name,'試合結果','B.ONE・B.NEXT','2026-10-13')
            with patch.object(build,'ROOT',folder), patch.object(build,'DATA_DIR',str(Path(folder)/'data')), patch.object(build,'log'):
                build.main()
                build.main()
                self.assertEqual(len([a for a in build.read_articles() if a['href']==name]),1)
            self.assertIn(name,(Path(folder)/'sitemap.xml').read_text())
            self.assertIn(name,(Path(folder)/'cat-kekka.html').read_text())
            self.assertTrue(any(name in f.read_text() for f in Path(folder).glob('articles*.html')))

    def test_existing_premier_regression(self):
        from scripts import stats
        fixture=Path(__file__).parents[1]/'data/stats/2026-10-12.json'
        s=json.loads(fixture.read_text())
        before=s['eff_top'][0]['eff']
        body=stats.body_sections(s)
        self.assertIn('B.LEAGUE PREMIER',body)
        self.assertIn(str(before),body)
        self.assertIn('被ファウル',body)
        self.assertIn('被ブロック',body)


if __name__ == '__main__': unittest.main()
