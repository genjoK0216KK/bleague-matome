"""日別の貢献度ランキング（stats）を、保存済みの確定結果から作る（10/24・未公開）。

原因（10/18 を最後に止まっていた）：stats は公式の日程ページと、確定済み試合ページの同日リンクだけで
試合を探していた。日程ページに未来の試合しか無い回は、未確定・ボックススコアの無いページを「なし」として
捨て（保留にも残さない）、過去日の試合へたどり着けなかった。保留（pending）も空のまま残った。
修正：結果側（update_results / update_match_features）が公式の確定条件で保存した試合データの
ボックススコアから集計する。公式への追加取得はしない。ニュース取得の成否にも依存しない。
"""
import copy
import itertools
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from scripts import stats, update_results

FIX = Path(__file__).parent / 'fixtures' / 'stats'
NOW = datetime(2026, 10, 24, 7, 0, tzinfo=stats.JST)


_ids = itertools.count(1000)


def row(team_id, name, eff, pts=10, play='20:00', period=18, category=1, key=None, pid=None):
    """公式ボックススコアの1行（試合合計）。ScheduleKey は game() が試合IDで埋める。PlayerID は一意。"""
    return {'Category': category, 'PeriodCategory': period, 'ScheduleKey': key, 'TeamID': team_id,
            'PlayerID': str(next(_ids)) if pid is None else pid, 'TeamNameJ': 'T' + team_id,
            'PlayerNameJ': name, 'PlayerNameE': name, 'PlayerNo': '1', 'PlayTime': play, 'Point': pts,
            'PT2M': 3, 'PT2A': 6, 'PT3M': 1, 'PT3A': 3, 'FTM': 1, 'FTA': 2, 'RB_TOT': 5, 'AS': 2, 'ST': 1,
            'BS': 0, 'TO': 1, 'EFF': eff, 'PLUSMINUS': 3}


def game(key, competition='BP', status='final', players=None, home_score=80, away_score=70, **extra):
    """starts_at は保存日（save の date）の 19:05 JST を save() が入れる。別日にする試験は starts_at を明示する。"""
    final = status == 'final'
    g = dict(game_id=key, season='2026-27', competition=competition, status=status,
             starts_at=None, ended=final, fixed=final,
             source='https://www.bleague.jp/game_detail/?ScheduleKey=' + key,
             convention='りそなグループ B.LEAGUE 2026-27 B.LEAGUE PREMIER リーグ戦',
             home='H' + key, away='A' + key, home_full='Home' + key, away_full='Away' + key,
             home_id='1' + key, away_id='2' + key,
             home_score=home_score if final else None, away_score=away_score if final else None,
             players=players if players is not None else ([row('1' + key, '選手' + key, 30), row('2' + key, '相手' + key, 12)] if final else []))
    g.update(extra)
    for r in g['players']:
        if r.get('ScheduleKey') is None:
            r['ScheduleKey'] = int(key) if key.isdigit() else key
    return g


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data/match_articles').mkdir(parents=True)
        (self.root / 'data/stats').mkdir(parents=True)
        for name, value in (('ROOT', str(self.root)), ('STATS_DIR', str(self.root / 'data/stats')),
                            ('STATE_PATH', str(self.root / 'data/stats/state.json'))):
            p = patch.object(stats, name, value); p.start(); self.addCleanup(p.stop)
        self.status = {'dates': {}}

    def save(self, date, games, schedule_complete=True, content_as_of=None):
        for g in games:
            if g.get('starts_at') is None:
                g['starts_at'] = date + 'T19:05:00+09:00'
        path = self.root / 'data/match_articles' / ('article-games-' + date.replace('-', '') + '.json')
        path.write_text(json.dumps(dict(date=date, games=games, schedule_complete=dict(BP=schedule_complete, B1=True, BN=True)),
                                   ensure_ascii=False))
        if content_as_of:
            self.status['dates'][date] = {'state': 'ok', 'content_as_of': content_as_of, 'last_checked_at': content_as_of}
            (self.root / 'data/match_articles/result-status.json').write_text(json.dumps(self.status))

    def run_stats(self, now=NOW):
        with redirect_stdout(io.StringIO()) as out:
            days = stats.run_reported(now)
        self.log = out.getvalue()
        return days

    def state(self):
        return json.loads((self.root / 'data/stats/state.json').read_text())

    def day_json(self, date):
        return json.loads((self.root / 'data/stats' / (date + '.json')).read_text())

    def stats_page(self):
        return BeautifulSoup((self.root / 'stats.html').read_text(), 'html.parser')


