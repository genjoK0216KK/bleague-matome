"""チーム分析の数字（scripts/team_report.py）の試験。ネットには出ない。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import team_report as t  # noqa: E402


def side(p2m, p2a, p3m, p3a, ftm, fta, orb=10, drb=30, to=10, paint=30, second=10):
    return {'fgm': p2m + p3m, 'fga': p2a + p3a, 'p2m': p2m, 'p2a': p2a, 'p3m': p3m, 'p3a': p3a, 'ftm': ftm,
            'fta': fta, 'orb': orb, 'drb': drb, 'ast': 20, 'to': to, 'stl': 5, 'blk': 2, 'foul': 18,
            'paint': paint, 'pot': 12, 'second': second, 'fastbreak': 10}


def game(key, date, home, away, h, a):
    hp, ap = t._pts(h), t._pts(a)
    return {'key': key, 'convention': t.PREMIER, 'date': date, 'home': home, 'away': away,
            'home_score': hp, 'away_score': ap, 'quarters': {'home': [hp // 4] * 4, 'away': [ap // 4] * 4},
            'max_period': 4, 'summaries': {'18': {'home': h, 'away': a}, '15': {'home': h, 'away': a},
                                           '16': {'home': h, 'away': a}},
            'players': {'home': [], 'away': []}, 'paint_shots': {'home': [10, 20], 'away': [12, 20]},
            'url': f'https://www.bleague.jp/game_detail/?ScheduleKey={key}&tab=2'}


def season():
    games = []
    for i in range(6):
        games.append(game(str(506400 + i), f'2026-10-{10 + i:02d}', 'A', 'B',
                          side(30, 55, 8, 25, 15, 20), side(28, 50, 10, 30, 10, 14)))
    return games


class Metrics(unittest.TestCase):
    def test_points_split_adds_up_and_uses_last_five(self):
        r = t.metrics(season(), 'A')
        tot = r['totals']
        self.assertEqual(r['metrics']['games'], 5)
        self.assertEqual(tot['p2_points'][2] + tot['p3_points'][2] + tot['ft_points'][2], tot['points'][2])
        self.assertEqual(tot['points'], [5 * 99, 5 * 96, 15])

    def test_not_enough_games_is_skipped(self):
        self.assertIsNone(t.metrics(season()[:4], 'A'))

    def test_streak_counts_whole_season(self):
        self.assertEqual(t.current_streak(season(), 'A'), 6)
        self.assertEqual(t.current_streak(season(), 'B'), -6)


class Choose(unittest.TestCase):
    def test_team_written_within_two_weeks_is_skipped(self):
        cal = {'months': []}
        self.assertEqual(t.choose_team(season(), cal, '2026-10-20', {'A': '2026-10-15'}, {}), 'B')
        # 2週間たてば候補に戻る。同点なら、まだ書いていないチームが先
        self.assertEqual(t.choose_team(season(), cal, '2026-11-01', {'A': '2026-10-15'}, {}), 'B')
        self.assertEqual(t.choose_team(season(), cal, '2026-11-01', {'A': '2026-10-15', 'B': '2026-10-14'}, {}), 'B')
        self.assertEqual(t.choose_team(season(), cal, '2026-11-01', {'A': '2026-10-13', 'B': '2026-10-14'}, {}), 'A')


class Numbers(unittest.TestCase):
    def test_decimal_not_in_report_is_flagged(self):
        report = {'numbers': {'ortg': {'value': 108.418, 'league_avg': 111.801, 'percent': False}},
                  'totals': {'p3': {'team': [58, 189]}}}
        html = ('<article class="article"><p>100回あたり108.4点。平均より3.4点低い。3Pは30.7%。'
                '別の数字は12.9です。</p><details class="sources">99.9</details></article>')
        self.assertEqual(t.check_numbers(html, report), ['12.9'])


if __name__ == '__main__':
    unittest.main()
