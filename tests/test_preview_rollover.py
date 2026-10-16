import json,tempfile,unittest
from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from scripts import refresh_next_preview as r, next_preview as n

class Rollover(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.now=datetime.fromisoformat('2026-10-16T19:05:00+09:00')
  self.old={'games':[{'starts_at':self.now.isoformat(),'status':'scheduled','ended':False,'game_id':'1'}],'retrieved_at':self.now.isoformat()}
  p=self.root/'data/match_articles';p.mkdir(parents=True);self.path=p/'next-preview.json';self.path.write_text(json.dumps(self.old))
  self.new={'date':'2026-10-17','games':[dict(self.old['games'][0],starts_at=(self.now+timedelta(days=1)).isoformat())],'retrieved_at':self.now.isoformat(),'errors':[],'lineups':{}}
 def call(self,state):
  with patch.object(n,'collect',return_value=state),patch.object(n,'write') as write:
   result=r.refresh(self.root,2026,self.now,lambda:SimpleNamespace(request_count=50));return result,write
 def test_tipoff_rolls_to_next_fixture(self):
  result,write=self.call(self.new);self.assertTrue(result['changed']);write.assert_called_once();self.assertEqual(result['date'],'2026-10-17')
 def test_current_skips_all_fetch(self):
  self.path.write_text(json.dumps(self.new))
  with patch.object(n,'collect') as collect:
   self.assertEqual(r.refresh(self.root,2026,self.now)['requests'],0);collect.assert_not_called()
 def test_failure_retains_and_cools_down(self):
  before=self.path.read_bytes();result,write=self.call(dict(self.new,player_errors=['stats unavailable']));write.assert_not_called();self.assertEqual(self.path.read_bytes(),before)
  with patch.object(n,'collect') as collect:
   self.assertEqual(r.refresh(self.root,2026,self.now)['reason'],'retry_cooldown');collect.assert_not_called()
 def test_settled_results_still_roll_preview(self):
  from scripts import update_results as u
  with patch('sys.argv',['update_results','--season-year','2026','--root',str(self.root)]),patch.object(u,'run',return_value={'changed':False,'reason':'already_final'}),patch.object(u.refresh_next_preview,'refresh',return_value={'changed':True}) as refresh,patch.object(u.subprocess,'run') as build:
   self.assertEqual(u.main(),0);refresh.assert_called_once();build.assert_called_once()

 def test_successful_attempt_does_not_delay_tipoff_rollover(self):
  (self.path.parent/'next-preview-attempt.json').write_text(json.dumps({'at':(self.now-timedelta(minutes=13)).isoformat(),'errors':[]}))
  result,write=self.call(self.new);self.assertTrue(result['changed']);write.assert_called_once()
