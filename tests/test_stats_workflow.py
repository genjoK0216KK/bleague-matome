"""ニュース取得が失敗した回も、貢献度ランキングを独立に集計・保存する（差戻し 10/24 08:26 の1群）。

1) update.yml の各ステップの実行条件を GitHub Actions の規則どおりに評価し（tests/test_il_save.simulate）、
   失敗の組み合わせごとに stats の集計・保存ステップが動き、ジョブの失敗が失敗のまま残るかを確かめる。
2) save_stats.py を一時的な git リポジトリ（公開先は bare リポジトリ）で動かし、失敗した回の途中の生成物を
   公開も集計もせず、コミット済みの確定結果から作った stats の成果物だけが公開されることを確かめる。
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts import save_stats, stats
from tests.test_il_save import CHECK, FALLBACK, FEATURES, NORMAL, SAVE, BUILD, chdir, sh, simulate, steps
from tests.test_stats_daily import game

STATS_NAME = '貢献度ランキングを集計・保存（ニュースと独立）'
STATS = 'stats'   # simulate はステップの id で結果を持つ
NOW = datetime(2026, 10, 24, 7, 30, tzinfo=stats.JST)


class WorkflowConditions(unittest.TestCase):
    def test_stats_runs_on_every_failure_combination(self):
        cases = {
            'all ok':                 ({}, False),
            'news fails':             ({'fetch': 'failure'}, True),
            'news + listing fallback fail': ({'fetch': 'failure', FALLBACK: 'failure'}, True),
            'match features fail':    ({FEATURES: 'failure'}, True),
            'build fails':            ({BUILD: 'failure'}, True),
            'normal commit fails':    ({NORMAL: 'failure'}, True),
            'IL save fails':          ({SAVE: 'failure'}, True),
        }
        for name, (results, job_failed) in cases.items():
            for il in ('ok', 'failed'):
                with self.subTest(name, il=il):
                    if il == 'failed':
                        results = dict(results, **{CHECK: 'failure'})
                    ran, failed = simulate(results, {'il': {'il_status': il}})
                    self.assertIn(STATS, ran)
                    self.assertEqual(failed, job_failed or il == 'failed')   # 失敗は失敗のまま

    def test_news_failure_skips_features_but_not_stats(self):
        ran, failed = simulate({'fetch': 'failure'}, {'il': {'il_status': 'ok'}})
        self.assertNotIn(FEATURES, ran)
        self.assertNotIn(NORMAL, ran)
        self.assertIn(STATS, ran)
        self.assertTrue(failed)

    def test_stats_failure_is_reported(self):
        ran, failed = simulate({STATS: 'failure'}, {'il': {'il_status': 'ok'}})
        self.assertNotIn(CHECK, ran)
        self.assertTrue(failed)

    def test_order_and_definition(self):
        names = [s['name'] for s in steps()]
        self.assertEqual(names[-3:], [SAVE, STATS_NAME, CHECK])     # IL を保存した後・IL確認の前
        step = next(s for s in steps() if s['name'] == STATS_NAME)
        self.assertEqual(step['if'], 'always()')
        self.assertIn('python scripts/save_stats.py', step['run'])
        self.assertNotIn('continue-on-error', step)


class SaveStats(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.remote, self.repo = base / 'remote.git', base / 'work'
        sh(base, 'init', '-q', '--bare', '-b', 'main', str(self.remote))
        sh(base, 'clone', '-q', str(self.remote), str(self.repo))
        for k, v in (('user.name', 'bot'), ('user.email', 'bot@example.com')):
            sh(self.repo, 'config', k, v)
        (self.repo / 'data/match_articles').mkdir(parents=True)
        (self.repo / 'data/stats').mkdir(parents=True)
        self.results = self.repo / 'data/match_articles/article-games-20261022.json'
        self.write_results([game('506495')])
        (self.repo / 'data/stats/state.json').write_text('{"pending": {}, "published": []}')
        for name in ('index.html', 'injury.html'):
            (self.repo / name).write_text('old ' + name)
        sh(self.repo, 'add', '-A'); sh(self.repo, 'commit', '-q', '-m', 'base'); sh(self.repo, 'push', '-q', 'origin', 'main')
        for name in ('ROOT', 'STATS_DIR', 'STATE_PATH'):      # use_root がモジュール変数を書き換えるので戻す
            p = patch.object(stats, name, getattr(stats, name)); p.start(); self.addCleanup(p.stop)

    def write_results(self, games):
        for g in games:
            g['starts_at'] = '2026-10-22T19:05:00+09:00'
        self.results.write_text(json.dumps(dict(date='2026-10-22', games=games,
                                                schedule_complete=dict(BP=True, B1=True, BN=True)), ensure_ascii=False))

    def run_save(self):
        with chdir(self.repo), redirect_stdout(io.StringIO()) as out:
            result = save_stats.save(now=NOW, root=str(self.repo))
        self.log = out.getvalue()
        return result

    def last_commit_files(self):
        return sorted(sh(self.remote, 'log', '-1', '--name-only', '--format=', 'main').split())

    def published(self, path):
        return sh(self.remote, 'show', 'main:' + path)

    def test_news_failure_run_publishes_only_stats_from_committed_results(self):
        # 失敗した工程の途中の生成物：未コミットの結果（EFF を壊したもの）と途中の index.html
        broken = game('506495'); broken['players'][0]['EFF'] = 99
        self.write_results([broken])
        (self.repo / 'index.html').write_text('half built')
        self.assertEqual(self.run_save(), 'saved')
        files = self.last_commit_files()
        self.assertTrue(files)
        self.assertTrue(all(f in ('stats.html',) or f.startswith(('data/stats/', 'article-stats-', 'thumb-stats-')) for f in files), files)
        self.assertIn('data/stats/2026-10-22.json', files)
        summary = json.loads(self.published('data/stats/2026-10-22.json'))
        self.assertEqual(summary['eff_top'][0]['eff'], 30)                  # コミット済みの確定値（途中の 99 ではない）
        self.assertEqual(self.published('index.html'), 'old index.html')    # 途中の生成物は公開しない
        self.assertIn('::notice::stats date=2026-10-22 state=ready', self.log)

    def test_second_run_without_change_is_a_no_op(self):
        self.run_save()
        head = sh(self.remote, 'rev-parse', 'main')
        self.assertEqual(self.run_save(), 'nothing')
        self.assertEqual(sh(self.remote, 'rev-parse', 'main'), head)

    def test_held_day_record_is_saved_without_ranking(self):
        self.write_results([game('506495', status='scheduled')])
        sh(self.repo, 'commit', '-qam', 'results pending'); sh(self.repo, 'push', '-q', 'origin', 'main')
        self.assertEqual(self.run_save(), 'saved')
        self.assertEqual(self.last_commit_files(), ['data/stats/state.json'])
        state = json.loads(self.published('data/stats/state.json'))
        self.assertEqual(state['days']['2026-10-22']['holds'][0]['reason'], 'record_not_fixed')

    def test_stats_error_fails_the_step(self):
        with patch.object(stats, 'run', side_effect=OSError('disk')), self.assertRaises(RuntimeError):
            self.run_save()


if __name__ == '__main__':
    unittest.main()
