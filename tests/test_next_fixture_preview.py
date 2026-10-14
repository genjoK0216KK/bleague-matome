import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from scripts import next_preview as n, official_data as o, browse_ui

def game(key,date,league='BP',**kw):
 g=dict(game_id=key,starts_at=date,competition=league,status='scheduled',ended=False,home='A',away='B',source='https://www.bleague.jp/game_detail/?ScheduleKey='+key);g.update(kw);return g

class NextFixture(unittest.TestCase):
 def setUp(self):self.now=datetime.fromisoformat('2026-10-15T04:00:00+09:00')
 def test_two_idle_days_then_next_day_not_tomorrow(self):
  d,g=n.choose([game('1','2026-10-18T19:00:00+09:00'),game('2','2026-10-22T19:00:00+09:00','BN')],self.now)
  self.assertEqual(d,'2026-10-18');self.assertEqual([x['game_id'] for x in g],['1'])
 def test_jst_midnight_and_exact_tipoff(self):
  gs=[game('1','2026-10-15T15:00:00+00:00'),game('2','2026-10-16T19:00:00+09:00')]
  self.assertEqual(n.choose(gs,datetime.fromisoformat('2026-10-15T23:59:59+09:00'))[0],'2026-10-16')
  self.assertEqual([g['game_id'] for g in n.choose(gs,datetime.fromisoformat('2026-10-16T00:00:00+09:00'))[1]],['2'])
 def test_finished_cancelled_and_earlier_tipoff_excluded(self):
  gs=[game('1','2026-10-15T02:00:00+09:00'),game('2','2026-10-15T19:00:00+09:00'),game('3','2026-10-15T20:00:00+09:00',status='cancelled'),game('4','2026-10-15T21:00:00+09:00',ended=True)]
  self.assertEqual([g['game_id'] for g in n.choose(gs,self.now)[1]],['2'])
 def test_no_editorial_posts_home_still_links_preview(self):
  with tempfile.TemporaryDirectory() as root:
   g=game('1','2026-10-18T19:00:00+09:00');s=dict(date='2026-10-18',games=[g],errors=[],retrieved_at=self.now.isoformat())
   p=Path(root)/'data/match_articles';p.mkdir(parents=True);(p/'next-preview.json').write_text(json.dumps(s))
   html=browse_ui.home(root,self.now);self.assertIn('2026-10-18',html);self.assertIn('next-games.html',html);self.assertNotIn('#daily-lineups',html)
   self.assertIsNone(n.load(root,datetime.fromisoformat('2026-10-18T19:00:00+09:00')))
 def test_unknown_schedule_does_not_claim_no_games(self):
  with patch.object(o,'fetch_next_games',side_effect=o.DataError('maintenance')):
   s=n.collect(None,'.',2026,self.now)
  html=n.render(s,self.now);self.assertIn('次の日程を確認中',html);self.assertNotIn('この日の試合はありません',html)
 def test_unannounced_bounded_search(self):
  with patch.object(o,'fetch_next_games',return_value=[]):s=n.collect(None,'.',2026,self.now)
  self.assertIn('35日以内',n.render(s,self.now));self.assertIn('未発表',n.render(s,self.now))
 def test_only_earliest_day_selected_for_lineups(self):
  with patch.object(o,'fetch_next_games',side_effect=[[game('1','2026-10-16T19:00:00+09:00')],[game('2','2026-10-17T19:00:00+09:00','B1')],[]]),patch.object(n.daily_lineups,'collect',return_value={}) as collect:
   s=n.collect(None,'.',2026,self.now)
  self.assertEqual([g['game_id'] for g in collect.call_args.args[2]['games']],['1']);self.assertEqual(s['other_dates']['B1'],'2026-10-17')
 def test_maintenance_month_rejected(self):
  class C:
   def get(self,url):return '<html>maintenance</html>'
  with self.assertRaises(o.DataError):o.fetch_next_games(C(),2026,'BP',self.now)

 def test_month_crossing_and_consecutive_idle_days(self):
  from urllib.parse import urlparse,parse_qs
  class C:
   def get(self,url):
    month=int(parse_qs(urlparse(url).query)['mon'][0]);day=30 if month==10 else 3
    return f'<select name="year"><option selected value="2026"></option></select><select name="mon"><option selected value="{month}"></option></select><div id="schedule-b1"></div><a class="js_click_data" data-day="{day}"></a>'
  future=game('1','2026-11-03T19:00:00+09:00')
  with patch.object(o,'fetch_day',return_value=([future],True,'',[])) as fetch:
   rows=o.fetch_next_games(C(),2026,'BP',datetime.fromisoformat('2026-10-31T22:00:00+09:00'))
  self.assertEqual(rows,[future]);self.assertEqual(fetch.call_args.args[3],'2026-11-03')
 def test_expired_roster_cache_hidden_even_before_match(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root)/'data/match_articles';p.mkdir(parents=True)
   s=dict(games=[game('1','2026-10-18T19:00:00+09:00')],retrieved_at=self.now.isoformat(),lineups={'BP':{'retrieved_at':'2026-10-13T10:00:00+09:00'}})
   (p/'next-preview.json').write_text(json.dumps(s));self.assertIsNone(n.load(root,self.now))
 def test_offline_marker_and_missing_day_title(self):
  from scripts import day_articles
  s=dict(date=None,games=[],errors=[],schedule_complete={},lineups={},offline=True)
  self.assertIn('noindex,nofollow',n.render(s,self.now));self.assertIn('ローカル検証版',n.render(s,self.now))
  _,html=day_articles.render(dict(date='2026-10-15',games=[],schedule_complete={'BP':False},sources=[]),'.',[],'TEST')
  self.assertIn('10/15 日程未確認',html)
 def test_player_errors_reported(self):
  with patch.object(o,'fetch_next_games',side_effect=[[game('1','2026-10-16T19:00:00+09:00')],[],[]]),patch.object(n.daily_lineups,'collect',return_value={'BP':{'error':'IL unavailable'}}):
   s=n.collect(None,'.',2026,self.now)
  self.assertIn('IL unavailable',s['player_errors'][0]);self.assertIn('選手データ確認中',n.render(s,self.now))
