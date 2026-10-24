"""Official public JS feed, recorded 2026-10-24 17:52 JST (506500/99.json).

Fixture retains official Game and total player boxscores; omits play-by-play,
period rows and summaries not used by this adapter. No numeric reconstruction.
"""
import copy
import gzip
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from scripts import official_data as o, preview_data

FIX = Path(__file__).parent / 'fixtures'


def page():
    # Minimal canonical fixture header, same verified game/time/teams as payload.
    return '''<meta property="og:url" content="https://www.bleague.jp/game_detail/?ScheduleKey=506500">
    <section class="game-top"><div class="date-wrap"><span class="font-blg">2026.10.24</span></div>
    <span id="convention-name">B.LEAGUE 2026-27 B.LEAGUE PREMIER リーグ戦</span><p class="time">15:00 TIP OFF</p>
    <div class="team-wrap home"><div class="team-name"><p class="for-pc">秋田ノーザンハピネッツ</p><p class="for-sp">秋田</p></div><div class="team-point"><div>HOME</div></div></div>
    <div class="team-wrap away"><div class="team-name"><p class="for-pc">横浜ビー・コルセアーズ</p><p class="for-sp">横浜BC</p></div><div class="team-point"><div>AWAY</div></div></div></section>
    <div class="related-links"><a href="/club_detail/?TeamID=693">秋田ノーザンハピネッツ</a><a href="/club_detail/?TeamID=694">横浜ビー・コルセアーズ</a></div>
    <script>_contexts_s3id[506500]=98; _contexts.scheduleKey = 506500;</script>'''


class Capture:
    def __init__(self):
        self.payload = json.loads((FIX / 'game-506500-feed.json').read_text())
        self.calls = []
        self.latest = '99'
    def get(self, url):
        self.calls.append(url)
        return self.latest if url.endswith('latestid') else json.dumps(self.payload)


