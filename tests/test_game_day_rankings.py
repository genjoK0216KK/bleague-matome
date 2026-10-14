import copy,json,unittest
from pathlib import Path
from scripts import game_day_rankings as ranking

ROOT=Path(__file__).resolve().parents[1]
class GameDayRankings(unittest.TestCase):
 def setUp(self):
  s=json.loads((ROOT/'data/match_articles/article-games-20261014.json').read_text());self.game=s['games'][0]
  self.roster=json.loads((ROOT/'data/match_articles/players-507231.json').read_text())['players']
 def test_actual_game_totals(self):
  rows=ranking.player_rows(self.game,self.roster,'2026-10-14')
  self.assertTrue(rows);self.assertTrue(all('average' not in p for p in rows))
  self.assertEqual(len(rows),len({p['player_id'] for p in rows}))
 def test_missing_not_zero_and_zero_valid(self):
  game=copy.deepcopy(self.game);game['players'][0]['EFF']=None
  with self.assertRaises(ValueError):ranking.player_rows(game,self.roster,'2026-10-14')
  self.assertEqual(ranking.integer(0),0)
 def test_participation_second_and_dnp(self):
  self.assertEqual(ranking.seconds('00:01'),1);self.assertEqual(ranking.seconds('DNP'),0)
  with self.assertRaises(ValueError):ranking.seconds(None)
 def test_wrong_day_and_unfixed(self):
  with self.assertRaises(ValueError):ranking.player_rows(self.game,self.roster,'2026-10-15')
  game=copy.deepcopy(self.game);game['fixed']=False
  with self.assertRaises(ValueError):ranking.player_rows(game,self.roster,'2026-10-14')
 def test_missing_position(self):
  with self.assertRaises(ValueError):ranking.player_rows(self.game,[],'2026-10-14')
 def test_dual_positions_and_tie_cutoff(self):
  players=[dict(player_id=str(i),eff=10,positions=['PG','SG']) for i in [4,2,3,1]]
  r=ranking.select(players)
  self.assertEqual([p['player_id'] for p in r['PG']],['1','2','3'])
  self.assertEqual([p['rank'] for p in r['SG']],[1,1,1]);self.assertEqual(r['C'],[])
 def test_official_value_preserved_when_formula_differs(self):
  game=copy.deepcopy(self.game);game['players'][0]['EFF']=99
  rows=ranking.player_rows(game,self.roster,'2026-10-14')
  self.assertEqual(rows[0]['eff'],99);self.assertNotEqual(rows[0]['formula_value'],99)
 def test_no_games(self):
  r=ranking.collect(None,ROOT,dict(date='2026-10-15',games=[],schedule_complete={'BP':True,'B1':True,'BN':True}))
  self.assertEqual(r['leagues'],{})