class Oct23Shape(Base):
    """10/23 と同じ形：B.PREMIER 3試合はすべて記録待ち（うち1試合は得点表示だけ）、他リーグは対象外。"""

    def setUp(self):
        super().setUp()
        self.save('2026-10-22', [game('506495'), game('506496'), game('507273', 'B1')], content_as_of='2026-10-23 17:22 JST')
        self.save('2026-10-23', [game('506497', status='scheduled'), game('506498', status='scheduled'),
                                 game('506499', status='unconfirmed', record_note='score_shown_without_official_record'),
                                 game('507274', 'B1'), game('507921', 'BN', status='unconfirmed',
                                                               record_note='score_shown_without_official_record')],
                  content_as_of='2026-10-23 17:22 JST')

    def test_held_games_are_recorded_with_reasons(self):
        days = self.run_stats()
        self.assertEqual(days['2026-10-23'], 'held')
        d = self.state()['days']['2026-10-23']
        self.assertEqual([(h['key'], h['reason'], h['status']) for h in d['holds']],
                         [('506497', 'record_not_fixed', 'scheduled'), ('506498', 'record_not_fixed', 'scheduled'),
                          ('506499', 'record_not_fixed', 'unconfirmed')])
        self.assertEqual(d['holds'][2]['record_note'], 'score_shown_without_official_record')
        self.assertEqual((d['games_total'], d['games_ready']), (3, 0))   # B1・BN は定義外で数えない
        self.assertIsNone(d['players'])                                    # 未集計は 0 人ではない
        self.assertEqual(self.state()['pending'], {'506497': '2026-10-23', '506498': '2026-10-23', '506499': '2026-10-23'})
        self.assertNotIn('2026-10-23', self.state()['published'])
        self.assertFalse((self.root / 'data/stats/2026-10-23.json').exists())
        self.assertIn('::notice::stats date=2026-10-23 state=held games=0/3 players=None', self.log)

    def test_previous_day_is_published_and_page_shows_newer_day_waiting(self):
        self.run_stats()
        s = self.day_json('2026-10-22')
        self.assertEqual([g['key'] for g in s['games']], ['506495', '506496'])   # B.PREMIER だけ
        self.assertEqual(s['player_count'], 4)
        self.assertEqual(s['retrieved_at'], '2026-10-23 17:22 JST')
        self.assertEqual(s['definition']['league'], 'B.PREMIER')
        status = self.stats_page().select_one('#stats-status').text
        self.assertIn('表示中：10月22日のB.PREMIER 2試合', status)
        self.assertIn('10月23日：集計待ち（B.PREMIER 3試合中 3試合：公式記録が未確定・試合前）', status)

    def test_scores_alone_never_become_eff(self):
        """得点だけ表示された試合（記録なし）から EFF を作らない。"""
        self.run_stats()
        self.assertNotIn('506499', json.dumps(self.day_json('2026-10-22')))


