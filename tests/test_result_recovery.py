"""結果取得の復旧（10/22）：一時障害の再試行・公開情報のみのログ・状態の区別・日付跨ぎ・安全なエラー表示。"""
import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
from bs4 import BeautifulSoup

from scripts import browse_ui, official_data, preview_data, result_status, update_results

ROOT = Path(__file__).resolve().parents[1]
JST = preview_data.JST
URL = 'https://www.bleague.jp/game_detail/?ScheduleKey=506486'


def response(status, url=URL, text='ok'):
    r = requests.Response()
    r.status_code, r.url, r._content = status, url, text.encode()
    return r


class FakeClock:
    """Pseudo monotonic clock: every GET takes `per_get` seconds, sleep advances the clock."""

    def __init__(self, per_get=0.0):
        self.now, self.per_get, self.waits, self.timeouts = 1000.0, per_get, [], []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class Retry(unittest.TestCase):
    def client(self, statuses, budget=360, max_requests=120, per_get=0.0):
        clock = FakeClock(per_get)
        calls = []
        seq = iter(statuses)

        def fetch(url, timeout):
            calls.append(url)
            clock.timeouts.append(timeout)
            clock.now += min(clock.per_get, timeout)   # a GET never outlives its timeout
            item = next(seq)
            if isinstance(item, Exception):
                raise item
            return response(item, url)
        c = official_data.Client(max_requests=max_requests, time_budget=budget, sleep=clock.sleep,
                                 fetch=fetch, clock=clock)
        return c, calls, clock

    def test_503_then_success_is_retried_with_bounded_waits(self):
        c, calls, clock = self.client([503, 503, 200])
        self.assertEqual(c.get(URL), 'ok')
        self.assertEqual(len(calls), 3)
        self.assertEqual(clock.waits, [5, 15])
        self.assertEqual(c.request_count, 3)
        self.assertEqual(c.failures, [])

    def test_slow_503s_keep_real_elapsed_within_60s(self):
        """独立QA再現：各GET 20秒・503連続。旧実装は 20+5+20+15+20=80秒。"""
        c, calls, clock = self.client([503, 503, 503, 200], per_get=20)
        start = clock.now
        with self.assertRaises(official_data.FetchError) as ctx:
            c.get(URL)
        elapsed = clock.now - start
        self.assertLessEqual(elapsed, official_data.RETRY_MAX_ELAPSED)
        self.assertEqual(ctx.exception.status, 503)
        # 20 (GET) + 5 (wait) + 20 (GET) = 45; a further 15s wait + GET would cross 60s.
        self.assertEqual((len(calls), clock.waits, elapsed), (2, [5], 45))

    def test_each_get_timeout_is_capped_to_time_left(self):
        c, calls, clock = self.client([503, 503, 503, 200], per_get=30)
        start = clock.now
        with self.assertRaises(official_data.FetchError):
            c.get(URL)
        self.assertLessEqual(clock.now - start, official_data.RETRY_MAX_ELAPSED)
        self.assertEqual(clock.timeouts[0], official_data.REQUEST_TIMEOUT)
        self.assertTrue(all(t <= official_data.RETRY_MAX_ELAPSED for t in clock.timeouts))

    def test_persistent_503_stops_after_three_attempts_with_public_details(self):
        c, calls, clock = self.client([503, 503, 503, 200])
        with self.assertRaises(official_data.FetchError) as ctx:
            c.get(URL)
        self.assertEqual(len(calls), 3)
        self.assertEqual(ctx.exception.detail(), {'url': URL, 'http_status': 503, 'type': 'HTTPError', 'attempts': 3})
        self.assertEqual(c.failures, [ctx.exception.detail()])
        self.assertIsInstance(ctx.exception, ValueError)  # existing callers keep data on ValueError

    def test_client_errors_are_not_retried(self):
        c, calls, clock = self.client([404])
        with self.assertRaises(official_data.FetchError) as ctx:
            c.get(URL)
        self.assertEqual((len(calls), clock.waits, ctx.exception.status), (1, [], 404))

    def test_connection_error_is_retried(self):
        c, calls, clock = self.client([requests.ConnectionError('reset'), 200])
        self.assertEqual(c.get(URL), 'ok')
        self.assertEqual(clock.waits, [5])

    def test_time_budget_caps_retries(self):
        # 36s run budget: the first GET fits the 32s safety margin, a further 5s wait does not.
        c, calls, clock = self.client([503, 200], budget=36)
        with self.assertRaises(official_data.FetchError):
            c.get(URL)
        self.assertEqual((len(calls), clock.waits), (1, []))

    def test_request_budget_caps_retries(self):
        c, calls, clock = self.client([503, 503, 200], max_requests=2)
        with self.assertRaises(official_data.FetchError):
            c.get(URL)
        self.assertEqual(len(calls), 2)

    def test_repeated_unreadable_urls_stop_the_run(self):
        c, calls, _ = self.client([404, 404, 404, 200])
        for key in range(3):
            with self.assertRaises(official_data.FetchError):
                c.get(URL + str(key))
        with self.assertRaises(official_data.FetchError) as ctx:
            c.get(URL + '9')
        self.assertEqual(ctx.exception.kind, 'Stopped')
        self.assertEqual(len(calls), 3)  # the 4th URL was not requested


