"""ニュース取得（fetch.py）の取得元別診断と上限つき再試行（10/22）。

再現元：run 39634093412（01:22 JST）。B.LEAGUE公式ニュースとバスケット・カウントRSSが
両方 HTTP 503 → 全取得元失敗で exit 1。全滅は今後も成功扱いにしない。
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import requests

from scripts import fetch

NEWS_URL = fetch.BLEAGUE_NEWS_URL
FEED_URL = fetch.RSS_FEEDS[0][1]
NEWS_HTML = ('<html><body><a href="/news_detail/id=1">2026.10.21 千葉ジェッツが勝利した試合の公式発表</a>'
             '</body></html>')
RSS = ('<?xml version="1.0"?><rss><channel><item><title>Bリーグ 宇都宮が勝利</title>'
       '<link>https://basket-count.com/a</link><pubDate>Wed, 21 Oct 2026 10:00:00 +0900</pubDate></item>'
       '</channel></rss>')


def response(status, url, text=''):
    r = requests.Response()
    r.status_code, r.url, r._content, r.encoding = status, url, text.encode(), 'utf-8'
    return r


class Clock:
    def __init__(self, per_get=0.0):
        self.now, self.per_get, self.waits = 1000.0, per_get, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        if seconds != fetch.SLEEP:          # politeness pause is not a retry wait
            self.waits.append(seconds)
        self.now += seconds


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        for name, value in (('_clock', self.clock), ('_sleep', self.clock.sleep), ('_run_started', None)):
            p = patch.object(fetch, name, value); p.start(); self.addCleanup(p.stop)
        fetch.REPORT.clear()
        self.addCleanup(fetch.REPORT.clear)
        self.calls = []

    def serve(self, table):
        """table: url -> list of status codes / exceptions / (status, text); last item repeats."""
        def request(url, headers=None, timeout=None):
            self.calls.append((url, timeout))
            self.clock.now += min(self.clock.per_get, timeout)
            seq = table[url]
            item = seq.pop(0) if len(seq) > 1 else seq[0]
            if isinstance(item, Exception):
                raise item
            status, text = item if isinstance(item, tuple) else (item, '')
            return response(status, url, text)
        p = patch.object(fetch.requests, 'get', side_effect=request); p.start(); self.addCleanup(p.stop)


class Retry(Base):
    def test_503_then_200_is_retried(self):
        self.serve({NEWS_URL: [503, 503, (200, NEWS_HTML)]})
        self.assertEqual(len(fetch.fetch_bleague_news()), 1)
        self.assertEqual(self.clock.waits, [5, 15])
        self.assertEqual(fetch.REPORT[-1]['category'], 'ok')

    def test_persistent_503_stops_after_three_attempts(self):
        self.serve({NEWS_URL: [503]})
        self.assertEqual(fetch.fetch_bleague_news(), [])
        self.assertEqual(len(self.calls), 3)
        e = fetch.REPORT[-1]
        self.assertEqual((e['category'], e['http_status'], e['type'], e['attempts']), ('http', 503, 'HTTPError', 3))

    def test_404_is_not_retried(self):
        self.serve({NEWS_URL: [404]})
        fetch.fetch_bleague_news()
        self.assertEqual((len(self.calls), self.clock.waits), (1, []))
        self.assertEqual(fetch.REPORT[-1]['http_status'], 404)

    def test_connection_error_is_network_and_retried(self):
        self.serve({FEED_URL: [requests.ConnectionError('reset'), (200, RSS)]})
        self.assertEqual(len(fetch.fetch_rss('バスケット・カウント', FEED_URL)), 1)
        self.assertEqual(self.clock.waits, [5])

    def test_slow_503s_stay_within_60s_per_url(self):
        self.clock.per_get = 20
        self.serve({NEWS_URL: [503]})
        start = self.clock.now
        fetch.fetch_bleague_news()
        self.assertLessEqual(self.clock.now - start, fetch.URL_MAX_ELAPSED)
        self.assertTrue(all(t <= fetch.TIMEOUT for _, t in self.calls))

    def test_run_budget_caps_total_time(self):
        self.clock.per_get = 20
        self.serve({NEWS_URL: [503], FEED_URL: [503]})
        with patch.object(fetch, 'RUN_BUDGET', 50):   # 20+5+20 = 45s on the first URL
            fetch.fetch_bleague_news()
            fetch.fetch_rss('バスケット・カウント', FEED_URL)
        self.assertLessEqual(self.clock.now - 1000.0, 50)
        # The second source only gets the 5s left in the run: one short GET, no retry.
        self.assertEqual(fetch.REPORT[-1]['attempts'], 1)
        self.assertEqual(self.calls[-1], (FEED_URL, 5))


class Categories(Base):
    def test_budget_exhausted_source_is_not_requested(self):
        self.clock.per_get = 20
        self.serve({NEWS_URL: [503], FEED_URL: [503]})
        with patch.object(fetch, 'RUN_BUDGET', 48):   # 45s used, 3s left < 5s minimum
            fetch.fetch_bleague_news()
            fetch.fetch_rss('バスケット・カウント', FEED_URL)
        self.assertEqual((fetch.REPORT[-1]['category'], fetch.REPORT[-1]['attempts']), ('budget', 0))
        self.assertNotIn(FEED_URL, [u for u, _ in self.calls])

    def test_rss_parse_error(self):
        self.serve({FEED_URL: [(200, '<html>maintenance</html')]})
        fetch.fetch_rss('バスケット・カウント', FEED_URL)
        self.assertEqual((fetch.REPORT[-1]['category'], fetch.REPORT[-1]['type']), ('parse', 'ParseError'))

    def test_empty_feed_and_empty_page_are_not_ok(self):
        self.serve({FEED_URL: [(200, '<rss><channel></channel></rss>')], NEWS_URL: [(200, '<html></html>')]})
        fetch.fetch_rss('バスケット・カウント', FEED_URL)
        fetch.fetch_bleague_news()
        self.assertEqual([e['category'] for e in fetch.REPORT], ['empty', 'empty'])

    def test_feed_with_only_unrelated_items_is_ok(self):
        rss = RSS.replace('Bリーグ 宇都宮が勝利', 'NCAA の話題')
        self.serve({FEED_URL: [(200, rss)]})
        self.assertEqual(fetch.fetch_rss('バスケット・カウント', FEED_URL), [])
        e = fetch.REPORT[-1]
        self.assertEqual((e['category'], e['items'], e['entries']), ('ok', 0, 1))


class QaRegressions(Base):
    """13d7222 独立検品の指摘（10/22 01:44）の回帰テスト。"""

    def test_polite_pause_does_not_exceed_run_budget(self):
        # GET が timeout ぶん（5秒）かかって 200。旧実装は礼儀の2秒を足して7秒。
        self.clock.per_get = 99
        self.serve({NEWS_URL: [(200, NEWS_HTML)]})
        with patch.object(fetch, 'RUN_BUDGET', 5), patch.object(fetch, 'MIN_ATTEMPT', 1):
            fetch.fetch_bleague_news()
        self.assertLessEqual(self.clock.now - 1000.0, 5)

    def test_polite_pause_does_not_exceed_per_url_limit(self):
        """4a8527a 再検品：(10秒,503)(5秒,503)(25秒,200)＋待ち5・15秒で60秒→礼儀2秒で62秒になっていた。"""
        steps = [(10, 503), (5, 503), (25, 200)]

        def request(url, headers=None, timeout=None):
            seconds, status = steps.pop(0)
            self.clock.now += min(seconds, timeout)
            return response(status, url, NEWS_HTML if status == 200 else '')
        with patch.object(fetch.requests, 'get', side_effect=request):
            start = self.clock.now
            self.assertEqual(len(fetch.fetch_bleague_news()), 1)
        self.assertLessEqual(self.clock.now - start, fetch.URL_MAX_ELAPSED)   # old code: 62
        self.assertEqual(self.clock.waits[:2], [5, 15])              # retry waits unchanged
        self.assertEqual(self.clock.waits[2:], [0.0])                 # polite pause shrunk to the 0s left
        self.assertEqual(fetch.REPORT[-1]['attempts'], 3)

    def test_robots_is_not_requested_without_budget(self):
        url = fetch.MATOME_FEEDS[0][1]
        self.serve({})
        with patch.object(fetch, 'RUN_BUDGET', 3), patch.dict(fetch._robots_cache, clear=True):
            self.assertEqual(fetch.fetch_feed_items('バスケまとめ・COM', url, lambda t: True), [])
        self.assertEqual(self.calls, [])
        e = fetch.REPORT[-1]
        self.assertEqual((e['category'], e['type']), ('budget', 'BudgetExhausted'))

    def test_robots_timeout_is_capped_and_unknown_answer_keeps_old_policy(self):
        url = fetch.MATOME_FEEDS[0][1]
        robots = 'https://basketballbbs.com/robots.txt'
        self.serve({robots: [requests.ConnectionError('down')], url: [(200, RSS)]})
        with patch.object(fetch, 'RUN_BUDGET', 12), patch.dict(fetch._robots_cache, clear=True):
            fetch.fetch_feed_items('バスケまとめ・COM', url, lambda t: True)
        self.assertEqual(self.calls[0], (robots, 12))          # capped to time left, one try only
        self.assertEqual([u for u, _ in self.calls].count(robots), 1)
        self.assertEqual(fetch.REPORT[-1]['category'], 'ok')    # unreadable robots = allowed (unchanged)

    def test_attempts_are_kept_for_ok_parse_and_empty(self):
        self.serve({NEWS_URL: [503, 503, (200, NEWS_HTML)],
                    FEED_URL: [503, (200, '<rss>broken')]})
        fetch.fetch_bleague_news()
        fetch.fetch_rss('バスケット・カウント', FEED_URL)
        self.assertEqual([(e['category'], e['attempts']) for e in fetch.REPORT], [('ok', 3), ('parse', 2)])
        fetch.REPORT.clear()
        self.serve({NEWS_URL: [(200, '<html></html>')]})
        fetch.fetch_bleague_news()
        self.assertEqual((fetch.REPORT[-1]['category'], fetch.REPORT[-1]['attempts']), ('empty', 1))


class Main(Base):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        p = patch.object(fetch, 'DATA_DIR', self.temp.name); p.start(); self.addCleanup(p.stop)
        self.news = Path(self.temp.name) / 'news.json'
        self.news.write_text(json.dumps([{'title': '前回の見出し', 'url': 'https://x/1', 'source': 'B.LEAGUE公式',
                                          'date': '2026-10-21'}], ensure_ascii=False))
        self.later = []
        for name in ('fetch_matome', 'fetch_standings'):
            p = patch.object(fetch, name, side_effect=lambda n=name: self.later.append(n) or None)
            p.start(); self.addCleanup(p.stop)

    def run_main(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = fetch.main()
        return code, out.getvalue()

    def test_reproduces_both_503_as_failure_and_keeps_data(self):
        """run 39634093412：両方 503 → exit 1、既存データは同じバイトのまま、注記に取得元ごとの理由。"""
        self.serve({NEWS_URL: [503], FEED_URL: [503]})
        before = self.news.read_bytes()
        code, log = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(self.news.read_bytes(), before)
        self.assertEqual(self.later, [])     # unchanged dependency: later steps are not run
        self.assertIn('::warning::fetch source=B.LEAGUE公式 category=http http=503 type=HTTPError attempts=3', log)
        self.assertIn('::warning::fetch source=バスケット・カウント category=http http=503 type=HTTPError attempts=3', log)
        self.assertIn('::error::News fetch failed for every source', log)
        self.assertIn('B.LEAGUE公式=http(HTTP 503)、バスケット・カウント=http(HTTP 503)', log)

    def test_all_sources_empty_is_also_a_failure(self):
        self.serve({NEWS_URL: [(200, '<html></html>')], FEED_URL: [(200, '<rss><channel></channel></rss>')]})
        code, log = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn('B.LEAGUE公式=empty、バスケット・カウント=empty', log)

    def test_one_source_down_still_updates_with_warning(self):
        self.serve({NEWS_URL: [503], FEED_URL: [(200, RSS)]})
        with patch.dict('sys.modules', {'stats': type('S', (), {'run': staticmethod(lambda: None)})}):
            code, log = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(self.news.read_text())), 2)
        self.assertIn('::warning::fetch source=B.LEAGUE公式 category=http http=503', log)
        self.assertIn('::notice::fetch source=バスケット・カウント category=ok', log)
        self.assertEqual(self.later, ['fetch_matome', 'fetch_standings'])


if __name__ == '__main__':
    unittest.main()
