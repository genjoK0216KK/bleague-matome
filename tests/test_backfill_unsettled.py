"""Recovery of past unfinished JST dates (2026-10-20: 10/19 stayed 'scheduled' because the
delayed 01:24 JST run only fetched the new JST day). Network/build/publish are never used."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from scripts import update_results as subject
from scripts import day_articles


def game(date, gid='507246', final=False, league='B1', status=None):
    g = dict(game_id=gid, season='2026-27', competition=league, starts_at=date + 'T10:05:00+00:00',
             status=status or ('final' if final else 'scheduled'), ended=final, fixed=final,
             home='東京U', away='山形', home_id='1', away_id='2',
             home_score=87 if final else None, away_score=61 if final else None,
             source='https://www.bleague.jp/game_detail/?ScheduleKey=' + gid, players=[])
    return g


def day(date, games, rankings=None):
    s = dict(date=date, games=games, errors=[], sources=[], schedule_complete=dict(BP=True, B1=True, BN=True))
    if rankings is not None:
        s['game_day_rankings'] = {'date': date, 'leagues': rankings}
    return s


OK = {'B1': {'positions': {'PG': []}, 'eligible_players': 0}}
PENDING = {'B1': {'error': '全試合の公式記録確定待ち'}}


class Backfill(unittest.TestCase):
    def setUp(self):
        preview = patch.object(subject.refresh_next_preview, 'refresh', return_value={'changed': False})
        preview.start(); self.addCleanup(preview.stop)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.now = datetime.fromisoformat('2026-10-19T16:24:00+00:00')  # 2026-10-20 01:24 JST
        self.client = SimpleNamespace(request_count=0, max_requests=70)
        self.calls, self.writes = [], []
        self.official = {}  # date -> summary returned by the official read

    def path(self, date):
        return self.root / 'data/match_articles' / day_articles.filename(date).replace('.html', '.json')

    def save(self, summary):
        p = self.path(summary['date']); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(summary)); (self.root / day_articles.filename(summary['date'])).write_text('old')
        return p

    def collect(self, client, year, date):
        self.calls.append(date)
        value = self.official.get(date, day(date, []))
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    def write(self, client, root, summary, *args, **kwargs):
        self.writes.append((summary['date'], kwargs))
        out = dict(summary, game_day_rankings={'date': summary['date'], 'leagues': kwargs.get('_rankings', OK)})
        self.save(out)
        return day_articles.filename(summary['date'])

    def go(self, rankings=None):
        with patch.object(subject.day_articles, 'collect', side_effect=self.collect), \
                patch.object(subject.day_articles, 'write', side_effect=self.write), \
                patch.object(subject.day_articles.game_day_rankings, 'collect',
                             return_value={'leagues': rankings if rankings is not None else PENDING}) as trial:
            return subject.run(self.root, self.client, 2026, self.now), trial

    def test_delayed_run_after_midnight_recovers_yesterday_with_ranking_fetch_allowed(self):
        self.save(day('2026-10-19', [game('2026-10-19')], PENDING))
        self.official['2026-10-19'] = day('2026-10-19', [game('2026-10-19', final=True)])
        result, _ = self.go()
        self.assertEqual(self.calls, ['2026-10-20', '2026-10-19'])
        self.assertEqual([d for d, _ in self.writes], ['2026-10-19'])
        kwargs = self.writes[0][1]
        self.assertIs(kwargs['refresh_players'], False)
        self.assertIs(kwargs['rankings_client'], self.client)  # stale (>36h) positions can be re-read
        self.assertTrue(result['changed'])

    def test_same_instant_in_utc_or_jst_gives_same_dates(self):
        self.save(day('2026-10-19', [game('2026-10-19')], PENDING))
        a = subject.pending_dates(self.root, self.now)
        b = subject.pending_dates(self.root, datetime.fromisoformat('2026-10-20T01:24:00+09:00'))
        self.assertEqual(a, b); self.assertEqual(a, ['2026-10-20', '2026-10-19'])
        # 23:59 JST on the 19th is still the 19th
        self.assertEqual(subject.pending_dates(self.root, datetime.fromisoformat('2026-10-19T14:59:00+00:00'))[0], '2026-10-19')

    def test_final_result_without_eff_top3_is_retried_not_settled(self):
        s = day('2026-10-19', [game('2026-10-19', final=True)], PENDING)
        self.assertFalse(subject.settled(s)); self.assertFalse(subject.done(s))
        self.assertTrue(subject.done(day('2026-10-19', [game('2026-10-19', final=True)], OK)))
        self.save(s); self.official['2026-10-19'] = copy.deepcopy(s)
        # unchanged games, TOP3 still unavailable -> no rewrite, no commit churn
        result, trial = self.go(rankings=PENDING)
        self.assertEqual([r['reason'] for r in result['dates'] if r['date'] == '2026-10-19'], ['rankings_still_pending'])
        self.assertEqual(self.writes, []); trial.assert_called_once()
        # TOP3 now available -> rewritten
        self.calls.clear(); result, _ = self.go(rankings=OK)
        self.assertEqual([d for d, _ in self.writes], ['2026-10-19'])

    def test_today_failure_does_not_block_yesterday(self):
        self.save(day('2026-10-19', [game('2026-10-19')], PENDING))
        self.official['2026-10-20'] = ValueError('synthetic transient')
        self.official['2026-10-19'] = day('2026-10-19', [game('2026-10-19', final=True)])
        result, _ = self.go()
        self.assertTrue(result['changed'])
        # 10/22: errors also carry public diagnostics (type / HTTP status / URL) for the run log.
        # Nothing recorded by the client for this synthetic error -> category 'unknown'.
        self.assertEqual(result['errors'], [{'date': '2026-10-20', 'error': 'synthetic transient',
                                             'category': 'unknown', 'type': 'ValueError', 'http_status': None, 'url': None,
                                             'fetch_failures': []}])
        self.assertEqual([d for d, _ in self.writes], ['2026-10-19'])

    def test_all_failing_raises_and_keeps_bytes(self):
        p = self.save(day('2026-10-19', [game('2026-10-19')], PENDING)); before = p.read_bytes()
        broken = dict(day('2026-10-19', [game('2026-10-19')]), errors=['x'], schedule_complete=dict(BP=False, B1=False, BN=False))
        self.official['2026-10-19'] = broken; self.official['2026-10-20'] = broken
        with self.assertRaises(ValueError): self.go()
        self.assertEqual(p.read_bytes(), before); self.assertEqual(self.writes, [])

    def test_finished_old_and_unsaved_dates_are_not_fetched(self):
        self.save(day('2026-10-18', [game('2026-10-18', final=True)], OK))    # done
        self.save(day('2026-10-16', [game('2026-10-16')], PENDING))           # older than LOOKBACK_DAYS (3)
        self.save(day('2027-01-01', [game('2027-01-01')], PENDING))           # future
        result, _ = self.go()
        self.assertEqual(self.calls, ['2026-10-20'])  # 10/17 has no saved file -> not created here

    def test_budget_defers_past_date_without_partial_write(self):
        self.save(day('2026-10-19', [game('2026-10-19', gid=str(i)) for i in range(30)], PENDING))
        self.client.max_requests = 20
        result, _ = self.go()
        self.assertEqual(self.calls, ['2026-10-20'])
        self.assertEqual([r['reason'] for r in result['dates'] if r['date'] == '2026-10-19'], ['deferred_budget'])
        self.assertEqual(self.writes, [])

    def test_regressed_past_result_keeps_saved_bytes(self):
        p = self.save(day('2026-10-19', [game('2026-10-19', final=True)], PENDING)); before = p.read_bytes()
        self.official['2026-10-19'] = day('2026-10-19', [game('2026-10-19')])
        with self.assertRaisesRegex(ValueError, 'regressed'): self.go()
        self.assertEqual(p.read_bytes(), before)

    def test_rerun_after_completion_is_idempotent(self):
        self.save(day('2026-10-19', [game('2026-10-19')], PENDING))
        self.official['2026-10-19'] = day('2026-10-19', [game('2026-10-19', final=True)])
        self.go()
        self.calls.clear(); self.writes.clear()
        result, _ = self.go()
        self.assertEqual(self.calls, ['2026-10-20']); self.assertEqual(self.writes, [])

    def test_no_game_day_and_cancelled_postponed_are_done(self):
        self.assertTrue(subject.done(day('2026-10-15', [])))
        off = game('2026-10-19', status='postponed')
        self.assertTrue(subject.done(day('2026-10-19', [off], {})))
        self.assertFalse(subject.done(day('2026-10-19', [dict(off, source='')], {})))

    def test_merge_keeps_built_league_when_retry_fails(self):
        fresh = {'leagues': {'B1': {'error': 'Official fetch budget exhausted'}, 'BP': {'positions': {}}}}
        merged = day_articles.merge_rankings(fresh, {'B1': OK['B1']}, ['B1'])
        self.assertEqual(merged['leagues']['B1'], OK['B1'])
        self.assertEqual(day_articles.merge_rankings(fresh, {'B1': OK['B1']}, [])['leagues']['B1'], fresh['leagues']['B1'])

    def test_corrupt_past_file_is_isolated_to_its_date(self):
        self.save(day('2026-10-19', [game('2026-10-19')], PENDING))
        bad = self.path('2026-10-18'); bad.write_text('{not json'); (self.root / day_articles.filename('2026-10-18')).write_text('old')
        self.official['2026-10-19'] = day('2026-10-19', [game('2026-10-19', final=True)])
        result, _ = self.go()
        self.assertEqual([d for d, _ in self.writes], ['2026-10-19'])
        self.assertEqual([e['date'] for e in result['errors']], ['2026-10-18'])
        self.assertEqual(bad.read_text(), '{not json')


class ContextGameScheduleNotice(unittest.TestCase):
    """A game with an official context page still honours the schedule's 中止/延期 notice."""
    def page(self, ended, fixed):
        from scripts import official_data as official
        raw = (Path(__file__).parent / 'fixtures/game-507233.html').read_text()
        ctx = official.context(raw)
        ctx['Game'].update(GameEndedFlg=ended, RecordFixedFlg=fixed)
        return raw[:raw.index('_contexts_s3id.data')] + '_contexts_s3id.data = ' + json.dumps(ctx, ensure_ascii=False) + ';</script>'

    def test_unfinished_context_game_takes_cancelled_or_postponed(self):
        from scripts import official_data as official
        for notice in ('cancelled', 'postponed'):
            g = official.parse_game(self.page(False, False), '507233', 2026, notice)
            self.assertEqual(g['status'], notice)
            self.assertFalse(subject.data.is_verified_final(g))
        self.assertEqual(official.parse_game(self.page(False, False), '507233', 2026)['status'], 'unconfirmed')

    def test_fixed_final_contradicting_notice_is_an_error(self):
        from scripts import official_data as official
        with self.assertRaises(official.DataError):
            official.parse_game(self.page(True, True), '507233', 2026, 'cancelled')
        self.assertEqual(official.parse_game(self.page(True, True), '507233', 2026)['status'], 'final')


if __name__ == '__main__':
    unittest.main()