class States(unittest.TestCase):
    game = dict(game_id='1', status='scheduled', ended=False, fixed=False, home_score=None, away_score=None,
                starts_at='2026-10-21T19:05:00+09:00', source=URL)

    def state(self, now, **change):
        return result_status.game_state(dict(self.game, **change), now, preview_data.is_verified_final)

    def test_before_tipoff_after_tipoff_and_unfixed_are_distinct(self):
        before = datetime(2026, 10, 21, 17, 26, tzinfo=JST)
        after = datetime(2026, 10, 21, 23, 27, tzinfo=JST)
        self.assertEqual(self.state(before), '19:05 試合前')
        self.assertEqual(self.state(after), '19:05 開始・公式記録未確定')
        # Ended but RecordFixedFlg false: never shown as final, score not shown.
        self.assertEqual(self.state(after, status='unconfirmed', ended=True, fixed=False,
                                    home_score=80, away_score=70), '19:05 開始・公式記録未確定')

    def test_final_condition_is_unchanged(self):
        final = dict(self.game, status='final', ended=True, fixed=True, home_score=80, away_score=70)
        self.assertTrue(preview_data.is_verified_final(final))
        for broken in (dict(final, fixed=False), dict(final, ended=False), dict(final, source=''),
                       dict(final, home_score=None), dict(final, away_score=-1)):
            self.assertFalse(preview_data.is_verified_final(broken))

    def test_notice_shows_no_remote_error_text(self):
        html = result_status.notice_html({'failing_since': '2026-10-21 23:27 JST',
                                          'last_checked_at': '2026-10-21 17:26 JST',
                                          'content_as_of': '2026-10-21 17:26 JST',
                                          'error': {'type': 'HTTPError', 'http_status': 503, 'url': URL}})
        self.assertIn('2026-10-21 17:26 JST 時点の公式記録', html)
        self.assertNotIn('HTTPError', html)
        self.assertNotIn('503', html)