class Rules(Base):
    def test_eff_is_the_official_field_and_zero_minutes_are_excluded(self):
        rows = [row('1x', '公式値', 7, pts=40), row('1x', '出場なし', 0, play='00:00'),
                row('2x', '第1Q行', 50, period=1), row('2x', 'チーム行', 50, category=2), row('2x', '相手', 9)]
        self.save('2026-10-22', [game('x', players=rows, home_id='1x', away_id='2x')])
        self.run_stats()
        top = self.day_json('2026-10-22')['eff_top']
        self.assertEqual([(p['name'], p['eff']) for p in top], [('相手', 9), ('公式値', 7)])

    def test_final_without_boxscore_is_held(self):
        self.save('2026-10-22', [game('506495'), game('506496', players=[])])
        self.assertEqual(self.run_stats()['2026-10-22'], 'held')
        self.assertEqual(self.state()['days']['2026-10-22']['holds'][0]['reason'], 'boxscore_missing')

    def test_boxscore_team_mismatch_is_held(self):
        self.save('2026-10-22', [game('506495', players=[row('999', 'X', 20), row('2506495', 'Y', 5)])])
        self.assertEqual(self.run_stats()['2026-10-22'], 'held')
        self.assertEqual(self.state()['days']['2026-10-22']['holds'][0]['reason'], 'boxscore_id_mismatch')

    def test_incomplete_schedule_is_held(self):
        self.save('2026-10-22', [game('506495')], schedule_complete=False)
        self.assertEqual(self.run_stats()['2026-10-22'], 'held')
        self.assertEqual(self.state()['days']['2026-10-22']['holds'][0]['reason'], 'schedule_incomplete')

    def test_cancelled_game_is_excluded_not_held(self):
        self.save('2026-10-22', [game('506495'), game('506496', status='cancelled')])
        self.assertEqual(self.run_stats()['2026-10-22'], 'ready')
        self.assertEqual(self.state()['days']['2026-10-22']['excluded'], [{'key': '506496', 'status': 'cancelled'}])

    def test_not_retrieved_is_not_zero_games(self):
        self.save('2026-10-20', [game('507000', 'B1')])           # 取得済み・B.PREMIER の試合なし
        days = self.run_stats()
        self.assertEqual(days['2026-10-20'], 'no_games')
        self.assertEqual(days['2026-10-21'], 'not_retrieved')     # 結果データが無い日
        d = self.state()['days']['2026-10-21']
        self.assertEqual((d['games_total'], d['players'], d['content_as_of']), (None, None, None))

    def test_today_not_yet_retrieved_is_not_shown_as_missing(self):
        self.save('2026-10-22', [game('506495')])
        self.save('2026-10-21', [game('506490', status='unconfirmed')])
        self.run_stats()
        status = self.stats_page().select_one('#stats-status').text
        self.assertIn('表示中：10月22日', status)
        self.assertIn('10月21日：集計待ち', status)                      # 表示中より古い未公開日も出す
        self.assertIn('10月23日：試合結果データが未取得', status)       # 過去日の未取得は出す
        self.assertNotIn('10月24日', status)                            # 当日（NOW=10/24）はまだ出さない

    def test_unverified_final_flags_are_not_trusted(self):
        """status が final でも、終了・記録確定・得点が揃わなければ集計しない（結果側と同じ条件）。"""
        self.save('2026-10-22', [game('506495', fixed=False)])
        self.assertEqual(self.run_stats()['2026-10-22'], 'held')


