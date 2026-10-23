import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from scripts import update_results as subject


class ResultsRefresh(unittest.TestCase):
    def setUp(self):
        preview = patch.object(subject.refresh_next_preview, "refresh", return_value={"changed":False})
        preview.start(); self.addCleanup(preview.stop)
        # 貢献度ランキングは tests/test_stats_daily.py で確かめる（ここでは実データに書かない）
        ranking = patch.object(subject, "refresh_stats", return_value=False)
        ranking.start(); self.addCleanup(ranking.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime.fromisoformat('2026-10-14T13:45:00+00:00')
        self.client = SimpleNamespace(request_count=14)
        self.game = dict(game_id='1', competition='B1', season='2026-27',
                         starts_at='2026-10-14T10:00:00+00:00', status='scheduled',
                         ended=False, fixed=False, home_score=None, away_score=None,
                         source='https://www.bleague.jp/game_detail/?ScheduleKey=1')
        self.summary = dict(date='2026-10-14', games=[self.game], errors=[],
                            schedule_complete=dict(BP=True, B1=True, BN=True))
        self.path = self.root / 'data/match_articles/article-games-20261014.json'

    def save(self, summary):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(summary))
        (self.root / 'article-games-20261014.html').write_text('retained')

    def call(self, summary):
        with patch.object(subject.day_articles, 'collect', return_value=summary) as collect, patch.object(subject.day_articles, 'write', return_value='article-games-20261014.html') as write:
            result = subject.run(self.root, self.client, 2026, self.now)
            return result, collect, write

    def test_timestamp_only_does_not_write(self):
        self.save(dict(self.summary, retrieved_at='old', lineups={'existing': True}))
        result, collect, write = self.call(dict(self.summary, retrieved_at='new'))
        self.assertFalse(result['changed']); write.assert_not_called()
        self.assertEqual(collect.call_args.args[2], '2026-10-14')

    def test_final_skips_all_fetches(self):
        prior = copy.deepcopy(self.summary)
        prior['games'][0].update(status='final', ended=True, fixed=True, home_score=80, away_score=71)
        # 2026-10-20: "done" now also requires the day's EFF/position TOP3; a final result
        # without it is retried (see test_backfill_unsettled.py).
        prior['game_day_rankings'] = {'leagues': {'B1': {'positions': {}}}}
        self.save(prior)
        result, collect, write = self.call(self.summary)
        self.assertEqual(result['reason'], 'already_final'); collect.assert_not_called(); write.assert_not_called()

    def test_no_games_does_not_generate(self):
        result, _, write = self.call(dict(self.summary, games=[]))
        self.assertEqual(result['reason'], 'no_games'); write.assert_not_called()

    def test_score_change_writes_without_player_refresh(self):
        self.save(self.summary)
        final = copy.deepcopy(self.summary)
        final['games'][0].update(status='final', ended=True, fixed=True, home_score=80, away_score=71)
        result, _, write = self.call(final)
        self.assertTrue(result['changed'])
        self.assertIs(write.call_args.kwargs['refresh_players'], False)

    def test_incomplete_retains_bytes(self):
        self.save(self.summary); before = self.path.read_bytes()
        broken = dict(self.summary, schedule_complete=dict(BP=True, B1=False, BN=True))
        with self.assertRaises(ValueError): self.call(broken)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_known_games_retained_even_complete(self):
        self.save(self.summary)
        with self.assertRaisesRegex(ValueError, 'Known games missing'): self.call(dict(self.summary, games=[]))

    def test_final_regression_rejected_in_partially_settled_day(self):
        prior = copy.deepcopy(self.summary)
        prior['games'][0].update(status='final', ended=True, fixed=True, home_score=80, away_score=71)
        prior['games'].append(dict(self.game, game_id='2'))
        self.save(prior)
        changed = dict(self.summary, games=[self.game, dict(self.game, game_id='2')])
        with self.assertRaisesRegex(ValueError, 'regressed'): self.call(changed)

    def test_raw_boxscore_change_is_semantic(self):
        left = copy.deepcopy(self.summary); right = copy.deepcopy(self.summary)
        left['games'][0]['players'] = [{'PlayerID': '1', 'EFF': 10}]
        right['games'][0]['players'] = [{'PlayerID': '1', 'EFF': 11}]
        self.assertNotEqual(subject.semantic(left), subject.semantic(right))

    def test_failure_exit_nonzero_without_build(self):
        with patch('sys.argv', ['update_results', '--season-year', '2026']), patch.object(subject, 'run', side_effect=ValueError('failed')), patch.object(subject.subprocess, 'run') as build:
            self.assertEqual(subject.main(), 1); build.assert_not_called()

    def test_no_change_does_not_build(self):
        with patch('sys.argv', ['update_results', '--season-year', '2026']), patch.object(subject, 'run', return_value={'changed': False}), patch.object(subject.subprocess, 'run') as build:
            self.assertEqual(subject.main(), 0); build.assert_not_called()

    def test_change_builds_once_and_build_failure_is_nonzero(self):
        with patch('sys.argv', ['update_results', '--season-year', '2026']), patch.object(subject, 'run', return_value={'changed': True}), patch.object(subject.subprocess, 'run') as build:
            self.assertEqual(subject.main(), 0); build.assert_called_once()
        with patch('sys.argv', ['update_results', '--season-year', '2026']), patch.object(subject, 'run', return_value={'changed': True}), patch.object(subject.subprocess, 'run', side_effect=subject.subprocess.CalledProcessError(1, 'build')):
            self.assertEqual(subject.main(), 1)