class RunFlow(unittest.TestCase):
    """Uses a copy of the saved 10/21 data (9 games saved as scheduled at 17:24-26)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data/match_articles').mkdir(parents=True)
        for name in ('article-games-20261021.html',):
            shutil.copy(ROOT / name, self.root / name)
        shutil.copy(ROOT / 'data/match_articles/article-games-20261021.json', self.root / 'data/match_articles/')
        self.saved = json.loads((self.root / 'data/match_articles/article-games-20261021.json').read_text())
        preview = patch.object(update_results.refresh_next_preview, 'refresh', return_value={'changed': False})
        preview.start(); self.addCleanup(preview.stop)

    def failing_client(self):
        return SimpleNamespace(request_count=3, max_requests=70, failures=[])

    def collect_failing(self, client, year, date):
        # What official_data.Client records when the schedule page answers 503 three times.
        client.failures.append({'url': 'https://www.bleague.jp/schedule/?tab=1&year=2026&mon=10&day=' + date[-2:],
                                'http_status': 503, 'type': 'HTTPError', 'attempts': 3})
        return dict(date=date, games=[], errors=['Official fetch failed: HTTPError HTTP 503'],
                    schedule_complete=dict(BP=False, B1=False, BN=False))

    def run_at(self, now, client, collect):
        with patch.object(update_results.day_articles, 'collect', side_effect=collect):
            return update_results.run(self.root, client, 2026, now)

    def test_next_day_keeps_previous_day_and_marks_fetch_failure(self):
        now = datetime(2026, 10, 22, 18, 7, tzinfo=JST)
        self.assertIn('2026-10-21', update_results.pending_dates(self.root, now))
        before = (self.root / 'data/match_articles/article-games-20261021.json').read_bytes()
        with self.assertRaises(ValueError) as ctx:
            self.run_at(now, self.failing_client(), self.collect_failing)
        err = next(e for e in ctx.exception.result_errors if e['date'] == '2026-10-21')
        self.assertEqual((err['http_status'], err['type']), (503, 'HTTPError'))
        self.assertTrue(ctx.exception.status_changed)
        # Results untouched; status + notice added.
        self.assertEqual((self.root / 'data/match_articles/article-games-20261021.json').read_bytes(), before)
        entry = result_status.failed(self.root, '2026-10-21')
        self.assertEqual(entry['failing_since'], '2026-10-22 18:07 JST')
        # No earlier record: both times fall back to the article's own 資料取得 line.
        self.assertEqual((entry['last_checked_at'], entry['content_as_of']), ('2026-10-21 17:26 JST',) * 2)
        soup = BeautifulSoup((self.root / 'article-games-20261021.html').read_text(), 'html.parser')
        notice = soup.select_one('#result-fetch-status')
        self.assertIsNotNone(notice)
        self.assertEqual(notice.find_next_sibling('section')['id'], 'daily-results')
        self.assertEqual(len(soup.select('.daily-score')), 9)  # games kept, no guessed result
        self.assertEqual(soup.select('.daily-score strong')[0].text, '—')

    def test_identical_failure_does_not_rewrite_files(self):
        now = datetime(2026, 10, 22, 18, 7, tzinfo=JST)
        with self.assertRaises(ValueError):
            self.run_at(now, self.failing_client(), self.collect_failing)
        files = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        later = datetime(2026, 10, 22, 18, 22, tzinfo=JST)
        with self.assertRaises(ValueError) as ctx:
            self.run_at(later, self.failing_client(), self.collect_failing)
        self.assertFalse(ctx.exception.status_changed)
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, files)

    def test_recovery_clears_notice_and_records_success(self):
        now = datetime(2026, 10, 22, 18, 7, tzinfo=JST)
        with self.assertRaises(ValueError):
            self.run_at(now, self.failing_client(), self.collect_failing)
        # Official site back, still not final: unchanged data, state cleared, notice removed.
        same = copy.deepcopy(self.saved)
        ok_client = SimpleNamespace(request_count=12, max_requests=70, failures=[])
        later = datetime(2026, 10, 22, 18, 22, tzinfo=JST)
        result = self.run_at(later, ok_client, lambda c, y, d: same if d == '2026-10-21' else dict(
            date=d, games=[], errors=[], schedule_complete=dict(BP=True, B1=True, BN=True)))
        self.assertFalse(result['changed'])
        self.assertTrue(result['status_changed'])
        self.assertIsNone(result_status.failed(self.root, '2026-10-21'))
        self.assertIsNone(BeautifulSoup((self.root / 'article-games-20261021.html').read_text(),
                                        'html.parser').select_one('#result-fetch-status'))


class Timeline(unittest.TestCase):
    """独立QA再現：20:00 成功（変化あり）→ 20:10 成功（変化なし）→ 20:20 失敗。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def at(self, hhmm):
        h, m = map(int, hhmm.split(':'))
        return datetime(2026, 10, 21, h, m, tzinfo=JST)

    def test_failure_shows_last_real_read_and_content_time_separately(self):
        result_status.record_success(self.root, '2026-10-21', self.at('20:00'), changed=True)
        result_status.record_success(self.root, '2026-10-21', self.at('20:10'), changed=False)
        result_status.record_failure(self.root, '2026-10-21', self.at('20:20'),
                                     {'type': 'HTTPError', 'http_status': 503, 'url': URL})
        entry = result_status.failed(self.root, '2026-10-21')
        self.assertEqual((entry['last_checked_at'], entry['content_as_of'], entry['failing_since']),
                         ('2026-10-21 20:10 JST', '2026-10-21 20:00 JST', '2026-10-21 20:20 JST'))
        text = result_status.notice_html(entry)
        self.assertIn('最後に公式サイトを確認できたのは 2026-10-21 20:10 JST', text)
        self.assertIn('表示中の内容は 2026-10-21 20:00 JST に取得した公式記録', text)

    def test_recovery_with_same_data_moves_check_time_only(self):
        result_status.record_success(self.root, '2026-10-21', self.at('20:00'), changed=True)
        result_status.record_failure(self.root, '2026-10-21', self.at('20:20'),
                                     {'type': 'HTTPError', 'http_status': 503, 'url': URL})
        cleared = result_status.record_success(self.root, '2026-10-21', self.at('20:35'), changed=False)
        self.assertTrue(cleared)   # notice must be removed
        entry = result_status.load(self.root)['2026-10-21']
        self.assertEqual(entry, {'state': 'ok', 'last_checked_at': '2026-10-21 20:35 JST',
                                 'content_as_of': '2026-10-21 20:00 JST'})

    def test_runs_without_a_network_read_do_not_advance_times(self):
        root = self.root
        (root / 'data/match_articles').mkdir(parents=True)
        done = json.loads((ROOT / 'data/match_articles/article-games-20261019.json').read_text())
        (root / 'data/match_articles/article-games-20261019.json').write_text(json.dumps(done))
        (root / 'article-games-20261019.html').write_text('retained')
        result_status.record_success(root, '2026-10-19', self.at('20:00'), changed=True)
        before = (root / result_status.PATH).read_bytes()
        client = SimpleNamespace(request_count=0, max_requests=70, failures=[])
        with patch.object(update_results.day_articles, 'collect') as collect:
            report = update_results.run_date(root, client, 2026, datetime(2026, 10, 20, 9, 0, tzinfo=JST), '2026-10-19')
        self.assertEqual(report['reason'], 'already_final')
        collect.assert_not_called()
        self.assertNotIn(report['reason'], update_results.READ_REASONS)
        self.assertEqual((root / result_status.PATH).read_bytes(), before)