class KeepOldResults(Base):
    def test_published_day_is_kept_when_a_newer_day_is_held(self):
        self.save('2026-10-22', [game('506495')])
        self.run_stats()
        before = (self.root / 'data/stats/2026-10-22.json').read_bytes()
        article = (self.root / 'article-stats-20261022.html').read_bytes()
        self.save('2026-10-23', [game('506497', status='scheduled')])
        self.run_stats(datetime(2026, 10, 24, 12, 0, tzinfo=stats.JST))
        self.assertEqual((self.root / 'data/stats/2026-10-22.json').read_bytes(), before)
        self.assertEqual((self.root / 'article-stats-20261022.html').read_bytes(), article)
        self.assertIn('表示中：10月22日', self.stats_page().select_one('#stats-status').text)

    def test_published_day_held_later_is_not_demoted(self):
        self.save('2026-10-22', [game('506495')])
        self.run_stats()
        self.save('2026-10-22', [game('506495'), game('506496', status='scheduled')])   # 追加の試合が記録待ち
        self.run_stats()
        self.assertIn('2026-10-22', self.state()['published'])
        self.assertEqual(len(self.day_json('2026-10-22')['games']), 1)

    def test_published_day_grows_when_late_game_is_fixed(self):
        self.save('2026-10-22', [game('506495')])
        self.run_stats()
        self.save('2026-10-22', [game('506495'), game('506496', players=[row('1506496', '後から', 45), row('2506496', 'B', 1)])])
        self.run_stats()
        s = self.day_json('2026-10-22')
        self.assertEqual(len(s['games']), 2)
        self.assertEqual(s['eff_top'][0]['eff'], 45)

    def test_stable_day_is_not_rewritten(self):
        self.save('2026-10-22', [game('506495')])
        self.run_stats()
        path = self.root / 'data/stats/2026-10-22.json'
        before = path.stat().st_mtime_ns, path.read_bytes()
        self.run_stats(datetime(2026, 10, 24, 12, 0, tzinfo=stats.JST))
        self.assertEqual((path.stat().st_mtime_ns, path.read_bytes()), before)

    def test_old_published_day_from_previous_method_is_kept(self):
        """旧方式で公開済みの日（試合集合が同じ）は書き換えない。"""
        self.save('2026-10-22', [game('506495')])
        self.run_stats()
        path = self.root / 'data/stats/2026-10-22.json'
        legacy = {k: v for k, v in self.day_json('2026-10-22').items() if k not in ('retrieved_at', 'definition', 'source')}
        legacy['generated'] = 'old'                                   # 旧方式の形（新しい項目なし）
        path.write_text(json.dumps(legacy, ensure_ascii=False))
        self.run_stats()
        self.assertEqual(self.day_json('2026-10-22')['generated'], 'old')


class SameAsPreviousMethod(Base):
    """10/18 の公開済みランキング（旧方式：公式ページを直接集計）と、保存済みの結果からの集計が一致する。"""

    def test_oct18_matches_published_ranking(self):
        saved = json.loads((FIX / 'article-games-20261018.json').read_text())
        old = json.loads((FIX / 'stats-2026-10-18.json').read_text())
        day = stats.assess_day('2026-10-18', saved)
        self.assertEqual(day['state'], 'ready')
        new = stats.summarise('2026-10-18', day['games'])
        self.assertEqual(new['eff_top'], old['eff_top'])
        self.assertEqual(new['leaders'], old['leaders'])
        self.assertEqual(new['player_count'], old['player_count'])
        self.assertEqual([g['key'] for g in new['games']], [g['key'] for g in old['games']])


