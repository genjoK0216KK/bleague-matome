import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from scripts import daily_lineups as dl, official_data as official, preview_data as data, day_articles, match_articles
from bs4 import BeautifulSoup

class Backfill(unittest.TestCase):
 def setUp(self):
  self.now=datetime.now(data.JST)
  self.game=dict(game_id='123',competition='B1',season='2026-27',starts_at='2026-10-13T19:05:00+09:00',home_id='1',away_id='2',home='A',away='B',status='final',ended=True,fixed=True,home_score=80,away_score=71,source='https://www.bleague.jp/game_detail/?ScheduleKey=123')
  self.client=SimpleNamespace(get=lambda url:'official',sources=[dict(url='https://www.bleague.jp/stats/',retrieved_at=self.now.isoformat())])
 def roster(self,client,team_id,team,year,league):
  return [dict(player_id=team_id,team_id=team_id,team=team,name=team,season='2026-27',competition=league,positions=['PG'],position_source='https://www.bleague.jp/club/',availability='unknown')]
 def test_ended_game_missing_snapshot_backfills_both_exact_teams(self):
  with tempfile.TemporaryDirectory() as root,patch.object(official,'parse_game',return_value=self.game),patch.object(official,'fetch_averages',return_value={p:dict(average=10,games=3,stats_source='https://www.bleague.jp/stats/') for p in ['1','2']}),patch.object(official,'fetch_roster',side_effect=self.roster) as roster:
   bundle=dl.player_bundle(self.client,root,self.game,'2026-10-13',self.now)
   self.assertEqual({p['team_id'] for p in bundle['players']},{'1','2'})
   self.assertEqual(roster.call_count,2)
   self.assertTrue(Path(root,'data/match_articles/players-123.json').exists())
 def test_official_wrong_day_never_saved(self):
  wrong=dict(self.game,starts_at='2026-10-14T19:05:00+09:00')
  with tempfile.TemporaryDirectory() as root,patch.object(official,'parse_game',return_value=wrong):
   with self.assertRaisesRegex(ValueError,'不一致'):dl.player_bundle(self.client,root,self.game,'2026-10-13',self.now)
   self.assertFalse(Path(root,'data/match_articles/players-123.json').exists())
 def test_different_team_never_saved(self):
  with tempfile.TemporaryDirectory() as root,patch.object(official,'parse_game',return_value=dict(self.game,home_id='99')):
   with self.assertRaisesRegex(ValueError,'不一致'):dl.player_bundle(self.client,root,self.game,'2026-10-13',self.now)
 def test_result_first_and_notes_below_players(self):
  s=dict(date='2026-10-13',games=[self.game],sources=[self.game['source']],schedule_complete=dict(BP=True,B1=True,BN=True),lineups={'B1':dict(teams=[[('PG',None)],[('PG',None)]],sources=[],retrieved_at=self.now.isoformat())})
  _,html=day_articles.render(s,'.',[],'TEST')
  soup=BeautifulSoup(match_articles.readable_match(html),'html.parser')
  self.assertIsNone(soup.select_one('.daily-lineups'))
  self.assertLess(str(soup).index('daily-results'),str(soup).index('match-notes'))
  self.assertNotIn('取得',soup.select_one('.pmeta').get_text())
  self.assertLess(len(soup.h1.get_text()),25)
  self.assertIn('試合結果・当日のEFF',soup.h1.get_text())

 def test_schedule_warning_remains_visible_and_returns_preserved(self):
  p=dict(name='選手A',team='A',average=10,games=3,il_removed_date='10月1日',il_source='https://www.bleague.jp/news/injury.html')
  s=dict(date='2026-10-13',games=[dict(self.game,status='scheduled',ended=False,fixed=False)],sources=[],schedule_complete=dict(BP=False,B1=True,BN=True),lineups={'B1':dict(teams=[[('PG',p)],[('PG',None)]],sources=[],retrieved_at=self.now.isoformat())})
  _,html=day_articles.render(s,'.',[],'TEST')
  soup=BeautifulSoup(match_articles.readable_match(html),'html.parser')
  warning=soup.select_one('.schedule-warning')
  self.assertIsNotNone(warning)
  self.assertFalse(warning.find_parent('details'))
  notes=soup.select_one('.match-notes').get_text()
  self.assertIn('選手A：IL抹消 10月1日',notes)
