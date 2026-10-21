"""公式ILを毎日の実行枠でニュースと独立に取得・保存する（10/22・未公開）。

- ニュース失敗＋IL成功、IL失敗（前回値保持＋未確認）、初回失敗、日付跨ぎ、記事が古いILを最新扱いしない、
  同じ回でILを再取得しない、ワークフローの構成（新スケジュールなし・失敗は失敗のまま）を確かめる。
"""
import io
import json
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import requests
from bs4 import BeautifulSoup

from scripts import fetch, injury_page, match_articles, official_data as official, update_injury
from scripts import update_match_features as features

ROOT = Path(__file__).resolve().parents[1]
URL = injury_page.URL
RealClient = official.Client


def il_page():
    rows = [('9月30日/', '9月30日', '10月30日', 'B.NEXT', '山口パッツファイブ', 'ヘイデン・ディークハンス', 'DIAG'),
            ('9月1日/10月1日', '9月1日', '10月1日', 'B.PREMIER', '茨城ロボッツ', '復帰選手', 'DIAG')]
    return ('<p>公示日：2026年10月21日</p><table class="flat-tbl02"><thead><th>再登録不可期日</th></thead><tbody>'
            + ''.join('<tr>' + ''.join('<td>' + v + '</td>' for v in r) + '</tr>' for r in rows) + '</tbody></table>')


def response(status, url, text=''):
    r = requests.Response()
    r.status_code, r.url, r._content = status, url, text.encode()
    return r


def client(status=200):
    def fetch_(url, timeout):
        return response(status, url, il_page() if status == 200 else '')
    return RealClient(max_requests=5, time_budget=120, sleep=lambda s: None, fetch=fetch_)


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data/match_articles').mkdir(parents=True)
        shutil.copy(ROOT / 'data/site_config.json', self.root / 'data/site_config.json')
        self.state_path = self.root / 'data/match_articles/injury.json'
        self.capture = self.root / 'il-capture.json'
        polite = patch.object(official.time, 'sleep'); polite.start(); self.addCleanup(polite.stop)

    def html(self):
        return BeautifulSoup((self.root / 'injury.html').read_text(), 'html.parser')

    def status(self):
        dl = self.html().select_one('#il-status')
        return dict(zip([d.text for d in dl.find_all('dt')], [d.text for d in dl.find_all('dd')]))