class PublicGameFeed(unittest.TestCase):
    def test_verified_record_restores_score_and_eff(self):
        client = Capture()
        game = o.fetch_game(client, page(), '506500', 2026)
        self.assertTrue(preview_data.is_verified_final(game))
        self.assertEqual((game['home_score'], game['away_score']), (95, 86))
        self.assertEqual(len(game['players']), 22)
        self.assertEqual(game['players'][0]['EFF'], client.payload['HomeBoxscores'][0]['EFF'])
        self.assertEqual(client.calls, [o.GAME_FEED + '506500/latestid', o.GAME_FEED + '506500/99.json'])
        self.assertEqual(game['record_source'], client.calls[-1])

    def test_missing_eff_not_filled_and_zero_not_removed(self):
        client = Capture()
        client.payload['HomeBoxscores'][0]['EFF'] = None
        client.payload['HomeBoxscores'][1]['EFF'] = 0
        game = o.fetch_game(client, page(), '506500', 2026)
        self.assertIsNone(game['players'][0]['EFF'])
        self.assertEqual(game['players'][1]['EFF'], 0)

    def test_both_flags_required(self):
        for flag in ('GameEndedFlg', 'RecordFixedFlg'):
            client = Capture(); client.payload['Game'][flag] = False
            game = o.fetch_game(client, page(), '506500', 2026)
            self.assertFalse(preview_data.is_verified_final(game))
            self.assertEqual(game['status'], 'unconfirmed')

    def test_invalid_identity_time_score_and_duplicate_rows_fail_closed(self):
        changes = [('ScheduleKey', 999), ('Year', 2025), ('HomeTeamID', '999'),
                   ('GameDateTime', '/Date(1792825200000+0900)/'), ('HomeTeamScore', 96)]
        for key, value in changes:
            client = Capture(); client.payload['Game'][key] = value
            with self.subTest(key=key), self.assertRaises(o.DataError):
                o.fetch_game(client, page(), '506500', 2026)
        client = Capture(); client.payload['HomeBoxscores'].append(copy.deepcopy(client.payload['HomeBoxscores'][0]))
        with self.assertRaises(o.DataError): o.fetch_game(client, page(), '506500', 2026)

    def test_future_without_feed_and_other_game_advertisement_no_requests(self):
        for html in (page().replace('_contexts_s3id[506500]=98;', ''),
                     page().replace('_contexts_s3id[506500]=98;', '_contexts_s3id[999]=98;'),
                     page().replace('_contexts_s3id[506500]=98;', '_contexts_s3id[506500]=0;')):
            client = Capture(); game = o.fetch_game(client, html, '506500', 2026)
            self.assertFalse(client.calls); self.assertFalse(preview_data.is_verified_final(game))

    def test_denial_has_no_alternate_path_or_snapshot(self):
        client = Capture()
        def denied(url):
            client.calls.append(url)
            raise o.FetchError('AccessDenied', url, status=403)
        client.get = denied
        with self.assertRaises(o.FetchError): o.fetch_game(client, page(), '506500', 2026)
        self.assertEqual(client.calls, [o.GAME_FEED + '506500/latestid'])

    def test_feed_allowlist_rejects_other_hosts_paths_queries_and_http(self):
        good = o.GAME_FEED + '506500/99.json'
        self.assertTrue(o.allowed_source(good))
        for url in [good.replace('https:', 'http:'), good + '?token=x', good.replace('/99.json', '/../x'),
                    good.replace('b-league.s3.amazonaws.com', 'other.s3.amazonaws.com'),
                    good.replace('https://', 'https://user:password@'), good.replace('/v2_genius_contexts/', '/private/')]:
            self.assertFalse(o.allowed_source(url), url)

    def test_client_decodes_unmarked_gzip_feed_and_keeps_capture(self):
        url = o.GAME_FEED + '506500/99.json'
        body = gzip.compress(b'{"Game": {}}')
        response = SimpleNamespace(status_code=200, url=url, content=body, text='binary', raise_for_status=lambda:None)
        client = o.Client(fetch=lambda u,t:response)
        with patch.object(o.time, 'sleep'):
            self.assertEqual(client.get(url), '{"Game": {}}')
        self.assertEqual(client.get(url), '{"Game": {}}')
        self.assertEqual(client.request_count, 1)

    def test_boxscore_shapes_and_cross_team_duplicates_fail_closed(self):
        for rows in (None, [None], {}, 'bad'):
            client = Capture(); client.payload['HomeBoxscores'] = rows
            with self.subTest(rows=rows), self.assertRaises(o.DataError):
                o.fetch_game(client, page(), '506500', 2026)
        client = Capture()
        client.payload['AwayBoxscores'][0]['PlayerID'] = client.payload['HomeBoxscores'][0]['PlayerID']
        with self.assertRaises(o.DataError): o.fetch_game(client, page(), '506500', 2026)

    def test_missing_eff_becomes_league_error_without_zero_fill(self):
        from scripts import game_day_rankings as ranking
        client = Capture()
        client.payload['HomeBoxscores'][0]['EFF'] = None
        game = o.fetch_game(client, page(), '506500', 2026)
        positions = [dict(player_id=str(p['PlayerID']), team_id=str(p['TeamID']),
                          season=game['season'], competition='BP', positions=['PG'],
                          position_source='https://www.bleague.jp/club_detail/?TeamID='+str(p['TeamID']))
                     for p in game['players']]
        summary = dict(date='2026-10-24', games=[game], schedule_complete={'BP':True})
        with patch.object(ranking, 'roster', return_value=(positions, '2026-10-24T17:52:00+09:00')):
            result = ranking.collect(None, '.', summary)
        self.assertIn('error', result['leagues']['BP'])
        self.assertNotIn('positions', result['leagues']['BP'])
        game['players'][0]['EFF'] = 0
        rows = ranking.player_rows(game, positions, '2026-10-24')
        self.assertEqual(rows[0]['eff'], 0)
