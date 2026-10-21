"""10/22 01:16 の手動実行で 10/21 が「ValueError・URL/HTTPなし」になった件の再現と修正確認。

当時の記録：10/22 は B.NEXT 日程ページ HTTP 503、10/21 は種別 ValueError で URL・HTTP 状態なし。
コード上、読めないURLが3件続くと以降の取得を打ち切る（Stopped）が、打ち切りは記録されず、
日付単位の例外（Official results incomplete）だけが残っていた。パース不整合も同様に記録されなかった。
"""
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import requests

from scripts import official_data, preview_data, result_status, update_results

ROOT = Path(__file__).resolve().parents[1]
JST = preview_data.JST


def response(status, url, text=''):
    r = requests.Response()
    r.status_code, r.url, r._content = status, url, text.encode()
    return r


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def client(answer):
    clock = Clock()
    calls = []

    def fetch(url, timeout):
        calls.append(url)
        clock.now += 1
        return answer(url)
    c = official_data.Client(max_requests=70, time_budget=180, sleep=clock.sleep, fetch=fetch, clock=clock)
    return c, calls


class Diagnostics(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data/match_articles').mkdir(parents=True)
        for stem in ('20261021', '20261022'):
            shutil.copy(ROOT / ('article-games-' + stem + '.html'), self.root)
            shutil.copy(ROOT / 'data/match_articles' / ('article-games-' + stem + '.json'), self.root / 'data/match_articles')
        # Start from the pre-run state (no status file).
        status = self.root / result_status.PATH
        if status.exists():
            status.unlink()
        preview = patch.object(update_results.refresh_next_preview, 'refresh', return_value={'changed': False})
        preview.start(); self.addCleanup(preview.stop)
        polite = patch.object(official_data.time, 'sleep')   # the 2s pause after each successful GET
        polite.start(); self.addCleanup(polite.stop)
        self.now = datetime(2026, 10, 22, 1, 16, tzinfo=JST)

    def run_with(self, c):
        with self.assertRaises(ValueError) as ctx:
            update_results.run(self.root, c, 2026, self.now)
        return {e['date']: e for e in ctx.exception.result_errors}

    def test_503_then_stopped_keeps_date_url_and_category(self):
        c, calls = client(lambda url: response(503, url))
        errors = self.run_with(c)
        today, yesterday = errors['2026-10-22'], errors['2026-10-21']
        # 10/22: three schedule pages each answered 503 (3 attempts), then the run stopped.
        self.assertEqual((today['category'], today['http_status']), ('http', 503))
        self.assertEqual([f['url'][-21:] for f in today['fetch_failures']],
                         ['tab=1&year=2026&mon=10&day=22'[-21:], 'tab=2&year=2026&mon=10&day=22'[-21:],
                          'tab=3&year=2026&mon=10&day=22'[-21:]])
        self.assertTrue(all(f['attempts'] == 3 for f in today['fetch_failures']))
        # 10/21: never requested -> recorded as "stopped" with each URL, not ValueError/None.
        self.assertEqual(yesterday['category'], 'stopped')
        self.assertEqual(yesterday['type'], 'Stopped')
        self.assertIn('day=21', yesterday['url'])
        self.assertEqual({f['category'] for f in yesterday['fetch_failures']}, {'stopped'})
        self.assertFalse(any('day=21' in u for u in calls))
        entry = result_status.failed(self.root, '2026-10-21')
        self.assertEqual(entry['error']['category'], 'stopped')
        self.assertEqual(result_status.failed(self.root, '2026-10-22')['error']['http_status'], 503)

    def test_parse_mismatch_is_distinguished_from_http(self):
        c, _ = client(lambda url: response(200, url, '<html><body>maintenance</body></html>'))
        errors = self.run_with(c)
        e = errors['2026-10-22']
        self.assertEqual((e['category'], e['http_status'], e['type']), ('parse', None, 'DataError'))
        self.assertIn('/schedule/?tab=1', e['url'])
        self.assertIn('Schedule period mismatch', e['fetch_failures'][0]['message'])

    def test_game_page_problem_keeps_game_url(self):
        def answer(url):
            if '/schedule/' in url:
                d = 22 if 'day=22' in url else 21
                return response(200, url, schedule_html(url, d))
            return response(503, url)
        c, _ = client(answer)
        errors = self.run_with(c)
        e = errors['2026-10-22']
        self.assertEqual(e['category'], 'http')
        self.assertIn('/game_detail/?ScheduleKey=', e['url'])

    def test_annotations_list_every_problem(self):
        import io
        from contextlib import redirect_stdout
        c, _ = client(lambda url: response(503, url))
        errors = list(self.run_with(c).values())
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            update_results.log_errors(errors)
        log = buffer.getvalue()
        self.assertIn('::warning::Result refresh failed date=2026-10-21 category=stopped type=Stopped', log)
        self.assertIn('::warning::  date=2026-10-22 problem category=http http=503 type=HTTPError attempts=3', log)
        self.assertIn('::warning::  date=2026-10-21 problem category=stopped', log)


def schedule_html(url, day):
    """Minimal official-like schedule page with one game key for the requested league/day."""
    tab = url.split('tab=')[1].split('&')[0]
    key = {'1': '506495', '2': '507273', '3': '507923'}[tab]
    return ('<select name="year"><option value="2026" selected>2026</option></select>'
            '<select name="mon"><option value="10" selected>10</option></select>'
            '<div class="js-schedule-date-slider-item is-current"><span class="js_click_data" data-day="' + str(day) + '"></span></div>'
            '<div id="schedule-b' + tab + '"><li class="list-item" id="' + key + '">'
            '<a href="/game_detail/?ScheduleKey=' + key + '">game</a></li></div>')


if __name__ == '__main__':
    unittest.main()
