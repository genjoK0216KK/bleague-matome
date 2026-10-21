"""原典照合の設計（10/22・未接続）。参考記録で確定扱いしない・推測で寄せない。"""
import copy
import unittest

from scripts import result_evidence as rev

SEARCH = 'official_search_index'


def game(gid='506494', home='琉球', away='A千葉', **kw):
    g = dict(game_id=gid, competition='BP', season='2026-27', starts_at='2026-10-21T19:35:00+09:00',
             status='scheduled', ended=False, fixed=False, home=home, away=away, home_score=None, away_score=None,
             source='https://www.bleague.jp/game_detail/?ScheduleKey=' + gid)
    g.update(kw)
    return g


def ev(**kw):
    base = dict(route=SEARCH, url='https://www.bleague.jp/schedule/?tab=1', date_jst='2026-10-21', home='琉球',
                away='A千葉', game_id='506494', home_score=94, away_score=65, status_text='FINAL',
                retrieved_at='2026-10-22T04:20:00+09:00', crawled_at=None)
    base.update(kw)
    return rev.evidence(**base)


class Evidence(unittest.TestCase):
    def test_unknown_values_are_recorded_as_unknown(self):
        e = ev(game_id=None)
        self.assertEqual((e['crawled_at'], e['league'], e['season'], e['game_id']), ('不明', '不明', '不明', None))
        self.assertEqual(e['route_label'], '公式サイトの検索インデックス（検索結果の断片）')

    def test_partial_and_final_mixed_is_mismatch_not_final(self):
        items = [ev(url='https://www.bleague.jp/schedule/', home_score=82, away_score=60, status_text='途中'),
                 ev(url='https://www.bleague.jp/en/game_detail/?ScheduleKey=506494&tab=2')]
        g = game()
        before = copy.deepcopy(g)
        r = rev.reconcile(g, items, direct_fetch_ok=False)
        self.assertEqual(r['state'], 'mismatch')
        self.assertFalse(r['can_publish_score'])
        self.assertEqual(g, before)                       # 保存データに自動で入れない

    def test_different_date_or_matchup_is_rejected(self):
        r = rev.reconcile(game(), [ev(date_jst='2026-10-20'), ev(home='沖縄')], direct_fetch_ok=False)
        self.assertEqual(r['state'], 'unverified')
        self.assertEqual(len(r['rejected']), 2)
        self.assertIn('日付が違う（記録 2026-10-20／試合 2026-10-21）', r['rejected'][0]['reasons'])

    def test_unknown_game_id_is_not_linked(self):
        """信州90–97東京SR など ID 未確認の一覧断片：対戦・日付が合っても同一試合と確定しない。"""
        g = game(gid='506490', home='信州', away='東京SR', starts_at='2026-10-21T19:05:00+09:00')
        r = rev.reconcile(g, [ev(game_id=None, home='信州', away='東京SR', home_score=90, away_score=97)],
                          direct_fetch_ok=False)
        self.assertEqual(r['state'], 'unverified')
        self.assertIn('試合IDが不明（対戦と日付だけでは同一試合と確定しない）', r['rejected'][0]['reasons'])

    def test_old_or_unknown_crawl_is_only_a_stale_reference(self):
        g = game(gid='506486', home='北海道', away='富山', starts_at='2026-10-21T19:05:00+09:00')
        for crawled in (None, '2026-10-19T12:00:00+09:00'):
            with self.subTest(crawled=crawled):
                r = rev.reconcile(g, [ev(game_id='506486', home='北海道', away='富山', home_score=87, away_score=105,
                                         crawled_at=crawled)], direct_fetch_ok=False)
                self.assertEqual(r['state'], 'reference_stale')
                self.assertFalse(r['can_publish_score'])

    def test_fresh_reference_is_still_not_confirmed_when_direct_fetch_failed(self):
        g = game(gid='506486', home='北海道', away='富山', starts_at='2026-10-21T19:05:00+09:00')
        r = rev.reconcile(g, [ev(game_id='506486', home='北海道', away='富山', home_score=87, away_score=105,
                                 crawled_at='2026-10-21T21:30:00+09:00', route='club_official',
                                 url='https://example-club.jp/news/1')], direct_fetch_ok=False)
        self.assertEqual(r['state'], 'reference_only')
        self.assertFalse(r['can_publish_score'])

    def test_direct_fetch_ok_but_not_fixed_is_distinguished(self):
        g = game(status='unconfirmed', ended=True, fixed=False, home_score=94, away_score=65)
        r = rev.reconcile(g, [ev()], direct_fetch_ok=True)
        self.assertEqual(r['state'], 'official_not_fixed')
        self.assertFalse(r['can_publish_score'])

    def test_only_existing_official_condition_confirms(self):
        g = game(status='final', ended=True, fixed=True, home_score=94, away_score=65)
        r = rev.reconcile(g, [ev(home_score=82, away_score=60, status_text='途中')], direct_fetch_ok=True)
        self.assertEqual(r['state'], 'confirmed_official')
        self.assertTrue(r['can_publish_score'])


if __name__ == '__main__':
    unittest.main()