class InvalidInput(Base):
    """差戻し 10/24 08:26：欠損を0にしない・片側だけ・別日・ID重複／欠落は理由つきで保留（game_day_rankings と同じ基準）。"""

    def held(self, games, date='2026-10-22'):
        self.save(date, games)
        days = self.run_stats()
        self.assertEqual(days[date], 'held')
        self.assertFalse((self.root / 'data/stats' / (date + '.json')).exists())
        d = self.state()['days'][date]
        self.assertIsNone(d['players'])
        return [h['reason'] for h in d['holds']]

    def rows(self, key, **change):
        rows = [row('1' + key, '選手', 30), row('2' + key, '相手', 12)]
        rows[0].update(change)
        return rows

    def test_official_zero_eff_is_counted_as_zero(self):
        self.save('2026-10-22', [game('506495', players=self.rows('506495', EFF=0))])
        self.assertEqual(self.run_stats()['2026-10-22'], 'ready')
        self.assertIn(('選手', 0), [(p['name'], p['eff']) for p in self.day_json('2026-10-22')['eff_top']])

    def test_missing_or_invalid_eff_is_not_zero(self):
        for bad in (None, '', '-', 'abc', 1.5, True):
            with self.subTest(EFF=bad):
                self.assertEqual(self.held([game('506495', players=self.rows('506495', EFF=bad))]), ['boxscore_value_invalid'])

    def test_missing_other_stat_or_playtime_is_held(self):
        for change in ({'Point': None}, {'RB_TOT': ''}, {'PLUSMINUS': None}, {'PlayTime': None}, {'PlayTime': '12:7'},
                       {'PlayerNameJ': ''}, {'Category': None}):
            with self.subTest(change=change):
                self.assertEqual(self.held([game('506495', players=self.rows('506495', **change))]), ['boxscore_value_invalid'])

    def test_one_team_only_is_held(self):
        self.assertEqual(self.held([game('506495', players=[row('1506495', '片側', 30), row('1506495', '片側2', 10)])]),
                         ['boxscore_one_team'])
        self.assertEqual(self.held([game('506495', players=[row('1506495', '片側', 30), row('2506495', '出場なし', 0, play='00:00')])]),
                         ['boxscore_one_team'])

    def test_other_day_or_missing_start_is_held(self):
        self.assertEqual(self.held([game('506495', starts_at='2026-10-23T10:05:00+00:00')]), ['date_mismatch'])   # 10/23 19:05 JST
        self.assertEqual(self.held([game('506495', starts_at='')]), ['date_mismatch'])
        self.assertEqual(self.held([game('506495', starts_at='2026-10-22T19:05:00')]), ['date_mismatch'])          # 時差なし

    def test_missing_ids_are_held(self):
        for change in ({'PlayerID': ''}, {'PlayerID': None}, {'ScheduleKey': 999999}, {'TeamID': ''}):
            with self.subTest(change=change):
                self.assertEqual(self.held([game('506495', players=self.rows('506495', **change))]), ['boxscore_id_mismatch'])
        self.assertEqual(self.held([game('506495', home_id='')]), ['boxscore_id_mismatch'])

    def test_duplicate_player_in_game_is_held(self):
        rows = self.rows('506495') + [row('1506495', '重複', 5, pid=None)]
        rows[2]['PlayerID'] = rows[0]['PlayerID']
        self.assertEqual(self.held([game('506495', players=rows)]), ['duplicate_player_id'])

    def test_same_player_in_two_games_is_held(self):
        a, b = game('506495'), game('506496')
        b['players'][0]['PlayerID'] = a['players'][0]['PlayerID']
        self.assertEqual(self.held([a, b]), ['duplicate_player_id'])

    def test_duplicate_or_missing_game_id_is_held(self):
        self.assertEqual(self.held([game('506495'), game('506495')]), ['duplicate_game_id', 'duplicate_game_id'])
        self.assertIn('duplicate_game_id', self.held([game('506495'), dict(game('506496'), game_id='')]))

    def test_held_reason_is_shown_on_page_without_dropping_old_ranking(self):
        self.save('2026-10-21', [game('506490')])
        self.run_stats()
        self.save('2026-10-22', [game('506495', players=self.rows('506495', EFF=None))])
        self.run_stats()
        status = self.stats_page().select_one('#stats-status').text
        self.assertIn('表示中：10月21日', status)
        self.assertIn('10月22日：集計待ち（B.PREMIER 1試合中 1試合：' + stats.REASON_LABEL['boxscore_value_invalid'], status)


