"""日別の貢献度ランキング（stats）を、保存済みの確定結果から作る（10/24・未公開）。

原因（10/18 を最後に止まっていた）：stats は公式の日程ページと、確定済み試合ページの同日リンクだけで
試合を探していた。日程ページに未来の試合しか無い回は、未確定・ボックススコアの無いページを「なし」として
捨て（保留にも残さない）、過去日の試合へたどり着けなかった。保留（pending）も空のまま残った。
修正：結果側（update_results / update_match_features）が公式の確定条件で保存した試合データの
ボックススコアから集計する。公式への追加取得はしない。ニュース取得の成否にも依存しない。
"""
import copy
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


def row(team_id, name, eff, pts=10, play='20:00', period=18, category=1):
    return {'Category': category, 'PeriodCategory': period, 'TeamID': team_id, 'TeamNameJ': 'T' + team_id,
            'PlayerNameJ': name, 'PlayerNameE': name, 'PlayerNo': '1', 'PlayTime': play, 'Point': pts,
            'PT2M': 3, 'PT2A': 6, 'PT3M': 1, 'PT3A': 3, 'FTM': 1, 'FTA': 2, 'RB_TOT': 5, 'AS': 2, 'ST': 1,
            'BS': 0, 'TO': 1, 'EFF': eff, 'PLUSMINUS': 3}


def game(key, competition='BP', status='final', players=None, home_score=80, away_score=70, **extra):
    final = status == 'final'
    g = dict(game_id=key, season='2026-27', competition=competition, status=status,
             starts_at='2026-10-23T10:05:00+00:00', ended=final, fixed=final,
             source='https://www.bleague.jp/game_detail/?ScheduleKey=' + key,
             convention='りそなグループ B.LEAGUE 2026-27 B.LEAGUE PREMIER リーグ戦',
             home='H' + key, away='A' + key, home_full='Home' + key, away_full='Away' + key,
             home_id='1' + key, away_id='2' + key,
             home_score=home_score if final else None, away_score=away_score if final else None,
             players=players if players is not None else ([row('1' + key, '選手' + key, 30), row('2' + key, '相手' + key, 12)] if final else []))
    g.update(extra)
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
        self.assertIn('10月23日：集計待ち（B.PREMIER 3試合中 3試合が公式記録が未確定）', status)

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
        self.save('2026-10-22', [game('506495', players=[row('999', 'X', 20)])])
        self.assertEqual(self.run_stats()['2026-10-22'], 'held')
        self.assertEqual(self.state()['days']['2026-10-22']['holds'][0]['reason'], 'boxscore_team_mismatch')

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
