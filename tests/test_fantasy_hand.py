import unittest
from pathlib import Path
from scripts import fantasy_hand as fh


def row(pid, name, eff, bits, rare, star1=True):
    return dict(player_id=pid, name=name, team='T', league='BP', eff=eff, bits=bits, max_rare=rare, star1=star1)


class FantasyHandTest(unittest.TestCase):
    def test_score_rounds_down_and_floors_at_one(self):
        self.assertEqual(fh.score(26, 4), 70)      # 26 × 2.7 = 70.2
        self.assertEqual(fh.score(38, 5), 114)
        self.assertEqual(fh.score(-3, 1), 1)

    def test_each_player_fills_one_slot_only(self):
        rows = [row('1', 'A', 40, 1 | 2, 1), row('2', 'B', 30, 1, 1), row('3', 'C', 20, 2, 1),
                row('4', 'D', 10, 4, 1), row('5', 'E', 10, 8, 1), row('6', 'F', 10, 16, 1)]
        hand = fh.best_hand(rows, lambda r: 1)
        names = [r['name'] for r in hand['lineup']]
        self.assertEqual(len(set(names)), 5)
        self.assertEqual(hand['total'], (40 + 30 + 10 + 10 + 10) * 2)

    def test_rare_card_can_beat_higher_eff(self):
        rows = [row('1', 'Hi', 22, 1, 1), row('2', 'Rare', 15, 1, 5)] + [
            row(str(i), 'X' + str(i), 5, b, 1) for i, b in ((3, 2), (4, 4), (5, 8), (6, 16))]
        self.assertEqual(fh.best_hand(rows, lambda r: r['max_rare'])['lineup'][0]['name'], 'Rare')
        self.assertEqual(fh.best_hand(rows, lambda r: 1 if r['star1'] else 0)['lineup'][0]['name'], 'Hi')

    def test_waits_until_every_game_is_final(self):
        summary = {'schedule_complete': {'BP': True}, 'games': [{'status': 'scheduled', 'season': '2026-27', 'competition': 'BP'}]}
        self.assertEqual(fh.collect('.', summary)['error'], '全試合の公式記録確定待ち')

    def test_forecast_uses_season_average_and_waits_for_every_league(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'data/fantasy').mkdir(parents=True)
            players = {'T|P' + str(i): dict(bits=b, max_rare=1 if i else 4, star1=True) for i, b in enumerate((1, 2, 4, 8, 16))}
            (Path(root) / 'data/fantasy/cards-2026.json').write_text(json.dumps(
                {'retrieved_at': '2026-11-17T00:00:00+09:00', 'source': 'x', 'players': players}))
            pool = [dict(player_id=str(i), name='P' + str(i), team='T', average='10.5') for i in range(5)]
            state = {'games': [{'season': '2026-27', 'competition': 'BP', 'status': 'scheduled'}],
                     'lineups': {'BP': {'pool': pool}}}
            hand = fh.forecast(root, state)
            self.assertEqual(hand['star1']['total'], 21 * 5)          # 10.5 × 2 = 21
            self.assertEqual(hand['best']['total'], 21 * 4 + 28)      # ★4：10.5 × 2.7 = 28.35
            self.assertIn('id="fantasy-forecast"', fh.html(hand, forecast=True))
            state['games'].append({'season': '2026-27', 'competition': 'B1', 'status': 'scheduled'})
            self.assertIn('error', fh.forecast(root, state))


if __name__ == '__main__':
    unittest.main()
