import unittest,json
from pathlib import Path
from scripts import stats

class Nationality(unittest.TestCase):
 def test_name_and_old_flags_not_evidence(self):
  for name in ['山田 太郎','ジョン・スミス','張 三']:
   self.assertFalse(stats.verified_japanese(dict(name=name,jp=True)))
 def test_only_explicit_official_verified_fact(self):
  p=dict(nationality='JPN',nationality_verified=True,nationality_source='https://www.bleague.jp/roster_detail/?PlayerID=1')
  self.assertTrue(stats.verified_japanese(p))
  self.assertFalse(stats.verified_japanese(dict(p,nationality_verified=False)))
  self.assertFalse(stats.verified_japanese(dict(p,nationality_source='https://example.com/')))
 def test_legacy_summary_cannot_restore_inferred_ranking(self):
  s=json.loads((Path(__file__).parents[1]/'data/stats/2026-10-12.json').read_text())
  s['eff_top_jp']=[dict(s['eff_top'][0],jp=True)]
  self.assertEqual(stats.verified_japanese_rows(s),[])
  self.assertNotIn('日本人トップ',stats.article_title(s))
  self.assertIn('国籍別ランキングは未掲載',stats.body_sections(s))

if __name__=='__main__':unittest.main()