class MainLogging(unittest.TestCase):
    def test_failure_logs_public_facts_builds_notice_and_exits_1(self):
        exc = ValueError('Official results incomplete; previous data retained')
        exc.result_errors = [{'date': '2026-10-21', 'error': str(exc), 'type': 'HTTPError', 'http_status': 503,
                              'url': 'https://www.bleague.jp/schedule/?tab=1', 'fetch_failures': [
                                  {'url': 'https://www.bleague.jp/schedule/?tab=1', 'http_status': 503,
                                   'type': 'HTTPError', 'attempts': 3}]}]
        exc.status_changed = True
        with tempfile.NamedTemporaryFile('r', delete=False) as out:
            path = out.name
        self.addCleanup(os.unlink, path)
        buffer = io.StringIO()
        with patch.object(update_results, 'run', side_effect=exc), patch.object(update_results, 'build') as build, \
                patch.dict(os.environ, {'GITHUB_OUTPUT': path}), patch('sys.argv', ['x', '--season-year', '2026']), \
                redirect_stdout(buffer):
            code = update_results.main()
        log = buffer.getvalue()
        self.assertEqual(code, 1)
        build.assert_called_once()
        self.assertIn('date=2026-10-21 type=HTTPError http=503 url=https://www.bleague.jp/schedule/?tab=1', log)
        self.assertIn('attempts=3', log)
        self.assertEqual(Path(path).read_text(), 'status_saved=1\n')

    def test_unchanged_failure_does_not_build_or_save(self):
        exc = ValueError('x')
        exc.result_errors = [{'date': '2026-10-21', 'error': 'x', 'type': 'HTTPError', 'http_status': 503, 'url': URL}]
        exc.status_changed = False
        with patch.object(update_results, 'run', side_effect=exc), patch.object(update_results, 'build') as build, \
                patch.dict(os.environ, {'GITHUB_OUTPUT': ''}), patch('sys.argv', ['x', '--season-year', '2026']), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(update_results.main(), 1)
        build.assert_not_called()


class Listing(unittest.TestCase):
    def test_home_keeps_previous_day_pending_results_visible_after_midnight(self):
        row = json.loads((ROOT / 'data/match_articles/article-games-20261021.json').read_text())
        now = datetime(2026, 10, 22, 1, 0, tzinfo=JST)
        html = browse_ui.pending_past([row], now)
        self.assertIn('10/21 の 9 試合は公式記録の確定待ちです', html)
        failed = dict(row, fetch_status={'failing_since': '2026-10-21 23:27 JST', 'last_checked_at': '2026-10-21 20:10 JST',
                                         'content_as_of': '2026-10-21 17:26 JST'})
        self.assertIn('公式サイトから取得できていません', browse_ui.pending_past([failed], now))
        body = browse_ui.day_body(failed, now=now)
        self.assertIn('最後に公式サイトを確認できたのは 2026-10-21 20:10 JST、表示中の内容は 2026-10-21 17:26 JST に取得した公式記録です', body)
        self.assertIn('19:05 開始・公式記録未確定・取得失敗', body)


if __name__ == '__main__':
    unittest.main()