class IlState(Base):
    def test_success_records_times_scope_and_capture(self):
        now = datetime(2026, 10, 22, 22, 0, tzinfo=timezone.utc)   # 10/23 07:00 JST
        error, state = update_injury.run(self.root, client(), self.capture, now)
        self.assertIsNone(error)
        self.assertEqual(state['status'], 'ok')
        self.assertEqual(state['last_success_at'], state['retrieved_at'])
        self.assertEqual(state['last_attempt_at'], now.isoformat())
        self.assertEqual(state['scope'], {'leagues': ['B.NEXT', 'B.PREMIER'], 'season': None})
        self.assertNotIn('DIAG', self.state_path.read_text())
        self.assertEqual(json.loads(self.capture.read_text())['url'], URL)
        st = self.status()
        self.assertEqual(st['取得状態'], '取得できた一覧を表示中')
        self.assertEqual(st['シーズン'], '不明（原典に記載なし）')
        self.assertEqual(st['対象リーグ（一覧の記載）'], 'B.NEXT・B.PREMIER')
        self.assertIn('IL登録中（取得時点）', self.html().text)
        self.assertIsNotNone(self.html().select_one('header.hdr'))   # finalized like build.py

    def test_failure_keeps_previous_list_and_marks_unconfirmed(self):
        update_injury.run(self.root, client(), self.capture, datetime(2026, 10, 21, 22, tzinfo=timezone.utc))
        ok = json.loads(self.state_path.read_text())
        error, state = update_injury.run(self.root, client(503), self.capture, datetime(2026, 10, 22, 3, tzinfo=timezone.utc))
        self.assertTrue(error)
        self.assertEqual(state['records'], ok['records'])                  # 前回値保持
        self.assertEqual(state['last_success_at'], ok['last_success_at'])  # 最終成功は進まない
        self.assertEqual(state['last_attempt_at'], '2026-10-22T03:00:00+00:00')
        self.assertEqual(state['last_error'], {'type': 'HTTPError', 'http_status': 503, 'url': URL, 'category': 'http'})
        self.assertFalse(self.capture.exists())                            # 古い原文を後続に渡さない
        st = self.status()
        self.assertEqual(st['取得状態'], '最新の取得に失敗（前回取得の一覧を表示中・現在の状況は未確認）')
        self.assertEqual(st['最新の確認（取得を試みた日時）'], '2026-10-22 12:00 JST')

    def test_first_ever_failure_shows_not_fetched(self):
        error, state = update_injury.run(self.root, client(503), self.capture, datetime(2026, 10, 22, 3, tzinfo=timezone.utc))
        self.assertTrue(error)
        self.assertEqual(state['records'], [])
        st = self.status()
        self.assertEqual(st['取得状態'], '取得できていません（一覧は未取得）')
        self.assertEqual(st['最終成功（表示中の一覧の取得日時）'], '未取得')
        self.assertIn('登録者がいないという意味ではありません', self.html().text)

    def test_next_day_shows_stale_warning(self):
        update_injury.run(self.root, client(), self.capture, datetime(2026, 10, 21, 11, tzinfo=timezone.utc))
        state = json.loads(self.state_path.read_text())
        html = injury_page.render(state, datetime(2026, 10, 22, 0, 30, tzinfo=timezone.utc), failed=True)
        self.assertIn('12時間超', html)
        self.assertIn('前回取得の情報です', html)

    def test_legacy_state_without_new_fields(self):
        self.state_path.write_text(json.dumps({'source': URL, 'retrieved_at': '2026-10-21T08:24:01+00:00',
                                               'records': official.injury_records(il_page())}))
        error, state = update_injury.run(self.root, client(503), self.capture, datetime(2026, 10, 22, 3, tzinfo=timezone.utc))
        self.assertEqual(state['last_success_at'], '2026-10-21T08:24:01+00:00')
        self.assertEqual(self.status()['最終成功（表示中の一覧の取得日時）'], '2026-10-21 17:24 JST')

    def test_main_reports_failure_to_workflow_without_stopping(self):
        out = self.root / 'gh-output'
        out.write_text('')
        with patch.object(official, 'Client', side_effect=lambda **kw: client(503)), \
                patch('sys.argv', ['x', '--root', str(self.root), '--capture', str(self.capture)]), \
                patch.dict('os.environ', {'GITHUB_OUTPUT': str(out)}), redirect_stdout(io.StringIO()) as log:
            self.assertEqual(update_injury.main(), 0)
        self.assertIn('il_status=failed', out.read_text())
        self.assertIn('::warning::IL fetch failed category=http type=HTTPError http=503', log.getvalue())


class NewsAndIl(Base):
    def test_news_failure_does_not_block_il(self):
        """ニュース（fetch.py）が全滅しても、先に動いた IL の取得・保存は残る。ニュースは失敗のまま。"""
        update_injury.run(self.root, client(), self.capture, datetime(2026, 10, 22, 3, tzinfo=timezone.utc))
        (self.root / 'data/news.json').write_text('[{"title":"前回","url":"https://x/1","source":"B.LEAGUE公式","date":"2026-10-21"}]')
        before = (self.root / 'data/news.json').read_bytes()

        def down(url, headers=None, timeout=None):
            return response(503, url)
        with patch.object(fetch, 'DATA_DIR', str(self.root / 'data')), patch.object(fetch.requests, 'get', side_effect=down), \
                patch.object(fetch, '_sleep', lambda s: None), patch.object(fetch, '_run_started', None), \
                patch.object(fetch, 'fetch_matome'), patch.object(fetch, 'fetch_standings'), redirect_stdout(io.StringIO()):
            fetch.REPORT.clear()
            self.assertEqual(fetch.main(), 1)
        self.assertEqual((self.root / 'data/news.json').read_bytes(), before)
        self.assertEqual(json.loads(self.state_path.read_text())['status'], 'ok')
        self.assertTrue(self.capture.exists())


