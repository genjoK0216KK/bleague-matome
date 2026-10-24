"""Regression for the official JS-only scoreboard observed on 2026-10-24.

An empty score is not zero, proof of a future game, or a verified final record.
Only validated fixture metadata may survive this unavailable-record condition.
"""
from datetime import datetime
from pathlib import Path
import unittest
from scripts import official_data as official, next_preview, preview_data, result_status

FIX = Path(__file__).parent / 'fixtures'


def shell(home='', away=''):
    html = (FIX / 'game-506464.html').read_text()
    for value in (home, away):
        html = html.replace('<div class="team-point font-blg">--',
                            '<div class="team-point font-blg">' + value, 1)
    return html


class DynamicScoreShell(unittest.TestCase):
    def test_empty_or_whitespace_keeps_identity_but_not_result(self):
        for home, away in [('', ''), (' \n ', '\t'), ('--', ''), ('', '--')]:
            with self.subTest(home=home, away=away):
                game = official.parse_game(shell(home, away), '506464', 2026)
                self.assertEqual(game['status'], 'unconfirmed')
                self.assertEqual(game['record_note'], 'official_record_not_loaded')
                self.assertEqual((game['home'], game['away']), ('川崎', '茨城'))
                self.assertEqual(game['starts_at'], '2026-10-16T19:05:00+09:00')
                self.assertEqual((game['home_score'], game['away_score']), (None, None))
                self.assertEqual((game['ended'], game['fixed'], game['players']), (False, False, []))
                self.assertFalse(preview_data.is_verified_final(game))

    def test_numeric_score_wins_over_partial_empty_shell(self):
        for home, away in [('0', ''), ('', '75'), ('78', '75')]:
            game = official.parse_game(shell(home, away), '506464', 2026)
            self.assertEqual(game['record_note'], 'score_shown_without_official_record')
            self.assertFalse(next_preview.upcoming([game], datetime.fromisoformat('2026-10-15T12:00:00+09:00')))

    def test_cancelled_and_postponed_remain_excluded(self):
        for status in ('cancelled', 'postponed'):
            game = official.parse_game(shell(), '506464', 2026, status)
            self.assertEqual(game['status'], status)
            self.assertFalse(next_preview.upcoming([game], datetime.fromisoformat('2026-10-15T12:00:00+09:00')))

    def test_future_fixture_only_until_exact_tipoff(self):
        game = official.parse_game(shell(), '506464', 2026)
        before = datetime.fromisoformat('2026-10-16T19:04:59+09:00')
        at = datetime.fromisoformat(game['starts_at'])
        self.assertEqual(next_preview.choose([game], before), ('2026-10-16', [game]))
        self.assertEqual(next_preview.choose([game], at), (None, []))
        self.assertEqual(next_preview.choose([game], datetime.fromisoformat('2026-10-17T12:00:00+09:00')), (None, []))

    def test_identity_validation_stays_fail_closed(self):
        for html in [shell().replace('team-point', 'missing-point'),
                     shell().replace('ScheduleKey=506464', 'ScheduleKey=999999'),
                     shell().replace('19:05 TIP OFF', '未定'), shell('unknown', '')]:
            with self.assertRaises(official.DataError):
                official.parse_game(html, '506464', 2026)

    def test_unconfirmed_without_exact_reason_not_included(self):
        game = official.parse_game(shell(), '506464', 2026)
        for note in (None, 'score_shown_without_official_record', 'unknown'):
            game['record_note'] = note
            self.assertFalse(next_preview.upcoming([game], datetime.fromisoformat('2026-10-15T12:00:00+09:00')))

    def test_daily_labels_distinguish_future_shell_from_record_pending(self):
        game = official.parse_game(shell(), '506464', 2026)
        before = datetime.fromisoformat('2026-10-16T19:04:59+09:00')
        at = datetime.fromisoformat(game['starts_at'])
        self.assertEqual(result_status.game_state(game, before, preview_data.is_verified_final), '19:05 試合前')
        self.assertEqual(result_status.game_state(game, at, preview_data.is_verified_final), '19:05 開始・公式記録未確定')
        scored = official.parse_game(shell('78', ''), '506464', 2026)
        self.assertEqual(result_status.game_state(scored, before, preview_data.is_verified_final), '19:05 開始・公式記録未確定')