class Corrections(Base):
    def test_corrected_value_with_same_games_is_reflected(self):
        g = game('506495')
        self.save('2026-10-22', [g])
        self.run_stats()
        self.assertEqual(self.day_json('2026-10-22')['eff_top'][0]['eff'], 30)
        g2 = copy.deepcopy(g); g2['players'][0]['EFF'] = 33           # 公式記録の訂正（試合集合は同じ）
        self.save('2026-10-22', [g2])
        self.run_stats()
        self.assertEqual(self.day_json('2026-10-22')['eff_top'][0]['eff'], 33)
        self.assertIn('<strong>33</strong>', (self.root / 'article-stats-20261022.html').read_text())
        self.assertIn('<strong>33</strong>', (self.root / 'stats.html').read_text())

    def test_corrected_score_is_reflected(self):
        g = game('506495')
        self.save('2026-10-22', [g]); self.run_stats()
        self.save('2026-10-22', [dict(copy.deepcopy(g), home_score=81)]); self.run_stats()
        self.assertEqual(self.day_json('2026-10-22')['games'][0]['home_score'], 81)

    def test_fewer_games_do_not_shrink_published_day(self):
        self.save('2026-10-22', [game('506495'), game('506496')]); self.run_stats()
        self.save('2026-10-22', [game('506495')]); self.run_stats()
        self.assertEqual(len(self.day_json('2026-10-22')['games']), 2)
        self.assertIn('少ないため維持', self.log)


class SavedRealData(unittest.TestCase):
    """main 98f7b38 の保存済み結果（10/19・21・22）は新しい厳格な検査を通り、件数も結果側と一致する。"""

    def test_saved_days_pass_strict_checks(self):
        root = Path(__file__).resolve().parents[1]
        for date, games, players in (('2026-10-19', 9, 198), ('2026-10-21', 9, 202), ('2026-10-22', 2, 42)):
            path = root / 'data/match_articles' / ('article-games-' + date.replace('-', '') + '.json')
            if not path.exists():
                self.skipTest('saved data not present')
            with self.subTest(date=date):
                saved = json.loads(path.read_text())
                day = stats.assess_day(date, saved)
                self.assertEqual((day['state'], day['games_ready'], day['players']), ('ready', games, players))
                self.assertEqual(day['players'], saved['game_day_rankings']['leagues']['BP']['eligible_players'])


class Independence(unittest.TestCase):
    def test_news_fetch_no_longer_runs_stats(self):
        text = (Path(stats.__file__).parent / 'fetch.py').read_text()
        self.assertNotIn('stats.run', text)
        self.assertNotIn('import stats', text)

    def test_stats_makes_no_official_requests(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(stats, 'ROOT', tmp), patch.object(stats, 'STATS_DIR', os.path.join(tmp, 'data/stats')), \
                patch.object(stats, 'STATE_PATH', os.path.join(tmp, 'data/stats/state.json')), \
                patch.object(stats, 'get', side_effect=AssertionError('official request')), \
                patch.object(stats.requests, 'get', side_effect=AssertionError('official request')), \
                redirect_stdout(io.StringIO()):
            stats.run(NOW)

    def test_results_failure_still_refreshes_stats(self):
        """当日結果の取得が失敗した回でも、保存済みの確定分からランキングを作り、保存対象にする。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'gh-output'; out.write_text('')
            err = ValueError('down'); err.result_errors = [{'date': '2026-10-24', 'error': 'down'}]
            with patch.object(update_results, 'run', side_effect=err), \
                    patch.object(update_results, 'refresh_stats', return_value=True) as refresh, \
                    patch.object(update_results, 'build') as build, \
                    patch('sys.argv', ['x', '--season-year', '2026', '--root', tmp]), \
                    patch.dict('os.environ', {'GITHUB_OUTPUT': str(out)}), redirect_stdout(io.StringIO()):
                self.assertEqual(update_results.main(), 1)          # 結果の失敗は失敗のまま
            refresh.assert_called_once_with(tmp)
            build.assert_called_once()
            self.assertIn('status_saved=1', out.read_text())

    def test_stats_problem_does_not_stop_results(self):
        with patch.object(stats, 'run', side_effect=OSError('disk')), redirect_stdout(io.StringIO()) as log:
            self.assertEqual(stats.run_reported(NOW), {'error': 'OSError'})
        self.assertIn('::warning::Stats ranking failed type=OSError', log.getvalue())


if __name__ == '__main__':
    unittest.main()