class Downstream(Base):
    def test_same_run_reuses_il_without_refetch(self):
        update_injury.run(self.root, client(), self.capture, datetime(2026, 10, 22, 3, tzinfo=timezone.utc))
        c = official.Client(max_requests=5, time_budget=60, fetch=lambda url, t: (_ for _ in ()).throw(AssertionError('refetch')))
        self.assertTrue(features.use_il_capture(c, self.capture))
        self.assertIn('ディークハンス', c.get(URL))
        self.assertEqual(c.request_count, 0)

    def test_failed_il_is_not_refetched_and_stays_unconfirmed(self):
        update_injury.run(self.root, client(503), self.capture, datetime(2026, 10, 22, 3, tzinfo=timezone.utc))
        c = official.Client(max_requests=5, time_budget=60, fetch=lambda url, t: (_ for _ in ()).throw(AssertionError('refetch')))
        self.assertFalse(features.use_il_capture(c, self.capture))
        with self.assertRaises(official.DataError):
            c.get(URL)
        self.assertEqual(c.request_count, 0)

    def test_article_shows_il_retrieval_time_not_now(self):
        """記事側：IL登録の注記に、その一覧を取得した日時を書く（古い一覧を最新に見せない）。"""
        update_injury.run(self.root, client(), self.capture, datetime(2026, 10, 21, 17, tzinfo=timezone.utc))
        c = official.Client(max_requests=5, time_budget=60, fetch=lambda url, t: (_ for _ in ()).throw(AssertionError('refetch')))
        features.use_il_capture(c, self.capture)
        retrieved = json.loads(self.capture.read_text())['retrieved_at']
        records = official.injury_records(c.get(URL))
        roster = [dict(player_id='9', name='ヘイデン・ディークハンス', team_id='50')]
        game = dict(home_id='40', away_id='50', home_full='ウォルガ湘南', away_full='山口パッツファイブ')
        official.apply_injuries(c, roster, [r for r in records if r['active']], game)
        stamp = datetime.fromisoformat(retrieved).astimezone(official.JST).strftime('%Y-%m-%d %H:%M JST')
        self.assertEqual(roster[0]['availability'], 'out')
        self.assertIn('公式IL登録中（' + stamp + ' 取得時点）', roster[0]['availability_detail'])

    def test_labels_do_not_call_il_a_game_day_absence(self):
        self.assertEqual(match_articles.AVAILABILITY_LABELS['out'], 'IL登録中（取得時点・当日の出欠は別）')
        self.assertNotIn('欠場', match_articles.AVAILABILITY_LABELS['out'])
        self.assertNotIn('欠場', match_articles.EXCLUSIONS['out'])


class Workflow(unittest.TestCase):
    def test_il_step_is_inside_existing_schedule_and_failure_is_reported(self):
        text = (ROOT / '.github/workflows/update.yml').read_text()
        self.assertEqual(len(re.findall(r'- cron:', text)), 4)                    # 新しいスケジュールなし
        il, news = text.index('id: il'), text.index('id: fetch')
        self.assertLess(il, news)                                                 # IL はニュースより前・独立
        self.assertIn('--il-capture "$RUNNER_TEMP/il-capture.json"', text)        # 後続は再取得しない
        self.assertIn("injury.html data/match_articles/injury.json", text)       # ニュース失敗時も IL を保存
        self.assertIn("if: always() && steps.il.outputs.il_status == 'failed'", text)
        self.assertNotIn('continue-on-error', text)


if __name__ == '__main__':
    unittest.main()
