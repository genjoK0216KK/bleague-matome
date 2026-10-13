import unittest,tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from scripts import daily_lineups as lineup, preview_data as data, build, official_data as official, day_articles, update_match_features as update

def player(i,pos,avg,**extra):
 p=dict(player_id=str(i),name=str(i),team='T',positions=pos,season='2026-27',competition='B1',metric='EFF',aggregation='average',average=avg,games=3,coverage_complete=True,position_source='https://official/roster',stats_source='https://official/stats',availability='unknown');p.update(extra);return p

class DailyLineups(unittest.TestCase):
 def test_unique_across_first_and_second_with_ties(self):
  players=[player('1',['PG','SG'],30),player('2',['PG'],20),player('3',['SG'],20),player('4',['SG'],20),player('5',['SF'],10),player('6',['PF'],5),player('7',['C'],4)]
  teams=lineup.select(players,'2026-27','B1')
  ids=[p['player_id'] for t in teams for pos,p in t if p]
  self.assertEqual(len(ids),len(set(ids)))
  self.assertEqual([p['player_id'] if p else None for pos,p in teams[0]],['1','3','5','6','7'])
  self.assertEqual([p['player_id'] if p else None for pos,p in teams[1]],['2','4',None,None,None])
 def test_exclude_il_missing_other_league(self):
  players=[player('1',['PG'],50,availability='out',availability_source='https://official/il'),player('2',['PG'],99,competition='BP'),player('3',['PG'],None),player('4',['PG'],3,il_removed_date='10月1日')]
  self.assertEqual(lineup.select(players,'2026-27','B1')[0][0][1]['player_id'],'4')
 def test_order_today_before_remote_future(self):
  now=datetime(2026,10,14,tzinfo=data.JST)
  rows=[dict(href='article-games-'+d.replace('.','')+'.html',date=d) for d in ['2026.10.22','2026.10.14','2026.10.13','2026.10.16']]
  self.assertEqual([r['date'] for r in sorted(rows,key=lambda a:build.article_order(a,now),reverse=True)],['2026.10.14','2026.10.16','2026.10.22','2026.10.13'])
 def test_titles_require_verified_results(self):
  self.assertEqual(day_articles.label({'games':[]}), '試合予定')
  self.assertEqual(day_articles.label({'games':[dict(status='scheduled',ended=False)]}), '試合予定')
  self.assertEqual(day_articles.label({'games':[dict(status='final',ended=True,fixed=True,home_score=1,away_score=0,source='official')]}), '試合結果・予定')
 def test_missing_roster_withholds_entire_league(self):
  summary=dict(date='2026-10-14',games=[dict(game_id='1',competition='B1',status='scheduled')],schedule_complete={'B1':True})
  with tempfile.TemporaryDirectory() as root:
   self.assertIn('error',lineup.collect(None,root,summary)['B1'])
 def test_fetch_day_rejects_fallback(self):
  class C:
   def get(self,url):return ''
  plan=dict(keys=['1'],complete=True,no_games=False,notices={},notice_dates={})
  game=dict(game_id='1',competition='B1',status='scheduled',starts_at='2026-10-22T19:00:00+09:00')
  with patch.object(official,'parse_schedule',return_value=plan),patch.object(official,'parse_game',return_value=game):
   games,complete,url,errors=official.fetch_day(C(),2026,'B1','2026-10-14')
   self.assertEqual(games,[]);self.assertFalse(complete);self.assertIn('different actual game date',errors[0])
 def test_preview_generation_gate_and_no_duplicate(self):
  tomorrow=dict(game_id='2',starts_at='2026-10-15T19:00:00+09:00')
  far=dict(game_id='3',starts_at='2026-10-22T19:00:00+09:00')
  states={'B1':[tomorrow,tomorrow,far,dict(game_id='4',status='cancelled',starts_at=None,official_date='2026-10-15')]}
  self.assertEqual(update.releasable_games(datetime.fromisoformat('2026-10-14T22:59:00+09:00'),[far],states),[])
  self.assertEqual(update.releasable_games(datetime.fromisoformat('2026-10-14T23:00:00+09:00'),[far],states),[tomorrow])
  self.assertEqual(update.releasable_games(datetime.fromisoformat('2026-10-15T00:00:00+09:00'),[tomorrow],{}),[tomorrow])
 def test_release_boundary(self):
  # Use actual read_articles filtering with only one dated page.
  class Clock:
   current=None
   @classmethod
   def now(cls,tz):return cls.current
   strptime=staticmethod(datetime.strptime)
  with tempfile.TemporaryDirectory() as root,patch.object(build,'ROOT',root),patch.object(build,'datetime',Clock):
   Path(root,'article-games-20261015.html').write_text('<h1>予定</h1><div class="pmeta"><span>2026.10.15</span></div>')
   for date,count in [('2026-10-14T22:59:00+09:00',0),('2026-10-14T23:00:00+09:00',1),('2026-10-15T00:00:00+09:00',1)]:
    Clock.current=datetime.fromisoformat(date);self.assertEqual(len(build.read_articles()),count)

if __name__=='__main__':unittest.main()
