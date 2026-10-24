"""確定した試合だけ先に反映する（10/24 本人「進めて」）。

10/23 は 507921・507924 の試合ページに得点の表示があるのに公式記録（試合データ）が無く、
「形式が違う」として止まり、確定済みの試合を含む7試合すべてが保留になった。
得点表示だけのページは「開始・公式記録未確定」（得点は取り込まない）として扱い、ほかの試合の反映を止めない。
"""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import official_data as official, preview_data, update_results

FIX = Path(__file__).parent / 'fixtures'


def page_with_scores(home='78', away='75'):
    text = (FIX / 'game-506464.html').read_text()
    text = text.replace('<div class="team-point font-blg">--', '<div class="team-point font-blg">' + home, 1)
    return text.replace('<div class="team-point font-blg">--', '<div class="team-point font-blg">' + away, 1)


class ScoresWithoutRecord(unittest.TestCase):
    def test_scores_shown_without_record_are_unconfirmed_and_not_taken(self):
        g = official.parse_game(page_with_scores(), '506464', 2026)
        self.assertEqual(g['status'], 'unconfirmed')
        self.assertEqual((g['home_score'], g['away_score']), (None, None))   # 表示の得点は取り込まない
        self.assertEqual((g['ended'], g['fixed']), (False, False))
        self.assertFalse(preview_data.is_verified_final(g))
        self.assertEqual(g['record_note'], 'score_shown_without_official_record')

    def test_future_page_is_still_scheduled(self):
        g = official.parse_game((FIX / 'game-506464.html').read_text(), '506464', 2026)
        self.assertEqual(g['status'], 'scheduled')
        self.assertNotIn('record_note', g)

    def test_cancel_notice_with_scores_is_still_an_error(self):
        with self.assertRaises(official.DataError):
            official.parse_game(page_with_scores(), '506464', 2026, 'cancelled')


class PartialDay(unittest.TestCase):
    """10/23 と同じ形：確定済みの試合と、記録待ちの試合が同じ日にある。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        p = patch.object(update_results.refresh_next_preview, 'refresh', return_value={'changed': False})
        p.start(); self.addCleanup(p.stop)
        base = dict(season='2026-27', starts_at='2026-10-23T19:05:00+09:00', source='https://www.bleague.jp/game_detail/?ScheduleKey=')
        self.scheduled = [dict(base, game_id=k, competition=c, status='scheduled', ended=False, fixed=False,
                               home_score=None, away_score=None, source=base['source'] + k)
                          for k, c in (('506497', 'BP'), ('507921', 'BN'))]
        self.saved = dict(date='2026-10-23', games=copy.deepcopy(self.scheduled), errors=[],
                          schedule_complete=dict(BP=True, B1=True, BN=True))
        path = self.root / 'data/match_articles/article-games-20261023.json'
        path.parent.mkdir(parents=True); path.write_text(json.dumps(self.saved))
        (self.root / 'article-games-20261023.html').write_text('retained')

    def test_final_game_is_published_while_other_waits_for_record(self):
        fresh = copy.deepcopy(self.saved)
        fresh['games'][0].update(status='final', ended=True, fixed=True, home_score=80, away_score=70)
        fresh['games'][1].update(status='unconfirmed', record_note='score_shown_without_official_record')
        client = SimpleNamespace(request_count=10, max_requests=70, failures=[])
        with patch.object(update_results.day_articles, 'collect', return_value=fresh), \
                patch.object(update_results.day_articles, 'write', return_value='article-games-20261023.html') as write:
            report = update_results.run_date(self.root, client, 2026, datetime(2026, 10, 23, 22, 0, tzinfo=preview_data.JST))
        self.assertTrue(report['changed'])
        written = write.call_args.args[2]['games']
        self.assertTrue(preview_data.is_verified_final(written[0]))
        self.assertEqual((written[1]['home_score'], written[1]['status']), (None, 'unconfirmed'))
        # 記録待ちが残る日は「完了」にならず、次の回も確認を続ける
        self.assertFalse(update_results.done(dict(fresh, game_day_rankings={'leagues': {}})))


class StartedDayHeading(unittest.TestCase):
    """10/23：全試合が「開始・公式記録未確定」の日を「出場予定選手のベスト5」と見出しにしない（10/25 本人「修正して」）。"""

    def render(self, statuses):
        from bs4 import BeautifulSoup
        from scripts import day_articles, match_articles
        games = [dict(game_id=str(500 + i), competition='BP', season='2026-27', starts_at='2026-10-23T19:05:00+09:00',
                      status=st, ended=False, fixed=False, home='H', away='A', home_id='1', away_id='2',
                      home_score=None, away_score=None, source='https://www.bleague.jp/game_detail/?ScheduleKey=' + str(500 + i))
                 for i, st in enumerate(statuses)]
        s = dict(date='2026-10-23', games=games, sources=[], schedule_complete=dict(BP=True, B1=True, BN=True), lineups={})
        _, html = day_articles.render(s, '.', [], '2026-10-24 09:23 JST')
        return BeautifulSoup(match_articles.readable_match(html), 'html.parser'), html

    def test_started_without_record_is_a_results_page_waiting_for_record(self):
        soup, html = self.render(['unconfirmed', 'unconfirmed', 'scheduled'])
        self.assertEqual(soup.h1.get_text(), '10/23 試合結果（公式記録の確定待ち）')
        self.assertEqual(soup.select_one('#daily-results h2').get_text(), '試合結果')
        self.assertNotIn('出場予定選手', soup.h1.get_text())

    def test_before_start_keeps_preview_heading(self):
        soup, _ = self.render(['scheduled', 'scheduled'])
        self.assertEqual(soup.h1.get_text(), '10/23 出場予定選手（登録選手）のベスト5')
        self.assertEqual(soup.select_one('#daily-results h2').get_text(), '試合予定')


if __name__ == '__main__':
    unittest.main()
